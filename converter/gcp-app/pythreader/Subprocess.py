
from .core import synchronized, Primitive

try:
    import subprocess, fcntl, select, os, time
    __subprocessing_enabled__ = hasattr(subprocess, "Popen")
    
    if __subprocessing_enabled__:

        class Subprocess(subprocess.Popen, Primitive):
    
            def __init__(self, *params, **args):
                subprocess.Popen.__init__(self, *params, **args)
                Primitive.__init__(self)
        
            @synchronized
            def waitCompletion(self, timeout = None, input = None):
                if timeout is None:
                    out, err = self.communicate(input)
                    return self.poll(), out, err
            
                t0 = time.time()
                t1 = t0 + timeout
                if input is not None:
                    assert self.stdin is not None
                    self.stdin.write(input)

                outfd = self.stdout.fileno() if self.stdout is not None else None
                errfd = self.stderr.fileno() if self.stderr is not None else None
                out_lst = []
                err_lst = []
                status = self.poll()
                #print "Subprocess.wait: initial status=%s" % (status,)
                if outfd is None and errfd is None:
                    raise ValueError("Timeout can be specified only if either stderr or stdout is a pipe")
                else:
                    poll = select.poll()
                    open_pipes = 0
                    if outfd is not None:   
                        out_flags = fcntl.fcntl(outfd, fcntl.F_GETFL)
                        fcntl.fcntl(outfd, fcntl.F_SETFL, out_flags | os.O_NONBLOCK)
                        poll.register(outfd, select.POLLIN)
                        open_pipes += 1
                    if errfd is not None:   
                        err_flags = fcntl.fcntl(errfd, fcntl.F_GETFL)
                        fcntl.fcntl(errfd, fcntl.F_SETFL, err_flags | os.O_NONBLOCK)
                        poll.register(errfd, select.POLLIN)
                        open_pipes += 1
                    while time.time() < t1 and open_pipes > 0 and status is None:
                        dt = max(0.0, t1 - time.time())
                        if dt > 0.0:
                            for fd, event in poll.poll(dt*1000.0):
                                if fd == outfd:
                                    data = self.stdout.read(100000)
                                    if not data:
                                        open_pipes -= 1
                                        poll.unregister(outfd)
                                    else:
                                        out_lst.append(data)
                                elif fd == errfd:
                                    data = self.stderr.read(100000)
                                    if not data:
                                        open_pipes -= 1
                                        poll.unregister(errfd)
                                    else:
                                        err_lst.append(data)
                        status = self.poll()
                        #print "Subprocess.wait: status=%s, pipes=%d" % (status,open_pipes)

                    if outfd is not None:
                        fcntl.fcntl(outfd, fcntl.F_SETFL, out_flags)
                    if errfd is not None:
                        fcntl.fcntl(errfd, fcntl.F_SETFL, err_flags)

                if status is None:
                    while status is None and time.time() < t1:
                        #print "keep waiting after all pipes closed..."
                        time.sleep(0.1)
                        status = self.poll()

                    if status is not None:
                        out = self.stdout.read()
                        out_lst.append(out or "")
                        err = self.stderr.read()
                        err_lst.append(err or "")

            	#print "status=", status
                    return status, "".join(out_lst), "".join(err_lst)
        
        
except ImportError:
    __subprocessing_enabled__ = False
                        
if not __subprocessing_enabled__:
    # if running in the environment where subprocessing is disabled (e.g. cloud), just create dummy classes

    class Subprocess: 
        def __init__(self, *params, **args):
            raise NotImplementedError("Subprocessing is disabled")

del __subprocessing_enabled__
            
class ShellCommand(Subprocess):

    def __init__(self, command, cwd=None, env=None, input=None):
        Subprocess.__init__(self, command, shell=True, close_fds=True,
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            stdin=None if input is None else suprocess.PIPE,
            cwd=cwd, env=env)
        if input is not None:
            self.stdin.write(input)

    
