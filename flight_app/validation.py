"""用户输入解析与跨字段验证。"""
from datetime import date
from decimal import Decimal, InvalidOperation

from .errors import ValidationError
from .models import SearchCriteria, SortOrder


def parse_date(text: str, label: str = "日期") -> date:
    text = text.strip()
    try:
        value = date.fromisoformat(text)
        if value.isoformat() != text:
            raise ValueError
        return value
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"{label}请填写真实日期，格式为YYYY-MM-DD，例如2026-11-10。") from exc


def parse_budget(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
        if not amount.is_finite() or amount < 0 or amount > Decimal("1000000") or amount * 100 != (amount * 100).to_integral_value():
            raise ValueError
        return int(amount * 100)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ValidationError("预算须为0至1000000元的金额，最多保留两位小数；留空表示不限。") from exc


def validate_criteria(criteria: SearchCriteria, cities: tuple[str, ...]) -> None:
    if criteria.origin not in cities or criteria.destination not in cities:
        raise ValidationError("请选择数据集中存在的出发城市和到达城市。")
    if criteria.origin == criteria.destination:
        raise ValidationError("出发城市和到达城市不能相同。")
    if type(criteria.departure_date) is not date or (criteria.return_date is not None and type(criteria.return_date) is not date):
        raise ValidationError("查询日期必须为date类型。")
    if criteria.return_date is not None and criteria.return_date < criteria.departure_date:
        raise ValidationError("返程日期不能早于出发日期。")
    if type(criteria.passengers) is not int or criteria.passengers != 1:
        raise ValidationError("初版固定查询1名成人。")
    if criteria.budget_cents is not None and (type(criteria.budget_cents) is not int or not 0 <= criteria.budget_cents <= 100000000):
        raise ValidationError("预算须使用非负整数分，且不超过100万元。")
    if not isinstance(criteria.sort_order, SortOrder):
        raise ValidationError("不支持的排序方式。")
