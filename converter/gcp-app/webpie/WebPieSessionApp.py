from .webob import Response, Request
import time, os, pickle, logging, sys
from .WebPieApp import WebPieApp
from threading import Thread, RLock
import glob, uuid, hashlib

_hash_algorithm = None

def random_string():
    return uuid.uuid1().hex
        

# Cookie module stolen from pesto
# Copyright (c) 2007-2010 Oliver Cope. All rights reserved.
# See LICENSE.txt for terms of redistribution and use.

import cgi
import copy

try:
    # Python 2
    from urllib import quote as url_quote
    from urllib import unquote as url_unquote
except:
    # Python 2
    from urllib.parse import quote as url_quote
    from urllib.parse import unquote as url_unquote

from datetime import datetime, timedelta
from time import timezone
from calendar import timegm
try:
    from email.utils import formatdate
except ImportError:
    from email.Utils import formatdate
    
def synchronized(method):
    def f(self, *params, **args):
        with self.Lock:
            out = method(self, *params, **args)
        return out
    return f

class Cookie(object):
    """
    Represents an HTTP cookie.

    See rfc2109, HTTP State Management Mechanism

    >>> from pesto.cookie import Cookie
    >>> c = Cookie('session_id', 'abc123')
    >>> c.path = '/cgi-bin'
    >>> c.domain = '.ucl.ac.uk'
    >>> c.path
    '/cgi-bin'
    >>> print str(c)
    session_id=abc123;Domain=.ucl.ac.uk;Path=/cgi-bin;Version=1
    """
    attributes = [
        ("Comment", "comment"),
        ("Domain", "domain"),
        ("Expires", "expires"),
        ("Max-Age", "maxage"),
        ("Path", "path"),
        ("Secure", "secure"),
        ("Version", "version"),
    ]
    attribute_dict = dict(attributes)

    def __init__(
        self, name, value, maxage=None, expires=None, path=None,
        secure=None, domain=None, comment=None, http_only=False,
        version=1
    ):
        """
        Initialize a ``Cookie`` instance.
        """
        self.name = name
        self.value = value
        self.maxage = maxage
        self.path = path
        self.secure = secure
        self.domain = domain
        self.comment = comment
        self.version = version
        self.expires = expires
        self.http_only = http_only


    def __str__(self):
        """
        Returns a string representation of the cookie in the format, eg
        ``session_id=abc123;Path=/cgi-bin;Domain=.example.com;Version=1``
        """
        cookie = ['%s=%s' % (self.name, url_quote(str(self.value)))]
        for cookie_name, att_name in self.attributes:
            value = getattr(self, att_name, None)
            if value is not None:
                cookie.append('%s=%s' % (cookie_name, str(value)))
        if self.http_only:
            cookie.append('HttpOnly')
        return ';'.join(cookie)

    def set_expires(self, dt):
        """
        Set the cookie ``expires`` value to ``datetime`` object ``dt``
        """
        self._expires = dt

    def get_expires(self):
        """
        Return the cookie ``expires`` value as an instance of ``datetime``.
        """
        if self._expires is None and self.maxage is not None:
            if self.maxage == 0:
                # Make sure immediately expiring cookies get a date firmly in
                # the past.
                self._expires = datetime(1980, 1, 1)
            else:
                self._expires = datetime.now() + timedelta(seconds = self.maxage)

        if isinstance(self._expires, datetime):
            return formatdate(timegm(self._expires.utctimetuple()))

        else:
            return self._expires

    expires = property(get_expires, set_expires)

