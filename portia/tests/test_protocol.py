import json
from datetime import datetime

from twisted.trial.unittest import TestCase
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, maybeDeferred, Deferred
from twisted.test.proto_helpers import StringTransportWithDisconnection

from txredisapi import Connection

from portia.portia import Portia
from portia.protocol import JsonProtocol, JsonProtocolFactory


class ProtocolTest(TestCase):

    timeout = 1

    @inlineCallbacks
    def setUp(self):
        self.redis = yield Connection()
        self.addCleanup(self.redis.disconnect)

        self.portia = Portia(self.redis)
        self.addCleanup(self.portia.flush)

        self.proto = JsonProtocol(self.portia)
        self.transport = StringTransportWithDisconnection()
        self.proto.makeConnection(self.transport)
        self.transport.protocol = self.proto
        self.proto.factory = JsonProtocolFactory(self.portia)

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
        timestamp = datetime.utcnow()
        result = yield self.send_command('annotate', msisdn='27123456789',
                                         key='X-Foo', value='Bar',
                                         timestamp=timestamp.isoformat())
        self.assertEqual(result['status'], 'ok')
        entry = yield self.portia.read_annotation('27123456789', 'X-Foo')
        self.assertEqual(entry, {
            'X-Foo': 'Bar',
            'X-Foo-timestamp': timestamp.isoformat(),
        })
