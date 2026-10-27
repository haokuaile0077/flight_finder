"""公共不可变模型。金额单位为分，时间为北京时间。"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum

CHINA_TZ = timezone(timedelta(hours=8))


class SortOrder(str, Enum):
    PRICE = "价格从低到高"
    DEPARTURE = "起飞时间从早到晚"


@dataclass(frozen=True)
class Airport:
    code: str
    city: str
    name: str


@dataclass(frozen=True)
class Segment:
    flight_number: str
    airline: str
    origin: Airport
    destination: Airport
    departure: datetime
    arrival: datetime


@dataclass(frozen=True)
class Flight:
    """一次单程报价，可包含多个实际飞行航段。"""
    id: str
    segments: tuple[Segment, ...]
    price_cents: int
    seats: int
    cabin: str = "economy"

    @property
    def origin(self) -> Airport:
        return self.segments[0].origin

    @property
    def destination(self) -> Airport:
        return self.segments[-1].destination

    @property
    def departure(self) -> datetime:
        return self.segments[0].departure

    @property
    def arrival(self) -> datetime:
        return self.segments[-1].arrival

    @property
    def direct(self) -> bool:
        return len(self.segments) == 1

    @property
    def duration_minutes(self) -> int:
        return int((self.arrival - self.departure).total_seconds() // 60)

    @property
    def flight_numbers(self) -> str:
        return " / ".join(s.flight_number for s in self.segments)

    @property
    def airline_names(self) -> str:
        return " / ".join(dict.fromkeys(s.airline for s in self.segments))


@dataclass(frozen=True)
class SearchCriteria:
    origin: str
    destination: str
    departure_date: date
    return_date: date | None = None
    budget_cents: int | None = None
    direct_only: bool = False
    airline: str | None = None
    sort_order: SortOrder = SortOrder.PRICE
    passengers: int = 1


@dataclass(frozen=True)
class Itinerary:
    outbound: Flight
    inbound: Flight | None = None

    @property
    def legs(self) -> tuple[Flight, ...]:
        return (self.outbound,) if self.inbound is None else (self.outbound, self.inbound)

    @property
    def id(self) -> str:
        return "|".join(f.id for f in self.legs)

    @property
    def base_price_cents(self) -> int:
        return sum(f.price_cents for f in self.legs)


@dataclass(frozen=True)
class PriceLine:
    label: str
    amount_cents: int


@dataclass(frozen=True)
class Quote:
    itinerary: Itinerary
    base_price_cents: int
    discount_cents: int
    final_price_cents: int
    breakdown: tuple[PriceLine, ...]
    currency: str = "CNY"
