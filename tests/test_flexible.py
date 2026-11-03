"""日期范围、多城市、优惠联合查询的回归与边界测试。"""
import copy
import csv
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flight_app.date_search import search_dates
from flight_app.discount_pricing import AirlineDiscountPricing, load_pricing
from flight_app.errors import DataError, SearchCancelled, ValidationError
from flight_app.exporting import export_range_quotes
from flight_app.models import Flight, Itinerary, RangeCriteria, SearchCriteria, SortOrder
from flight_app.pricing import NoDiscountPricing
from flight_app.provider import JsonFlightProvider
from flight_app.range_search import RangeSearchService
from flight_app.service import SearchService
from tests.helpers import MemoryProvider, flight

DAY = date(2026, 11, 10)
END = date(2026, 11, 11)
ROOT = Path(__file__).resolve().parents[1]
CONFIG = dict(enabled=True, airline="云翼", threshold_cents=50000, reduction_cents=10000,
              start_date="2026-11-10", end_date="2026-11-11")


def rule(**changes):
    values = dict(airline="云翼", threshold_cents=50000, reduction_cents=10000, start_date=DAY, end_date=END)
    values.update(changes)
    return AirlineDiscountPricing(**values)


class DateSearchTests(unittest.TestCase):
    def setUp(self):
        self.a = flight("a")
        self.b = flight("b", start="2026-11-11T09:00", end="2026-11-11T12:00", price=40000)
        self.service = SearchService(MemoryProvider([self.a, self.b]))
        self.c = SearchCriteria("深圳", "北京", DAY)

    def test_single_day_matches_existing_search(self):
        self.assertEqual(search_dates(self.service, self.c, DAY), self.service.search(self.c))

    def test_both_endpoints_included_and_sorted(self):
        self.assertEqual([q.itinerary.id for q in search_dates(self.service, self.c, END)], ["b", "a"])

    def test_time_sort_and_no_mutation(self):
        c = replace(self.c, sort_order=SortOrder.DEPARTURE)
        result = search_dates(self.service, c, END)
        self.assertEqual([q.itinerary.id for q in result], ["a", "b"])
        self.assertEqual(c.departure_date, DAY)

    def test_budget_and_airline_filters_preserved(self):
        self.assertEqual(len(search_dates(self.service, replace(self.c, budget_cents=40000), END)), 1)
        self.assertEqual(search_dates(self.service, replace(self.c, airline="不存在"), END), ())

    def test_invalid_span_and_round_trip(self):
        for c, end in [(self.c, date(2026, 11, 9)), (self.c, date(2026, 12, 11)),
                       (self.c, "2026-11-11"), (replace(self.c, return_date=END), END)]:
            with self.subTest(c=c, end=end), self.assertRaises(ValidationError):
                search_dates(self.service, c, end)

    def test_empty_and_progress(self):
        calls = []
        self.assertEqual(search_dates(SearchService(MemoryProvider([])), self.c, END,
                                      progress=lambda a, b: calls.append((a, b))), ())
        self.assertEqual(calls, [(1, 2), (2, 2)])

    def test_cancel_stops_without_partial_result(self):
        calls = []
        with self.assertRaises(SearchCancelled):
            search_dates(self.service, self.c, END, cancel_check=lambda: bool(calls),
                         progress=lambda a, b: calls.append((a, b)))
        self.assertEqual(calls, [(1, 2)])

    def test_31_days_and_last_possible_date(self):
        s = SearchService(MemoryProvider([]))
        self.assertEqual(search_dates(s, replace(self.c, departure_date=date(2026, 1, 1)), date(2026, 1, 31)), ())
        self.assertEqual(search_dates(s, replace(self.c, departure_date=date.max), date.max), ())


class DiscountTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/"discount.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            return load_pricing(p)

    def test_config_loaded_and_disabled(self):
        self.assertIsInstance(self.load(CONFIG), AirlineDiscountPricing)
        self.assertIsInstance(self.load(dict(CONFIG, enabled=False)), NoDiscountPricing)

    def test_invalid_fields_types_dates_and_unknown_keys(self):
        cases = [dict(CONFIG, enabled=1), dict(CONFIG, threshold_cents=True), dict(CONFIG, reduction_cents=-1),
                 dict(CONFIG, reduction_cents=10.5), dict(CONFIG, airline=""),
                 dict(CONFIG, start_date="2026-11-12"), dict(CONFIG, end_date="2026-11-31"),
                 dict(CONFIG, start_date="20261110"), dict(CONFIG, end_date=123), dict(CONFIG, typo=1),
                 dict(CONFIG, threshold_cents=100000001), dict(CONFIG, enabled=False, threshold_cents=-1), []]
        missing = dict(CONFIG)
        missing.pop("airline")
        cases.append(missing)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(DataError):
                self.load(case)

    def test_missing_and_corrupt_file(self):
        with self.assertRaises(DataError):
            load_pricing(ROOT/"missing-discount.json")
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/"bad.json"
            p.write_text("{", encoding="utf-8")
            with self.assertRaises(DataError):
                load_pricing(p)

    def test_threshold_inclusive_and_unchanged_flight(self):
        f = flight()
        q = rule().quote(Itinerary(f))
        self.assertEqual((q.base_price_cents, q.discount_cents, q.final_price_cents), (50000, 10000, 40000))
        self.assertEqual(sum(x.amount_cents for x in q.breakdown), 40000)
        self.assertEqual(f.price_cents, 50000)
        self.assertEqual(rule().quote(Itinerary(flight(price=49999))).discount_cents, 0)

    def test_validity_start_and_end_inclusive(self):
        for day, expected in [(9, 0), (10, 10000), (11, 10000), (12, 0)]:
            f = flight(start=f"2026-11-{day:02}T08:00", end=f"2026-11-{day:02}T11:00")
            with self.subTest(day=day):
                self.assertEqual(rule().quote(Itinerary(f)).discount_cents, expected)

    def test_wrong_and_mixed_airlines_not_discounted(self):
        self.assertEqual(rule().quote(Itinerary(flight(airline="星海"))).discount_cents, 0)
        a = flight(dest="上海", end="2026-11-10T10:00")
        b = flight(origin="上海", start="2026-11-10T11:00", end="2026-11-10T14:00", airline="星海")
        f = Flight("transfer", (a.segments[0], b.segments[0]), 70000, 3)
        self.assertEqual(rule().quote(Itinerary(f)).discount_cents, 0)
        same = replace(f, segments=(a.segments[0], replace(b.segments[0], airline="云翼")))
        self.assertEqual(rule().quote(Itinerary(same)).discount_cents, 10000)

    def test_discount_capped_and_zero_amount(self):
        q = rule(threshold_cents=0, reduction_cents=99999).quote(Itinerary(flight()))
        self.assertEqual((q.discount_cents, q.final_price_cents), (50000, 0))
        self.assertEqual(rule(threshold_cents=0).quote(Itinerary(flight(price=0))).final_price_cents, 0)

    def test_no_discount_for_round_trip(self):
        back = flight("back", origin="北京", dest="深圳", start="2026-11-11T12:00", end="2026-11-11T15:00")
        self.assertEqual(rule().quote(Itinerary(flight(), back)).discount_cents, 0)


