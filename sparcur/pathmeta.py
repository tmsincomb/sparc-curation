"""
Classes for storing and converting metadata associated with a path or path like object.
"""
import pickle
import struct
from pathlib import PurePosixPath
from datetime import datetime
from dateutil import parser
from terminaltables import AsciiTable
from pyontutils.utils import TermColors as tc, isoformat
from sparcur import exceptions as exc
from sparcur.utils import log, FileSize


class PathMeta:
    """ Internal representation that every other format converts through. """

    # TODO register xattr prefixes

    @classmethod
    def from_metastore(cls, blob, prefix=None):
        """ db entry """
        xattrs = pickle.loads(blob)
        return cls.from_xattrs(xattrs, prefix)


    def __init__(self,
                 size=None,
                 created=None,
                 updated=None,
                 checksum=None,
                 etag=None,
                 chunksize=None,  # used for properly checksumming?
                 id=None,
                 file_id=None,
                 old_id=None,
                 gid=None,  # needed to determine local writability
                 user_id=None,
                 mode=None,
                 errors=tuple(),
                 **kwargs):

        if not file_id and file_id is not None and file_id is not 0:
            raise TypeError('wat')
        if created is not None and not isinstance(created, int) and not isinstance(created, datetime):
            created = parser.parse(created)

        if updated is not None and not isinstance(updated, int) and not isinstance(updated, datetime):
            updated = parser.parse(updated)

        if id is not None and not isinstance(id, str):
            # no implicit type mutation, the system providing the ids
            # is where the information about how to do the converstion lives
            # we don't handle it here
            raise TypeError(f'id must be a string! {id!r}')

        self.size = size if size is None else FileSize(size)
        self.created = created
        self.updated = updated
        self.checksum = checksum
        self.etag = etag
        self.chunksize = chunksize
        self.id = id
        self.file_id = file_id
        self.old_id = old_id
        self.gid = gid
        self.user_id = user_id
        self.mode = mode
        self.errors = tuple(errors) if errors else tuple()
        if kwargs:
            log.warning(f'Unexpected meta values! {kwargs}')
            self.__kwargs = kwargs  # roundtrip values we don't explicitly handle

    #def as_xattrs(self, prefix=None):
        #log.debug(f'{self} {prefix}')
        #embed()
        #return self._as_xattrs(self, prefix=prefix)

    def content_different(self, other):
        """ is there any evidence that the file itself changed? """
        return ((self.checksum and other.checksum and self.checksum != other.checksum) or
                self.size != other.size or
                self.updated < other.updated)

    def items(self):
        return self.__dict__.items()  # FIXME nonfields?
        #for field in self.fields:
            #yield field, getattr(self, field)

    def as_metastore(self, prefix=None):
        # FIXME prefix= is a bad api ...
        """ db entry """  # TODO json blob in sqlite? can it index?
        return pickle.dumps(self.as_xattrs(prefix))

    def keys(self):
        yield from self

    def __getitem__(self, key):
        try:
            getattr(self, key)
        except AttributeError as e:
            raise KeyError(key)

    def __iter__(self):
        yield from (k for k in self.__dict__ if not k.startswith('_'))

    def __reduce__(self):
        return (self.__class__, {k:v for k, v in self.items() if v is not None})

    def __repr__(self):
        _dict = {k:v for k, v in self.__dict__.items() if not k.startswith('_')}
        return f'{self.__class__.__name__}({_dict})'

    def __eq__(self, other):
        if isinstance(other, PathMeta):
             for field, value in self.__dict__.items():
                  if value != getattr(other, field):
                       return False
             else:
                  return True

    def __bool__(self):
        for k, v in self.__dict__.items():
            if v is not None:
                if k == 'errors' and not v:  # empty tuple ok
                    continue

                return True
        else:
            return False


class _PathMetaConverter:
    """ Base class for implementing PathMeta format converts.

        I haven't figured out how to properly abstract registering
        as_format_name and from_format_name yet, so look at one of
        the __init__ methods below to see how it is done. """

    pathmetaclass = PathMeta
    format_name = None


