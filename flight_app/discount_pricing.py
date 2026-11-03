"""一个模拟航司的可配置单程满减，无外部API或动态数据。"""
import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from .errors import DataError
from .models import Itinerary, PriceLine, Quote
from .pricing import NoDiscountPricing, PricingPolicy


@dataclass(frozen=True)
class AirlineDiscountPricing:
    airline: str
    threshold_cents: int
    reduction_cents: int
    start_date: date
    end_date: date

    def quote(self, itinerary: Itinerary) -> Quote:
        base = NoDiscountPricing().quote(itinerary)
        flight = itinerary.outbound
        eligible = (itinerary.inbound is None
                    and all(s.airline == self.airline for s in flight.segments)
                    and self.start_date <= flight.departure.date() <= self.end_date
                    and base.base_price_cents >= self.threshold_cents)
        discount = min(self.reduction_cents, base.base_price_cents) if eligible else 0
        if not discount:
            return base
        return replace(base, discount_cents=discount,
                       final_price_cents=base.base_price_cents-discount,
                       breakdown=base.breakdown + (PriceLine("模拟航司满减（不叠加）", -discount),))


def load_pricing(path: Path | str) -> PricingPolicy:
    """严格校验完整配置；关闭优惠仍校验格式，避免潜伏配置错误。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        fields = {"enabled", "airline", "threshold_cents", "reduction_cents", "start_date", "end_date"}
        if not isinstance(data, dict) or set(data) != fields:
            raise ValueError("须且仅须包含enabled、airline、threshold_cents、reduction_cents、start_date、end_date")
        if type(data["enabled"]) is not bool:
            raise ValueError("enabled须为true或false")
        if not isinstance(data["airline"], str) or not data["airline"].strip():
            raise ValueError("airline须为非空航司名称")
        for field in ("threshold_cents", "reduction_cents"):
            if type(data[field]) is not int or not 0 <= data[field] <= 100000000:
                raise ValueError(f"{field}须为0至100000000的整数分，不能使用小数或布尔值")
        dates = []
        for field in ("start_date", "end_date"):
            if not isinstance(data[field], str):
                raise ValueError(f"{field}须为YYYY-MM-DD")
            value = date.fromisoformat(data[field])
            if value.isoformat() != data[field]:
                raise ValueError(f"{field}须为YYYY-MM-DD")
            dates.append(value)
        if dates[0] > dates[1]:
            raise ValueError("优惠开始日期不能晚于结束日期")
        policy = AirlineDiscountPricing(data["airline"].strip(), data["threshold_cents"],
                                       data["reduction_cents"], *dates)
        return policy if data["enabled"] else NoDiscountPricing()
    except (OSError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise DataError(f"模拟优惠配置无法读取或格式不正确：{exc}") from exc


def pricing_description(policy: PricingPolicy) -> str:
    if isinstance(policy, AirlineDiscountPricing):
        return (f"{policy.airline} 满{policy.threshold_cents / 100:g}减{policy.reduction_cents / 100:g}元；"
                f"出发日期 {policy.start_date} 至 {policy.end_date}，仅单程、不叠加")
    return "配置已关闭模拟优惠，按原价查询"
