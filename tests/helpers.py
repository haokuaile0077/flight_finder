from datetime import datetime

from flight_app.models import Airport, CHINA_TZ, Flight, Segment

AIRPORTS = {"深圳": Airport("SZX", "深圳", "深圳宝安"),
            "北京": Airport("PEK", "北京", "北京首都"),
            "上海": Airport("SHA", "上海", "上海虹桥")}


def flight(id="out", origin="深圳", dest="北京", start="2026-11-10T08:00", end="2026-11-10T11:00", price=50000, seats=5, airline="云翼"):
    seg = Segment("YY100", airline, AIRPORTS[origin], AIRPORTS[dest],
                  datetime.fromisoformat(start).replace(tzinfo=CHINA_TZ),
                  datetime.fromisoformat(end).replace(tzinfo=CHINA_TZ))
    return Flight(id, (seg,), price, seats)


class MemoryProvider:
    cities = tuple(AIRPORTS)
    airlines = ("云翼", "星海")

    def __init__(self, flights):
        self.flights = tuple(flights)

    def search(self, origin, destination, on_date):
        return tuple(f for f in self.flights if f.origin.city==origin and f.destination.city==destination and f.departure.date()==on_date)