class _PathMetaAsSymlink(_PathMetaConverter):
    """ Convert to and from symlinks to nowhere.
        You can prepend whatever other info you want in front of this """

    format_name = 'symlink'
    empty = '#'
    fieldsep = '.'  # must match the file extension splitter for Path ...
    subfieldsep = ';'  # only one level, not going recursive in a filename ...
    versions = {'meta':('file_id',
                        'size',
                        'created',
                        'updated',
                        'checksum',
                        'old_id',
                        'gid',
                        'user_id',
                        'mode',
                        'errors',),
                'mdv1':('file_id',
                        'size',
                        'created',
                        'updated',
                        'checksum',
                        'chunksize',  # added
                        'old_id',
                        'gid',
                        'user_id',
                        'mode',
                        'errors',),
                'mdv2':('file_id',
                        'size',
                        'created',
                        'updated',
                        'checksum',
                        'etag',  # added
                        'chunksize',
                        'old_id',
                        'gid',
                        'user_id',
                        'mode',
                        'errors',),
    }
    write_version = 'mdv2'  # update this on new version
    extras = 'size.hr',

    def __init__(self):
        # register functionality on PathMeta
        def as_symlink(self, _as_symlink=self.as_symlink):
            return _as_symlink(self)

        @classmethod
        def from_symlink(cls, symlink_path, _from_symlink=self.from_symlink):
            return _from_symlink(symlink_path)

        self.pathmetaclass.as_symlink = as_symlink
        self.pathmetaclass.from_symlink = from_symlink

    @property
    def order_all(self):
        return self.versions[self.write_version] + self.extras

    def encode(self, field, value):
        if field == 'file_id':
            if not value:
                if value is not None:
                    log.critical(f'{value!r} for file_id empty but not None!')
                value = None

        if value is None:
            return self.empty

        if field in ('errors',):
            return self.subfieldsep.join(value)

        if field == 'checksum':
            return value.hex()  # raw hex may contain field separators :/

        return _str_encode(field, value)

    def decode(self, field, value):
        if value == self.empty:
            return None

        if field == 'errors':
            return [_ for _ in value.split(self.subfieldsep) if _]

        elif field in ('created', 'updated'):
            return parser.parse(value)

        elif field == 'checksum':  # FIXME checksum encoding ...
            #return value.encode()
            return bytes.fromhex(value)

        elif field == 'etag':
            checksum, strcount = value.rsplit('-', 1)
            count = int(strcount)
            return bytes.fromhex(checksum), count

        elif field == 'user_id':
            try:
                return int(value)
            except ValueError:  # FIXME :/ uid vs owner_id etc ...
                return value

        elif field in ('id', 'mode', 'old_id'):
            return value

        else:
            try:
                return int(value)
            except ValueError as e:
                breakpoint()
                raise e

        return value

    def as_symlink(self, pathmeta):
        """ encode meta as a relative path to be appended as a child, not a sibbling """

        __ignoreme = object()

        def multigetattr(object, attr, default=__ignoreme):
            rest = None
            if '.' in attr:
                first, attr = attr.split('.')
                object = multigetattr(object, first, default=default)

            if default != __ignoreme:
                return getattr(object, attr, default)
            else:
                return getattr(object, attr)


        gen = (self.encode(field, multigetattr(pathmeta, field, None))
               for field in self.order_all)

        id = self.encode('id', pathmeta.id)

        return PurePosixPath(id + f'/.{self.write_version}.' + self.fieldsep.join(gen))

    def from_symlink(self, symlink_path):
        """ contextual portion to make sure something weird isn't going on
            e.g. that a link got switched to point to another name somehow """
        pure_symlink = symlink_path.readlink()
        name, *parts = pure_symlink.parts
        msg = (symlink_path.name, name)
        assert symlink_path.name == name, msg
        return self.from_parts(parts)

    def from_parts(self, parts):
        data = parts[-1]
        _, version, *suffixes = data.split(self.fieldsep)
        order = self.versions[version]
        kwargs = {field:self.decode(field, value)
                  for field, value in zip(order, suffixes)}
        path = PurePosixPath(*parts)
        kwargs['id'] = str(path.parent)
        return self.pathmetaclass(**kwargs)


