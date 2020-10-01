from .core import Primitive, synchronized
from threading import current_thread
import threading

def _thread_id():
    return current_thread().ident

class RWLock(Primitive):
    
    def __init__(self):
        Primitive.__init__(self)
        self.Exclusive = None
        self.ExclusiveCount = 0
        self.ExclusiveQueue = []
        self.Shared = {}
        
    def __purge(self):
        threads = set([t.ident for t in threading.enumerate()])
        if not self.Exclusive in threads:
            self.Exclusive = None
            self.ExclusiveCount = None
        for t in list(self.Shared.keys()):
            if not t in threads:
                del self.Shared[t]
        self.ExclusiveQueue = [t for t in self.ExclusiveQueue if t in threads]
    
    def __acq_exclusive(self):
        tid = _thread_id()
        self.__purge()
        if tid == self.Exclusive:
            self.ExclusiveCount += 1
            return True
        if self.Exclusive == None and (len(self.Shared) == 0 or len(self.Shared) == 1 and tid in self.Shared):
            if self.ExclusiveQueue:
                if tid == self.ExclusiveQueue[0]:
                    self.ExclusiveQueue = self.ExclusiveQueue[1:]
                else:
                    self.ExclusiveQueue.append(tid)
                    return False
            self.Exclusive = tid
            self.ExclusiveCount = 1
            return True
        return False
        
    def __rel_exclusive(self):
        tid = _thread_id()
        assert self.Exclusive == tid and self.ExclusiveCount > 0
        self.ExclusiveCount -= 1
        if self.ExclusiveCount <= 0:
            self.ExclusiveCount = 0
            self.Exclusive= None
        self.wakeup(all=True)
        
    def __acq_shared(self):
        tid = _thread_id()
        self.__purge()
        if not self.Exclusive in (None, tid):
            return False
        if not tid in self.Shared:
            self.Shared[tid] = 0
        self.Shared[tid] = self.Shared[tid] + 1
        return True
            
    def __rel_shared(self):
        tid = _thread_id()
        n = self.Shared.get(tid)
        assert n is not None and n > 0
        n -= 1
        if n == 0:
            del self.Shared[tid]
        else:
            self.Shared[tid] = n
        self.wakeup(all=True)
        
    @synchronized
    def acquireExclusive(self):
        while not self.__acq_exclusive():
            self.sleep()
            
    @synchronized
    def acquireShared(self):
        while not self.__acq_shared():
            self.sleep()
            
    @synchronized
    def releaseExclusive(self):
        self.__rel_exclusive()
        
    @synchronized
    def releaseShared(self):
        self.__rel_shared()
        
            
    @property
    def exclusive(self):
        class ExclusiveContext(object):
            def __init__(self, rwlock):
                self.RWLock = rwlock
            
            def __enter__(self):
                return self.RWLock.acquireExclusive()
            
            def __exit__(self, t, v, tb):
                return self.RWLock.releaseExclusive()
        return ExclusiveContext(self)
    
    @property
    def shared(self):
        class SharedContext(object):
            def __init__(self, rwlock):
                self.RWLock = rwlock
            
            def __enter__(self):
                return self.RWLock.acquireShared()
            
            def __exit__(self, t, v, tb):
                return self.RWLock.releaseShared()
            
        return SharedContext(self)
        
    @synchronized
    def owners(self):
        return self.Exclusive, list(self.Shared.keys())
        
