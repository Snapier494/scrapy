"""
This module implements the FormRequest class which is a more covenient class
(than Request) to generate Requests based on form data.

See documentation in docs/ref/request-response.rst
"""

import urllib
from cStringIO import StringIO

from ClientForm import ParseFile

from scrapy.http.request import Request
from scrapy.utils.python import unicode_to_str

def _unicode_to_str(string, encoding):
    if hasattr(string, '__iter__'):
        return [unicode_to_str(k, encoding) for k in string]
    else:
        return unicode_to_str(string, encoding)


class FormRequest(Request):

    def __init__(self, *args, **kwargs):
        formdata = kwargs.pop('formdata', None)
        Request.__init__(self, *args, **kwargs)

        if formdata:
            items = formdata.iteritems() if isinstance(formdata, dict) else formdata
            query = [(unicode_to_str(k, self.encoding), _unicode_to_str(v, self.encoding))
                    for k, v in items]
            self.body = urllib.urlencode(query, doseq=1)
            self.headers['Content-Type'] = 'application/x-www-form-urlencoded'

    @classmethod
    def from_response(cls, response, formnumber=0, formdata=None, **kwargs):
        encoding = getattr(response, 'encoding', 'utf-8')
        forms = ParseFile(StringIO(response.body), response.url,
                          encoding=encoding, backwards_compat=False)
        if not forms:
            raise ValueError("No <form> element found in %s" % response)
        try:
            form = forms[formnumber]
        except IndexError:
            raise IndexError("Form number %d not found in %s" % (formnumber, response))
        if formdata:
            # remove all existing fields with the same name before, so that
            # formdata fields properly can properly override existing ones,
            # which is the desired behaviour
            form.controls = [c for c in form.controls if c.name not in formdata.keys()]
            for k, v in formdata.iteritems():
                for v2 in v if hasattr(v, '__iter__') else [v]:
                    form.new_control('text', k, {'value': v2})
                    
        url, body, headers = form.click_request_data()       
        request = cls(url, method=form.method, body=body, headers=headers, **kwargs)
        return request
