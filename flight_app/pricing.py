"""报价扩展点：后续优惠只需实现相同的quote接口。"""
from typing import Protocol

from .models import Itinerary, PriceLine, Quote


class PricingPolicy(Protocol):
    def quote(self, itinerary: Itinerary) -> Quote: ...


class NoDiscountPricing:
    def quote(self, itinerary: Itinerary) -> Quote:
        lines = [PriceLine("去程模拟含税价", itinerary.outbound.price_cents)]
        if itinerary.inbound:
            lines.append(PriceLine("返程模拟含税价", itinerary.inbound.price_cents))
        return Quote(itinerary, itinerary.base_price_cents, 0, itinerary.base_price_cents, tuple(lines))
