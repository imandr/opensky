from webpie import WebPieApp, WebPieHandler, Response
from urllib.request import urlopen
import json, csv, io, pprint

class Handler(WebPieHandler):

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
    
    def data(self, req, relpath, **args):
        box = { k:float(args[k]) for k in ["lamin", "lomin", "lamax", "lomax"] }        # sanity, injunction check
        resp = urlopen(self.URL_Template % box)
        data = json.load(resp)
        states = data["states"]
        timestamp = data["time"]
        
        filtered = []
        for s in states:
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
            csv_writer.writerow(row)
        
        return outbuf.getvalue()
        
application = app = WebPieApp(Handler)

if __name__ == "__main__":
    app.run_server(8888)
        
        

