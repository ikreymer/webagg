import re
import six
import string
import yaml
import os

from contextlib import closing

from pywb.utils.timeutils import timestamp_to_http_date
from pywb.utils.wbexception import BadRequestException

LINK_SPLIT = re.compile(',\s*(?=[<])')
LINK_SEG_SPLIT = re.compile(';\s*')
LINK_URL = re.compile('<(.*)>')
LINK_PROP = re.compile('([\w]+)="([^"]+)')

BUFF_SIZE = 16384


#=============================================================================
class MementoException(BadRequestException):
    pass


#=============================================================================
class MementoUtils(object):
    @staticmethod
    def parse_links(link_header, def_name='timemap'):
        links = LINK_SPLIT.split(link_header)
        results = {}
        mementos = []

        for link in links:
            props = LINK_SEG_SPLIT.split(link)
            m = LINK_URL.match(props[0])
            if not m:
                raise MementoException('Invalid Link Url: ' + props[0])

            result = dict(url=m.group(1))
            key = ''
            is_mem = False

            for prop in props[1:]:
                m = LINK_PROP.match(prop)
                if not m:
                    raise MementoException('Invalid prop ' + prop)

                name = m.group(1)
                value = m.group(2)

                if name == 'rel':
                    if 'memento' in value:
                        is_mem = True
                        result[name] = value
                    elif value == 'self':
                        key = def_name
                    else:
                        key = value
                else:
                    result[name] = value

            if key:
                results[key] = result
            elif is_mem:
                mementos.append(result)

        results['mementos'] = mementos
        return results

    @staticmethod
    def make_timemap_memento_link(cdx, datetime=None, rel='memento', end=',\n'):
        url = cdx.get('load_url')
        if not url:
            url = 'file://{0}:{1}:{2}'.format(cdx.get('filename'), cdx.get('offset'), cdx.get('length'))

        memento = '<{0}>; rel="{1}"; datetime="{2}"; src="{3}"' + end

        if not datetime:
            datetime = timestamp_to_http_date(cdx['timestamp'])

        return memento.format(url, rel, datetime, cdx.get('source', ''))


    @staticmethod
    def make_timemap(cdx_iter):
        # get first memento as it'll be used for 'from' field
        try:
            first_cdx = six.next(cdx_iter)
            from_date = timestamp_to_http_date(first_cdx['timestamp'])
        except StopIteration:
            first_cdx = None
            return

        # first memento link
        yield MementoUtils.make_timemap_memento_link(first_cdx, datetime=from_date)

        prev_cdx = None

        for cdx in cdx_iter:
            if prev_cdx:
                yield MementoUtils.make_timemap_memento_link(prev_cdx)

            prev_cdx = cdx

        # last memento link, if any
        if prev_cdx:
            yield MementoUtils.make_timemap_memento_link(prev_cdx, end='\n')

    @staticmethod
    def make_link(url, type):
        return '<{0}>; rel="{1}"'.format(url, type)


#=============================================================================
class ParamFormatter(string.Formatter):
    def __init__(self, params, name='', prefix='param.'):
        self.params = params
        self.prefix = prefix
        self.name = name

    def get_value(self, key, args, kwargs):
        # First, try the named param 'param.{name}.{key}'
        if self.name:
            named_key = self.prefix + self.name + '.' + key
            value = self.params.get(named_key)
            if value is not None:
                return value

        # Then, try 'param.{key}'
        named_key = self.prefix + key
        value = self.params.get(named_key)
        if value is not None:
            return value

        # default to just '{key}'
        value = kwargs.get(key, '')
        return value


#=============================================================================
def res_template(template, params, **extra_params):
    formatter = params.get('_formatter')
    if not formatter:
        formatter = ParamFormatter(params)
    res = formatter.format(template, url=params.get('url', ''), **extra_params)

    return res


#=============================================================================
def StreamIter(stream, header1=None, header2=None, size=BUFF_SIZE):
    with closing(stream):
        if header1:
            yield header1

        if header2:
            yield header2

        while True:
            buff = stream.read(size)
            if not buff:
                break
            yield buff


#=============================================================================
def chunk_encode_iter(orig_iter):
    for chunk in orig_iter:
        if not len(chunk):
            continue
        chunk_len = b'%X\r\n' % len(chunk)
        yield chunk_len
        yield chunk
        yield b'\r\n'

    yield b'0\r\n\r\n'


#=============================================================================
def load_config(main_env_var, main_default_file='',
                overlay_env_var='', overlay_file=''):

    configfile = os.environ.get(main_env_var, main_default_file)

    if configfile:
        # Load config
        with open(configfile, 'rb') as fh:
            config = yaml.load(fh)

    else:
        config = {}

    overlay_configfile = os.environ.get(overlay_env_var, overlay_file)

    if overlay_configfile:
        with open(overlay_configfile, 'rb') as fh:
            config.update(yaml.load(fh))

    return config

