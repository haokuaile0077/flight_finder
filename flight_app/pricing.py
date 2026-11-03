"""报价扩展点：后续优惠只需实现相同的quote接口。"""
from dataclasses import dataclass
from typing import Protocol

from .models import Itinerary, PriceLine, Quote


class PricingPolicy(Protocol):
    def quote(self, itinerary: Itinerary) -> Quote: ...


def _base_lines(itinerary: Itinerary) -> list[PriceLine]:
    lines = [PriceLine("去程模拟含税价", itinerary.outbound.price_cents)]
    if itinerary.inbound:
        lines.append(PriceLine("返程模拟含税价", itinerary.inbound.price_cents))
    return lines


class NoDiscountPricing:
    def quote(self, itinerary: Itinerary) -> Quote:
        lines = _base_lines(itinerary)
        return Quote(itinerary, itinerary.base_price_cents, 0, itinerary.base_price_cents, tuple(lines))


@dataclass(frozen=True)
class PercentageDiscountPricing:
    """按百分比折扣，例如 discount_percent=20 表示打8折。只影响 base_price_cents，最高减到0。"""
    discount_percent: int  # 0~100
    label: str = "模拟折扣"

    def quote(self, itinerary: Itinerary) -> Quote:
        if not 0 <= self.discount_percent <= 100:
            raise ValueError("折扣百分比必须在0到100之间。")
        base = itinerary.base_price_cents
        discount = int(base * self.discount_percent / 100)
        lines = _base_lines(itinerary)
        if discount > 0:
            lines.append(PriceLine(f"{self.label} -{self.discount_percent}%", -discount))
        return Quote(itinerary, base, discount, base - discount, tuple(lines))


@dataclass(frozen=True)
class ThresholdDiscountPricing:
    """满减优惠：满 threshold_cents 减 reduce_cents。"""
    threshold_cents: int
    reduce_cents: int
    label: str = "模拟满减"

    def quote(self, itinerary: Itinerary) -> Quote:
        if self.threshold_cents < 0 or self.reduce_cents < 0:
            raise ValueError("满减的门槛和减免金额不能为负。")
        base = itinerary.base_price_cents
        discount = self.reduce_cents if base >= self.threshold_cents else 0
        lines = _base_lines(itinerary)
        if discount > 0:
            lines.append(PriceLine(f"{self.label} 满{self.threshold_cents // 100}减{self.reduce_cents // 100}", -discount))
        return Quote(itinerary, base, discount, base - discount, tuple(lines))


@dataclass(frozen=True)
class CompositePricing:
    """组合多个优惠策略，叠加生效。"""
    policies: tuple[PricingPolicy, ...]

    def quote(self, itinerary: Itinerary) -> Quote:
        base_policy = NoDiscountPricing()
        result = base_policy.quote(itinerary)
        for policy in self.policies:
            result = policy.quote(itinerary)
            # 累积所有优惠
            if isinstance(policy, (PercentageDiscountPricing, ThresholdDiscountPricing)):
                pass  # 直接用最新的即可，因为每个policy都是独立的
        # 用 NoDiscountPricing 作为基础，然后逐个应用
        base_quote = NoDiscountPricing().quote(itinerary)
        total_discount = 0
        all_lines = list(base_quote.breakdown)
        for policy in self.policies:
            q = policy.quote(itinerary)
            total_discount += q.discount_cents
            for line in q.breakdown:
                if line not in base_quote.breakdown:
                    all_lines.append(line)
        final = max(base_quote.base_price_cents - total_discount, 0)
        return Quote(itinerary, base_quote.base_price_cents, total_discount, final, tuple(all_lines))
