import copy
import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from flight_app.errors import DataError, ValidationError
from flight_app.exporting import export_quotes
from flight_app.models import SearchCriteria
from flight_app.presentation import detail_text, leg_label
from flight_app.provider import JsonFlightProvider
from flight_app.service import SearchService
from flight_app.validation import parse_budget, parse_date
from tests.helpers import MemoryProvider, flight

ROOT=Path(__file__).resolve().parents[1]


class InputTests(unittest.TestCase):
    def test_valid_dates_and_leap_day(self):
        self.assertEqual(parse_date("2028-02-29"),date(2028,2,29))

    def test_invalid_dates(self):
        for text in ("", "2026-02-29","2026-11-31","2026/11/10","20261110","2026-1-1"):
            with self.subTest(text=text),self.assertRaises(ValidationError):parse_date(text)

    def test_budget_decimal_and_blank(self):
        self.assertIsNone(parse_budget(" "))
        self.assertEqual(parse_budget("0"),0)
        self.assertEqual(parse_budget("123.45"),12345)
        self.assertEqual(parse_budget("1000000"),100000000)

    def test_invalid_budget(self):
        for text in ("-1","1.001","abc","NaN","Infinity","1000000.01"):
            with self.subTest(text=text),self.assertRaises(ValidationError):parse_budget(text)


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload=json.loads((ROOT/'data'/'flights.json').read_text(encoding='utf-8'))

    def load(self,payload):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'data.json';path.write_text(json.dumps(payload),encoding='utf-8')
            return JsonFlightProvider(path)

    def small(self):
        p=copy.deepcopy(self.payload);p['flights']=p['flights'][:1];return p

    def test_real_dataset_and_default_queries(self):
        p=JsonFlightProvider(ROOT/'data'/'flights.json');s=SearchService(p)
        self.assertEqual(len(p.dates),30)
        self.assertEqual(len(p.cities),7)
        for return_date in (None,date(2026,11,15)):
            results=s.search(SearchCriteria('深圳','北京',date(2026,11,10),return_date=return_date))
            self.assertGreater(len(results),0)
            self.assertTrue(all(q.final_price_cents>=0 for q in results))

    def test_missing_file(self):
        with self.assertRaises(DataError):JsonFlightProvider(ROOT/'absent.json')

    def test_invalid_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.json';path.write_text('{broken',encoding='utf-8')
            with self.assertRaises(DataError):JsonFlightProvider(path)

    def test_duplicate_id_rejected(self):
        p=self.small();p['flights']*=2
        with self.assertRaises(DataError):self.load(p)

    def test_schema_and_simulation_marker(self):
        for key,value in [('schema_version',2),('schema_version',True),('simulated',False)]:
            p=self.small();p[key]=value
            with self.subTest(key=key),self.assertRaises(DataError):self.load(p)

    def test_invalid_money_and_seats(self):
        for key,value in [('price_cents',-1),('price_cents',12.3),('price_cents',True),('seats',-1),('seats','3')]:
            p=self.small();p['flights'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(DataError):self.load(p)

    def test_missing_timezone_and_invalid_chronology(self):
        for value in ['2026-11-01T08:00:00','2026-11-01T08:00:00+00:00','2026-10-31T08:00:00+08:00']:
            p=self.small();p['flights'][0]['segments'][0]['arrival']=value
            with self.subTest(value=value),self.assertRaises(DataError):self.load(p)

    def test_airport_and_empty_segments_rejected(self):
        p=self.small();p['flights'][0]['segments'][0]['origin']='???'
        with self.assertRaises(DataError):self.load(p)
        p=self.small();p['flights'][0]['segments']=[]
        with self.assertRaises(DataError):self.load(p)

    def test_empty_dataset_is_valid_and_has_no_results(self):
        p=self.small();p['flights']=[]
        self.assertEqual(self.load(p).dates,())

    def test_disconnected_segments_rejected(self):
        p=self.small();seg=copy.deepcopy(p['flights'][0]['segments'][0]);p['flights'][0]['segments'].append(seg)
        with self.assertRaises(DataError):self.load(p)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.c=SearchCriteria('深圳','北京',date(2026,11,10))
        self.results=SearchService(MemoryProvider([flight('a'),flight('b',price=30000)])).search(self.c)

    def test_csv_preserves_order_prices_and_chinese(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'results.csv'
            self.assertEqual(export_quotes(path,self.results,self.c),2)
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            with path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
            self.assertEqual([r['报价编号'] for r in rows],['b','a'])
            self.assertEqual(rows[0]['合计元'],'300.00')
            self.assertEqual(rows[0]['出发城市'],'深圳')
            self.assertEqual(rows[0]['返程航班'],'')

    def test_atomic_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'results.csv';path.write_text('original')
            with patch('flight_app.exporting.os.replace',side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):export_quotes(path,self.results,self.c)
            self.assertEqual(path.read_text(),'original')
            self.assertEqual(len(list(Path(folder).iterdir())),1)

    def test_formula_injection_escaped(self):
        weird=flight(airline='=1+1')
        q=SearchService(MemoryProvider([weird])).search(self.c)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'out.csv';export_quotes(path,q,self.c)
            with path.open(encoding='utf-8-sig',newline='') as stream:row=next(csv.DictReader(stream))
            self.assertEqual(row['去程航司'],"'=1+1")

    def test_cross_day_presentation(self):
        a=flight(start='2026-11-10T23:00',end='2026-11-11T02:00')
        self.assertIn('+1天',leg_label(a))
        q=SearchService(MemoryProvider([a])).search(self.c)[0]
        self.assertIn('2026-11-11 02:00',detail_text(q))
