"""筛选与排序不依赖GUI和数据文件。"""
from .models import Flight, Quote, SearchCriteria, SortOrder


def flight_matches(flight: Flight, criteria: SearchCriteria) -> bool:
    return (flight.seats >= criteria.passengers
            and (not criteria.direct_only or flight.direct)
            and (criteria.airline is None or all(s.airline == criteria.airline for s in flight.segments)))


def sort_quotes(quotes: list[Quote], order: SortOrder) -> tuple[Quote, ...]:
    if order == SortOrder.PRICE:
        key = lambda q: (q.final_price_cents, q.itinerary.outbound.departure, q.itinerary.id)
    else:
        key = lambda q: (q.itinerary.outbound.departure,
                         q.itinerary.inbound.departure if q.itinerary.inbound else q.itinerary.outbound.departure,
                         q.final_price_cents, q.itinerary.id)
    return tuple(sorted(quotes, key=key))
