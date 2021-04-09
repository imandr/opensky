from webpie import WPApp, WPHandler, WPStaticHandler
import sys, sqlite3, json, time



class DataHandler(WPHandler):
    
    Bin = {
        "y":        3600*24*7,
        "m":        3600*24,
        "w":        3600,
        "d":        1200
    }
    
    Window = {
        "y":        3600*24*365,
        "m":        3600*24*30,
        "w":        3600*24*7,
        "d":        3600*24
    }
    
    def stats_by_airline(self, request, relpath, window="w", **args):
        bin = self.Bin[window]
        now = int(time.time())
        t0 = (int(now - self.Window[window])//bin)*bin
        t1 = (now//bin)*bin
        times = list(range(t0, t1+bin, bin))
        #print(times)

        db = self.App.db()
        c = db.cursor()

        # find top 10 airlines

        c.execute("""
            select t, airline, count(*)
                from (
                    select distinct callsign, airline, (timestamp/?)*? as t from flights
                        where timestamp >= ? and airline in 
                        (
                            select airline
                                from (
                                    select distinct callsign, airline, date from flights
                                        where timestamp >= ?
                                    ) as counts
                                group by airline
                                order by count(*) desc limit 5
                        )
                    ) as counts 
                group by airline, t 
                order by t, airline
        """, (bin, bin, t0, t0))
        rows = c.fetchall()
        
        airlines = sorted(list(set(airline for t, airline, n in rows)))
        counts_by_time = {t:{a:0 for a in airlines} for t in times}
        
        for t, a, n in rows:
            if t == t1: counts_by_time[t][a] = None
            else:   counts_by_time[t][a] = n/bin*3600
        
        
        
        out = {
            "airlines": airlines,
            "times": times,
            "rows":   [
                [t] + [counts_by_time[t][a] for a in airlines]
                for t in times
            ]
        }
        
        return json.dumps(out), "text/json"
        
class GUIHandler(WPHandler):
        
    def stats_by_airline(self, request, relpath, window="w", **args):
        return self.render_to_response("stats_by_airline.html", window=window)
        
class TopHandler(WPHandler):

    def __init__(self, request, app):
        WPHandler.__init__(self, request, app)
        self.static = WPStaticHandler(request, app, root="static", cache_ttl=60)
        self.gui = GUIHandler(request, app)
        self.data = DataHandler(request, app)
    
class App(WPApp):
    
    def __init__(self, handler, dbfilename, **args):
        WPApp.__init__(self, handler, **args)
        self.DBFile = dbfilename
        
    def init(self):
        self.initJinjaEnvironment(tempdirs=["templates"])
        
    def db(self):
        return sqlite3.connect(self.DBFile)
        
application = App(TopHandler, "flights.sqlite")
        
if __name__ == "__main__":
    
    application.run_server(8899)