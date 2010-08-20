"""
Scrapy Shell

See documentation in docs/topics/shell.rst
"""

import os
import urllib
import urlparse
import signal

from twisted.internet import reactor, threads
from twisted.python.failure import Failure

from scrapy import log
from scrapy.spider import BaseSpider, spiders
from scrapy.selector import XmlXPathSelector, HtmlXPathSelector
from scrapy.utils.misc import load_object
from scrapy.utils.response import open_in_browser
from scrapy.utils.console import start_python_console
from scrapy.conf import settings
from scrapy.core.manager import scrapymanager
from scrapy.core.queue import KeepAliveExecutionQueue
from scrapy.http import Request, TextResponse

def relevant_var(varname):
    return varname not in ['shelp', 'fetch', 'view', '__builtins__', 'In', \
        'Out', 'help', 'namespace'] and not varname.startswith('_')

def parse_url(url):
    """Parse url which can be a direct path to a direct file"""
    url = url.strip()
    if url:
        u = urlparse.urlparse(url)
        if not u.scheme:
            path = os.path.abspath(url).replace(os.sep, '/')
            url = 'file://' + urllib.pathname2url(path)
            u = urlparse.urlparse(url)
    return url


class Shell(object):

    def __init__(self, update_vars=None, nofetch=False):
        self.vars = {}
        self.update_vars = update_vars
        self.item_class = load_object(settings['DEFAULT_ITEM_CLASS'])
        self.nofetch = nofetch

    def fetch(self, request_or_url, print_help=False):
        if isinstance(request_or_url, Request):
            request = request_or_url
            url = request.url
        else:
            url = parse_url(request_or_url)
            request = Request(url, dont_filter=True)

        spider = spiders.create_for_request(request, BaseSpider('default'), \
            log_multiple=True)

        print "Fetching %s..." % request
        scrapymanager.engine.open_spider(spider)
        response = None
        try:
            response = threads.blockingCallFromThread(reactor, \
                scrapymanager.engine.schedule, request, spider)
        except:
            log.err(Failure(), "Error fetching response", spider=spider)
        self.populate_vars(url, response, request, spider)
        if print_help:
            self.print_help()
        else:
            print "Done - use shelp() to see available objects"

    def populate_vars(self, url=None, response=None, request=None, spider=None):
        item = self.item_class()
        self.vars['item'] = item
        if url:
            if isinstance(response, TextResponse):
                self.vars['xxs'] = XmlXPathSelector(response)
                self.vars['hxs'] = HtmlXPathSelector(response)
            self.vars['url'] = url
            self.vars['response'] = response
            self.vars['request'] = request
            self.vars['spider'] = spider
        if not self.nofetch:
            self.vars['fetch'] = self.fetch
        self.vars['view'] = open_in_browser
        self.vars['shelp'] = self.print_help

        if self.update_vars:
            self.update_vars(self.vars)

    def print_help(self):
        print
        print "Available objects:"
        for k, v in self.vars.iteritems():
            if relevant_var(k):
                print "  %-10s %s" % (k, v)
        print
        print "Convenient shortcuts:"
        print "  shelp()           Print this help"
        if not self.nofetch:
            print "  fetch(req_or_url) Fetch a new request or URL and update shell objects"
        print "  view(response)    View response in a browser"
        print

    def start(self, url):
        # disable accidental Ctrl-C key press from shutting down the engine
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        reactor.callInThread(self._console_thread, url)
        scrapymanager.queue = KeepAliveExecutionQueue()
        scrapymanager.start()

    def inspect_response(self, response):
        print
        print "Scrapy Shell - inspecting response: %s" % response
        print "Use shelp() to see available objects"
        print
        request = response.request
        url = request.url
        self.populate_vars(url, response, request)
        start_python_console(self.vars)

    def _console_thread(self, url=None):
        self.populate_vars()
        if url:
            result = self.fetch(url, print_help=True)
        else:
            self.print_help()
        start_python_console(self.vars)
        reactor.callFromThread(scrapymanager.stop)

def inspect_response(response):
    """Open a shell to inspect the given response"""
    Shell(nofetch=True).inspect_response(response)
