"""离线生成确定性的教学数据，不访问任何网络。会覆盖data/flights.json。"""
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


def build_dataset() -> dict:
    airport_rows = [("SZX", "深圳", "深圳宝安"), ("CAN", "广州", "广州白云"),
                    ("ZUH", "珠海", "珠海金湾"), ("PEK", "北京", "北京首都"),
                    ("SHA", "上海", "上海虹桥"), ("DAT", "大同", "大同云冈"),
                    ("TYN", "太原", "太原武宿")]
    airports = [dict(zip(("code", "city", "name"), row)) for row in airport_rows]
    # 全部航司、航班及价格为自行编写，不代表任何真实运营信息。
    airlines = [("云翼航空（模拟）", "YY"), ("星海航空（模拟）", "XH"), ("青禾航空（模拟）", "QH")]
    routes = [("SZX", "PEK", 190, 720), ("CAN", "PEK", 190, 680), ("ZUH", "PEK", 190, 650),
              ("SZX", "SHA", 145, 580), ("SZX", "DAT", 200, 760), ("CAN", "TYN", 165, 620),
              ("ZUH", "TYN", 170, 610), ("PEK", "SHA", 130, 500), ("PEK", "DAT", 70, 390),
              ("SHA", "TYN", 150, 530), ("SZX", "TYN", 185, 660), ("CAN", "DAT", 195, 710)]
    flights = []
    tz = timezone(timedelta(hours=8))
    for day_index in range(30):
        on_date = date(2026, 11, 1) + timedelta(days=day_index)
        for route_index, (a, b, minutes, base) in enumerate(routes):
            for reverse in (False, True):
                origin, dest = (b, a) if reverse else (a, b)
                for variant in range(4):
                    hour, minute = [(8, 15), (14, 30), (23, 20), (10, 5)][variant]
                    depart = datetime.combine(on_date, time(hour, minute), tzinfo=tz)
                    airline, prefix = airlines[(route_index + variant) % len(airlines)]
                    number = f"{prefix}{1000 + route_index * 20 + int(reverse) * 5 + variant}"
                    def segment(src, dst, start, end, flight_no):
                        return {"flight_number": flight_no, "airline": airline,
                                "origin": src, "destination": dst,
                                "departure": start.isoformat(), "arrival": end.isoformat()}
                    if variant == 3:
                        middle = next(x for x in ("SHA", "TYN", "PEK") if x not in (origin, dest))
                        first_arrival = depart + timedelta(minutes=100)
                        second_depart = first_arrival + timedelta(minutes=75)
                        segments = [segment(origin, middle, depart, first_arrival, number),
                                    segment(middle, dest, second_depart, second_depart+timedelta(minutes=110), number+"B")]
                    else:
                        segments = [segment(origin, dest, depart, depart+timedelta(minutes=minutes), number)]
                    price = (base + (day_index * 17 + route_index * 11) % 150 + [60, 0, -80, -120][variant]) * 100
                    # 演示余票为0的航班被排除，其他航班均为确定性的非随机数据。
                    seats = 0 if variant == 1 and (day_index+route_index) % 7 == 0 else 1 + (day_index+variant+route_index) % 9
                    flights.append({"id": f"SIM-{on_date:%Y%m%d}-{origin}-{dest}-{variant}",
                                    "segments": segments, "price_cents": price, "seats": seats, "cabin": "economy"})
    return {"schema_version": 1, "simulated": True,
            "description": "教学模拟数据：2026-11-01至2026-11-30；虚构航司、航班与含税价格，不可用于真实出行。",
            "airports": airports, "flights": flights}


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "data" / "flights.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset = build_dataset()
    path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"生成 {len(dataset['flights'])} 条模拟单程报价：{path}")
