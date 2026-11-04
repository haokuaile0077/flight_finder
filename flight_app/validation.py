"""用户输入解析与跨字段验证。"""
from datetime import date

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
    if not isinstance(criteria.sort_order, SortOrder):
        raise ValidationError("不支持的排序方式。")
