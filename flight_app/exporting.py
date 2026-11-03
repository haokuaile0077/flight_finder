"""导出不可变的查询快照；UTF-8 BOM、公式保护和原子替换。"""
import csv
import os
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from .models import Quote, RangeCriteria, SearchCriteria
from .presentation import money


HEADERS = ["数据性质", "出发城市", "到达城市", "查询去程日期", "查询返程日期", "预算上限元",
           "仅直飞", "全程航司筛选", "排序", "去程航班", "去程航司", "去程起飞", "去程到达",
           "返程航班", "返程航司", "返程起飞", "返程到达", "原价元", "优惠元", "合计元", "币种", "报价编号"]


def _safe(text: str) -> str:
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _write(path: Path | str, headers: list[str], rows: Iterable[list]) -> int:
    target = Path(path)
    temp_path = None
    count = 0
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="",
                                         dir=target.parent, delete=False) as stream:
            temp_path = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(headers)
            for row in rows:
                writer.writerow([_safe(str(v)) for v in row])
                count += 1
        os.replace(temp_path, target)
        return count
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _flight_columns(q: Quote) -> list:
    a, b = q.itinerary.outbound, q.itinerary.inbound
    return [a.flight_numbers, a.airline_names, a.departure.isoformat(), a.arrival.isoformat(),
            b.flight_numbers if b else "", b.airline_names if b else "", b.departure.isoformat() if b else "",
            b.arrival.isoformat() if b else "", money(q.base_price_cents).replace(",", ""),
            money(q.discount_cents).replace(",", ""), money(q.final_price_cents).replace(",", ""),
            q.currency, q.itinerary.id]


def export_quotes(path: Path | str, quotes: Sequence[Quote], criteria: SearchCriteria) -> int:
    """兼容初版接口，保留传入顺序；不重新查询或读取界面条件。"""
    def rows():
        for q in quotes:
            yield ["模拟数据 仅供教学", criteria.origin, criteria.destination, criteria.departure_date.isoformat(),
                   criteria.return_date.isoformat() if criteria.return_date else "",
                   money(criteria.budget_cents).replace(",", "") if criteria.budget_cents is not None else "不限",
                   "是" if criteria.direct_only else "否", criteria.airline or "不限", criteria.sort_order.value,
                   *_flight_columns(q)]
    return _write(path, HEADERS, rows())


def export_range_quotes(path: Path | str, quotes: Sequence[Quote], criteria: RangeCriteria,
                        discount_description: str = "") -> int:
    """实际路线与日期单列；完整保留多城市、日期范围及优惠快照。"""
    extra = ["查询模式", "查询出发城市范围", "查询到达城市范围", "查询开始日期", "查询结束日期",
             "应用模拟优惠", "模拟优惠规则", "价格明细"]
    def rows():
        for q in quotes:
            a = q.itinerary.outbound
            yield ["模拟数据 仅供教学", a.origin.city, a.destination.city, a.departure.date().isoformat(), "",
                   money(criteria.budget_cents).replace(",", "") if criteria.budget_cents is not None else "不限",
                   "是" if criteria.direct_only else "否", criteria.airline or "不限", criteria.sort_order.value,
                   *_flight_columns(q), "灵活单程", " / ".join(criteria.origins), " / ".join(criteria.destinations),
                   criteria.start_date.isoformat(), criteria.end_date.isoformat(),
                   "是" if criteria.discount_enabled else "否", discount_description,
                   "；".join(f"{line.label} {line.amount_cents / 100:.2f}元" for line in q.breakdown)]
    return _write(path, HEADERS + extra, rows())
