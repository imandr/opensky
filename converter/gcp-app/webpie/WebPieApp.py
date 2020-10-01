from .webob import Response
from .webob import Request as webob_request
from .webob.exc import HTTPTemporaryRedirect, HTTPException, HTTPFound, HTTPForbidden, HTTPNotFound
    
import os.path, os, stat, sys, traceback, fnmatch
from threading import RLock

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

if PY3:
    def to_bytes(s):    
        return s.encode("utf-8")
    def to_str(b):    
        return b.decode("utf-8", "ignore")
else:
    def to_bytes(s):    
        return bytes(s)
    def to_str(b):    
        return str(b)
    

try:
    from collections.abc import Iterable    # Python3
except ImportError:
    from collections import Iterable

_WebMethodSignature = "__WebPie:webmethod__"

#
# Decorators
#
 
def webmethod(permissions=None):
    #
    # Usage:
    #
    # class Handler(WebPieHandler):
    #   ...
    #   @webmethod()            # <-- important: parenthesis required !
    #   def hello(self, req, relpath, **args):
    #       ...
    #
    #   @webmethod(permissions=["admin"])
    #   def method(self, req, relpath, **args):
    #       ...
    #
    def decorator(method):
        def decorated(handler, request, relpath, *params, **args):
            #if isinstance(permissions, str):
            #    permissions = [permissions]
            if permissions is not None:
                try:    roles = handler._roles(request, relpath)
                except:
                    return HTTPForbidden("Can not authorize client")
                if isinstance(roles, str):
                    roles = [roles]
                for r in roles:
                    if r in permissions:
                        break
                else:
                    return HTTPForbidden()
            return method(handler, request, relpath, *params, **args)
        decorated.__doc__ = _WebMethodSignature
        return decorated
    return decorator

def app_synchronized(method):
    def synchronized_method(self, *params, **args):
        with self._app_lock():
            return method(self, *params, **args)
    return synchronized_method

atomic = app_synchronized

class Request(webob_request):
    def __init__(self, *agrs, **kv):
        webob_request.__init__(self, *agrs, **kv)
        self.args = self.environ['QUERY_STRING']
        self._response = Response()
        
    def write(self, txt):
        self._response.write(txt)
        
    def getResponse(self):
        return self._response
        
    def set_response_content_type(self, t):
        self._response.content_type = t
        
    def get_response_content_type(self):
        return self._response.content_type
        
    def del_response_content_type(self):
        pass
        
    response_content_type = property(get_response_content_type, 
        set_response_content_type,
        del_response_content_type, 
        "Response content type")

class HTTPResponseException(Exception):
    def __init__(self, response):
        self.value = response


def makeResponse(resp):
    #
    # acceptable responses:
    #
    # Response
    # text              -- ala Flask
    # status    
    # (text, status)            
    # (text, "content_type")            
    # (text, {headers})            
    # (text, status, "content_type")
    # (text, status, {headers})
    #
    
    if isinstance(resp, Response):
        return resp
    
    body_or_iter = None
    content_type = None
    status = None
    extra = None
    if isinstance(resp, tuple) and len(resp) == 2:
        body_or_iter, extra = resp
    elif isinstance(resp, tuple) and len(resp) == 3:
        body_or_iter, status, extra = resp
    elif PY2 and isinstance(resp, (str, bytes, unicode)):
        body_or_iter = resp
    elif PY3 and isinstance(resp, bytes):
        body_or_iter = resp
    elif PY3 and isinstance(resp, str):
        body_or_iter = to_bytes(resp)
    elif isinstance(resp, int):
        status = resp
    elif isinstance(resp, Iterable):
        body_or_iter = resp
    else:
        raise ValueError("Handler method returned uninterpretable value: " + repr(resp))
        
    response = Response()
    
    if body_or_iter is not None:
        if isinstance(body_or_iter, str):
            if sys.version_info >= (3,):
                response.text = body_or_iter
            else:
                response.text = unicode(body_or_iter, "utf-8")
        elif isinstance(body_or_iter, bytes):
            response.body = body_or_iter
        elif isinstance(body_or_iter, Iterable):
            response.app_iter = body_or_iter
        else:
            raise ValueError("Unknown type for response body: " + str(type(body_or_iter)))

    #print "makeResponse: extra: %s %s is str:%s" % (type(extra), extra, isinstance(extra, str))
    
    if status is not None:
        response.status = status
     
    if extra is not None:
        if isinstance(extra, dict):
            response.headers = extra
        elif isinstance(extra, str):
            response.content_type = extra
        elif isinstance(extra, int):
            #print "makeResponse: setting status to %s" % (extra,)
            response.status = extra
        else:
            raise ValueError("Unknown type for headers: " + repr(extra))