def expire_cookie(cookie_or_name, *args, **kwargs):
    """
    Synopsis::

        >>> from pesto.testing import TestApp
        >>> from pesto.response import Response
        >>> from pesto import to_wsgi
        >>>
        >>> def handler(request):
        ...     return Response(set_cookie = expire_cookie('Customer', path='/'))
        ...
        >>> TestApp(
        ...     to_wsgi(handler),
        ...     HTTP_COOKIE='''$Version="1";
        ...     Customer="WILE_E_COYOTE";
        ...     Part="Rocket_0001";
        ...     Part="catapult_0032"
        ... ''').get().get_header('Set-Cookie')
        'Customer=;Expires=Tue, 01 Jan 1980 00:00:00 -0000;Max-Age=0;Path=/;Version=1'
    """
    if isinstance(cookie_or_name, Cookie):
        expire = cookie_or_name
    else:
        expire = Cookie(name=cookie_or_name, value='', *args, **kwargs)
    return Cookie(
        name=expire.name,
        value='',
        expires=datetime(1980, 1, 1),
        maxage=0,
        domain=kwargs.get('domain', expire.domain),
        path=kwargs.get('path', expire.path)
    )


def parse_cookie_header(cookie_string, unquote=url_unquote):
    """
    Return a list of Cookie objects read from the request headers.

    cookie_string
        The cookie, eg ``CUSTOMER=FRED; path=/;``

    unquote
        A function to decode quoted values. If set to ``None``, values will be
        left as-is.

    See rfc2109, section 4.4

    The Cookie header should be a ';' separated list of name value pairs.
    If a name is prefixed by a '$', then that name is an attribute
    of the most recently (left to right) encountered cookie.  If no
    cookie has yet been parsed then the value applies to the cookie
    mechanism as a whole.
    """

    if unquote is None:
        unquote = lambda v: v

    if not cookie_string:
        return {}
    cookies = {}

    # Here we put the $ prefixed attributes that appear *before* a
    # named cookie, to use as a template for other cookies.
    cookie_template = Cookie(None, None)

    for part in cookie_string.split(";"):

        if not '=' in part:
            continue

        k, v = part.strip().split("=", 1)

        # Unquote quoted values ('"..."' => '...')
        if v and '"' == v[0] == v[-1] and len(v) > 1:
            v = v[1:-1]

        if k[0] == '$':
            # Value pertains to most recently read cookie,
            # or cookie_template
            k = k[1:]
            if len(cookies) == 0:
                cookie = copy.copy(cookie_template)
            else:
                cookie = cookies[-1]

            try:
                setattr(cookie, cookie.attribute_dict[k], v)
            except KeyError:
                pass
        else:
            c = copy.copy(cookie_template)
            c.name = unquote(k)
            c.value = unquote(v)
            cookies[c.name] = c
    return cookies

class CleanerThread(Thread):

    def __init__(self, data_root,
                        cleanup_frequency,
                        session_timeout,
                        lock         
        ):
        Thread.__init__(self)
        self.DataRoot = data_root
        self.CleanUpFrequency = cleanup_frequency
        self.SessionTimeout = session_timeout
        self.Lock = lock

    def run(self):
        while True:
            time.sleep(self.CleanUpFrequency)
            #print "Cleaner(%s) run. Session timeout=%d..." % (self.DataRoot, self.SessionTimeout)
            with self.Lock:
                try:
                    dirs = os.walk(self.DataRoot)
                    for path, subdirs, files in dirs:
                        for f in files:
                            f = path + '/' + f
                            st = os.stat(f)
                            if st.st_atime < time.time() - self.SessionTimeout:
                                try:    
                                    #print "Deleting %s. Access time=%s now=%s..." % (f, st.st_atime, time.time())
                                    os.unlink(f)
                                except:
                                    print("Can not delete file %s: %s %s" % (
                                            f, sys.exc_info()[0], sys.exc_info()[1])) 
                except:
                    print("Error in clean-up thread: %s %s" % (
                            sys.exc_info()[0], sys.exc_info()[1])) 

