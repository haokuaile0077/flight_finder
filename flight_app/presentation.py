"""GUI与CSV共用的格式化函数。"""
from .models import Flight, Quote


def money(cents: int) -> str:
    return f"{cents // 100:,}.{cents % 100:02d}"


def duration(flight: Flight) -> str:
    hours, minutes = divmod(flight.duration_minutes, 60)
    return f"{hours}小时{minutes:02d}分"


def leg_label(flight: Flight | None) -> str:
    if flight is None:
        return "—"
    day_difference = (flight.arrival.date() - flight.departure.date()).days
    suffix = f" (+{day_difference}天)" if day_difference else ""
    return f"{flight.departure:%m-%d %H:%M} → {flight.arrival:%H:%M}{suffix}"


def detail_text(quote: Quote) -> str:
    lines = ["模拟数据，仅供教学演示。北京时间 / 1名成人 / 经济舱 / CNY。", ""]
    for label, flight in zip(("去程", "返程"), quote.itinerary.legs):
        lines.extend([f"{label}  {flight.origin.city} → {flight.destination.city}",
                      f"{flight.flight_numbers}  {flight.airline_names}",
                      f"总时长 {duration(flight)}  |  余票 {flight.seats}  |  模拟含税价 ¥{money(flight.price_cents)}"])
        for idx, seg in enumerate(flight.segments):
            lines.append(f"  {seg.flight_number} {seg.airline}\n  {seg.origin.name} ({seg.origin.code}) → {seg.destination.name} ({seg.destination.code})\n  {seg.departure:%Y-%m-%d %H:%M} → {seg.arrival:%Y-%m-%d %H:%M}")
            if idx + 1 < len(flight.segments):
                wait = int((flight.segments[idx+1].departure-seg.arrival).total_seconds()//60)
                lines.append(f"  在{seg.destination.city}中转，等待{wait}分钟")
        lines.append("")
    lines.append("价格明细")
    lines.extend(f"{line.label}：{'-' if line.amount_cents < 0 else ''}¥{money(abs(line.amount_cents))}" for line in quote.breakdown)
    lines.extend([f"优惠金额：¥{money(quote.discount_cents)}", f"合计：¥{money(quote.final_price_cents)}"])
    if quote.itinerary.inbound:
        lines.append("往返价格为两张模拟单程票之和，并非真实航司往返联票。")
    return "\n".join(lines)
