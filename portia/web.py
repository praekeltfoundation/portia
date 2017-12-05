import json
import phonenumbers
from functools import wraps

from twisted.internet import reactor

from klein import Klein

from .exceptions import PortiaException


def validate_key(func):
    @wraps(func)
    def wrapper(portia_server, request, **kwargs):
        try:
            portia_server.portia.validate_annotate_key(kwargs['key'])
        except PortiaException, e:
            request.setResponseCode(400)
            return json.dumps(str(e))

        return func(portia_server, request, **kwargs)
    return wrapper


class PortiaWebServer(object):
    """
    Portia, Number portability as a service
    An API for doing: phone number network lookups.

    :param txredisapi.Connection redis:
        The txredis connection
    """

    app = Klein()
    clock = reactor
    timeout = 5

    def __init__(self, portia, cors=None):
        self.portia = portia
        self.cors = cors

    def default_headers(self, request):
        request.setHeader('Content-Type', 'application/json')
        if self.cors is not None:
            request.setHeader(
                'Access-Control-Allow-Origin',
                self.cors)

    @app.route('/resolve/<msisdn>', methods=['GET'])
    def resolve(self, request, msisdn):
        phonenumber = phonenumbers.parse(msisdn)
        self.default_headers(request)
        d = self.portia.resolve(phonenumber)
        d.addCallback(lambda data: json.dumps(data))
        return d

    @app.route('/entry/<msisdn>', methods=['GET'])
    def get_annotations(self, request, msisdn):
        phonenumber = phonenumbers.parse(msisdn)
        self.default_headers(request)
        d = self.portia.get_annotations(phonenumber)
        d.addCallback(lambda data: json.dumps(data))
        return d

    @app.route('/entry/<msisdn>/<key>', methods=['GET'])
    @validate_key
    def read_annotation(self, request, msisdn, key):
        phonenumber = phonenumbers.parse(msisdn)
        self.default_headers(request)
        d = self.portia.read_annotation(phonenumber, key)
        d.addCallback(lambda data: json.dumps(data))
        return d

    @app.route('/entry/<msisdn>/<key>', methods=['PUT'])
    @validate_key
    def annotate(self, request, msisdn, key):
        phonenumber = phonenumbers.parse(msisdn)
        content = request.content.read()
        self.default_headers(request)

        if not content:
            request.setResponseCode(400)
            return json.dumps('No content supplied')

        d = self.portia.annotate(phonenumber, key, content, self.portia.now())
        d.addCallback(lambda _: json.dumps(content))
        return d
