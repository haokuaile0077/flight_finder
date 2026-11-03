"""多城市与日期范围组合查询，不修改基础SearchService。"""
from collections.abc import Callable
from datetime import date

from .date_search import search_dates, validate_date_span
from .errors import SearchCancelled, ValidationError
from .filters import sort_quotes
from .models import Quote, RangeCriteria, SearchCriteria, SortOrder
from .service import SearchService
from .validation import validate_criteria


class RangeSearchService:
    def __init__(self, service: SearchService, cities: tuple[str, ...], *,
                 date_bounds: tuple[date, date] | None = None):
        self.service = service
        self.cities = cities
        self.date_bounds = date_bounds

    def validate(self, criteria: RangeCriteria) -> tuple[tuple[str, str], ...]:
        """一次校验全部条件；重复城市去重，同城组合排除。"""
        validate_date_span(criteria.start_date, criteria.end_date)
        if self.date_bounds:
            low, high = self.date_bounds
            if not low <= criteria.start_date <= criteria.end_date <= high:
                raise ValidationError(f"灵活查询日期须在数据覆盖范围 {low} 至 {high} 内。")
        groups = (criteria.origins, criteria.destinations)
        if any(not isinstance(g, (tuple, list)) or not g for g in groups):
            raise ValidationError("请至少选择一个出发城市和一个到达城市。")
        if any(not isinstance(c, str) or c not in self.cities for g in groups for c in g):
            raise ValidationError("城市列表包含未知城市，请从现有城市中选择。")
        routes = tuple((a, b) for a in dict.fromkeys(criteria.origins)
                       for b in dict.fromkeys(criteria.destinations) if a != b)
        if not routes:
            raise ValidationError("出发与到达不能只有同一个城市，请调整城市选择。")
        a, b = routes[0]
        validate_criteria(SearchCriteria(a, b, criteria.start_date, budget_cents=criteria.budget_cents,
                                        direct_only=criteria.direct_only, airline=criteria.airline,
                                        sort_order=criteria.sort_order), self.cities)
        return routes

    def search_range(self, origins: tuple[str, ...], destinations: tuple[str, ...],
                     start_date: date, end_date: date, budget_cents: int | None = None,
                     direct_only: bool = False, airline: str | None = None,
                     sort_order: SortOrder = SortOrder.PRICE, *,
                     cancel_check: Callable[[], bool] | None = None,
                     progress: Callable[[int, int], None] | None = None) -> tuple[Quote, ...]:
        criteria = RangeCriteria(origins, destinations, start_date, end_date, budget_cents,
                                 direct_only, airline, sort_order)
        routes = self.validate(criteria)
        days = validate_date_span(start_date, end_date)
        total = len(routes) * days
        results = {}
        for index, (a, b) in enumerate(routes):
            if cancel_check and cancel_check():
                raise SearchCancelled("查询已取消。")
            single = SearchCriteria(a, b, start_date, budget_cents=budget_cents,
                                    direct_only=direct_only, airline=airline, sort_order=sort_order)
            def report(done: int, _days: int, offset: int = index * days) -> None:
                if progress:
                    progress(offset + done, total)
            for quote in search_dates(self.service, single, end_date,
                                      cancel_check=cancel_check, progress=report):
                results[quote.itinerary.id] = quote
        if cancel_check and cancel_check():
            raise SearchCancelled("查询已取消。")
        return sort_quotes(list(results.values()), sort_order)
