import fnmatch, traceback, sys, select, time, os.path, stat, pprint
from socket import *
from pythreader import PyThread, synchronized, Task, TaskQueue
from .WebPieApp import Response

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

Debug = False
        
class BodyFile(object):
    
    def __init__(self, buf, sock, length):
        self.Buffer = buf
        self.Sock = sock
        self.Remaining = length
        
    def get_chunk(self, n):
        if self.Buffer:
            chunk = self.Buffer[0]
            if len(chunk) > n:
                out = chunk[:n]
                self.Buffer[0] = chunk[n:]
            else:
                out = chunk
                self.Buffer = self.Buffer[1:]
        elif self.Sock is not None:
            out = self.Sock.recv(n)
            if not out: self.Sock = None
        return out
        
    MAXMSG = 100000
    
    def read(self, N = None):
        #print ("read({})".format(N))
        #print ("Buffer:", self.Buffer)
        if N is None:   N = self.Remaining
        out = []
        n = 0
        eof = False
        while not eof and (N is None or n < N):
            ntoread = self.MAXMSG if N is None else N - n
            chunk = self.get_chunk(ntoread)
            if not chunk:
                eof = True
            else:
                n += len(chunk)
                out.append(chunk)
        out = b''.join(out)
        if self.Remaining is not None:
            self.Remaining -= len(out)
        #print ("returning:[{}]".format(out))
        return out
            
            
