"""单路线的日期范围查询，复用单日期查询的全部业务规则。"""
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta

from .errors import SearchCancelled, ValidationError
from .filters import sort_quotes
from .models import Quote, SearchCriteria
from .service import SearchService

MAX_RANGE_DAYS = 31


def validate_date_span(start_date: date, end_date: date) -> int:
    """验证日期，返回包含首尾的天数；避免误选导致无限扩大查询。"""
    if type(start_date) is not date or type(end_date) is not date:
        raise ValidationError("起止日期必须为date类型。")
    days = (end_date - start_date).days + 1
    if days < 1:
        raise ValidationError("开始日期不能晚于结束日期。")
    if days > MAX_RANGE_DAYS:
        raise ValidationError(f"一次最多查询{MAX_RANGE_DAYS}天，请缩小日期范围。")
    return days


def search_dates(service: SearchService, criteria: SearchCriteria, end_date: date, *,
                 cancel_check: Callable[[], bool] | None = None,
                 progress: Callable[[int, int], None] | None = None) -> tuple[Quote, ...]:
    """单程范围查询；回调仅传递普通数据，不依赖GUI。"""
    if criteria.return_date is not None:
        raise ValidationError("日期范围查询仅支持单程；往返请使用常规查询。")
    days = validate_date_span(criteria.departure_date, end_date)
    results = {}
    for offset in range(days):
        if cancel_check and cancel_check():
            raise SearchCancelled("查询已取消。")
        current = replace(criteria, departure_date=criteria.departure_date + timedelta(days=offset))
        for quote in service.search(current):
            results[quote.itinerary.id] = quote
        if progress:
            progress(offset + 1, days)
    return sort_quotes(list(results.values()), criteria.sort_order)
