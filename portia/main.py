import json
from functools import wraps

from klein import Klein

from .portia import Portia, PortiaException


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


class PortiaServer(object):
    """
    Portia, Number portability as a service
    An API for doing: phone number network lookups.

    :param txredisapi.Connection redis:
        The txredis connection
    """

    app = Klein()
    timeout = 5

    def __init__(self, redis, prefix="portia:", debug=False):
        self.redis = redis
        self.debug = debug
        self.portia = Portia(redis, prefix=prefix)

    @app.route('/entry/<msisdn>', methods=['GET'])
    def get_annotations(self, request, msisdn):
        request.setHeader('Content-Type', 'application/json')
        d = self.portia.get_annotations(msisdn)
        d.addCallback(lambda data: json.dumps(data))
        return d

    @app.route('/entry/<msisdn>/<key>', methods=['GET'])
    @validate_key
    def read_annotation(self, request, msisdn, key):
        request.setHeader('Content-Type', 'application/json')
        d = self.portia.read_annotation(msisdn, key)
        d.addCallback(lambda data: json.dumps(data))
        return d

    @app.route('/entry/<msisdn>/<key>', methods=['PUT'])
    @validate_key
    def annotate(self, request, msisdn, key):
        content = request.content.read()
        request.setHeader('Content-Type', 'application/json')

        if not content:
            request.setResponseCode(400)
            return json.dumps('No content supplied')

        d = self.portia.annotate(msisdn, key, content)
        d.addCallback(lambda _: json.dumps(content))
        return d