#print response
    
    return response


class WebPieHandler:

    Version = ""
    
    RouteMap = []
    _Strict = False
    _Methods = None
    
    def __init__(self, request, app, path):
        self.Request = request
        self.Path = path
        self.App = app
        self.BeingDestroyed = False
        try:    self.AppURL = request.application_url
        except: self.AppURL = None

    def _app_lock(self):
        return self.App._app_lock()

    def initAtPath(self, path):
        # override me
        pass

        
    def wsgi_call(self, environ, start_response):
        # path_to = '/'
        path = environ.get('PATH_INFO', '')
        path_down = path.split("/")
        try:
            args = self.parseQuery(environ.get("QUERY_STRING", ""))
            request = Request(environ)
            #response = self.walk_down(request, path_to, path_down)    
            response = self.walk_down(request, path_down, args)    
        except HTTPFound as val:    
            # redirect
            response = val
        except HTTPException as val:
            #print 'caught:', type(val), val
            response = val
        except HTTPResponseException as val:
            #print 'caught:', type(val), val
            response = val
        except:
            response = self.App.applicationErrorResponse(
                "Uncaught exception", sys.exc_info())

        try:    
            response = makeResponse(response)
        except ValueError as e:
            response = self.App.applicationErrorResponse(str(e), sys.exc_info())
        out = response(environ, start_response)
        self.destroy()
        self._destroy()
        return out
        
    def parseQuery(self, query):
        out = {}
        for w in (query or "").split("&"):
            if w:
                words = w.split("=", 1)
                k = words[0]
                if k:
                    v = None
                    if len(words) > 1:  v = words[1]
                    if k in out:
                        old = out[k]
                        if type(old) != type([]):
                            old = [old]
                            out[k] = old
                        out[k].append(v)
                    else:
                        out[k] = v
        return out
        
                
    def walk_down(self, request, path_down, args):

        while path_down and not path_down[0]:
            path_down = path_down[1:]
    
        if not path_down:
            if callable(self):
                return self(request, "", **request["query_dict"])
            else:
                return HTTPNotFound("Invalid path %s" % (request.path_info,))
        
        top_path_item = path_down[0]
        
        # Try methods and members
        if hasattr(self, top_path_item):
            member = getattr(self, top_path_item)
            if isinstance(member, WebPieHandler):
                child = member
                return child.walk_down(request, path_down[1:], args)
            elif callable(member):
                method_name = top_path_item
                method = member
                allowed = False
                if self._Strict:
                    allowed = (
                            (self._Methods is not None 
                                    and method_name in self._Methods)
                        or
                            (hasattr(method, "__doc__") 
                                    and method.__doc__ == _WebMethodSignature)
                        )
                else:
                    allowed = self._Methods is None or method_name in self._Methods
                if allowed:
                    relpath = "/".join(path_down[1:])
                    return method(request, relpath, **args)
                else:
                    return HTTPForbidden(request.path_info)
                
        
        # Try route map
        path = "/".join(path_down)
        for pattern, handler in self.RouteMap:
            if fnmatch.fnmatch(pattern, path) or top_path_item == pattern:
                try:    is_handler_class = issubclass(handler, WebPieHandler)
                except: is_handler_class = False
                if is_handler_class:
                    child = handler(self.Request, self.App, self.Path + "/" + top_path_item)
                    return child.walk_down(request, path_down[1:], args)
                elif callable(handler):
                    return handler(request, path, **args)
                else:
                    return handler

        # Try callable
        if callable(self):
            return self(self.Request, path, **args)
        
        # ... otherwise ...
        return HTTPNotFound("Invalid path %s" % (request.path_info,))
                    
        
    def hello(self, req, relpath):
        resp = Response("Hello")
        return resp
       
    def env(self, req, relpath):
        return (
            "%s = %s\n" % (k, repr(v)) for k, v in sorted(req.environ.items())
        ), "text/plain"

    def _checkPermissions(self, x):
        #self.apacheLog("doc: %s" % (x.__doc__,))
        try:    docstr = x.__doc__
        except: docstr = None
        if docstr and docstr[:10] == '__roles__:':
            roles = [x.strip() for x in docstr[10:].strip().split(',')]
            #self.apacheLog("roles: %s" % (roles,))
            return self.checkRoles(roles)
        return True
        
    def checkRoles(self, roles):
        # override me
        return True

    def _destroy(self):
        self.App = None
        if self.BeingDestroyed: return      # avoid infinite loops
        self.BeingDestroyed = True
        for k in self.__dict__:
            o = self.__dict__[k]
            if isinstance(o, WebPieHandler):
                try:    o.destroy()
                except: pass
                o._destroy()
        self.BeingDestroyed = False
        
    def destroy(self):
        # override me
        pass

    def initAtPath(self, path):
        # override me
        pass

    def addEnvironment(self, d):
        params = {  
            'APP_URL':  self.AppURL,
            'MY_PATH':  self.Path,
            "GLOBAL_AppTopPath":    self.scriptUri(),
            "GLOBAL_AppDirPath":    self.uriDir(),
            "GLOBAL_ImagesPath":    self.uriDir()+"/images",
            "GLOBAL_AppVersion":    self.Version,
            "GLOBAL_AppObject":     self,
            }
        params = self.App.addEnvironment(params)
        params.update(d)
        return params

    def render_to_string(self, temp, **args):
        params = self.addEnvironment(args)
        return self.App.render_to_string(temp, **params)

    def render_to_iterator(self, temp, **args):
        params = self.addEnvironment(args)
        #print 'render_to_iterator:', params
        return self.App.render_to_iterator(temp, **params)

    def render_to_response(self, temp, **more_args):
        return Response(self.render_to_string(temp, **more_args))

    def mergeLines(self, iter, n=50):
        buf = []
        for l in iter:
            if len(buf) >= n:
                yield ''.join(buf)
                buf = []
            buf.append(l)
        if buf:
            yield ''.join(buf)

    def render_to_response_iterator(self, temp, _merge_lines=0,
                    **more_args):
        it = self.render_to_iterator(temp, **more_args)
        #print it
        if _merge_lines > 1:
            merged = self.mergeLines(it, _merge_lines)
        else:
            merged = it
        return Response(app_iter = merged)

    def redirect(self, location):
        #print 'redirect to: ', location
        #raise HTTPTemporaryRedirect(location=location)
        raise HTTPFound(location=location)
        
    def getSessionData(self):
        return self.App.getSessionData()
        
        
    def scriptUri(self, ignored=None):
        return self.Request.environ.get('SCRIPT_NAME',
                os.environ.get('SCRIPT_NAME', '')
        )
        
    def uriDir(self, ignored=None):
        return os.path.dirname(self.scriptUri())
        
    def renderTemplate(self, ignored, template, _dict = {}, **args):
        # backward compatibility method
        params = {}
        params.update(_dict)
        params.update(args)
        raise HTTPException("200 OK", self.render_to_response(template, **params))

    def env(self, req, relpath, **args):
        lines = [b"WSGI environment\n----------------------\n"]
        for k in sorted(req.environ.keys()):
            lines.append(to_bytes("%s = %s\n" % (k, req.environ[k])))
        return Response(app_iter = lines, content_type = "text/plain")
    
    @property
    def session(self):
        return self.Request.environ["webpie.session"]
        
        