class CombinedRangeTests(unittest.TestCase):
    def setUp(self):
        self.flights = [flight("a"), flight("b", origin="上海", price=60000),
                        flight("next", start="2026-11-11T08:00", end="2026-11-11T11:00", price=55000),
                        flight("other", dest="上海", price=20000), flight("sold", seats=0)]
        self.provider = MemoryProvider(self.flights)
        self.base = SearchService(self.provider)
        self.service = RangeSearchService(SearchService(self.provider, rule()), self.provider.cities)

    def query(self, **changes):
        args = dict(origins=("深圳", "上海"), destinations=("北京",), start_date=DAY, end_date=END)
        args.update(changes)
        return self.service.search_range(**args)

    def test_combined_dates_cities_discount_and_budget(self):
        results = self.query(budget_cents=45000)
        self.assertEqual([q.itinerary.id for q in results], ["a", "next"])
        self.assertEqual([q.final_price_cents for q in results], [40000, 45000])
        self.assertTrue(all(q.discount_cents == 10000 for q in results))

    def test_joint_query_matches_independent_union(self):
        expected = []
        priced = SearchService(self.provider, rule())
        for a in ("深圳", "上海"):
            for day in (DAY, END):
                expected.extend(priced.search(SearchCriteria(a, "北京", day)))
        expected.sort(key=lambda q: (q.final_price_cents, q.itinerary.outbound.departure, q.itinerary.id))
        self.assertEqual(self.query(), tuple(expected))

    def test_duplicate_cities_and_same_city_pairs(self):
        self.assertEqual(self.query(origins=("深圳", "上海", "深圳")), self.query())
        result = self.query(origins=("深圳", "北京"), destinations=("北京", "上海"))
        self.assertEqual(len({q.itinerary.id for q in result}), len(result))
        self.assertTrue(all(q.itinerary.outbound.origin.city != q.itinerary.outbound.destination.city for q in result))

    def test_invalid_city_groups_and_dates(self):
        for changes in [dict(origins=()), dict(destinations="北京"), dict(origins=("不存在",)),
                        dict(origins=("北京",)), dict(start_date=END, end_date=DAY), dict(direct_only="yes")]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.query(**changes)

    def test_dataset_bounds_optional_and_empty_routes(self):
        bounded = RangeSearchService(self.base, self.provider.cities, date_bounds=(DAY, END))
        with self.assertRaises(ValidationError):
            bounded.search_range(("深圳",), ("北京",), date(2026, 11, 9), END)
        self.assertEqual(self.query(origins=("北京",), destinations=("上海",)), ())

    def test_single_date_city_and_no_discount_compatibility(self):
        plain = RangeSearchService(self.base, self.provider.cities)
        self.assertEqual(plain.search_range(("深圳",), ("北京",), DAY, DAY),
                         self.base.search(SearchCriteria("深圳", "北京", DAY)))

    def test_airline_and_zero_budget(self):
        self.assertEqual(self.query(airline="星海"), ())
        self.assertEqual(self.query(budget_cents=0), ())
        self.assertEqual(self.query(budget_cents=39999), ())

    def test_global_sort_and_progress(self):
        calls = []
        result = self.query(sort_order=SortOrder.DEPARTURE, progress=lambda a, b: calls.append((a, b)))
        self.assertEqual([q.itinerary.id for q in result], ["a", "b", "next"])
        self.assertEqual(calls, [(1, 4), (2, 4), (3, 4), (4, 4)])

    def test_cancel(self):
        with self.assertRaises(SearchCancelled):
            self.query(cancel_check=lambda: True)

    def test_range_csv_contains_snapshot_and_actual_routes(self):
        results = self.query()
        c = RangeCriteria(("深圳", "上海"), ("北京",), DAY, END)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"联合.csv"
            count = export_range_quotes(path, results, c, "云翼满500减100（模拟）")
            self.assertEqual(count, len(results))
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["查询出发城市范围"], "深圳 / 上海")
            self.assertEqual(rows[0]["查询结束日期"], "2026-11-11")
            self.assertEqual(rows[0]["应用模拟优惠"], "是")
            self.assertEqual(rows[0]["合计元"], "400.00")
            self.assertEqual({r["出发城市"] for r in rows}, {"深圳", "上海"})
            self.assertIn("-100.00", rows[0]["价格明细"])

    def test_range_export_failure_atomic_and_formula_protected(self):
        c = RangeCriteria(("深圳", "上海"), ("北京",), DAY, END)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"out.csv"
            path.write_text("original")
            with patch("flight_app.exporting.os.replace", side_effect=PermissionError):
                with self.assertRaises(PermissionError):
                    export_range_quotes(path, self.query(), c)
            self.assertEqual(path.read_text(), "original")
            self.assertEqual(len(list(Path(folder).iterdir())), 1)
            export_range_quotes(path, self.query(), c, "=1+1")
            with path.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(next(csv.DictReader(stream))["模拟优惠规则"], "'=1+1")

    def test_demo_data_joint_search(self):
        provider = JsonFlightProvider(ROOT/"data"/"flights.json")
        service = RangeSearchService(SearchService(provider, load_pricing(ROOT/"data"/"discount.json")), provider.cities)
        result = service.search_range(("深圳", "广州", "珠海"), ("北京",), DAY, date(2026, 11, 15))
        self.assertTrue(result)
        self.assertTrue(any(q.discount_cents > 0 for q in result))
        self.assertEqual(len({q.itinerary.id for q in result}), len(result))
        self.assertTrue(all(DAY <= q.itinerary.outbound.departure.date() <= date(2026, 11, 15) for q in result))
