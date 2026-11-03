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

    def test_budget_boundary_inclusive(self):
        self.assertEqual(len(self.query([flight()], budget_cents=50000)), 1)
        self.assertEqual(self.query([flight()], budget_cents=49999), ())

    def test_zero_budget_is_not_unlimited(self):
        self.assertEqual(self.query([flight()], budget_cents=0), ())
        self.assertEqual(len(self.query([flight(price=0)], budget_cents=0)), 1)

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

    def test_round_trip_budget_is_total(self):
        back=flight("back",origin="北京",dest="深圳",start="2026-11-15T15:00",end="2026-11-15T18:00")
        self.assertEqual(self.query([flight(),back],return_date=date(2026,11,15),budget_cents=60000),())

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

    def test_future_pricing_extension_applied_before_budget(self):
        class DiscountPolicy:
            def quote(self,itinerary):
                base=NoDiscountPricing().quote(itinerary)
                return replace(base,discount_cents=10000,final_price_cents=base.base_price_cents-10000,
                               breakdown=base.breakdown+(PriceLine("测试优惠",-10000),))
        s=SearchService(MemoryProvider([flight()]),DiscountPolicy())
        q=s.search(SearchCriteria("深圳","北京",DAY,budget_cents=40000))
        self.assertEqual(q[0].final_price_cents,40000)

    def test_inconsistent_pricing_fails(self):
        class BadPolicy:
            def quote(self,itinerary):
                return replace(NoDiscountPricing().quote(itinerary),final_price_cents=-1)
        with self.assertRaises(DataError):
            SearchService(MemoryProvider([flight()]),BadPolicy()).search(SearchCriteria("深圳","北京",DAY))

    def test_invalid_criteria(self):
        for kwargs in [dict(return_date=date(2026,11,9)),dict(passengers=2),dict(budget_cents=-1),dict(budget_cents=True),dict(sort_order="bad")]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValidationError):self.query([],**kwargs)
        for origin,dest in [("深圳","深圳"),("未知","北京")]:
            with self.subTest(origin=origin),self.assertRaises(ValidationError):
                SearchService(MemoryProvider([])).search(SearchCriteria(origin,dest,DAY))
