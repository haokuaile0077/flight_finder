"""真实Tk界面下验证联合查询、快照、分页及后台任务生命周期。"""
import csv
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from flight_app.discount_pricing import load_pricing, pricing_description
from flight_app.models import RangeCriteria, SortOrder
from flight_app.provider import JsonFlightProvider
from flight_app.range_search import RangeSearchService
from flight_app.service import SearchService

ROOT = Path(__file__).resolve().parents[1]


class RangeGuiTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
        except (ImportError, tk.TclError) as exc:
            self.skipTest(f"GUI需要Tk与可用显示：{exc}")
        from flight_app.gui import FlightApp
        self.provider = JsonFlightProvider(ROOT/"data"/"flights.json")
        policy = load_pricing(ROOT/"data"/"discount.json")
        self.range_service = RangeSearchService(SearchService(self.provider, policy), self.provider.cities,
                                               date_bounds=(self.provider.dates[0], self.provider.dates[-1]))
        self.app = FlightApp(self.root, self.provider, range_service=self.range_service,
                             discount_summary=pricing_description(policy))
        self.root.update()
        self.app.tabs.select(1)
        self.root.update()

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.close()

    def wait_done(self):
        end = time.monotonic()+4
        while self.app._busy and time.monotonic() < end:
            self.root.update()
            time.sleep(.005)
        self.assertFalse(self.app._busy)
        self.root.update()

    def query(self):
        self.app.search()
        self.wait_done()

    def test_joint_query_and_discount_detail(self):
        self.query()
        self.assertIsInstance(self.app.last_criteria, RangeCriteria)
        self.assertEqual(set(q.itinerary.outbound.origin.city for q in self.app.results), {"深圳", "广州", "珠海"})
        self.assertTrue(any(q.discount_cents for q in self.app.results))
        self.assertIn("最低价", self.app.cheapest.get())
        self.assertIn("价格明细", self.app.details.get("1.0", "end"))

    def test_discount_toggle_preserves_routes_and_changes_prices(self):
        self.query()
        priced = {q.itinerary.id: q for q in self.app.results}
        self.app.use_discount.set(False)
        self.query()
        self.assertFalse(self.app.last_criteria.discount_enabled)
        self.assertEqual(set(priced), {q.itinerary.id for q in self.app.results})
        self.assertTrue(all(q.discount_cents == 0 for q in self.app.results))
        self.assertTrue(any(q.final_price_cents > priced[q.itinerary.id].final_price_cents for q in self.app.results))

    def test_export_all_pages_and_snapshot_after_edit_and_sort(self):
        self.app.range_origins = self.provider.cities
        self.app.range_destinations = self.provider.cities
        self.app.range_start.set("2026-11-01")
        self.app.range_end.set("2026-11-30")
        self.query()
        all_count = len(self.app.results)
        self.assertGreater(all_count, 100)
        self.assertEqual(len(self.app.tree.get_children()), 100)
        self.app.change_page(1)
        self.assertEqual(self.app._page, 1)
        self.app.range_origins = ("深圳",)
        self.app.range_end.set("2026-11-01")
        self.app.budget.set("0")
        self.app.use_discount.set(False)
        self.app.sort_order.set(SortOrder.DEPARTURE.value)
        self.app.resort()
        self.assertEqual(self.app.last_criteria.origins, self.provider.cities)
        self.assertEqual(self.app.last_criteria.end_date.isoformat(), "2026-11-30")
        self.assertTrue(self.app.last_criteria.discount_enabled)
        self.assertEqual(len(self.app.results), all_count)
        self.app.locate_cheapest()
        index = int(self.app.tree.selection()[0])
        self.assertEqual(self.app.results[index].final_price_cents, min(q.final_price_cents for q in self.app.results))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"all.csv"
            with patch("flight_app.gui.filedialog.asksaveasfilename", return_value=str(path)):
                self.app.export()
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), all_count)
            self.assertEqual(rows[0]["查询结束日期"], "2026-11-30")
            self.assertEqual(rows[0]["应用模拟优惠"], "是")
            self.assertEqual(rows[0]["排序"], SortOrder.DEPARTURE.value)

    def test_invalid_input_clears_old_results(self):
        self.query()
        for start, end in [("2026-11-15", "2026-11-10"), ("2026-10-31", "2026-11-10"), ("bad", "2026-11-10")]:
            self.app.range_start.set(start)
            self.app.range_end.set(end)
            with patch("flight_app.gui.messagebox.showwarning") as warning:
                self.app.search()
                warning.assert_called_once()
            self.assertEqual(self.app.results, ())
            self.assertEqual(str(self.app.export_button["state"]), "disabled")
        self.app.range_start.set("2026-11-10")
        self.app.range_origins = ()
        with patch("flight_app.gui.messagebox.showwarning") as warning:
            self.app.search()
            warning.assert_called_once()

    def test_cancel_and_stale_worker_cannot_overwrite_new_results(self):
        started, release = Event(), Event()
        original = self.range_service.search_range
        def slow(*args, **kwargs):
            started.set()
            release.wait(2)
            # 故意模拟不响应取消的外部实现，GUI仍须忽略其迟到结果。
            return original(*args[:4])
        with patch.object(self.range_service, "search_range", side_effect=slow):
            self.app.search()
            self.assertTrue(started.wait(1))
            tick = []
            self.root.after(0, lambda: tick.append(True))
            self.root.update()
            self.assertTrue(tick)
            self.app.cancel_query()
            self.assertFalse(self.app._busy)
            self.assertEqual(self.app.results, ())
        self.app.budget.set("0")
        self.query()
        self.assertEqual(self.app.results, ())
        release.set()
        for _ in range(20):
            self.root.update()
            time.sleep(.005)
        self.assertEqual(self.app.results, ())
        self.assertEqual(self.app.last_criteria.budget_cents, 0)

    def test_switch_mode_clears_export_and_regular_round_trip_unaffected(self):
        self.query()
        self.app.tabs.select(0)
        self.root.update()
        self.assertEqual(self.app.results, ())
        self.app.trip.set("往返")
        self.query()
        self.assertTrue(self.app.results)
        self.assertTrue(all(q.itinerary.inbound is not None and q.discount_cents == 0 for q in self.app.results))

    def test_small_window_keeps_result_status_and_cancel_visible(self):
        self.root.geometry("1030x650")
        self.root.update()
        self.query()
        self.assertGreater(self.app.tree.winfo_height(), 150)
        self.assertGreater(self.app.details.winfo_height(), 40)
        self.assertGreater(self.app.tree.winfo_width(), 400)
        self.assertLessEqual(self.app.status_label.winfo_rooty()+self.app.status_label.winfo_height(),
                             self.root.winfo_rooty()+self.root.winfo_height())
        self.assertTrue(self.app.search_button.winfo_ismapped())

    def test_calendar_selection_and_city_dialog(self):
        self.app.dep_field.open_calendar()
        self.root.update()
        win = self.app.dep_field.popup
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        day = next(w for w in descendants(win) if w.winfo_class() == "TButton" and w.cget("text") == "12")
        day.invoke()
        self.assertEqual(self.app.dep_date.get(), "2026-11-12")
        win = self.app.pick_cities(True)
        self.root.update()
        clear = next(w for w in descendants(win) if w.winfo_class() == "TButton" and w.cget("text") == "清空")
        clear.invoke()
        confirm = next(w for w in descendants(win) if w.winfo_class() == "TButton" and w.cget("text") == "确认选择")
        confirm.invoke()
        self.assertEqual(self.app.range_origins, ())
        self.assertIn("选择", self.app.origin_caption.get())

    def test_no_range_service_keeps_original_constructor_compatible(self):
        from flight_app.gui import FlightApp
        self.app.close()
        import tkinter as tk
        self.root = tk.Tk()
        self.app = FlightApp(self.root, self.provider)
        self.root.update()
        self.assertEqual(self.app.tabs.tab(1, "state"), "disabled")
        self.query()
        self.assertTrue(self.app.results)

    def test_error_in_worker_and_window_close(self):
        with patch.object(self.range_service, "search_range", side_effect=RuntimeError("test error")), \
                patch("flight_app.gui.messagebox.showwarning") as warning, \
                patch("flight_app.gui.logging.exception") as log:
            self.query()
            warning.assert_called_once()
            log.assert_called_once()
        self.assertEqual(self.app.results, ())
        self.assertEqual(str(self.app.search_button["state"]), "normal")
        self.app.search()
        self.app.close()
        self.assertTrue(self.app._closed)
        self.app.close()  # 关闭是幂等的；后台线程不得访问已销毁的Tk。
