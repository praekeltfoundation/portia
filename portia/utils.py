from urlparse import urlparse

from twisted.internet.endpoints import serverFromString
from twisted.internet import reactor as default_reactor
from twisted.web.server import Site

from txredisapi import Connection

from .web import PortiaWebServer
from .protocol import JsonProtocolFactory
from .exceptions import PortiaException


def start_redis(redis_uri='redis://localhost:6379/1'):
    try:
        url = urlparse(redis_uri)
    except (AttributeError, TypeError):
        raise PortiaException('Invalid url: %s.' % (redis_uri,))

    if not url.hostname:
        raise PortiaException('Missing Redis hostname.')

    try:
        int(url.path[1:])
    except (IndexError, ValueError):
        raise PortiaException('Invalid Redis db index.')

    return Connection(url.hostname, int(url.port or 6379),
                      dbid=int(url.path[1:]))


def start_webserver(portia, endpoint_str, reactor=default_reactor):
    endpoint = serverFromString(reactor, str(endpoint_str))
    return endpoint.listen(Site(PortiaWebServer(portia).app.resource()))


def start_tcpserver(portia, endpoint_str, reactor=default_reactor):
    endpoint = serverFromString(reactor, str(endpoint_str))
    return endpoint.listen(JsonProtocolFactory(portia))
