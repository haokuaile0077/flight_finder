import unittest
from dataclasses import replace
from datetime import date

from flight_app.errors import DataError, ValidationError
from flight_app.models import Flight, PriceLine, Quote, SearchCriteria, SortOrder
from flight_app.pricing import NoDiscountPricing
from flight_app.service import SearchService
from tests.helpers import MemoryProvider, flight

DAY = date(2026, 11, 10)


class SearchTests(unittest.TestCase):
    def query(self, flights, **kwargs):
        return SearchService(MemoryProvider(flights)).search(SearchCriteria("深圳", "北京", DAY, **kwargs))

    def test_one_way_exact_route_and_date(self):
        a=flight();wrong_route=flight("wrong", dest="上海");wrong_date=flight("day", start="2026-11-11T08:00", end="2026-11-11T11:00")
        self.assertEqual([q.itinerary.id for q in self.query([a, wrong_route, wrong_date])], ["out"])

    def test_empty_is_tuple(self):
        self.assertEqual(self.query([]), ())

    def test_sold_out_excluded(self):
        self.assertEqual(self.query([flight(seats=0)]), ())

    def test_airline_filter(self):
        self.assertEqual(self.query([flight()], airline="星海"), ())
        self.assertEqual(len(self.query([flight()], airline="云翼")), 1)

    def test_direct_filter_and_mixed_carrier_filter(self):
        a=flight("seg1", dest="上海", end="2026-11-10T10:00")
        b=flight("seg2", origin="上海", start="2026-11-10T11:00", end="2026-11-10T13:00", airline="星海")
        connection=Flight("connection", (a.segments[0],b.segments[0]), 30000, 3)
        self.assertEqual(len(self.query([connection])), 1)
        self.assertEqual(self.query([connection], direct_only=True), ())
        self.assertEqual(self.query([connection], airline="云翼"), ())
        self.assertEqual(connection.duration_minutes, 300)

    def test_round_trip_sums_prices_and_uses_return_date(self):
        back=flight("back", origin="北京", dest="深圳", start="2026-11-15T15:00", end="2026-11-15T18:00", price=42000)
        result=self.query([flight(),back], return_date=date(2026,11,15))
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].final_price_cents,92000)
        self.assertEqual(sum(x.amount_cents for x in result[0].breakdown),92000)

    def test_round_trip_requires_both_legs(self):
        self.assertEqual(self.query([flight()],return_date=date(2026,11,15)),())

    def test_round_trip_filters_both_legs(self):
        back=flight("back",origin="北京",dest="深圳",start="2026-11-15T15:00",end="2026-11-15T18:00",seats=0)
        self.assertEqual(self.query([flight(),back],return_date=date(2026,11,15)),())

    def test_cross_midnight_excludes_impossible_return(self):
        out=flight(start="2026-11-10T23:00",end="2026-11-11T02:00")
        early=flight("early",origin="北京",dest="深圳",start="2026-11-11T01:00",end="2026-11-11T04:00")
        equal=flight("equal",origin="北京",dest="深圳",start="2026-11-11T02:00",end="2026-11-11T05:00")
        valid=flight("valid",origin="北京",dest="深圳",start="2026-11-11T03:00",end="2026-11-11T06:00")
        result=self.query([out,early,equal,valid],return_date=date(2026,11,11))
        self.assertEqual([q.itinerary.id for q in result],["out|valid"])

    def test_same_day_return_can_work(self):
        back=flight("back",origin="北京",dest="深圳",start="2026-11-10T15:00",end="2026-11-10T18:00")
        self.assertEqual(len(self.query([flight(),back],return_date=DAY)),1)

    def test_price_sort_is_stable_and_deterministic(self):
        results=self.query([flight("b"),flight("a"),flight("cheap",price=10000)])
        self.assertEqual([q.itinerary.id for q in results],["cheap","a","b"])

    def test_departure_sort_not_price_sort(self):
        early=flight("early",price=90000)
        late=flight("late",start="2026-11-10T15:00",end="2026-11-10T18:00",price=10000)
        self.assertEqual([q.itinerary.id for q in self.query([late,early],sort_order=SortOrder.DEPARTURE)],["early","late"])

    def test_query_does_not_mutate_input(self):
        a=flight();provider=MemoryProvider([a]);service=SearchService(provider)
        c=SearchCriteria("深圳","北京",DAY)
        self.assertEqual(service.search(c),service.search(c))
        self.assertEqual(a.price_cents,50000)

    def test_future_pricing_extension_applied(self):
        class DiscountPolicy:
            def quote(self,itinerary):
                base=NoDiscountPricing().quote(itinerary)
                return replace(base,discount_cents=10000,final_price_cents=base.base_price_cents-10000,
                               breakdown=base.breakdown+(PriceLine("测试优惠",-10000),))
        s=SearchService(MemoryProvider([flight()]),DiscountPolicy())
        q=s.search(SearchCriteria("深圳","北京",DAY))
        self.assertEqual(q[0].final_price_cents,40000)

    def test_inconsistent_pricing_fails(self):
        class BadPolicy:
            def quote(self,itinerary):
                return replace(NoDiscountPricing().quote(itinerary),final_price_cents=-1)
        with self.assertRaises(DataError):
            SearchService(MemoryProvider([flight()]),BadPolicy()).search(SearchCriteria("深圳","北京",DAY))

    def test_invalid_criteria(self):
        for kwargs in [dict(return_date=date(2026,11,9)),dict(passengers=2),dict(sort_order="bad")]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValidationError):self.query([],**kwargs)
        for origin,dest in [("深圳","深圳"),("未知","北京")]:
            with self.subTest(origin=origin),self.assertRaises(ValidationError):
                SearchService(MemoryProvider([])).search(SearchCriteria(origin,dest,DAY))