class _PathMetaAsXattrs(_PathMetaConverter):
    """ Convert to and from unix xattrs. """

    format_name = 'xattrs'

    fields = ('size',
              'created',
              'updated',
              'checksum',
              'etag',
              'chunksize',
              'id',
              'file_id',
              'old_id',
              'gid',
              'user_id',
              'mode',
              'errors')

    def __init__(self):
        # register functionality on PathMeta
        def as_xattrs(self, prefix=None, _as_xattrs=self.as_xattrs):
            #log.debug(f'{self} {prefix}')
            return _as_xattrs(self, prefix=prefix)

        # as a note: information hiding in python is ... weird ...
        # even when that isn't what you set out to do ...
        @classmethod
        def from_xattrs(cls, xattrs, prefix=None, path_object=None, _from_xattrs=self.from_xattrs):
            # FIXME cls(**kwargs) vs calling self.pathmetaclass
            return _from_xattrs(xattrs, prefix=prefix, path_object=path_object)

        self.pathmetaclass.as_xattrs = as_xattrs
        self.pathmetaclass.from_xattrs = from_xattrs

    @staticmethod
    def deprefix(string, prefix):
        if string.startswith(prefix):
            string = string[len(prefix):]

        # deal with normalizing old form here until it is all cleaned up
        if prefix == 'bf.':
            if string.endswith('_at'):
                string = string[:-3]

        return string

    def from_xattrs(self, xattrs, prefix=None, path_object=None):
        """ decoding from bytes """
        _decode = getattr(path_object, 'decode_value', None)
        if path_object and _decode is not None:
            # some classes may need their own encoding rules _FOR NOW_
            # we will remove them once we standardize the xattrs format
            def decode(field, value, dv=_decode):
                out = dv(field, value)
                if value is not None and out is None:
                    out = self.decode(field, value)

                return out

        else:
            decode = self.decode

        if prefix:
            prefix += '.'
            kwargs = {k:decode(k, v)
                    for kraw, v in xattrs.items()
                    for k in (self.deprefix(kraw.decode(), prefix),)}
        else:  # ah manual optimization
            kwargs = {k:decode(k, v)
                    for kraw, v in xattrs.items()
                    for k in (kraw.decode(),)}

        return self.pathmetaclass(**kwargs)

    def as_xattrs(self, pathmeta, prefix=None):
        """ encoding to bytes """
        #log.debug(pathmeta)
        out = {}
        for field in self.fields:
            value = getattr(pathmeta, field)
            empty_iterable = hasattr(value, '__iter__') and not value
            if value is not None and not empty_iterable:  # xattrs discard type
                value_bytes = self.encode(field, value)
                if prefix:
                    key = prefix + '.' + field
                else:
                    key = field

                key_bytes = key.encode()
                out[key_bytes] = self.encode(field, value)

        return out

    def encode(self, field, value):
        #if field in ('created', 'updated') and not isinstance(value, datetime):
            #field.replace(cls.path_field_sep, ',')  # FIXME hack around iso8601
            # turns it 8601 isnt actually standard >_< with . instead of , sigh

        empty_iterable = hasattr(value, '__iter__') and not value
        if value is None or empty_iterable:
            raise TypeError('cannot encode an empty value')

        try:
            return _bytes_encode(field, value)
        except exc.UnhandledTypeError:
            log.warning(f'conversion not implemented for field {field}')

        raise exc.UnhandledTypeError(f'dont know what to do with {value!r}')
        return
        if field == 'errors':
            value = ';'.join(value)

        if isinstance(value, datetime):  # FIXME :/ vs iso8601
            value = value.isoformat().replace('.', ',')
            #value = value.timestamp()  # I hate dealing with time :/

        if isinstance(value, int):
            # this is local and will pass through here before move?
            #out = value.to_bytes(value.bit_length() , sys.byteorder)
            out = str(value).encode()  # better to have human readable
        elif isinstance(value, float):
            out = struct.pack('d', value) #= bytes(value.hex())

        elif isinstance(value, str):
            out = value.encode()

        else:
            raise exc.UnhandledTypeError(f'dont know what to do with {value!r}')

        return out

    def decode(self, field, value):
        if field in ('created', 'updated'):  # FIXME human readable vs integer :/
            try:
                # needed for legacy cases
                value, = struct.unpack('d', value)
                return datetime.fromtimestamp(value)
            except struct.error:
                pass

            return parser.parse(value.decode())  # FIXME with timezone vs without ...

        elif field == 'checksum':
            return value

        elif field == 'etag':
            # struct pack this sucker so the count can fit as well?
            value = value.decode()  # FIXME
            checksum, strcount = value.rsplit('-', 1)
            count = int(strcount)
            return bytes.fromhex(checksum), count

        elif field == 'errors':
            value = value.decode()
            return tuple(_ for _ in value.split(';') if _)

        elif field == 'user_id':
            try:
                return int(value)
            except ValueError:  # FIXME :/ uid vs owner_id etc ...
                return value.decode()

        elif field in ('id', 'mode', 'old_id'):
            return value.decode()

        elif field not in self.fields:
            log.warning(f'Unhandled field {field}')
            return value

        else:
            try:
                return int(value)
            except ValueError as e:
                log.exception(f'{field} {value}')
                raise e

