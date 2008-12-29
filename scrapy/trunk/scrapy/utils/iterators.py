import re, csv

from scrapy.xpath import XmlXPathSelector
from scrapy.http import Response
from scrapy import log
from scrapy.utils.python import re_rsearch, str_to_unicode, unicode_to_str

def _normalize_input(obj, unicode=True):
    assert isinstance(obj, (Response, basestring)), "obj must be Response or basestring, not %s" % type(obj).__name__
    if isinstance(obj, Response):
        return obj.body.to_unicode() if unicode else obj.body.to_string()
    elif isinstance(obj, str):
        return obj.decode('utf-8') if unicode else obj
    else:
        return obj if unicode else obj.encode('utf-8')

def xmliter(obj, nodename):
    """Return a iterator of XPathSelector's over all nodes of a XML document,
       given tha name of the node to iterate. Useful for parsing XML feeds.

    obj can be:
    - a Response object
    - a unicode string
    - a string encoded as utf-8
    """
    HEADER_START_RE = re.compile(r'^(.*?)<\s*%s(?:\s|>)' % nodename, re.S)
    HEADER_END_RE = re.compile(r'<\s*/%s\s*>' % nodename, re.S)
    text = _normalize_input(obj)

    header_start = re.search(HEADER_START_RE, text)
    header_start = header_start.group(1).strip() if header_start else ''
    header_end = re_rsearch(HEADER_END_RE, text)
    header_end = text[header_end[1]:].strip() if header_end else ''

    r = re.compile(r"<%s[\s>].*?</%s>" % (nodename, nodename), re.DOTALL)
    for match in r.finditer(text):
        nodetext = header_start + match.group() + header_end
        yield XmlXPathSelector(text=nodetext).x('//' + nodename)[0]

def csviter(obj, delimiter=None, headers=None):
    """ Returns an iterator of dictionaries from the given csv object

    obj can be:
    - a Response object
    - a unicode string
    - a string encoded as utf-8

    delimiter is the character used to separate field on the given obj.
    
    headers is an iterable that when provided offers the keys
    for the returned dictionaries, if not the first row is used.
    """
    def _getrow(csv_r):
        return [str_to_unicode(field) for field in csv_r.next()]

    lines = _normalize_input(obj, unicode=False).splitlines(True)
    if delimiter:
        csv_r = csv.reader(lines, delimiter=delimiter)
    else:
        csv_r = csv.reader(lines)

    if not headers:
        headers = _getrow(csv_r)

    while True:
        row = _getrow(csv_r)
        if len(row) != len(headers):
            log.msg("ignoring row %d (length: %d, should be: %d)" % (csv_r.line_num, len(row), len(headers)), log.WARNING)
            continue
        else:
            yield dict(zip(headers, row))

