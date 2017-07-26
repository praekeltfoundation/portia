import csv
import phonenumbers
from phonenumbers import geocoder
from phonenumbers import timezone
from phonenumbers import carrier
from datetime import datetime, tzinfo, timedelta

from twisted.internet.defer import gatherResults, succeed, maybeDeferred

from .exceptions import PortiaException


class UTC(tzinfo):
    """
    UTC implementation taken from Python's docs.
    """

    def __repr__(self):
        return "<UTC>"

    def utcoffset(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return timedelta(0)


def as_msisdn(pn):
    return phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)


class Portia(object):

    ANNOTATION_KEYS = frozenset([
        'observed-network',
        'ported-to',
        'ported-from',
        'do-not-call',
    ])

    RESOLVE_KEYS = frozenset([
        'observed-network',
        'ported-to',
    ])

    def __init__(self, redis, prefix="portia:", network_prefix_mapping=None):
        self.redis = redis
        self.prefix = prefix
        self.network_prefix_mapping = network_prefix_mapping or {}
        self.timezone = UTC()

    def to_utc(self, timestamp):
        if timestamp.tzinfo:
            return timestamp.astimezone(self.timezone)
        return timestamp.replace(tzinfo=self.timezone)

    def now(self):
        return self.to_utc(datetime.utcnow())

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
        phonenumber = phonenumbers.parse(msisdn)
        d = gatherResults([
            self.annotate(
                phonenumber,
                self.validate_annotate_key('ported-to'),
                recipient,
                timestamp=timestamp),
            self.annotate(
                phonenumber,
                self.validate_annotate_key('ported-from'),
                donor,
                timestamp=timestamp),
        ])
        d.addCallback(lambda _: phonenumber)
        return d

    def remove(self, phonenumber):
        return self.redis.delete(self.key(as_msisdn(phonenumber)))

    def validate_annotate_key(self, key):
        if key not in self.ANNOTATION_KEYS and not key.startswith('X-'):
            raise PortiaException('Invalid Key: %s' % (key,))
        return key

    def network_prefix_lookup(self, phonenumber, mapping):
        msisdn = as_msisdn(phonenumber)
        for key, value in mapping.iteritems():
            if msisdn.startswith('+%s' % (key,)):
                if isinstance(value, dict):
                    return self.network_prefix_lookup(
                        phonenumber, value)
                return succeed(value)
        return succeed(None)

    def resolve(self, phonenumber):
        d = self.get_annotations(phonenumber)
        d.addCallback(self.resolve_cb, phonenumber)
        d.addCallback(self.resolve_geocode, phonenumber)
        return d

    def resolve_geocode(self, annotations, phonenumber):
        defaults = {
            'msisdn': phonenumbers.format_number(
                phonenumber, phonenumbers.PhoneNumberFormat.E164),
            'country_code': phonenumber.country_code,
            'national_number': phonenumber.national_number,
            'region_code': geocoder.region_code_for_country_code(
                phonenumber.country_code),
            'country_description': geocoder.country_name_for_number(
                phonenumber, "en"),
            'original_carrier': carrier.name_for_number(phonenumber, "en"),
            'timezones': timezone.time_zones_for_number(
                phonenumber)
        }
        defaults.update(annotations)
        return defaults

    def iterate_annotations(self, annotations):
        keys = [key for key in annotations.keys()
                if not key.endswith('-timestamp')]
        return [(key, annotations[key], annotations['%s-timestamp' % (key,)])
                for key in keys]

    def resolve_cb(self, annotations, phonenumber):
        resolve_keys = [
            (key, value, timestamp)
            for (key, value, timestamp)
            in self.iterate_annotations(annotations)
            if key in self.RESOLVE_KEYS]
        if not any(resolve_keys):
            return self.resolve_prefix_guess(phonenumber, annotations)

        strategy, value, timestamp = max(
            resolve_keys, key=lambda tuple_: tuple_[2])
        return {
            'network': value,
            'strategy': strategy,
            'entry': annotations,
        }

    def resolve_prefix_guess(self, phonenumber, annotations):
        d = self.network_prefix_lookup(
            phonenumber, self.network_prefix_mapping)
        d.addCallback(lambda network: {
            'network': network,
            'strategy': 'prefix-guess',
            'entry': annotations,
        })
        return d

    def annotate(self, phonenumber, key, value, timestamp):
        d = maybeDeferred(self.validate_annotate_key, key)
        d.addCallback(lambda key: self.redis.hmset(
            self.key(as_msisdn(phonenumber)), {
                key: value,
                '%s-timestamp' % (key,): self.to_utc(timestamp).isoformat(),
            }))
        return d

    def get_annotations(self, phonenumber):
        return self.redis.hgetall(self.key(as_msisdn(phonenumber)))

    def remove_annotations(self, phonenumber, *keys):
        d = gatherResults([
            maybeDeferred(self.validate_annotate_key, key) for key in keys])
        d.addCallback(lambda keys: keys + [
            '%s-timestamp' % (key,) for key in keys])
        d.addCallback(lambda keys: self.redis.hdel(
            self.key(as_msisdn(phonenumber)), keys))
        return d

    def read_annotation(self, phonenumber, key):
        d = maybeDeferred(self.validate_annotate_key, key)
        d.addCallback(lambda key: [key, '%s-timestamp' % (key,)])
        d.addCallback(
            lambda keys: self.redis.hmget(
                self.key(as_msisdn(phonenumber)), keys))
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