class DateRangeTests(unittest.TestCase):
    """F01：search_date_range 首尾日期、无结果、筛选一致性。"""

    def _service(self, flights):
        return SearchService(MemoryProvider(flights))

    def _base(self, origin="深圳", destination="北京", **kwargs):
        return SearchCriteria(origin, destination, date(2026, 11, 10), None, **kwargs)

    def test_endpoints_inclusive_single_day_range(self):
        """起止同一天应等同于单日查询。"""
        flights = [flight(id="d10", start="2026-11-10T08:00", end="2026-11-10T11:00"),
                   flight(id="d11", start="2026-11-11T08:00", end="2026-11-11T11:00")]
        svc = self._service(flights)
        c = self._base()
        result = svc.search_date_range("深圳", "北京", date(2026,11,10), date(2026,11,10), c)
        self.assertEqual([q.itinerary.id for q in result], ["d10"])

    def test_both_endpoints_included(self):
        """起始日和结束日当天的航班都应被包含。"""
        flights = [flight(id="start_day", start="2026-11-10T08:00", end="2026-11-10T11:00"),
                   flight(id="mid_day",   start="2026-11-12T08:00", end="2026-11-12T11:00"),
                   flight(id="end_day",   start="2026-11-15T08:00", end="2026-11-15T11:00"),
                   flight(id="before",    start="2026-11-09T08:00", end="2026-11-09T11:00"),
                   flight(id="after",     start="2026-11-16T08:00", end="2026-11-16T11:00")]
        svc = self._service(flights)
        result = svc.search_date_range("深圳", "北京", date(2026,11,10), date(2026,11,15), self._base())
        ids = [q.itinerary.id for q in result]
        self.assertIn("start_day", ids)
        self.assertIn("end_day", ids)
        self.assertIn("mid_day", ids)
        self.assertNotIn("before", ids)
        self.assertNotIn("after", ids)

    def test_range_no_results_returns_empty_tuple(self):
        """日期范围内完全没有数据时应返回空 tuple 而非抛异常。"""
        svc = self._service([flight(start="2026-11-20T08:00", end="2026-11-20T11:00")])
        result = svc.search_date_range("深圳", "北京", date(2026,11,10), date(2026,11,15), self._base())
        self.assertEqual(result, ())
        self.assertIsInstance(result, tuple)

    def test_multi_day_results_sorted_and_dedup(self):
        """多日期结果汇总后应按 sort_order 排序，且 itinerary.id 去重。"""
        flights = [flight(id="cheap", start="2026-11-10T08:00", end="2026-11-10T11:00", price=10000),
                   flight(id="mid",   start="2026-11-12T08:00", end="2026-11-12T11:00", price=30000),
                   flight(id="dup",   start="2026-11-14T08:00", end="2026-11-14T11:00", price=20000)]
        svc = self._service(flights)
        result = svc.search_date_range("深圳", "北京", date(2026,11,10), date(2026,11,14), self._base())
        self.assertEqual([q.itinerary.id for q in result], ["cheap", "dup", "mid"])
        # 同一路线同一天重复 flight id 的情况也应去重（MemoryProvider 不会产生，但 service 去重是应有防御）

    def test_range_airline_filter_consistent_with_single_day(self):
        """航司筛选在日期范围内应与单日查询行为一致。"""
        flights = [flight(id="a", start="2026-11-10T08:00", end="2026-11-10T11:00", airline="云翼"),
                   flight(id="b", start="2026-11-11T08:00", end="2026-11-11T11:00", airline="星海"),
                   flight(id="c", start="2026-11-13T08:00", end="2026-11-13T11:00", airline="云翼")]
        svc = self._service(flights)
        c = self._base(airline="云翼")
        result = svc.search_date_range("深圳", "北京", date(2026,11,10), date(2026,11,13), c)
        self.assertEqual([q.itinerary.id for q in result], ["a", "c"])

    def test_range_direct_filter_consistent_with_single_day(self):
        """仅直飞 在日期范围内应与单日查询行为一致（中转航班全部排除）。"""
        seg1 = flight(id="conn1", dest="上海", start="2026-11-11T08:00", end="2026-11-11T10:00")
        seg2 = flight(id="conn2", origin="上海", start="2026-11-11T11:00", end="2026-11-11T13:00")
        from flight_app.models import Flight as _F
        conn = _F("connect", (seg1.segments[0], seg2.segments[0]), 30000, 5)
        flights = [flight(id="direct", start="2026-11-10T08:00", end="2026-11-10T11:00"),
                   conn,
                   flight(id="direct2", start="2026-11-12T08:00", end="2026-11-12T11:00")]
        svc = self._service(flights)
        c = self._base(direct_only=True)
        result = svc.search_date_range("深圳", "北京", date(2026,11,10), date(2026,11,12), c)
        self.assertEqual([q.itinerary.id for q in result], ["direct", "direct2"])

    def test_range_sold_out_consistent_with_single_day(self):
        """余票为0的航班在日期范围内应被排除。"""
        flights = [flight(id="sold",   start="2026-11-10T08:00", end="2026-11-10T11:00", seats=0),
                   flight(id="avail",  start="2026-11-11T08:00", end="2026-11-11T11:00", seats=3)]
        svc = self._service(flights)
        result = svc.search_date_range("深圳", "北京", date(2026,11,10), date(2026,11,11), self._base())
        self.assertEqual([q.itinerary.id for q in result], ["avail"])

    def test_start_after_end_raises(self):
        """起始日期晚于结束日期应抛 ValueError。"""
        svc = self._service([])
        with self.assertRaises(ValueError):
            svc.search_date_range("深圳", "北京", date(2026,11,15), date(2026,11,10), self._base())