class _PathMetaAsPretty(_PathMetaConverter):
    """ Convert to and from unix xattrs. """

    format_name = 'pretty'

    fields = ('size',
              'created',
              'updated',
              'checksum',
              'etag',
              'chunksize',
              'id',
              'file_id',
              'old_id',
              'gid',
              'user_id',
              'mode',
              'errors')

    def __init__(self):
        # register functionality on PathMeta
        def as_pretty(self, pathobject=None, title=None, human=False, _as_pretty=self.as_pretty):
            return _as_pretty(self, pathobject=pathobject, title=title, human=human)

        @classmethod
        def from_pretty(cls, pretty, _from_pretty=self.from_pretty):
            # FIXME cls(**kwargs) vs calling self.pathmetaclass
            return _from_pretty(pretty)

        self.pathmetaclass.as_pretty = as_pretty
        self.pathmetaclass.from_pretty = from_pretty

        self.maxf = max([len(f) for f in self.fields])

    def encode(self, field, value):
        if field == 'errors':
            return list(value)

        if field == 'checksum':
            if isinstance(value, bytes):
                value = value.hex()

        try:
            return _str_encode(field, value)
        except exc.UnhandledTypeError:
            log.warning(f'conversion not implemented for field {field}')
        
        return value

    def rows(self, meta, human=False):
        def key(kv):
            k, v = kv
            if k in self.fields:
                return 0, self.fields.index(k), k, v
            else:
                return 1, 0, k, v

        return sorted(([k, v.hr
                        if human and isinstance(v, FileSize)
                        else self.encode(k, v)]
                       for k, v in meta.items()
                       if (v is not None and
                           (isinstance(v, tuple) and
                            v or not isinstance(v, tuple)))),
                      key=key)

    def as_pretty(self, pathmeta, pathobject=None, title=None, human=False):
        if title is None:
            if pathobject is not None:
                title = pathobject.name
            else:
                title = ''
            
        h = [['Key', f'Value    {title}']]
        rows = h + self.rows(pathmeta, human=human)

        try:
            table = AsciiTable(rows, title=title).table
        except TypeError as e:
            breakpoint()
            raise e

        return table

    def from_pretty(self, pretty):
        raise NotImplementedError('yeah ... really don\'t want to do this')


