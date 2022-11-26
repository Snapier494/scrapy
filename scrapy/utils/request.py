"""
This module provides some useful functions for working with
scrapy.http.Request objects
"""

import hashlib
import json
import warnings
from typing import Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlunparse
from weakref import WeakKeyDictionary

from w3lib.http import basic_auth_header
from w3lib.url import canonicalize_url

from scrapy import Request, Spider
from scrapy.exceptions import ScrapyDeprecationWarning
from scrapy.utils.httpobj import urlparse_cached
from scrapy.utils.misc import load_object
from scrapy.utils.python import to_bytes, to_unicode


_deprecated_fingerprint_cache: "WeakKeyDictionary[Request, Dict[Tuple[Optional[Tuple[bytes, ...]], bool], str]]"
_deprecated_fingerprint_cache = WeakKeyDictionary()


def _serialize_headers(headers, request):
    for header in headers:
        if header in request.headers:
            yield header
            for value in request.headers.getlist(header):
                yield value


def request_fingerprint(
    request: Request,
    include_headers: Optional[Iterable[Union[bytes, str]]] = None,
    keep_fragments: bool = False,
) -> str:
    """
    Return the request fingerprint as an hexadecimal string.

    The request fingerprint is a hash that uniquely identifies the resource the
    request points to. For example, take the following two urls:

    http://www.example.com/query?id=111&cat=222
    http://www.example.com/query?cat=222&id=111

    Even though those are two different URLs both point to the same resource
    and are equivalent (i.e. they should return the same response).

    Another example are cookies used to store session ids. Suppose the
    following page is only accessible to authenticated users:

    http://www.example.com/members/offers.html

    Lots of sites use a cookie to store the session id, which adds a random
    component to the HTTP Request and thus should be ignored when calculating
    the fingerprint.

    For this reason, request headers are ignored by default when calculating
    the fingerprint. If you want to include specific headers use the
    include_headers argument, which is a list of Request headers to include.

    Also, servers usually ignore fragments in urls when handling requests,
    so they are also ignored by default when calculating the fingerprint.
    If you want to include them, set the keep_fragments argument to True
    (for instance when handling requests with a headless browser).
    """
    if include_headers or keep_fragments:
        message = (
            'Call to deprecated function '
            'scrapy.utils.request.request_fingerprint().\n'
            '\n'
            'If you are using this function in a Scrapy component because you '
            'need a non-default fingerprinting algorithm, and you are OK '
            'with that non-default fingerprinting algorithm being used by '
            'all Scrapy components and not just the one calling this '
            'function, use crawler.request_fingerprinter.fingerprint() '
            'instead in your Scrapy component (you can get the crawler '
            'object from the \'from_crawler\' class method), and use the '
            '\'REQUEST_FINGERPRINTER_CLASS\' setting to configure your '
            'non-default fingerprinting algorithm.\n'
            '\n'
            'Otherwise, consider using the '
            'scrapy.utils.request.fingerprint() function instead.\n'
            '\n'
            'If you switch to \'fingerprint()\', or assign the '
            '\'REQUEST_FINGERPRINTER_CLASS\' setting a class that uses '
            '\'fingerprint()\', the generated fingerprints will not only be '
            'bytes instead of a string, but they will also be different from '
            'those generated by \'request_fingerprint()\'. Before you switch, '
            'make sure that you understand the consequences of this (e.g. '
            'cache invalidation) and are OK with them; otherwise, consider '
            'implementing your own function which returns the same '
            'fingerprints as the deprecated \'request_fingerprint()\' function.'
        )
    else:
        message = (
            'Call to deprecated function '
            'scrapy.utils.request.request_fingerprint().\n'
            '\n'
            'If you are using this function in a Scrapy component, and you '
            'are OK with users of your component changing the fingerprinting '
            'algorithm through settings, use '
            'crawler.request_fingerprinter.fingerprint() instead in your '
            'Scrapy component (you can get the crawler object from the '
            '\'from_crawler\' class method).\n'
            '\n'
            'Otherwise, consider using the '
            'scrapy.utils.request.fingerprint() function instead.\n'
            '\n'
            'Either way, the resulting fingerprints will be returned as '
            'bytes, not as a string, and they will also be different from '
            'those generated by \'request_fingerprint()\'. Before you switch, '
            'make sure that you understand the consequences of this (e.g. '
            'cache invalidation) and are OK with them; otherwise, consider '
            'implementing your own function which returns the same '
            'fingerprints as the deprecated \'request_fingerprint()\' function.'
        )
    warnings.warn(message, category=ScrapyDeprecationWarning, stacklevel=2)
    processed_include_headers: Optional[Tuple[bytes, ...]] = None
    if include_headers:
        processed_include_headers = tuple(
            to_bytes(h.lower()) for h in sorted(include_headers)
        )
    cache = _deprecated_fingerprint_cache.setdefault(request, {})
    cache_key = (processed_include_headers, keep_fragments)
    if cache_key not in cache:
        fp = hashlib.sha1()
        fp.update(to_bytes(request.method))
        fp.update(to_bytes(canonicalize_url(request.url, keep_fragments=keep_fragments)))
        fp.update(request.body or b'')
        if processed_include_headers:
            for part in _serialize_headers(processed_include_headers, request):
                fp.update(part)
        cache[cache_key] = fp.hexdigest()
    return cache[cache_key]