class SessionStorage:

    GlobalLock = RLock()
    Storages = {}               # root path -> storage object

    @staticmethod
    def storage(root_path, 
                        cleanup_frequency = 3600,   # 1/hour
                        session_timeout = 24*3600   # 24 hours             
                        ):
        with SessionStorage.GlobalLock:
            if root_path not in SessionStorage.Storages:
                SessionStorage.Storages[root_path] = SessionStorage(root_path, 
                        cleanup_frequency,
                        session_timeout)
            return SessionStorage.Storages[root_path]

    def __init__(self, root_path, 
                        cleanup_frequency,
                        session_timeout           
                        ):
        self.RootPath = root_path
        self.CleanUpFrequency = cleanup_frequency
        self.SessionTimeout = session_timeout
        self.Lock = RLock()
        self.CleanerThread = CleanerThread(root_path, self.CleanUpFrequency, self.SessionTimeout, self.Lock)
        self.CleanerThread.start()
        
    def dataFilePath(self, sid):
        c1 = sid[-1]
        c2 = sid[-2]
        return "%s/%s/%s/%s.data" % (self.RootPath, c1, c2, sid)
        
    def bulkFilePath(self, sid, key):
        c1 = sid[-1]
        c2 = sid[-2]
        return "%s/%s/%s/%s:%s.data" % (self.RootPath, c1, c2, 
                sid, key)

    @synchronized
    def sessionExists(self, sid):
        try:    os.stat(self.dataFilePath(sid))
        except OSError:
            return False
        return True
                
    def saveData(self, path, data):
        #print ("saveData:", type(data), data)
        try:
            os.makedirs(os.path.dirname(path))
        except OSError:
            # Path exists or cannot be created. The latter error will be
            # picked up later :)
            pass

        f = open(path, 'wb')
        try:
            pickle.dump(data, f)
        finally:
            f.close()
        #print "saveData(%s) done" % (path,)


    def loadData(self, path):
        try:
            f = open(path, 'rb')
        except IOError:
            return None
        try:
            try:
                return pickle.load(f)
            except (EOFError, IOError):
                logging.exception("Could not read data from: %s" % (path,))
                return None
        finally:
            f.close()

    @synchronized
    def bulkLoad(self, sid, key, default=None):
        return self.loadData(self.bulkFilePath(sid, key))
        
    @synchronized
    def bulkSave(self, sid, key, value):
        self.saveData(self.bulkFilePath(sid, key), value)
        
    @synchronized
    def bulkDelete(self, sid, key):
        try:    os.unlink(self.bulkFilePath(sid, key))
        except: pass
        
    @synchronized
    def load(self, sid):
        return self.loadData(self.dataFilePath(sid))
        
    @synchronized
    def save(self, sid, data):
        return self.saveData(self.dataFilePath(sid), data)
        
    @synchronized
    def delete(self, sid):
        try:    os.unlink(self.dataFilePath(sid))
        except: pass
        

class BulkProxy:

    def __init__(self, sess):
        self.Session = sess
        
    def get(self, key, default=None):
        #print "BulkProxy: reading %s" % (key,)
        v = self.Session.bulkRead(key, default)
        #print v
        return v

    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __setitem__(self, key, val):
        return self.Session.bulkSave(key, val)

    def __delitem__(self, key):
        return self.Session.bulkDelete(key)
        