class HTTPConnection(Task):

    MAXMSG = 100000

    def __init__(self, server, csock, caddr):
        Task.__init__(self)
        self.Server = server
        self.CAddr = caddr
        self.CSock = csock
        self.ReadClosed = False
        self.RequestHeadline = None
        self.RequestReceived = False
        self.RequestBuffer = ""
        self.Body = []
        self.Headers = []
        self.HeadersDict = {}
        self.URL = None
        self.RequestMethod = None
        self.QueryString = ""
        self.OutIterable = None
        self.OutBuffer = ""
        self.OutputEnabled = False
        self.BodyLength = None
        self.BytesSent = 0
        self.ResponseStatus = None
        self.OriginalPathInfo = self.PathInfo = None
        self.ValidRequest = False
        
    def debug(self, msg):
        if Debug:
            print (msg)

    def parseRequest(self):
        #print("requestReceived:[%s]" % (self.RequestBuffer,))
        # parse the request
        lines = self.RequestBuffer.split('\n')
        lines = [l.strip() for l in lines if l.strip()]
        if not lines:
            return False
        self.RequestHeadline = lines[0].strip()
        words = self.RequestHeadline.split()
        #self.debug("Request: %s" % (words,))
        if len(words) != 3:
            return False
        self.RequestMethod = words[0].upper()
        self.RequestProtocol = words[2]
        self.URL = words[1]
        uwords = self.URL.split('?',1)
        self.OriginalPathInfo = request_path = uwords[0]
        if not self.Server.urlMatch(request_path):
            return False
        self.PathInfo = self.Server.rewritePath(request_path)
        if len(uwords) > 1: self.QueryString = uwords[1]
        #ignore HTTP protocol
        for h in lines[1:]:
            words = h.split(':',1)
            name = words[0].strip()
            value = ''
            if len(words) > 1:
                value = words[1].strip()
            if name:
                self.Headers.append((name, value))
                self.HeadersDict[name] = value
        return True
        
    def getHeader(self, header, default = None):
        # case-insensitive version of dictionary lookup
        h = header.lower()
        for k, v in self.HeadersDict.items():
            if k.lower() == h:
                return v
        return default
        
    def addToRequest(self, data):
        #print("Add to request:", data)
        self.RequestBuffer += data
        inx_nn = self.RequestBuffer.find('\n\n')
        inx_rnrn = self.RequestBuffer.find('\r\n\r\n')
        if inx_nn < 0:
            inx = inx_rnrn
            n = 4
        elif inx_rnrn < 0:
            inx = inx_nn
            n = 2
        elif inx_nn < inx_rnrn:
            inx = inx_nn
            n = 2
        else:
            inx = inx_rnrn
            n = 4
        #print ("addToRequest: inx={}, n={}".format(inx, n))
        if inx < 0:
            return False        # request not received yet
            
        rest = self.RequestBuffer[inx+n:]
        self.RequestBuffer = self.RequestBuffer[:inx]
        self.ValidRequest = self.parseRequest()
        #print("rest:[{}]".format(rest))
        if self.ValidRequest and rest:    
            self.addToBody(rest)
        return True                     # request received, even if it is invalid
            
    def addToBody(self, data):
        if PY3 and isinstance(data, str):   data = bytes(data)
        #print ("addToBody:", data)
        self.Body.append(data)

    def parseQuery(self, query):
        out = {}
        for w in query.split("&"):
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
                
    def processRequest(self):        
        #self.debug("processRequest()")
        env = dict(
            REQUEST_METHOD = self.RequestMethod.upper(),
            PATH_INFO = self.PathInfo,
            SCRIPT_NAME = "",
            SERVER_PROTOCOL = self.RequestProtocol,
            QUERY_STRING = self.QueryString
        )
        
        if self.HeadersDict.get("Expect") == "100-continue":
            self.CSock.send(b'HTTP/1.1 100 Continue\n\n')
                
        env["wsgi.url_scheme"] = "http"
        env["query_dict"] = self.parseQuery(self.QueryString)
        
        #print ("processRequest: env={}".format(env))
        
        for h, v in self.HeadersDict.items():
            h = h.lower()
            if h == "content-type": env["CONTENT_TYPE"] = v
            elif h == "host":
                words = v.split(":",1)
                words.append("")    # default port number
                env["HTTP_HOST"] = v
                env["SERVER_NAME"] = words[0]
                env["SERVER_PORT"] = words[1]
            elif h == "content-length": 
                env["CONTENT_LENGTH"] = self.BodyLength = int(v)
            else:
                env["HTTP_%s" % (h.upper().replace("-","_"),)] = v

        env["wsgi.input"] = BodyFile(self.Body, self.CSock, self.BodyLength)
        
        
        try:
            self.OutIterable = self.Server.wsgi_app(env, self.start_response)    
        except:
            self.start_response("500 Error", 
                            [("Content-Type","text/plain")])
            self.OutBuffer = error = traceback.format_exc()
            self.Server.log_error(self.CAddr, error)
        self.OutputEnabled = True
        #self.debug("registering for writing: %s" % (self.CSock.fileno(),))    

    def start_response(self, status, headers):
        #print("start_response({}, {})".format(status, headers))
        self.ResponseStatus = status.split()[0]
        out = ["HTTP/1.1 " + status]
        for h,v in headers:
            out.append("{}: {}".format(h, v))
        self.OutBuffer = "\n".join(out) + "\n\n"
        #print("OutBuffer: [{}]".format(self.OutBuffer))
        
    def doClientRead(self):
        if self.ReadClosed:
            return

        try:    
            data = self.CSock.recv(self.MAXMSG)
            if PY3: data = data.decode("utf-8")
        except: 
            data = ""
        
        #print("data:[{}]".format(data))

        request_just_received = False
    
        if data:
            if not self.RequestReceived:
                self.RequestReceived = request_just_received = self.addToRequest(data)
            else:
                self.addToBody(data)
        else:
            self.ReadClosed = True
            
        if request_just_received:
            if self.ValidRequest:
                self.processRequest()
            else:
                self.shutdown()

        if self.ReadClosed and not self.RequestReceived:
            self.shutdown()
                    
    def doWrite(self):
        #print ("doWrite: outbuffer:", len(self.OutBuffer))
        line = None
        #print ("doWrite: buffer: {}, iterable: {}".format(self.OutBuffer, self.OutIterable))
        if self.OutBuffer:
            line = self.OutBuffer
            self.OutBuffer = None
        elif isinstance(self.OutIterable, list):
            if self.OutIterable:
                line = self.OutIterable[0]
                self.OutIterable = self.OutIterable[1:]
            else: 
                self.OutIterable = None
                #print("OutIterable removed")
        elif self.OutIterable is not None:
            try:    
                line = next(self.OutIterable)
            except StopIteration:
                self.OutIterable = None
                #print("OutIterable removed")
        if line is not None:
            try:
                if isinstance(line, str) and sys.version_info >= (3,):
                    line = bytes(line, "utf-8")
                sent = self.CSock.send(line)
            except: 
                sent = 0
            self.BytesSent += sent
            if not sent:
                #self.debug("write socket closed")
                self.shutdown()
                return
            else:
                line = line[sent:]
                self.OutBuffer = line or None
        
    def shutdown(self):
            self.Server.log(self.CAddr, self.RequestMethod, self.URL, self.ResponseStatus, self.BytesSent)
            self.debug("shutdown")
            if self.CSock != None:
                self.debug("closing client socket")
                try:    
                    self.CSock.shutdown(SHUT_RDWR)
                    self.CSock.close()
                except:
                    pass
                self.CSock = None
            if self.Server is not None:
                self.Server.connectionClosed(self)
                self.Server = None
            
    def run(self):
        while self.CSock is not None:       # shutdown() will set it to None
            rlist = [] if self.ReadClosed else [self.CSock]
            wlist = [self.CSock] if self.OutputEnabled else []
            rlist, wlist, exlist = select.select(rlist, wlist, [], 10.0)
            if self.CSock in rlist:
                self.doClientRead()
            if self.CSock in wlist:
                self.doWrite()
            if self.OutputEnabled and not self.OutBuffer and self.OutIterable is None:
                self.shutdown()     # noting else to send
                
