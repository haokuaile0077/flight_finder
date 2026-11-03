"""单路线单日期查询服务。日期范围和多城市可在上层复用本服务。"""
from datetime import date, timedelta

from .errors import DataError
from .filters import flight_matches, sort_quotes
from .models import Itinerary, Quote, SearchCriteria
from .pricing import NoDiscountPricing, PricingPolicy
from .provider import FlightProvider
from .validation import validate_criteria


def _check_quote_consistency(q: Quote, itinerary: Itinerary) -> None:
    """校验报价模块返回值的一致性。"""
    if (q.itinerary != itinerary or q.currency != "CNY"
            or any(type(v) is not int for v in (q.base_price_cents, q.discount_cents, q.final_price_cents))
            or q.base_price_cents != itinerary.base_price_cents
            or not 0 <= q.discount_cents <= q.base_price_cents
            or q.final_price_cents != q.base_price_cents - q.discount_cents
            or sum(line.amount_cents for line in q.breakdown) != q.final_price_cents):
        raise DataError("报价模块返回了不一致的价格，请检查计价规则。")


class SearchService:
    def __init__(self, provider: FlightProvider, pricing: PricingPolicy | None = None):
        self.provider = provider
        self.pricing = pricing if pricing is not None else NoDiscountPricing()

    def _quotes_for(self, criteria: SearchCriteria) -> tuple[Quote, ...]:
        """执行一次单路线单日期查询，返回未排序的 Quote 列表。"""
        validate_criteria(criteria, self.provider.cities)
        outbound = tuple(f for f in self.provider.search(criteria.origin, criteria.destination, criteria.departure_date)
                         if flight_matches(f, criteria))
        if criteria.return_date is None:
            itineraries = (Itinerary(f) for f in outbound)
        else:
            inbound = tuple(f for f in self.provider.search(criteria.destination, criteria.origin, criteria.return_date)
                            if flight_matches(f, criteria))
            itineraries = (Itinerary(a, b) for a in outbound for b in inbound if b.departure > a.arrival)
        results = []
        for itinerary in itineraries:
            q = self.pricing.quote(itinerary)
            _check_quote_consistency(q, itinerary)
            if criteria.budget_cents is None or q.final_price_cents <= criteria.budget_cents:
                results.append(q)
        return tuple(results)

    def search(self, criteria: SearchCriteria) -> tuple[Quote, ...]:
        results = self._quotes_for(criteria)
        return sort_quotes(results, criteria.sort_order)

    def search_date_range(self, origin: str, destination: str,
                          start_date: date, end_date: date,
                          base_criteria: SearchCriteria) -> tuple[Quote, ...]:
        """日期范围查询：遍历 start_date 到 end_date，每天复用 search，去重后排序。"""
        from dataclasses import replace
        if start_date > end_date:
            raise ValueError("起始日期不能晚于结束日期。")
        all_quotes: list[Quote] = []
        seen_ids: set[str] = set()
        current = start_date
        while current <= end_date:
            criteria = replace(base_criteria, origin=origin, destination=destination,
                               departure_date=current, return_date=None)
            for q in self._quotes_for(criteria):
                if q.itinerary.id not in seen_ids:
                    seen_ids.add(q.itinerary.id)
                    all_quotes.append(q)
            current += timedelta(days=1)
        return sort_quotes(all_quotes, base_criteria.sort_order)

    def search_multi_city(self, origins: tuple[str, ...], destinations: tuple[str, ...],
                          criteria: SearchCriteria) -> tuple[Quote, ...]:
        """多城市查询：遍历所有出发×到达组合，去重后排序。"""
        from dataclasses import replace
        if not origins or not destinations:
            raise ValueError("出发和到达城市列表不能为空。")
        all_quotes: list[Quote] = []
        seen_ids: set[str] = set()
        for origin in origins:
            for destination in destinations:
                if origin == destination:
                    continue
                c = replace(criteria, origin=origin, destination=destination)
                for q in self._quotes_for(c):
                    if q.itinerary.id not in seen_ids:
                        seen_ids.add(q.itinerary.id)
                        all_quotes.append(q)
        return sort_quotes(all_quotes, criteria.sort_order)
