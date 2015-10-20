# -*- coding: utf-8 -*-
import sys
import json
import pkg_resources

from twisted.python import log
from twisted.internet import reactor
from twisted.internet.defer import gatherResults
from twisted.internet.task import react

from .portia import Portia

import click


@click.group()
def main():
    pass


@main.command()
@click.option('--redis-uri', default='redis://localhost:6379/1',
              help='The redis://hostname:port/db to connect to.',
              type=str)
@click.option('--web/--no-web', default=True)
@click.option('--web-endpoint', default='tcp:8000', type=str)
@click.option('--tcp/--no-tcp', default=False)
@click.option('--tcp-endpoint', default='tcp:8001', type=str)
@click.option('--prefix', default='bayes:',
              help='The Redis keyspace prefix to use.',
              type=str)
@click.option('--mappings-path',
              type=click.Path(),
              default=[pkg_resources.resource_filename(
                  'portia', 'assets/mappings/*.mapping.json')],
              help='Mappings files to load, defaults to: %s' % (
                  pkg_resources.resource_filename(
                      'portia', 'assets/mappings/*.mapping.json'),
              ),
              multiple=True)
@click.option('--logfile',
              help='Where to log output to.',
              type=click.File('a'),
              default=sys.stdout)
def run(redis_uri, web, web_endpoint, tcp, tcp_endpoint,
        prefix, mappings_path, logfile):
    from .utils import (
        start_redis, start_webserver, start_tcpserver,
        compile_network_prefix_mappings)
    log.startLogging(logfile)

    d = start_redis(redis_uri)
    d.addCallback(
        Portia, prefix=prefix,
        network_prefix_mapping=compile_network_prefix_mappings(mappings_path))

    def start_servers(portia):
        callbacks = []
        if web:
            callbacks.append(start_webserver(portia, web_endpoint))
        if tcp:
            callbacks.append(start_tcpserver(portia, tcp_endpoint))
        return gatherResults(callbacks)

    d.addCallback(start_servers)
    reactor.run()


@main.group('import')
def import_():
    pass


@import_.command('porting-db')
@click.option('--redis-uri', default='redis://localhost:6379/1',
              help='The redis://hostname:port/db to connect to.',
              type=str)
@click.option('--prefix', default='bayes:',
              help='The Redis keyspace prefix to use.',
              type=str)
@click.option('--logfile',
              help='Where to log output to.',
              type=click.File('a'),
              default=sys.stdout)
@click.option('--header/--no-header', default=True,
              help='Whether the CSV file has a header or not.')
@click.argument('file', type=click.File())
def import_porting_db(redis_uri, prefix, logfile, header, file):
    from .utils import start_redis
    log.startLogging(logfile)
    d = start_redis(redis_uri)
    d.addCallback(Portia, prefix=prefix)
    d.addCallback(lambda portia: portia.import_porting_file(file, header))
    d.addCallback(
        lambda msisdns: [
            log.msg('Imported %s' % (msisdn,)) for msisdn in msisdns])

    react(lambda _reactor: d)
