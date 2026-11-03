"""需图形显示的GUI集成测试；没有显示服务时明确跳过。"""
import csv
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from flight_app.models import SortOrder
from flight_app.provider import JsonFlightProvider


class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f"GUI需要可用的Tk与桌面显示：{exc}")
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            if 'display' not in str(exc).lower():
                raise
            self.skipTest(f"GUI需要桌面显示：{exc}")
        from flight_app.gui import FlightApp
        self.app = FlightApp(self.root, JsonFlightProvider(Path(__file__).resolve().parents[1]/'data'/'flights.json'))
        self.root.update()

    def tearDown(self):
        if hasattr(self,'app'):
            self.app.close()
        elif getattr(self,'root',None) is not None:
            self.root.destroy()

    def run_query(self):
        self.app.search()
        deadline=time.monotonic()+2
        while self.app._busy and time.monotonic()<deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app._busy)
        self.root.update()

    def test_default_one_way_and_details(self):
        self.run_query()
        self.assertGreater(len(self.app.results),0)
        self.assertEqual(len(self.app.tree.get_children()),len(self.app.results))
        self.assertIn('模拟',self.app.details.get('1.0','end'))
        self.assertIn('合计',self.app.details.get('1.0','end'))

    def test_round_trip_return_enabled_and_csv(self):
        self.app.trip.set('往返');self.root.update()
        self.assertEqual(str(self.app.return_entry['state']),'normal')
        self.run_query()
        self.assertTrue(all(q.itinerary.inbound for q in self.app.results))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'results.csv'
            with patch('flight_app.gui.filedialog.asksaveasfilename',return_value=str(path)):
                self.app.export()
            with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),len(self.app.results))
            self.assertEqual(rows[0]['查询返程日期'],'2026-11-15')

    def test_invalid_input_clears_stale_export(self):
        self.run_query();self.app.dep_date.set('invalid')
        with patch('flight_app.gui.messagebox.showwarning') as warning:
            self.run_query();warning.assert_called_once()
        self.assertEqual(self.app.results,())
        self.assertEqual(str(self.app.export_button['state']),'disabled')

    def test_sort_and_export_use_last_query_snapshot(self):
        self.run_query();self.app.budget.set('0')
        self.app.sort_order.set(SortOrder.DEPARTURE.value);self.app.resort()
        self.assertIsNone(self.app.last_criteria.budget_cents)
        self.assertEqual(self.app.results,tuple(sorted(self.app.results,key=lambda q:(q.itinerary.outbound.departure,q.final_price_cents,q.itinerary.id))))

    def test_empty_result_and_swap_reset(self):
        self.app.budget.set('0');self.run_query()
        self.assertEqual(self.app.results,())
        self.assertIn('没有',self.app.status.get())
        self.app.swap();self.assertEqual(self.app.origin.get(),'北京')
        self.app.reset();self.assertEqual(self.app.origin.get(),'深圳')
        self.assertEqual(str(self.app.return_entry['state']),'disabled')

    def test_export_cancel_and_failure(self):
        self.run_query()
        with patch('flight_app.gui.filedialog.asksaveasfilename',return_value=''):
            self.app.export()
        with patch('flight_app.gui.filedialog.asksaveasfilename',return_value='/not-valid/out.csv'),patch('flight_app.gui.messagebox.showerror') as error:
            self.app.export();error.assert_called_once()

    def test_result_and_details_panes_visible_after_layout(self):
        deadline=time.monotonic()+.2
        while time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertGreater(self.app.tree.winfo_width(),500)
        self.assertGreater(self.app.details.winfo_width(),200)
        self.root.geometry('1030x650');self.root.update()
        self.assertGreater(self.app.tree.winfo_width(),400)
        self.assertGreater(self.app.details.winfo_width(),180)
        self.assertTrue(self.app.status_label.winfo_ismapped())
        self.assertLessEqual(self.app.status_label.winfo_rooty()+self.app.status_label.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())

    def test_closing_cancels_pending_query(self):
        self.app.search()
        self.assertTrue(self.app._pending)
        self.app.close()
        del self.app
        self.root=None
