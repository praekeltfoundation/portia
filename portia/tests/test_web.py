import pkg_resources
from datetime import datetime

from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.web.client import HTTPConnectionPool
from twisted.trial.unittest import TestCase

import treq

from portia.web import PortiaWebServer
from portia.portia import Portia
from portia import utils


class PortiaServerTest(TestCase):

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

        self.portia_server = PortiaWebServer(self.portia)
        self.listener = yield utils.start_webserver(self.portia, 'tcp:0')
        self.listener_port = self.listener.getHost().port
        self.addCleanup(self.listener.loseConnection)

        # cleanup stuff for treq's global http request pool
        self.pool = HTTPConnectionPool(reactor, persistent=False)
        self.addCleanup(self.pool.closeCachedConnections)

    def request(self, method, path, data=None):
        return treq.request(
            method, 'http://localhost:%s%s' % (
                self.listener_port,
                path
            ),
            data=data,
            pool=self.pool)

    @inlineCallbacks
    def test_lookup_empty(self):
        response = yield self.request('GET', '/entry/27123456789')
        data = yield response.json()
        self.assertEqual(data, {})

    @inlineCallbacks
    def test_lookup(self):
        timestamp = datetime.now()
        self.portia.import_porting_record(
            '27123456789', 'MNO1', 'MNO2', timestamp)
        response = yield self.request('GET', '/entry/27123456789')
        data = yield response.json()
        self.assertEqual(data, {
            'ported-to': 'MNO2',
            'ported-to-timestamp': timestamp.isoformat(),
            'ported-from': 'MNO1',
            'ported-from-timestamp': timestamp.isoformat(),
        })

    @inlineCallbacks
    def test_lookup_key(self):
        timestamp = datetime.now()
        self.portia.import_porting_record(
            '27123456789', 'MNO1', 'MNO2', timestamp)
        response = yield self.request('GET', '/entry/27123456789/ported-to')
        data = yield response.json()
        self.assertEqual(data, {
            'ported-to': 'MNO2',
            'ported-to-timestamp': timestamp.isoformat(),
        })

    @inlineCallbacks
    def test_bad_key(self):
        response = yield self.request('GET', '/entry/27123456789/foo')
        content = yield response.json()
        self.assertEqual(content, 'Invalid Key: foo')
        self.assertEqual(response.code, 400)

    @inlineCallbacks
    def test_lookup_key_empty(self):
        response = yield self.request('GET', '/entry/27123456789/ported-to')
        data = yield response.json()
        self.assertEqual(data, {
            'ported-to': None,
            'ported-to-timestamp': None,
        })

    @inlineCallbacks
    def test_annotate(self):
        response = yield self.request('PUT', '/entry/27123456789/ported-to',
                                      data='MNO1')
        data = yield response.json()
        self.assertEqual(data, 'MNO1')
        annotation = yield self.portia.read_annotation(
            '27123456789', 'ported-to')
        self.assertEqual(annotation['ported-to'], 'MNO1')
        self.assertTrue(annotation['ported-to-timestamp'])

    @inlineCallbacks
    def test_annotate_empty(self):
        response = yield self.request('PUT', '/entry/27123456789/ported-to',
                                      data='')
        data = yield response.json()
        self.assertEqual(data, 'No content supplied')
        self.assertEqual(response.code, 400)

    @inlineCallbacks
    def test_resolve_observation(self):
        yield self.portia.annotate(
            '27123456789', 'observed-network', 'MNO')
        response = yield self.request('GET', '/resolve/27123456789')
        result = yield response.json()
        self.assertEqual(result['network'], 'MNO')
        self.assertEqual(result['strategy'], 'observed-network')

    @inlineCallbacks
    def test_resolve_prefix_guess(self):
        response = yield self.request('GET', '/resolve/27763456789')
        result = yield response.json()
        self.assertEqual(result['network'], 'VODACOM')
        self.assertEqual(result['strategy'], 'prefix-guess')

    @inlineCallbacks
    def test_resolve_prefix_guess_unknown(self):
        response = yield self.request('GET', '/resolve/000000000000')
        result = yield response.json()
        self.assertEqual(result['network'], None)
        self.assertEqual(result['strategy'], 'prefix-guess')