class WebPieStaticHandler(WebPieHandler):

    def __init__(self, root_path):
        WebPieHandler.__init__(self, None, None, None)
        self.RootPath = root_path

    def __call__(self, request, relpath):
        while ".." in relpath:
            # prevent jumping up
            relpath = relpath.replace("..",".")
        home = self.RootPath
        path = os.path.join(home, relpath)
        try:
            st_mode = os.stat(path).st_mode
            if not stat.S_ISREG(st_mode):
                #print "not a regular file"
                return Response(status=403)
        except:
            #raise
            return Response("Not found", status=404)

        ext = path.rsplit('.',1)[-1]
        mime_type = self.MIME_TYPES_BASE.get(ext, "text/html")

        def read_iter(f):
            while True:
                data = f.read(100000)
                if not data:    break
                yield data
        return Response(app_iter = read_iter(open(path, "rb")), content_type = mime_type)

class WebPieApp(object):

    Version = "Undefined"

    MIME_TYPES_BASE = {
        "gif":   "image/gif",
        "jpg":   "image/jpeg",
        "jpeg":   "image/jpeg",
        "js":   "text/javascript",
        "html":   "text/html",
        "txt":   "text/plain",
        "css":  "text/css"
    }

    def __init__(self, root_class, strict=False, 
            static_path="/static", static_location="static", enable_static=False,
            disable_robots=True):
        assert issubclass(root_class, WebPieHandler)
        self.RootClass = root_class
        self.JEnv = None
        self._AppLock = RLock()
        self._Strict = strict
        self.ScriptHome = None
        self.StaticPath = static_path
        self.StaticLocation = static_location
        self.StaticEnabled = enable_static and static_location
        self.Initialized = False
        self.DisableRobots = disable_robots

    def _app_lock(self):
        return self._AppLock
        
    def __enter__(self):
        return self._AppLock.__enter__()
        
    def __exit__(self, *params):
        return self._AppLock.__exit(*params)
    
    # override
    @app_synchronized
    def acceptIncomingTransfer(self, method, uri, headers):
        return True
            
    @app_synchronized
    def initJinjaEnvironment(self, tempdirs = [], filters = {}, globals = {}):
        # to be called by subclass
        #print "initJinja2(%s)" % (tempdirs,)
        from jinja2 import Environment, FileSystemLoader
        if not isinstance(tempdirs, list):
            tempdirs = [tempdirs]
        self.JEnv = Environment(
            loader=FileSystemLoader(tempdirs)
            )
        for n, f in filters.items():
            self.JEnv.filters[n] = f
        self.JGlobals = {}
        self.JGlobals.update(globals)
                
    @app_synchronized
    def setJinjaFilters(self, filters):
            for n, f in filters.items():
                self.JEnv.filters[n] = f

    @app_synchronized
    def setJinjaGlobals(self, globals):
            self.JGlobals = {}
            self.JGlobals.update(globals)
        
    def applicationErrorResponse(self, headline, exc_info):
        typ, val, tb = exc_info
        exc_text = traceback.format_exception(typ, val, tb)
        exc_text = ''.join(exc_text)
        text = """<html><body><h2>Application error</h2>
            <h3>%s</h3>
            <pre>%s</pre>
            </body>
            </html>""" % (headline, exc_text)
        #print exc_text
        return Response(text, status = '500 Application Error')

    def static(self, relpath):
        while ".." in relpath:
            relpath = relpath.replace("..",".")
        home = self.StaticLocation
        path = os.path.join(home, relpath)
        #print "static: path=", path
        try:
            st_mode = os.stat(path).st_mode
            if not stat.S_ISREG(st_mode):
                #print "not a regular file"
                raise ValueError("Not regular file")
        except:
            #raise
            return Response("Not found", status=404)

        ext = path.rsplit('.',1)[-1]
        mime_type = self.MIME_TYPES_BASE.get(ext, "text/html")

        def read_iter(f):
            while True:
                data = f.read(100000)
                if not data:    break
                yield data
        #print "returning response..."
        return Response(app_iter = read_iter(open(path, "rb")),
            content_type = mime_type)

    def __call__(self, environ, start_response):
        #print 'app call ...'
        path_to = '/'
        path_down = environ.get('PATH_INFO', '')
        #print 'path:', path_down
        req = Request(environ)
        if not self.Initialized:
            self.ScriptName = environ.get('SCRIPT_NAME','')
            self.Script = environ.get('SCRIPT_FILENAME', 
                        os.environ.get('UWSGI_SCRIPT_FILENAME'))
            self.ScriptHome = os.path.dirname(self.Script or sys.argv[0]) or "."
            if self.StaticEnabled:
                if not self.StaticLocation[0] in ('.', '/'):
                    self.StaticLocation = self.ScriptHome + "/" + self.StaticLocation
                    #print "static location:", self.StaticLocation
            self.Initialized = True
            
        if self.StaticEnabled and path_down.startswith(self.StaticPath+"/"):
            path = path_down[len(self.StaticPath)+1:]
            resp = self.static(path)
        elif self.DisableRobots and path_down.endswith("/robots.txt"):
            resp = Response("User-agent: *\nDisallow: /\n", content_type = "text/plain")
        else:
            if issubclass(self.RootClass, WebPieHandler):
                root = self.RootClass(req, self, "/")
            else:
                root = RootClass(self)
            try:
                return root.wsgi_call(environ, start_response)
            except:
                resp = self.applicationErrorResponse(
                    "Uncaught exception", sys.exc_info())
        return resp(environ, start_response)
        
    def JinjaGlobals(self):
        # override me
        return {}

    def addEnvironment(self, d):
        params = {}
        params.update(self.JGlobals)
        params.update(self.JinjaGlobals())
        params.update(d)
        return params
        
    def render_to_string(self, temp, **kv):
        t = self.JEnv.get_template(temp)
        return t.render(self.addEnvironment(kv))

    def render_to_iterator(self, temp, **kv):
        t = self.JEnv.get_template(temp)
        return t.generate(self.addEnvironment(kv))

    def run_server(self, port, **args):
        from .HTTPServer import HTTPServer
        srv = HTTPServer(port, self, **args)
        srv.start()
        srv.join()

if __name__ == '__main__':
    from HTTPServer import HTTPServer
    
    class MyApp(WebPieApp):
        pass
        
    class MyHandler(WebPieHandler):
        pass
            
    MyApp(MyHandler).run_server(8080)
