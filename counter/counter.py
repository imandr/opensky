from webpie import WPApp, WPHandler, Response
import json, csv, io, pprint, sqlite3, time, re
import requests
from pythreader import Task, TaskQueue, PyThread, synchronized, DEQueue

Airports = {
    "KORD":  (41.978611, -87.904722),
    "KATL":  (33.636667, -84.428056),
    "KSFO":  (37.618889, -122.375),
    "KJFK":  (40.63980103,-73.77890015),
    "KDEN":  (39.861667, -104.673056),
    "KEWR":  (40.692501068115234,-74.168701171875),
    "KMCO":  (28.429399490356445,-81.30899810791016),
    "KDFW":  (32.896944, -97.038056),
    "KLAX":  (33.94250107,-118.4079971),
    "KSEA":  (47.449001,-122.308998),
    #"KBOS":  (42.36429977,-71.00520325),
    "KIAH":  (29.984399795532227,-95.34140014648438),
    "KIAD":  (38.94449997,-77.45580292),
    "PHNL":  (21.32062,-157.924228),
    "MMUN":  (21.036500930800003,-86.8770980835),
    #"KMEM":  (35.04240036010742,-89.97669982910156),           # FedEx hub
    "KMIA":  (25.79319953918457,-80.29060363769531),    
    "KLGA":  (40.77719879,-73.87259674),
    #"KTPA":  (27.975500106811523,-82.533203125)
}

Airlines = {
    "AAL", "UAL", "FDX", "DLH", "SJJ", "SWA", "SKW", "ASA"
}

GALT = 13
BALT = 7
ICAO24 = 0
CALL = 1
COUNTRY = 2
LON = 5
LAT = 6
ON_GROUND = 8
VELOCITY = 9
TRACK = 10
VERTICAL_RATE = 11


class Database(PyThread):
    
    def __init__(self, dbfile):
        PyThread.__init__(self)
        self.DBFile = dbfile
        self.DB = None
        
        self.InputQueue = DEQueue()
        self.Stop = False

    def date(self, t):
        return int(t/3600/24)

    def add(self, timestamp, airport, flights):
        self.InputQueue.append((timestamp, airport, flights))

    def stop(self):
        self.Stop = True
        self.InputQueue.close()

    def run(self):
        self.DB = sqlite3.connect(self.DBFile)
        self.DB.cursor().execute("""
            create table if not exists 
            flights(
                timestamp   int,
                callsign    text,
                airline     text,
                date        int,
                airport     text,
                icao        text,
                primary key(callsign, date, airport)
            );
        """)
        while not self.Stop:
            tup = self.InputQueue.pop()
            if tup is not None:
                timestamp, airport, flights = tup
                stored = self.store(timestamp, airport, flights)    
                for tup in stored:
                    print(*tup)    
        
    Airline_RE = re.compile("[A-Z]+")
        
    def store(self, timestamp, airport, flights):
        d = int(timestamp/3600/24)
        c = self.DB.cursor()
        c.execute("""select callsign from flights where date=? and airport=?""", (d, airport))
        found = set(callsign for (callsign,) in c.fetchall())
        #print("found:", sorted(list(found)))
        to_store = []
        for f in flights:
            callsign = f["callsign"]
            if callsign and not callsign in found:
                airline = self.Airline_RE.match(callsign)
                if airline:
                    airline = airline[0]
                if airline != "N":
                    to_store.append((timestamp, f["callsign"], airline, d, airport, f["icao"]))
        #for f in sorted(to_store):
        #    print (f)
        c.executemany("insert into flights(timestamp, callsign, airline, date, airport, icao) values(?,?,?,?,?,?)", to_store)
        c.execute("commit")
        return to_store

class ScanTask(Task):
    
    Window = 50 # km
    
    def __init__(self, db, airport):
        Task.__init__(self)
        self.DB = db
        self.Airport = airport
                
    URL_Template = "https://opensky-network.org/api/states/all?lamin=%(lamin)f&lomin=%(lomin)f&lamax=%(lamax)f&lomax=%(lomax)f"

    def run(self):
        airport = self.Airport
        
        #print(f"starting scan for {self.Airport}")

        dw = self.Window/111.0
    
        la, lo = Airports[airport]
        lomin, lomax = lo-dw, lo+dw
        lamin, lamax = la-dw, la+dw
    
        url = self.URL_Template % dict(lamin=lamin, lamax=lamax, lomin=lomin, lomax=lomax)    
        #print(url)
        resp = requests.get(url)
        try:    data = resp.json()
        except:
            print("Error parsing response for %s:\n%s\n" % (self.Airport, resp.text))
            return

        #print(data)
        states = data["states"]
    
        if not states:
            print(f"No flights for {airport} (lo:[{lomin}:{lomax}], la:[{lamin}:{lamax})]")
            return []
    
        timestamp = data["time"]
    
        data = [
            {"icao":d[ICAO24].strip(), "callsign":d[CALL].strip(), "country":d[COUNTRY]}
            for d in states       
        ]
    
        self.DB.add(timestamp, airport, data)
            
    
if __name__ == "__main__":
    tstart = time.time()
    window = 20       # km
    db = Database("flights.sqlite")
    db.start()
    scanner_queue = TaskQueue(10, stagger=0.5)
    for airport in Airports.keys():
        scanner_queue.addTask(ScanTask(db, airport))
    scanner_queue.waitUntilEmpty()
    db.stop()
    db.join()
    tend = time.time()
    print("runtime:", tend-tstart)
    
        
        

