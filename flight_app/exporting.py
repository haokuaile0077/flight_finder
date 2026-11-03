"""导出当前结果快照；UTF-8 BOM便于Excel识别中文。"""
import csv
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .models import Quote, SearchCriteria
from .presentation import money


def _safe(text: str) -> str:
    # 防止用户编辑的数据文件在电子表格中被解释为公式。
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def export_quotes(path: Path | str, quotes: Sequence[Quote], criteria: SearchCriteria) -> int:
    """保留传入结果的顺序；写失败时不覆盖已有文件。"""
    target = Path(path)
    headers = ["数据性质", "出发城市", "到达城市", "查询去程日期", "查询返程日期", "预算上限元", "仅直飞", "全程航司筛选", "排序", "去程航班", "去程航司", "去程起飞", "去程到达", "返程航班", "返程航司", "返程起飞", "返程到达", "原价元", "优惠元", "合计元", "币种", "报价编号"]
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=target.parent, delete=False) as stream:
            temp_path = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(headers)
            for q in quotes:
                a, b = q.itinerary.outbound, q.itinerary.inbound
                row = ["模拟数据 仅供教学", criteria.origin, criteria.destination, criteria.departure_date.isoformat(),
                       criteria.return_date.isoformat() if criteria.return_date else "", money(criteria.budget_cents) if criteria.budget_cents is not None else "不限",
                       "是" if criteria.direct_only else "否", criteria.airline or "不限", criteria.sort_order.value,
                       a.flight_numbers, a.airline_names, a.departure.isoformat(), a.arrival.isoformat(),
                       b.flight_numbers if b else "", b.airline_names if b else "", b.departure.isoformat() if b else "", b.arrival.isoformat() if b else "",
                       money(q.base_price_cents).replace(",", ""), money(q.discount_cents).replace(",", ""), money(q.final_price_cents).replace(",", ""), q.currency, q.itinerary.id]
                writer.writerow([_safe(str(v)) for v in row])
        os.replace(temp_path, target)
        return len(quotes)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