def _request_fingerprint_as_bytes(*args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return bytes.fromhex(request_fingerprint(*args, **kwargs))


_fingerprint_cache: "WeakKeyDictionary[Request, Dict[Tuple[Optional[Tuple[bytes, ...]], bool], bytes]]"
_fingerprint_cache = WeakKeyDictionary()


def fingerprint(
    request: Request,
    *,
    include_headers: Optional[Iterable[Union[bytes, str]]] = None,
    keep_fragments: bool = False,
) -> bytes:
    """
    Return the request fingerprint.

    The request fingerprint is a hash that uniquely identifies the resource the
    request points to. For example, take the following two urls:

    http://www.example.com/query?id=111&cat=222
    http://www.example.com/query?cat=222&id=111

    Even though those are two different URLs both point to the same resource
    and are equivalent (i.e. they should return the same response).

    Another example are cookies used to store session ids. Suppose the
    following page is only accessible to authenticated users:

    http://www.example.com/members/offers.html

    Lots of sites use a cookie to store the session id, which adds a random
    component to the HTTP Request and thus should be ignored when calculating
    the fingerprint.

    For this reason, request headers are ignored by default when calculating
    the fingerprint. If you want to include specific headers use the
    include_headers argument, which is a list of Request headers to include.

    Also, servers usually ignore fragments in urls when handling requests,
    so they are also ignored by default when calculating the fingerprint.
    If you want to include them, set the keep_fragments argument to True
    (for instance when handling requests with a headless browser).
    """
    processed_include_headers: Optional[Tuple[bytes, ...]] = None
    if include_headers:
        processed_include_headers = tuple(
            to_bytes(h.lower()) for h in sorted(include_headers)
        )
    cache = _fingerprint_cache.setdefault(request, {})
    cache_key = (processed_include_headers, keep_fragments)
    if cache_key not in cache:
        # To decode bytes reliably (JSON does not support bytes), regardless of
        # character encoding, we use bytes.hex()
        headers: Dict[str, List[str]] = {}
        if processed_include_headers:
            for header in processed_include_headers:
                if header in request.headers:
                    headers[header.hex()] = [
                        header_value.hex()
                        for header_value in request.headers.getlist(header)
                    ]
        fingerprint_data = {
            'method': to_unicode(request.method),
            'url': canonicalize_url(request.url, keep_fragments=keep_fragments),
            'body': (request.body or b'').hex(),
            'headers': headers,
        }
        fingerprint_json = json.dumps(fingerprint_data, sort_keys=True)
        cache[cache_key] = hashlib.sha1(fingerprint_json.encode()).digest()
    return cache[cache_key]


class RequestFingerprinter:
    """Default fingerprinter.

    It takes into account a canonical version
    (:func:`w3lib.url.canonicalize_url`) of :attr:`request.url
    <scrapy.http.Request.url>` and the values of :attr:`request.method
    <scrapy.http.Request.method>` and :attr:`request.body
    <scrapy.http.Request.body>`. It then generates an `SHA1
    <https://en.wikipedia.org/wiki/SHA-1>`_ hash.

    .. seealso:: :setting:`REQUEST_FINGERPRINTER_IMPLEMENTATION`.
    """

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def __init__(self, crawler=None):
        if crawler:
            implementation = crawler.settings.get(
                'REQUEST_FINGERPRINTER_IMPLEMENTATION'
            )
        else:
            implementation = '2.6'
        if implementation == '2.6':
            message = (
                '\'2.6\' is a deprecated value for the '
                '\'REQUEST_FINGERPRINTER_IMPLEMENTATION\' setting.\n'
                '\n'
                'It is also the default value. In other words, it is normal '
                'to get this warning if you have not defined a value for the '
                '\'REQUEST_FINGERPRINTER_IMPLEMENTATION\' setting. This is so '
                'for backward compatibility reasons, but it will change in a '
                'future version of Scrapy.\n'
                '\n'
                'See the documentation of the '
                '\'REQUEST_FINGERPRINTER_IMPLEMENTATION\' setting for '
                'information on how to handle this deprecation.'
            )
            warnings.warn(message, category=ScrapyDeprecationWarning, stacklevel=2)
            self._fingerprint = _request_fingerprint_as_bytes
        elif implementation == '2.7':
            self._fingerprint = fingerprint
        else:
            raise ValueError(
                f'Got an invalid value on setting '
                f'\'REQUEST_FINGERPRINTER_IMPLEMENTATION\': '
                f'{implementation!r}. Valid values are \'2.6\' (deprecated) '
                f'and \'2.7\'.'
            )

    def fingerprint(self, request: Request):
        return self._fingerprint(request)


def request_authenticate(
    request: Request,
    username: str,
    password: str,
) -> None:
    """Authenticate the given request (in place) using the HTTP basic access
    authentication mechanism (RFC 2617) and the given username and password
    """
    request.headers['Authorization'] = basic_auth_header(username, password)


def request_httprepr(request: Request) -> bytes:
    """Return the raw HTTP representation (as bytes) of the given request.
    This is provided only for reference since it's not the actual stream of
    bytes that will be send when performing the request (that's controlled
    by Twisted).
    """
    parsed = urlparse_cached(request)
    path = urlunparse(('', '', parsed.path or '/', parsed.params, parsed.query, ''))
    s = to_bytes(request.method) + b" " + to_bytes(path) + b" HTTP/1.1\r\n"
    s += b"Host: " + to_bytes(parsed.hostname or b'') + b"\r\n"
    if request.headers:
        s += request.headers.to_string() + b"\r\n"
    s += b"\r\n"
    s += request.body
    return s


def referer_str(request: Request) -> Optional[str]:
    """ Return Referer HTTP header suitable for logging. """
    referrer = request.headers.get('Referer')
    if referrer is None:
        return referrer
    return to_unicode(referrer, errors='replace')


def request_from_dict(d: dict, *, spider: Optional[Spider] = None) -> Request:
    """Create a :class:`~scrapy.Request` object from a dict.

    If a spider is given, it will try to resolve the callbacks looking at the
    spider for methods with the same name.
    """
    request_cls = load_object(d["_class"]) if "_class" in d else Request
    kwargs = {key: value for key, value in d.items() if key in request_cls.attributes}
    if d.get("callback") and spider:
        kwargs["callback"] = _get_method(spider, d["callback"])
    if d.get("errback") and spider:
        kwargs["errback"] = _get_method(spider, d["errback"])
    return request_cls(**kwargs)


def _get_method(obj, name):
    """Helper function for request_from_dict"""
    name = str(name)
    try:
        return getattr(obj, name)
    except AttributeError:
        raise ValueError(f"Method {name!r} not found in: {obj}")