class _PathMetaAsPrettyDiff(_PathMetaAsPretty):
    """ TODO """
    format_name = 'pretty-diff'

    def __init__(self):
        # register functionality on PathMeta
        def as_pretty_diff(self, othermeta, pathobject=None, title=None, human=False,
                           _as_pretty_diff=self.as_pretty_diff):
            return _as_pretty_diff(self, othermeta, pathobject=pathobject, title=title, human=human)

        @classmethod
        def from_pretty_diff(cls, pretty, _from_pretty_diff=self.from_pretty_diff):
            # FIXME cls(**kwargs) vs calling self.pathmetaclass
            return _from_pretty_diff(pretty)

        self.pathmetaclass.as_pretty_diff = as_pretty_diff
        self.pathmetaclass.from_pretty_diff = from_pretty_diff

        self.maxf = max([len(f) for f in self.fields])

    def as_pretty_diff(self, pathmeta, othermeta, pathobject=None, title=None, human=False):
        if title is None:
            if pathobject is not None:
                title = pathobject.name
            else:
                title = ''
            
        if pathmeta.content_different(othermeta):
            title = tc.red(title)

        def merge(a, b):
            keys = [k for k, _ in a]
            okeys = [ok for ok, _ in b]
            kind = [(k, okeys.index(k) - i, k) if k in okeys else (None, 0, k)
                    for i, k in enumerate(keys)]
            okind = [(ok, keys.index(ok) - i, ok) if ok in keys else (None, 0, ok)
                     for i, ok in enumerate(okeys)]
            long, short = (kind, okind) if len(kind) > len(okind) else (okind, kind)
            start_align = None
            aligned = []
            offset = 0
            for i, (k, v, av) in enumerate(long):
                i -= offset
                if k is None and start_align is None:
                    aligned.append(av)
                    aligned.append(short[i + v][-1])
                elif k is not None:
                    if v <= 0:
                        start_align = i
                        aligned.append(av)
                    else:
                        for j in range(v):
                            aligned.append(short[i + j][-1])
                        offset += v
                        aligned.append(av)

                elif k is None:
                    aligned.append(av)
                # FIXME what to do if short has a key that long does not?

            lkv = len(a[0])
            lokv = len(b[0])
            kv = {k:[k, v] for k, v in a}
            okv = {k:[k, v] for k, v in b}
            for k in aligned:
                l = kv[k] if k in kv else ([''] * lkv)
                r = okv[k] if k in okv else ([''] * lokv)
                yield l + r

        h = [['Key', 'Value', 'Key Other', 'Value Other']]
        rows = h + list(merge(self.rows(pathmeta, human=human), self.rows(othermeta, human=human)))
        try:
            table = AsciiTable(rows, title=title).table
        except TypeError as e:
            breakpoint()
            raise e

        return table

    def from_pretty_diff(self, pretty):
        raise NotImplementedError('yeah ... really don\'t want to do this')


class _EncodeByField:
    def __call__(self, field, value):
        if type(value) == str:
            return value

        try:
            return getattr(self, field)(value)
        except AttributeError as e:
            raise exc.UnhandledTypeError(field) from e
        
    def _datetime(self, value):
        if not isinstance(value, datetime):
            raise TypeError(f'{type(value)} is not a datetime for {value}')

        has_tz = value.tzinfo is not None and value.tzinfo.utcoffset(None) is not None
        value = isoformat(value)
        if not has_tz:
            log.warning('why do you have a timestamp without a timezone ;_;')

        return value

    def _list(self, value):
        return ';'.join(value)

    def errors(self, value):
        return self._list(value)

    def created(self, value):
        return self._datetime(value)

    def updated(self, value):
        return self._datetime(value)

    def id(self, value):
        if not isinstance(value, str):
            raise TypeError('ids must always be strings!')

        return value

    def size(self, value): return str(value)
    def checksum(self, value): return value
    def etag(self, value): return f'{value[0].hex()}-{value[1]}'  # checksum-count  # TODO pack this?
    def chunksize(self, value): return str(value)
    def file_id(self, value): return str(value)
    def gid(self, value): return str(value)
    def user_id(self, value): return str(value)


class _EncodeByFieldBytes(_EncodeByField):
    def __call__(self, field, value):
        if isinstance(value, bytes):
            return value

        out = super().__call__(field, value)
        if isinstance(out, str):
            out = out.encode()

        return out


# load encoders
_str_encode = _EncodeByField()
_bytes_encode = _EncodeByFieldBytes()

# register helpers
_PathMetaAsSymlink()
_PathMetaAsXattrs()
_PathMetaAsPretty()
_PathMetaAsPrettyDiff()  # TODO

