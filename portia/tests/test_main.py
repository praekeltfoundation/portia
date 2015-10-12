from datetime import datetime

from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.web.client import HTTPConnectionPool
from twisted.web.server import Site
from twisted.trial.unittest import TestCase

import txredisapi

import treq

from portia.main import PortiaServer


class PortiaServerTest(TestCase):

    timeout = 1

    @inlineCallbacks
    def setUp(self):
        self.redis = yield txredisapi.Connection()
        self.addCleanup(self.redis.disconnect)
        self.portia_server = PortiaServer(self.redis)
        self.portia = self.portia_server.portia
        self.addCleanup(self.portia_server.portia.flush)

        self.site = Site(self.portia_server.app.resource())
        self.listener = reactor.listenTCP(0, self.site, interface='localhost')
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
        response = yield self.request('GET', '/lookup/27123456789')
        data = yield response.json()
        self.assertEqual(data, {})

    @inlineCallbacks
    def test_lookup(self):
        timestamp = datetime.now()
        self.portia.import_porting_record(
            '27123456789', 'MNO1', 'MNO2', timestamp)
        response = yield self.request('GET', '/lookup/27123456789')
        data = yield response.json()
        self.assertEqual(data, {
            'network': 'MNO2',
            'network-timestamp': timestamp.isoformat(),
            'ported-from': 'MNO1',
            'ported-from-timestamp': timestamp.isoformat(),
        })

    @inlineCallbacks
    def test_lookup_key(self):
        timestamp = datetime.now()
        self.portia.import_porting_record(
            '27123456789', 'MNO1', 'MNO2', timestamp)
        response = yield self.request('GET', '/lookup/27123456789/network')
        data = yield response.json()
        self.assertEqual(data, {
            'network': 'MNO2',
            'network-timestamp': timestamp.isoformat(),
        })

    @inlineCallbacks
    def test_bad_key(self):
        response = yield self.request('GET', '/lookup/27123456789/foo')
        content = yield response.json()
        self.assertEqual(content, 'Invalid Key: foo')
        self.assertEqual(response.code, 400)

    @inlineCallbacks
    def test_lookup_key_empty(self):
        response = yield self.request('GET', '/lookup/27123456789/network')
        data = yield response.json()
        self.assertEqual(data, {
            'network': None,
            'network-timestamp': None,
        })

    @inlineCallbacks
    def test_annotate(self):
        response = yield self.request('PUT', '/annotate/27123456789/network',
                                      data='MNO1')
        data = yield response.json()
        self.assertEqual(data, 'MNO1')
        annotation = yield self.portia.read_annotation(
            '27123456789', 'network')
        self.assertEqual(annotation['network'], 'MNO1')
        self.assertTrue(annotation['network-timestamp'])

    @inlineCallbacks
    def test_annotate_empty(self):
        response = yield self.request('PUT', '/annotate/27123456789/network',
                                      data='')
        data = yield response.json()
        self.assertEqual(data, 'No content supplied')
        self.assertEqual(response.code, 400)
