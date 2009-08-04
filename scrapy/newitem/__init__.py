from UserDict import DictMixin

from scrapy.item.models import BaseItem

class Field(dict):
    pass

class _ItemMeta(type):

    def __new__(mcs, class_name, bases, attrs):
        fields = {}
        new_attrs = {}
        for n, v in attrs.iteritems():
            if isinstance(v, Field):
                fields[n] = v
            else:
                new_attrs[n] = v

        cls = type.__new__(mcs, class_name, bases, new_attrs)
        cls.fields = cls.fields.copy()
        cls.fields.update(fields)
        return cls


class Item(DictMixin, BaseItem):

    __metaclass__ = _ItemMeta

    fields = {}

    def __init__(self, *args, **kwargs):
        self._values = {}

        if args or kwargs: # don't instantiate dict for simple (most common) case
            for k, v in dict(*args, **kwargs).iteritems():
                self[k] = v

    def __getitem__(self, key):
        try:
            return self._values[key]
        except KeyError:
            field = self.fields[key]
            default_factory = field.get('default_factory')
            if default_factory:
                return default_factory()
            else:
                raise KeyError(key)

    def __setitem__(self, key, value):
        if key in self.fields:
            self._values[key] = value
        else:
            raise KeyError("%s does not support field: %s" % \
                (self.__class__.__name__, key))

    def __delitem__(self, key):
        del self._values[key]

    def __getattr__(self, name):
        if name in self.fields:
            raise AttributeError("Use [%r] to access item field value" % name)
        raise AttributeError(name)

    def keys(self):
        return self._values.keys()

    def __repr__(self):
        """Generate a representation of this item that can be used to
        reconstruct the item by evaluating it
        """
        values = ', '.join('%s=%r' % field for field in self.iteritems())
        return "%s(%s)" % (self.__class__.__name__, values)

    def get_id(self):
        """Returns the unique id for this item."""
        raise NotImplementedError

