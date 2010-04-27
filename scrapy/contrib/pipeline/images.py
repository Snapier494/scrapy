"""
Images Pipeline

See documentation in topics/images.rst
"""

from __future__ import with_statement
import os
import time
import hashlib
import urlparse
import rfc822
import Image
from cStringIO import StringIO
from collections import defaultdict

from twisted.internet import defer

from scrapy.xlib.pydispatch import dispatcher
from scrapy import log
from scrapy.stats import stats
from scrapy.utils.misc import md5sum
from scrapy.core import signals
from scrapy.core.engine import scrapyengine
from scrapy.core.exceptions import DropItem, NotConfigured, IgnoreRequest
from scrapy.spider import BaseSpider
from scrapy.contrib.pipeline.media import MediaPipeline
from scrapy.http import Request
from scrapy.conf import settings


class NoimagesDrop(DropItem):
    """Product with no images exception"""

class ImageException(Exception):
    """General image error exception"""


class FSImagesStore(object):

    def __init__(self, basedir):
        if '://' in basedir:
            basedir = basedir.split('://', 1)[1]
        self.basedir = basedir
        self._mkdir(self.basedir)
        self.created_directories = defaultdict(set)
        dispatcher.connect(self.spider_closed, signals.spider_closed)

    def spider_closed(self, spider):
        self.created_directories.pop(spider.name, None)

    def persist_image(self, key, image, buf, info):
        absolute_path = self._get_filesystem_path(key)
        self._mkdir(os.path.dirname(absolute_path), info)
        image.save(absolute_path)

    def stat_image(self, key, info):
        absolute_path = self._get_filesystem_path(key)
        try:
            last_modified = os.path.getmtime(absolute_path)
        except: # FIXME: catching everything!
            return {}

        with open(absolute_path, 'rb') as imagefile:
            checksum = md5sum(imagefile)

        return {'last_modified': last_modified, 'checksum': checksum}

    def _get_filesystem_path(self, key):
        path_comps = key.split('/')
        return os.path.join(self.basedir, *path_comps)

    def _mkdir(self, dirname, domain=None):
        seen = self.created_directories[domain] if domain else set()
        if dirname not in seen:
            if not os.path.exists(dirname):
                os.makedirs(dirname)
            seen.add(dirname)


class _S3AmazonAWSSpider(BaseSpider):
    """This spider is used for uploading images to Amazon S3

    It is basically not a crawling spider like a normal spider is, this spider is
    a placeholder that allows us to open a different slot in downloader and use it
    for uploads to S3.

    The use of another downloader slot for S3 images avoid the effect of normal
    spider downloader slot to be affected by requests to a complete different
    domain (s3.amazonaws.com).

    It means that a spider that uses download_delay or alike is not going to be
    delayed even more because it is uploading images to s3.
    """
    name = "s3.amazonaws.com"
    start_urls = ['http://s3.amazonaws.com/']
    max_concurrent_requests = 100


class S3ImagesStore(object):

    request_priority = 1000

    def __init__(self, uri):
        assert uri.startswith('s3://')
        self.bucket, self.prefix = uri[5:].split('/', 1)
        self._set_custom_spider()

    def _set_custom_spider(self):
        use_custom_spider = bool(settings['IMAGES_S3STORE_SPIDER'])
        if use_custom_spider:
            self.s3_spider = _S3AmazonAWSSpider()
        else:
            self.s3_spider = None

    def stat_image(self, key, info):
        def _onsuccess(response):
            if response.status == 200:
                checksum = response.headers['Etag'].strip('"')
                last_modified = response.headers['Last-Modified']
                modified_tuple = rfc822.parsedate_tz(last_modified)
                modified_stamp = int(rfc822.mktime_tz(modified_tuple))
                return {'checksum': checksum, 'last_modified': modified_stamp}

        req = self._build_request(key, method='HEAD')
        return self._download_request(req, info).addCallback(_onsuccess)

    def persist_image(self, key, image, buf, info):
        """Upload image to S3 storage"""
        width, height = image.size
        headers = {
                'Content-Type': 'image/jpeg',
                'X-Amz-Acl': 'public-read',
                'X-Amz-Meta-Width': str(width),
                'X-Amz-Meta-Height': str(height),
                'Cache-Control': 'max-age=172800',
                }

        buf.seek(0)
        req = self._build_request(key, method='PUT', body=buf.read(), headers=headers)
        return self._download_request(req, info)

    def _build_request(self, key, method, body=None, headers=None):
        url = 'http://%s.s3.amazonaws.com/%s%s' % (self.bucket, self.prefix, key)
        return Request(url, method=method, body=body, headers=headers, \
                meta={'sign_s3_request': True}, priority=self.request_priority)

    def _download_request(self, request, info):
        """This method is used for HEAD and PUT requests sent to amazon S3

        It tries to use a specific spider domain for uploads, or defaults
        to current domain spider.
        """
        if self.s3_spider:
            # need to use schedule to auto-open domain
            return scrapyengine.schedule(request, self.s3_spider)
        return scrapyengine.download(request, info.spider)