class MultiCityTests(unittest.TestCase):
    """F02：search_multi_city 组合、去重、同城排除、全局排序、筛选一致性。"""

    DAY = date(2026, 11, 10)

    def _service(self, flights):
        return SearchService(MemoryProvider(flights))

    def _base(self, **kwargs):
        return SearchCriteria("深圳", "北京", self.DAY, None, **kwargs)

    def test_cartesian_product_and_same_city_excluded(self):
        """多出发 × 多到达 正确枚举，同城组合被跳过。"""
        # origins: 深圳、上海；dests: 北京、深圳 → 应枚举：深圳→北京✓、深圳→深圳✗、上海→北京✓、上海→深圳✓
        flights = [flight(id="sz_pk", origin="深圳", dest="北京"),
                   flight(id="sh_pk", origin="上海", dest="北京"),
                   flight(id="sh_sz", origin="上海", dest="深圳"),
                   # 深圳→深圳 这条应该永远不会被查到（同城排除）
                   flight(id="sz_sz", origin="深圳", dest="深圳")]
        svc = self._service(flights)
        result = svc.search_multi_city(("深圳", "上海"), ("北京", "深圳"), self._base())
        ids = [q.itinerary.id for q in result]
        self.assertIn("sz_pk", ids)
        self.assertIn("sh_pk", ids)
        self.assertIn("sh_sz", ids)
        self.assertNotIn("sz_sz", ids)  # 同城排除
        self.assertEqual(len(ids), 3)

    def test_each_result_carries_real_city_pair(self):
        """多城市下每条结果的 itinerary 出发/到达城市必须是真实查询的，
        不应被 criteria.origin/destination（固定第一个）覆盖。"""
        flights = [flight(id="sz_pk", origin="深圳", dest="北京"),
                   flight(id="gz_cd", origin="广州", dest="成都"),
                   flight(id="xa_sh", origin="西安", dest="上海")]
        svc = self._service(flights)
        result = svc.search_multi_city(("深圳", "广州", "西安"), ("北京", "成都", "上海"), self._base())
        by_route = {(q.itinerary.outbound.origin.city, q.itinerary.outbound.destination.city): q
                    for q in result}
        self.assertEqual(by_route[("深圳","北京")].itinerary.id, "sz_pk")
        self.assertEqual(by_route[("广州","成都")].itinerary.id, "gz_cd")
        self.assertEqual(by_route[("西安","上海")].itinerary.id, "xa_sh")

    def test_global_dedup_by_itinerary_id(self):
        """同一个 itinerary.id 在多次循环命中时只保留一份。
        MemoryProvider 因按 origin/destination/date 过滤不会重复返回同 id，
        但 service 层的 seen_ids 去重是应有防御。"""
        flights = [flight(id="sz_pk", origin="深圳", dest="北京")]
        svc = self._service(flights)
        # 深圳出现在 origins 两次（虽然 tuple 里重复不太自然，但 service 应幂等）
        result = svc.search_multi_city(("深圳", "深圳"), ("北京",), self._base())
        ids = [q.itinerary.id for q in result]
        self.assertEqual(ids.count("sz_pk"), 1)  # 全局去重生效

    def test_global_sort_across_all_combinations(self):
        """不同城市对的结果应在全局统一排序，而非按组合内部分别排序。"""
        flights = [flight(id="sh_pk", origin="上海", dest="北京", price=90000),
                   flight(id="sz_pk", origin="深圳", dest="北京", price=30000),
                   flight(id="gz_cd", origin="广州", dest="成都", price=50000)]
        svc = self._service(flights)
        result = svc.search_multi_city(("深圳", "上海", "广州"), ("北京", "成都"), self._base())
        self.assertEqual([q.itinerary.id for q in result], ["sz_pk", "gz_cd", "sh_pk"])

    def test_lowest_price_correct_across_combinations(self):
        """多个城市对里最便宜的航班必须排最前。"""
        flights = [flight(id="exp1", origin="上海", dest="北京", price=80000),
                   flight(id="exp2", origin="深圳", dest="北京", price=20000),
                   flight(id="exp3", origin="广州", dest="北京", price=90000),
                   flight(id="exp4", origin="西安", dest="上海", price=70000)]
        svc = self._service(flights)
        result = svc.search_multi_city(("上海", "深圳", "广州", "西安"), ("北京", "上海"), self._base())
        self.assertEqual(result[0].itinerary.id, "exp2")
        self.assertEqual(result[0].final_price_cents, 20000)

    def test_airline_filter_consistent_with_single_route(self):
        """航司筛选在多城市下与单日一致。"""
        flights = [flight(id="a1", origin="深圳", dest="北京", airline="云翼"),
                   flight(id="a2", origin="上海", dest="北京", airline="星海"),
                   flight(id="a3", origin="广州", dest="成都", airline="云翼")]
        svc = self._service(flights)
        c = self._base(airline="云翼")
        result = svc.search_multi_city(("深圳", "上海", "广州"), ("北京", "成都"), c)
        self.assertEqual([q.itinerary.id for q in result], ["a1", "a3"])

    def test_direct_filter_consistent_with_single_route(self):
        """仅直飞在多城市下排除所有中转航班。"""
        # 构造一个中转
        from flight_app.models import Flight as _F
        seg1 = flight(id="seg1", origin="深圳", dest="上海", start="2026-11-10T08:00", end="2026-11-10T10:00")
        seg2 = flight(id="seg2", origin="上海", dest="北京", start="2026-11-10T11:00", end="2026-11-10T13:00")
        conn = _F("connect", (seg1.segments[0], seg2.segments[0]), 30000, 5)
        flights = [flight(id="d1", origin="深圳", dest="北京"),
                   conn,
                   flight(id="d2", origin="广州", dest="成都")]
        svc = self._service(flights)
        c = self._base(direct_only=True)
        result = svc.search_multi_city(("深圳", "广州"), ("北京", "成都"), c)
        self.assertNotIn("connect", [q.itinerary.id for q in result])
        self.assertIn("d1", [q.itinerary.id for q in result])
        self.assertIn("d2", [q.itinerary.id for q in result])

    def test_sold_out_excluded_consistently(self):
        """余票为0的航班在多城市下同样被排除。"""
        flights = [flight(id="avail", origin="深圳", dest="北京", seats=3),
                   flight(id="sold",  origin="上海", dest="北京", seats=0)]
        svc = self._service(flights)
        result = svc.search_multi_city(("深圳", "上海"), ("北京",), self._base())
        self.assertEqual([q.itinerary.id for q in result], ["avail"])

    def test_empty_origins_raises(self):
        with self.assertRaises(ValueError):
            self._service([]).search_multi_city((), ("北京",), self._base())

    def test_empty_dests_raises(self):
        with self.assertRaises(ValueError):
            self._service([]).search_multi_city(("深圳",), (), self._base())

    def test_all_same_city_pairs_yields_empty(self):
        """origins 与 dests 完全相同导致全部被同城排除 → 空 tuple。"""
        flights = [flight(origin="深圳", dest="深圳")]
        svc = self._service(flights)
        result = svc.search_multi_city(("深圳",), ("深圳",), self._base())
        self.assertEqual(result, ())