class Session:
    def __init__(self, storage_path, session_id, session_timeout):
        self.Storage = SessionStorage.storage(storage_path, 
                session_timeout=session_timeout)
        self.is_new = session_id == None
        self.Data = None
        self.SessionID = session_id or self.generateSessionID()
        if not self.Storage.sessionExists(self.SessionID):
            self.Data = {}
            self.save()
        self.Changed = False
                
    @staticmethod
    def is_valid_id(s):
        try:    int(s, 16)
        except: return False
        else:   return True
        
    @property
    def session_id(self):           # just an alias for backward compatibility
        return self.SessionID
        
    def generateSessionID(self):
        return random_string()
        
    @property
    def data(self):
        if self.Data is None:    
            self.Data = self.load() or {}
        return self.Data
    
    def bulkRead(self, key, default=None):
        return self.Storage.bulkLoad(self.SessionID, key)
        
    def bulkSave(self, key, value):
        return self.Storage.bulkSave(self.SessionID, key, value)
        
    def bulkDelete(self, key):
        self.Storage.bulkDelete(self.SessionID, key)
        
    @property
    def bulk(self):
        return BulkProxy(self)
        
    def save(self):
        self.Storage.save(self.SessionID, self.Data)
        self.Changed = False
        #print "Session saved"

    def saveIfChanged(self):
        if self.Changed:
            self.save()
            self.Changed = False
        
    def load(self):
        self.Data = self.Storage.load(self.SessionID)
        self.Changed = False
        return self.Data
        
    def invalidate(self):
        """
        invalidate and remove this session from the sessionmanager
        """
        self.Storage.delete(self.SessionID)
        self.SessionID = None
        self.Data = {}

    #
    # Mapping interface
    #
    def clear(self):
        out = self.data.clear()
        self.Changed = True
        return out

    def has_key(self, key):
        return key in self.data

    def items(self):
        return list(self.data.items())

    def iteritems(self):
        return iter(self.data.items())

    def iterkeys(self):
        return iter(self.data.keys())

    def itervalues(self):
        return iter(self.data.values())

    def update(self, other, **kwargs):
        out = self.data.update(other, **kwargs)
        self.Changed = True
        return out

    def values(self):
        return list(self.data.values())

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]

    def __iter__(self):
        return self.data.__iter__()

    def __setitem__(self, key, val):
        out = self.data.__setitem__(key, val)
        self.Changed = True
        return out

    def __delitem__(self, key):
        out = self.data.__delitem__(key)
        self.Changed = True
        return out
    
class WebPieSessionApp(WebPieApp):

    def __init__(self, root_class,
            session_storage = "/tmp", cookie_name = 'webpie_session_id',
            domain = None, cookie_path = None,  session_timeout = 3600  # seconds
        ):
        WebPieApp.__init__(self, root_class)
        self.SessionStorage = session_storage
        self.CookieName = cookie_name
        self.CookieDomain = domain
        self.CookiePath = cookie_path
        self.SessionLifetime = session_timeout
        
    def __call__(self, environ, start_response):
        #
        # get session id from cookie
        # load session data
        # call the WebPieApp
        # store session data
        # add cookie
        #
        
        #
        # get session id from cookie
        #
        session_id = None
        req = Request(environ)
        cookies = parse_cookie_header(req.headers.get('Cookie', ''))
        cookie = cookies.get(self.CookieName)
        if cookie and Session.is_valid_id(cookie.value):
            session_id = cookie.value

        #
        # load session data
        #
        session = Session(self.SessionStorage, session_id, 
                self.SessionLifetime)
        environ["webpie.session"] = session

        def my_start_response(status, headers):
            _cookie_path = self.CookiePath
            if _cookie_path is None:
                _cookie_path = environ.get('SCRIPT_NAME')
            if not _cookie_path:
                _cookie_path = '/'
            #print "SCRIPT_NAME=%s" % (environ.get('SCRIPT_NAME'),)
            #print "_cookie_path=", _cookie_path
            cookie = Cookie(
                self.CookieName,
                session.SessionID,
                path=_cookie_path,
                domain=self.CookieDomain,
                http_only=True
            )
            #print "Cookie: %s" % (cookie,)
            return start_response(
                status,
                list(headers) + [("Set-Cookie", str(cookie))]
            )

        #print "Calling WebPieApp, request: %s %s" % (environ.get("REQUEST_METHOD"), environ.get("REQUEST_URI"))
        output = WebPieApp.__call__(self, environ, my_start_response)
        #print "Changed: %s" % (self.Session.Changed,)
        session.saveIfChanged()
        return output
        
        
        
        

