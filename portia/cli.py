# -*- coding: utf-8 -*-
import sys
from urlparse import urlparse

import click


class UrlType(click.ParamType):
    name = 'uri'

    def convert(self, value, param, ctx):
        try:
            url = urlparse(value)
        except (AttributeError, TypeError):
            self.fail('Invalid url: %s.' % (value,), param, ctx)

        if not url.hostname:
            self.fail('Missing Redis hostname.')

        try:
            int(url.path[1:])
        except (IndexError, ValueError):
            self.fail('Invalid Redis db index.')

        return url


@click.group()
def main():
    pass


@main.command()
@click.option('--redis-uri', default='redis://localhost:6379/1',
              help='The redis://hostname:port/db to connect to.',
              type=UrlType())
@click.option('--interface', default='localhost',
              help='The interface to bind to.',
              type=str)
@click.option('--port', default=8000,
              help='The TCP port to listen on.',
              type=int)
@click.option('--prefix', default='bayes:',
              help='The Redis keyspace prefix to use.',
              type=str)
@click.option('--logfile',
              help='Where to log output to.',
              type=click.File('a'),
              default=sys.stdout)
@click.option('--debug/--no-debug', default=False,
              help='Log debug output or not.')
def run(redis_uri, interface, port, prefix, logfile, debug):
    from .main import PortiaServer
    from twisted.internet import reactor
    from twisted.python import log
    from txredisapi import Connection

    log.startLogging(logfile)

    d = Connection(redis_uri.hostname, int(redis_uri.port or 6379),
                   int(redis_uri.path[1:]))
    d.addCallback(
        lambda redis: PortiaServer(redis, prefix=prefix, debug=debug))
    d.addCallback(lambda portia: portia.app.run(interface, port))

    reactor.run()


@main.group('import')
def import_():
    pass


@import_.command('porting-db')
@click.option('--redis-uri', default='redis://localhost:6379/1',
              help='The redis://hostname:port/db to connect to.',
              type=UrlType())
@click.option('--prefix', default='bayes:',
              help='The Redis keyspace prefix to use.',
              type=str)
@click.option('--logfile',
              help='Where to log output to.',
              type=click.File('a'),
              default=sys.stdout)
@click.option('--debug/--no-debug', default=True,
              help='Log debug output or not.')
@click.option('--header/--no-header', default=True,
              help='Whether the CSV file has a header or not.')
@click.argument('file', type=click.File())
def import_porting_db(redis_uri, prefix, logfile, debug, header, file):
    from .portia import Portia
    from twisted.internet.task import react
    from twisted.python import log
    from txredisapi import Connection

    log.startLogging(logfile)

    d = Connection(redis_uri.hostname, int(redis_uri.port or 6379),
                   int(redis_uri.path[1:]))
    d.addCallback(lambda redis: Portia(redis, prefix=prefix))
    d.addCallback(lambda portia: portia.import_porting_file(file, header))
    d.addCallback(
        lambda msisdns: [
            log.msg('Imported %s' % (msisdn,)) for msisdn in msisdns])

    react(lambda _reactor: d)