class ImagesPipeline(MediaPipeline):
    """Abstract pipeline that implement the image downloading and thumbnail generation logic

    This pipeline tries to minimize network transfers and image processing,
    doing stat of the images and determining if image is new, uptodate or
    expired.

    `new` images are those that pipeline never processed and needs to be
        downloaded from supplier site the first time.

    `uptodate` images are the ones that the pipeline processed and are still
        valid images.

    `expired` images are those that pipeline already processed but the last
        modification was made long time ago, so a reprocessing is recommended to
        refresh it in case of change.

    """

    MEDIA_NAME = 'image'
    MIN_WIDTH = settings.getint('IMAGES_MIN_WIDTH', 0)
    MIN_HEIGHT = settings.getint('IMAGES_MIN_HEIGHT', 0)
    EXPIRES = settings.getint('IMAGES_EXPIRES', 90)
    THUMBS = settings.get('IMAGES_THUMBS', {})
    STORE_SCHEMES = {
            '': FSImagesStore,
            'file': FSImagesStore,
            's3': S3ImagesStore,
            }

    def __init__(self):
        store_uri = settings['IMAGES_STORE']
        if not store_uri:
            raise NotConfigured
        self.store = self._get_store(store_uri)
        super(ImagesPipeline, self).__init__()

    def _get_store(self, uri):
        if os.path.isabs(uri): # to support win32 paths like: C:\\some\dir
            scheme = 'file'
        else:
            scheme = urlparse.urlparse(uri).scheme
        store_cls = self.STORE_SCHEMES[scheme]
        return store_cls(uri)

    def media_downloaded(self, response, request, info):
        referer = request.headers.get('Referer')

        if response.status != 200:
            log.msg('Image (http-error): Error downloading image from %s referred in <%s>' \
                    % (request, referer), level=log.WARNING, spider=info.spider)
            raise ImageException

        if not response.body:
            log.msg('Image (empty-content): Empty image from %s referred in <%s>: no-content' \
                    % (request, referer), level=log.WARNING, spider=info.spider)
            raise ImageException

        status = 'cached' if 'cached' in response.flags else 'downloaded'
        msg = 'Image (%s): Downloaded image from %s referred in <%s>' % \
                (status, request, referer)
        log.msg(msg, level=log.DEBUG, spider=info.spider)
        self.inc_stats(info.spider, status)

        try:
            key = self.image_key(request.url)
            checksum = self.image_downloaded(response, request, info)
        except ImageException, ex:
            log.msg(str(ex), level=log.WARNING, spider=info.spider)
            raise
        except Exception:
            log.err(spider=info.spider)
            raise ImageException

        return {'url': request.url, 'path': key, 'checksum': checksum}

    def media_failed(self, failure, request, info):
        if not isinstance(failure.value, IgnoreRequest):
            referer = request.headers.get('Referer')
            msg = 'Image (unknown-error): Error downloading %s from %s referred in <%s>: %s' \
                    % (self.MEDIA_NAME, request, referer, str(failure))
            log.msg(msg, level=log.WARNING, spider=info.spider)
        raise ImageException

    def media_to_download(self, request, info):
        def _onsuccess(result):
            if not result:
                return # returning None force download

            last_modified = result.get('last_modified', None)
            if not last_modified:
                return # returning None force download

            age_seconds = time.time() - last_modified
            age_days = age_seconds / 60 / 60 / 24
            if age_days > self.EXPIRES:
                return # returning None force download

            referer = request.headers.get('Referer')
            log.msg('Image (uptodate): Downloaded %s from <%s> referred in <%s>' % \
                    (self.MEDIA_NAME, request.url, referer), level=log.DEBUG, spider=info.spider)
            self.inc_stats(info.spider, 'uptodate')

            checksum = result.get('checksum', None)
            return {'url': request.url, 'path': key, 'checksum': checksum}

        key = self.image_key(request.url)
        dfd = defer.maybeDeferred(self.store.stat_image, key, info)
        dfd.addCallbacks(_onsuccess, lambda _:None)
        dfd.addErrback(log.err, self.__class__.__name__ + '.store.stat_image')
        return dfd

    def image_downloaded(self, response, request, info):
        first_buf = None
        for key, image, buf in self.get_images(response, request, info):
            self.store.persist_image(key, image, buf, info)
            if first_buf is None:
                first_buf = buf
        first_buf.seek(0)
        return md5sum(first_buf)

    def get_images(self, response, request, info):
        key = self.image_key(request.url)
        orig_image = Image.open(StringIO(response.body))

        width, height = orig_image.size
        if width < self.MIN_WIDTH or height < self.MIN_HEIGHT:
            raise ImageException("Image too small (%dx%d < %dx%d): %s" % \
                    (width, height, self.MIN_WIDTH, self.MIN_HEIGHT, response.url))

        image, buf = self.convert_image(orig_image)
        yield key, image, buf

        for thumb_id, size in self.THUMBS.iteritems():
            thumb_key = self.thumb_key(request.url, thumb_id)
            thumb_image, thumb_buf = self.convert_image(image, size)
            yield thumb_key, thumb_image, thumb_buf

    def inc_stats(self, spider, status):
        stats.inc_value('image_count', spider=spider)
        stats.inc_value('image_status_count/%s' % status, spider=spider)

    def convert_image(self, image, size=None):
        if image.mode != 'RGB':
            image = image.convert('RGB')

        if size:
            image = image.copy()
            image.thumbnail(size, Image.ANTIALIAS)

        buf = StringIO()
        try:
            image.save(buf, 'JPEG')
        except Exception, ex:
            raise ImageException("Cannot process image. Error: %s" % ex)

        return image, buf

    def image_key(self, url):
        image_guid = hashlib.sha1(url).hexdigest()
        return 'full/%s.jpg' % (image_guid)

    def thumb_key(self, url, thumb_id):
        image_guid = hashlib.sha1(url).hexdigest()
        return 'thumbs/%s/%s.jpg' % (thumb_id, image_guid)
