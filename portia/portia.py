import csv
from datetime import datetime

from twisted.internet.defer import gatherResults, succeed


class PortiaException(Exception):
    pass


class Portia(object):

    ANNOTATION_KEYS = frozenset([
        'observed-network',
        'ported-to',
        'ported-from',
        'do-not-call',
    ])

    def __init__(self, redis, prefix="portia:", network_prefix_mapping=None):
        self.redis = redis
        self.prefix = prefix
        self.network_prefix_mapping = network_prefix_mapping or {}

    def key(self, *parts):
        return '%s%s' % (self.prefix, ':'.join(parts))

    def import_porting_filename(self, file_name, has_header=True):
        with open(file_name, 'r') as fp:
            return self.import_porting_file(fp, has_header=has_header)

    def import_porting_file(self, fp, has_header=True):
        reader = csv.reader(fp)
        if has_header:  # Skip the first row if it is a document header
            reader.next()
        records = []
        for row in reader:
            msisdn, donor, recipient, date = row[0:4]
            records.append(
                self.import_porting_record(
                    msisdn, donor, recipient,
                    datetime.strptime(date, '%Y%m%d')))
        return gatherResults(records)

    def import_porting_record(self, msisdn, donor, recipient, timestamp):
        d = gatherResults([
            self.annotate(
                msisdn,
                self.validate_annotate_key('ported-to'),
                recipient,
                timestamp=timestamp),
            self.annotate(
                msisdn,
                self.validate_annotate_key('ported-from'),
                donor,
                timestamp=timestamp),
        ])
        d.addCallback(lambda _: msisdn)
        return d

    def remove(self, msisdn):
        return self.redis.delete(self.key(msisdn))

    def validate_annotate_key(self, key):
        if key not in self.ANNOTATION_KEYS and not key.startswith('X-'):
            raise PortiaException('Invalid Key: %s' % (key,))
        return key

    def resolve(self, msisdn):
        d = self.get_annotations(msisdn)
        d.addCallback(self.resolve_cb, msisdn)
        return d

    def network_prefix_lookup(self, msisdn, mapping):
        for key, value in mapping.iteritems():
            if msisdn.startswith(str(key)):
                if isinstance(value, dict):
                    return self.network_prefix_lookup(msisdn, value)
                return succeed(value)
        return succeed(None)

    def resolve_cb(self, annotations, msisdn):
        observed_network = annotations.get('observed-network')
        if observed_network:
            return {
                'network': observed_network,
                'strategy': 'observation',
                'entry': annotations,
            }
        ported_to = annotations.get('ported-to')
        if ported_to:
            return {
                'network': ported_to,
                'strategy': 'porting-db',
                'entry': annotations,
            }

        d = self.network_prefix_lookup(msisdn, self.network_prefix_mapping)
        d.addCallback(lambda network: {
            'network': network,
            'strategy': 'prefix-guess',
            'entry': annotations,
        })
        return d

    def annotate(self, msisdn, key, value, timestamp=None):
        timestamp = timestamp or datetime.utcnow()
        key = self.validate_annotate_key(key)
        return self.redis.hmset(
            self.key(msisdn), {
                key: value,
                '%s-timestamp' % (key,): timestamp.isoformat(),
            })

    def get_annotations(self, msisdn):
        return self.redis.hgetall(self.key(msisdn))

    def remove_annotations(self, msisdn, *keys):
        keys = [self.validate_annotate_key(key) for key in keys]
        keys.extend(['%s-timestamp' % (key,) for key in keys])
        return self.redis.hdel(self.key(msisdn), keys),

    def read_annotation(self, msisdn, key):
        d = self.redis.hmget(
            self.key(msisdn),
            [self.validate_annotate_key(key),
             '%s-timestamp' % (key,)])
        d.addCallback(lambda values: {
            key: values[0],
            '%s-timestamp' % (key,): values[1],
        })
        return d

    def flush(self):
        d = self.redis.keys('%s*' % (self.prefix,))
        d.addCallback(lambda keys: gatherResults([
            self.redis.delete(key) for key in keys
        ]))
        return d
