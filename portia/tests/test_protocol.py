import json
import pkg_resources
from datetime import datetime

from dateutil.parser import parse

from twisted.trial.unittest import TestCase
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, maybeDeferred, Deferred
from twisted.test.proto_helpers import StringTransportWithDisconnection

from portia.portia import Portia
from portia.protocol import JsonProtocolFactory
from portia import utils


class ProtocolTest(TestCase):

    timeout = 1

    @inlineCallbacks
    def setUp(self):
        self.redis = yield utils.start_redis()
        self.addCleanup(self.redis.disconnect)

        self.portia = Portia(
            self.redis,
            network_prefix_mapping=utils.compile_network_prefix_mappings(
                [pkg_resources.resource_filename(
                    'portia', 'assets/mappings/*.mapping.json')]))
        self.addCleanup(self.portia.flush)

        factory = JsonProtocolFactory(self.portia)
        self.proto = factory.buildProtocol()
        self.transport = StringTransportWithDisconnection()
        self.proto.makeConnection(self.transport)

    def send_command(self, cmd, id=1, **kwargs):
        data = {
            "cmd": cmd,
            "version": "0.1.0",
            "id": id,
        }

        data['version'] = kwargs.pop('version', self.proto.version)
        data["request"] = kwargs
        return self.send_data(json.dumps(data))

    def send_data(self, data):
        response_d = Deferred()

        def check(d):
            val = self.transport.value()
            self.transport.clear()
            if val:
                d.callback(json.loads(val))
                return
            reactor.callLater(0, check, d)
        reactor.callLater(0, check, response_d)

        error_d = maybeDeferred(self.proto.parseLine, data)
        error_d.addErrback(self.proto.error)

        return response_d

    @inlineCallbacks
    def test_get_empty(self):
        resp = yield self.send_command("get", id='123',
                                       msisdn="27123456789")
        self.assertEqual(resp['reference_id'], '123')
        self.assertEqual(resp['reference_cmd'], 'get')
        self.assertEqual(resp['status'], 'ok')
        self.assertEqual(resp['response'], {})

    @inlineCallbacks
    def test_invalid_command(self):
        resp = yield self.send_command("foo", id='123', foo="bar")
        self.assertEqual(resp['reference_id'], '123')
        self.assertEqual(resp['reference_cmd'], 'foo')
        self.assertEqual(resp['status'], 'error')
        self.assertEqual(resp['message'], 'Unsupported command: foo.')

    @inlineCallbacks
    def test_invalid_command_without_reference_id(self):
        resp = yield self.send_data(json.dumps({
            'cmd': 'foo',
            'version': self.proto.version,
        }))
        self.assertEqual(resp['reference_id'], None)
        self.assertEqual(resp['reference_cmd'], 'foo')
        self.assertEqual(resp['status'], 'error')
        self.assertEqual(resp['message'], 'Unsupported command: foo.')

    @inlineCallbacks
    def test_empty_json(self):
        resp = yield self.send_data(json.dumps({}))
        self.assertEqual(resp['reference_id'], None)
        self.assertEqual(resp['reference_cmd'], None)
        self.assertEqual(resp['status'], 'error')
        self.assertEqual(
            resp['message'],
            'Protocol version mismatch. Expected: 0.1.0, got: None.')

    @inlineCallbacks
    def test_version_mismatch(self):
        resp = yield self.send_data(json.dumps({
            'version': '-1',
            'id': 1,
            'cmd': 'get',
            'request': {}}))
        self.assertEqual(resp['reference_id'], 1)
        self.assertEqual(resp['reference_cmd'], 'get')
        self.assertEqual(resp['status'], 'error')
        self.assertEqual(
            resp['message'],
            'Protocol version mismatch. Expected: 0.1.0, got: -1.')

    @inlineCallbacks
    def test_get(self):
        timestamp = datetime.utcnow()
        yield self.portia.annotate('27123456789', 'ported-to', 'MNO',
                                   timestamp=timestamp)
        result = yield self.send_command('get', msisdn='27123456789')
        self.assertEqual(result['response'], {
            'ported-to': 'MNO',
            'ported-to-timestamp': timestamp.isoformat(),
        })

    @inlineCallbacks
    def test_annotate(self):
        timestamp = parse('2015-10-20T22:56:15.894220+00:00')
        result = yield self.send_command(
            'annotate', msisdn='27123456789',
            key='X-Foo', value='Bar',
            timestamp=timestamp.isoformat())
        self.assertEqual(result['status'], 'ok')
        entry = yield self.portia.read_annotation('27123456789', 'X-Foo')
        self.assertEqual(entry, {
            'X-Foo': 'Bar',
            'X-Foo-timestamp': self.portia.local_time(timestamp).isoformat(),
        })

    @inlineCallbacks
    def test_resolve_observed_network(self):
        result = yield self.send_command(
            'annotate', msisdn='27123456789',
            key='observed-network', value='MNO',
            timestamp=self.portia.now().now().isoformat())
        result = yield self.send_command('resolve', msisdn='27123456789')
        response = result['response']
        self.assertEqual(response['network'], 'MNO')
        self.assertEqual(response['strategy'], 'observed-network')

    @inlineCallbacks
    def test_resolve_ported_network(self):
        result = yield self.send_command(
            'annotate', msisdn='27123456789',
            key='ported-to', value='MNO',
            timestamp=self.portia.now().isoformat())
        result = yield self.send_command('resolve', msisdn='27123456789')
        response = result['response']
        self.assertEqual(response['network'], 'MNO')
        self.assertEqual(response['strategy'], 'ported-to')

    @inlineCallbacks
    def test_resolve_prefix_guess(self):
        result = yield self.send_command('resolve', msisdn='27761234567')
        response = result['response']
        self.assertEqual(response['network'], 'VODACOM')
        self.assertEqual(response['strategy'], 'prefix-guess')

    @inlineCallbacks
    def test_annotate_timestamp_with_timezone(self):
        timestamp_za = parse('2015-10-20T23:56:15.894220+02:00')
        timestamp_utc = parse('2015-10-20T22:56:15.894220+00:00')
        yield self.send_command('annotate', msisdn='27123456789',
                                key='observed-network',
                                value='za-network',
                                timestamp=timestamp_za.isoformat())
        yield self.send_command('annotate', msisdn='27123456789',
                                key='observed-network',
                                value='utc-network',
                                timestamp=timestamp_utc.isoformat())
        result = yield self.send_command('resolve', msisdn='27123456789')
        # NOTE: We're checking the timezone here, 22pm in +00:00 is more
        #       recent than 23pm in +02:00
        self.assertEqual(result['response']['network'], 'utc-network')
