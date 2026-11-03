"""数据源协议及JSON实现。按路线和日期索引，不包含GUI或优惠逻辑。"""
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from .errors import DataError
from .models import Airport, CHINA_TZ, Flight, Segment


class FlightProvider(Protocol):
    @property
    def cities(self) -> tuple[str, ...]: ...

    @property
    def airlines(self) -> tuple[str, ...]: ...

    def search(self, origin: str, destination: str, on_date: date) -> tuple[Flight, ...]: ...


def _text(obj: dict, key: str) -> str:
    value = obj[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}必须为非空文本")
    return value.strip()


def _integer(obj: dict, key: str) -> int:
    value = obj[key]
    if type(value) is not int or value < 0:
        raise ValueError(f"{key}必须为非负整数")
    return value


def _timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() != CHINA_TZ.utcoffset(None):
        raise ValueError("日期时间必须包含北京时间时区+08:00")
    return result.astimezone(CHINA_TZ)


class JsonFlightProvider:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if type(payload) is not dict or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
                raise ValueError("不支持的数据格式版本")
            if payload.get("simulated") is not True:
                raise ValueError("本版本仅允许明确标记的模拟数据")
            raw_airports = payload["airports"]
            if not isinstance(raw_airports, list) or not raw_airports:
                raise ValueError("airports必须是非空列表")
            airports = {}
            for item in raw_airports:
                airport = Airport(_text(item, "code"), _text(item, "city"), _text(item, "name"))
                if airport.code in airports:
                    raise ValueError("机场代码重复")
                airports[airport.code] = airport
            raw_flights = payload["flights"]
            if not isinstance(raw_flights, list):
                raise ValueError("flights必须是列表")
            flights = []
            ids = set()
            for item in raw_flights:
                ident = _text(item, "id")
                if ident in ids:
                    raise ValueError(f"报价编号重复：{ident}")
                ids.add(ident)
                raw_segments = item["segments"]
                if not isinstance(raw_segments, list) or not raw_segments:
                    raise ValueError(f"{ident}缺少航段")
                segments = []
                for raw in raw_segments:
                    seg = Segment(_text(raw, "flight_number"), _text(raw, "airline"),
                                  airports[_text(raw, "origin")], airports[_text(raw, "destination")],
                                  _timestamp(_text(raw, "departure")), _timestamp(_text(raw, "arrival")))
                    if seg.origin.code == seg.destination.code or seg.arrival <= seg.departure:
                        raise ValueError(f"{ident}的机场或起降时间无效")
                    if segments and (segments[-1].destination.code != seg.origin.code or
                                     segments[-1].arrival >= seg.departure):
                        raise ValueError(f"{ident}中转机场或衔接时间无效")
                    segments.append(seg)
                cabin = _text(item, "cabin")
                if cabin != "economy":
                    raise ValueError("初版仅支持economy舱位")
                flights.append(Flight(ident, tuple(segments), _integer(item, "price_cents"),
                                      _integer(item, "seats"), cabin))
            self._flights = tuple(flights)
            self._cities = tuple(sorted({a.city for a in airports.values()}))
            self._airlines = tuple(sorted({s.airline for f in flights for s in f.segments}))
            self._dates = tuple(sorted({f.departure.date() for f in flights}))
            self._index = defaultdict(list)
            for flight in flights:
                self._index[(flight.origin.city, flight.destination.city, flight.departure.date())].append(flight)
            self.description = _text(payload, "description")
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
            raise DataError(f"模拟航班数据无法读取或格式不正确：{exc}") from exc

    @property
    def cities(self) -> tuple[str, ...]:
        return self._cities

    @property
    def airlines(self) -> tuple[str, ...]:
        return self._airlines

    @property
    def dates(self) -> tuple[date, ...]:
        return self._dates

    def search(self, origin: str, destination: str, on_date: date) -> tuple[Flight, ...]:
        return tuple(self._index.get((origin, destination, on_date), ()))
