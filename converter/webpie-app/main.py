from webpie import WPApp, WPHandler, Response
import json, csv, io, pprint
import requests

class Handler(WPHandler):

    URL_Template = "https://opensky-network.org/api/states/all?lamin=%(lamin)f&lomin=%(lomin)f&lamax=%(lamax)f&lomax=%(lomax)f"
    
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
    
    Labels = """
        icao24 callsign origin_country time_position last_contact
        longitude latitude baro_altitude on_ground velocity true_track
        vertical_rate sensors geo_altitude squawk spi position_source
        """.split()
        
    
    
    def ping(self, req, relpath, **args):
        return "pong "+(relpath or "")
    
    def states(self, req, relpath, **args):
        box = { k:float(args[k]) for k in ["lamin", "lomin", "lamax", "lomax"] }        # sanity, injunction check
        resp = requests.get(self.URL_Template % box)
        data = resp.json()
        states = data["states"]
        timestamp = data["time"]
        
        out_states = []
        
        for s in states:
            out_states.append(dict(zip(self.Labels, s)))

        out = {
            "timestamp":timestamp,
            "states":out_states
        }
        return json.dumps(out), "text/json"

    def data_csv(self, req, relpath, **args):
        box = { k:float(args[k]) for k in ["lamin", "lomin", "lamax", "lomax"] }        # sanity, injunction check
        resp = requests.get(self.URL_Template % box)
        data = resp.json()
        states = data["states"]
        timestamp = data["time"]
        
        filtered = []
        for s in states:
            print("s:", s)
            if s[self.ON_GROUND]: continue
            alt = s[self.GALT] or s[self.BALT] or 0.0
            if alt <= 0.0:  continue
            if s[self.LON] is None or s[self.LAT] is None:  continue
            if not s[self.ICAO24]:  continue
            filtered.append((s[self.ICAO24], (s[self.CALL] or "").strip(), s[self.LON], s[self.LAT], alt, s[self.TRACK], s[self.VELOCITY], s[self.VERTICAL_RATE]))
        
        #pprint.pprint(filtered)
        
        outbuf = io.StringIO()
        csv_writer = csv.writer(outbuf)
        
        csv_writer.writerow([timestamp])
        for row in filtered:
            print(row)
            csv_writer.writerow(row)
        
        return outbuf.getvalue()
        
    data = data_csv
        
application = app = WPApp(Handler)

if __name__ == "__main__":
    import getopt, sys
    
    opts, args = getopt.getopt(sys.argv[1:], "p:")
    opts = dict(opts)
    port = int(opts.get("-p", 8888))
    print("Running at port", port)
    app.run_server(port)
        
        

