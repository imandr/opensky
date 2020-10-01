from threading import RLock, Thread, Event, Condition, Semaphore
import time
import sys

Waiting = []
In = []

def synchronized(method):
    def smethod(self, *params, **args):
        #print "@synchronized: wait %s..." % (method,)
        q = "%s(%x).@synch(%s)" % (self, id(self), method)
        Waiting.append(q)
        with self:
            Waiting.remove(q)
            #print "@synchronized: in %s" % (method,)
            In.append(q)
            out = method(self, *params, **args)
        #print "@synchronized: out %s" % (method,)
        In.remove(q)
        return out
    return smethod

def gated(method):
    def smethod(self, *params, **args):
        #print "@synchronized: wait %s..." % (method,)
        q = "%s(%x).@gated(%s)" % (self, id(self), method)
        Waiting.append(q)
        with self._Gate:
            Waiting.remove(q)
            #print "@synchronized: in %s" % (method,)
            In.append(q)
            out = method(self, *params, **args)
        #print "@synchronized: out %s" % (method,)
        In.remove(q)
        return out
    return smethod


def printWaiting():
    print("waiting:----")
    for w in Waiting:
        print(w)
    print("in:---------")
    for w in In:
        print(w)

class Primitive:
    def __init__(self, gate=1, lock=None):
        self._Lock = lock if lock is not None else RLock()
        self._WakeUp = Condition(self._Lock)
        self._Gate = Semaphore(gate)

    def getLock(self):
        return self._Lock
        
    def __enter__(self):
        return self._Lock.__enter__()
        
    def __exit__(self, exc_type, exc_value, traceback):
        return self._Lock.__exit__(exc_type, exc_value, traceback)

    @synchronized
    def sleep(self, timeout = None, function=None, arguments=()):
        self._WakeUp.wait(timeout)
        if function is not None:
            return function(*arguments)

    # await is a reserved word in Python 3, use "wakeup" instead
    @synchronized
    def wakeup(self, n=1, all=False, function=None, arguments=()):
        if function is not None:
            function(*arguments)
        if all:
            self._WakeUp.notifyAll()
        else:
            self._WakeUp.notify(n)

if sys.version_info < (3,0):
    # await is a reserved word in Python 3, keep it for backward compatibility
    # in Python 2.
    setattr(Primitive, "await", Primitive.sleep)


class PyThread(Thread, Primitive):
    def __init__(self, func=None, *params, **args):
        Thread.__init__(self)
        Primitive.__init__(self)
        self.Func = func
        self.Params = params
        self.Args = args
        
    def run(self):
        if self.Func is not None:
            self.Func(*self.Params, **self.Args)

class TimerThread(PyThread):
    def __init__(self, function, interval, *params, **args):
        PyThread.__init__(self)
        self.Interval = interval
        self.Func = function
        self.Params = params
        self.Args = args
        self.Pause = False

    def run(self):
        while True:
            if self.Pause:
                self.sleep()
            self.Func(*self.Params, **self.Args)
            time.sleep(self.Interval)
    
    def pause(self):
        self.Pause = True
        
    def resume(self):
        self.Pause = False
        self.wakeup()
                
            
            