class HTTPServer(PyThread):

    MIME_TYPES_BASE = {
        "gif":   "image/gif",
        "jpg":   "image/jpeg",
        "jpeg":   "image/jpeg",
        "js":   "text/javascript",
        "html":   "text/html",
        "txt":   "text/plain",
        "css":  "text/css"
    }

    def __init__(self, port, app, remove_prefix = "", url_pattern="*", max_connections = 100, 
                enabled = True, max_queued = 100,
                logging = True, log_file = None):
        PyThread.__init__(self)
        #self.debug("Server started")
        self.Port = port
        self.WSGIApp = app
        self.Match = url_pattern
        self.Enabled = False
        self.Logging = logging
        self.LogFile = sys.stdout if log_file is None else log_file
        self.Connections = TaskQueue(max_connections, capacity = max_queued)
        self.RemovePrefix = remove_prefix
        if enabled:
            self.enableServer()
        
    @synchronized
    def log(self, caddr, method, uri, status, bytes_sent):
        if self.Logging:
            self.LogFile.write("{}: {} {} {} {} {}\n".format(
                    time.ctime(), caddr[0], method, uri, status, bytes_sent
            ))
            if self.LogFile is sys.stdout:
                self.LogFile.flush()
            
    @synchronized
    def log_error(self, caddr, message):
        if self.Logging:
            self.LogFile.write("{}: {} {}\n".format(
                    time.ctime(), caddr[0], message
            ))
            if self.LogFile is sys.stdout:
                self.LogFile.flush()
        else:
            print ("{}: {} {}\n".format(
                    time.ctime(), caddr[0], message
            ))
        

    def urlMatch(self, path):
        return fnmatch.fnmatch(path, self.Match)
        
    def rewritePath(self, path):
        if self.RemovePrefix and path.startswith(self.RemovePrefix):
            path = path[len(self.RemovePrefix):]
        return path

    def wsgi_app(self, env, start_response):
        return self.WSGIApp(env, start_response)
        
    @synchronized
    def enableServer(self, backlog = 5):
        self.Enabled = True
                
    @synchronized
    def disableServer(self):
        self.Enabled = False

    def connectionClosed(self, conn):
        pass
            
    @synchronized
    def connectionCount(self):
        return len(self.Connections)    
            
    def run(self):
        self.Sock = socket(AF_INET, SOCK_STREAM)
        self.Sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self.Sock.bind(('', self.Port))
        self.Sock.listen(10)
        while True:
            csock, caddr = self.Sock.accept()
            conn = self.createConnection(csock, caddr)
            if conn is not None:
                self.Connections << conn

    # overridable
    def createConnection(self, csock, caddr):
        return HTTPConnection(self, csock, caddr)

                
    def isStaticURI(self, uri):
        return False
        return self.StaticURI is not None and uri.startswith(self.StaticURI + "/")
        
    def processStaticRequest(self, env, path, start_response):
        #print ("processStaticRequest({})".format(path))
        assert path.startswith(self.StaticURI + "/")
        path = path[len(self.StaticURI)+1:]
        while ".." in path:
            path = path.replace("..",".")       # can not jump up
        path = os.path.join(self.StaticLocation, path)
        #print ("path=", path)
        try:
            st_mode = os.stat(path).st_mode
            if not stat.S_ISREG(st_mode):
                #print "not a regular file"
                return Response("Prohibited", status=403)
        except:
            return Response("Not found", status=404)
            
        ext = path.rsplit('.',1)[-1]
        mime_type = self.MIME_TYPES_BASE.get(ext, "text/html")

        def read_iter(f):
            while True:
                data = f.read(100000)
                if not data:    break
                yield data
            
        return Response(app_iter = read_iter(open(path, "rb")),
            content_type = mime_type)
            
class HTTPSServer(HTTPServer):

    def __init__(self, port, app, certfile, keyfile, password=None, **args):
        HTTPServer.__init__(self, port, app, **args)
        import ssl
        self.SSLContext = ssl.SSLContext(ssl.PROTOCOL_TLS)
        self.SSLContext.load_cert_chain(certfile, keyfile, password=password)
        self.SSLContext.verify_mode = ssl.CERT_OPTIONAL
        self.SSLContext.load_default_certs()
        
    def createConnection(self, csock, caddr):
        from ssl import SSLError
        try:    
            tls_socket = self.SSLContext.wrap_socket(csock, server_side=True)
        except SSLError as e:
            self.log_error(caddr, str(e))
            csock.close()
            return None
        else:
            pprint.pprint(tls_socket.getpeercert())
            return HTTPConnection(self, tls_socket, caddr)
            

def run_server(port, app, url_pattern="*"):
    srv = HTTPServer(port, app, url_pattern=url_pattern)
    srv.start()
    srv.join()
    

if __name__ == '__main__':

    def app(env, start_response):
        start_response("200 OK", [("Content-Type","text/plain")])
        return (
            "%s = %s\n" % (k,v) for k, v in env.items()
            )

    run_server(8000, app)
