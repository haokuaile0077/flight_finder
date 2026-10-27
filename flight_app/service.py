"""单路线单日期查询服务。日期范围和多城市可在上层复用本服务。"""
from .errors import DataError
from .filters import flight_matches, sort_quotes
from .models import Itinerary, Quote, SearchCriteria
from .pricing import NoDiscountPricing, PricingPolicy
from .provider import FlightProvider
from .validation import validate_criteria


class SearchService:
    def __init__(self, provider: FlightProvider, pricing: PricingPolicy | None = None):
        self.provider = provider
        self.pricing = pricing if pricing is not None else NoDiscountPricing()

    def search(self, criteria: SearchCriteria) -> tuple[Quote, ...]:
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
            if (q.itinerary != itinerary or q.currency != "CNY"
                    or any(type(v) is not int for v in (q.base_price_cents, q.discount_cents, q.final_price_cents))
                    or q.base_price_cents != itinerary.base_price_cents
                    or not 0 <= q.discount_cents <= q.base_price_cents
                    or q.final_price_cents != q.base_price_cents - q.discount_cents
                    or sum(line.amount_cents for line in q.breakdown) != q.final_price_cents):
                raise DataError("报价模块返回了不一致的价格，请检查计价规则。")
            if criteria.budget_cents is None or q.final_price_cents <= criteria.budget_cents:
                results.append(q)
        return sort_quotes(results, criteria.sort_order)
