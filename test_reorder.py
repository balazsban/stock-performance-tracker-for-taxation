import tempfile, unittest
from pathlib import Path
import app

class ReorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DB;app.DB=Path(self.tmp.name)/'ledger.sqlite3'
    def tearDown(self):
        app.DB=self.old;self.tmp.cleanup()
    def add(self,side,amount,day='2025-01-02',ticker='ABC'):
        with app.connect() as c:
            d=app.prepare(dict(date=day,ticker=ticker,side=side,quantity='10',dkk_total=str(amount),note=''),c)
            d['sort_order']=c.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM transactions').fetchone()[0]
            return c.execute('INSERT INTO transactions ('+','.join(d)+') VALUES ('+','.join('?' for _ in d)+')',list(d.values())).lastrowid
    def move(self,ids,expected,ticker='ABC',day='2025-01-02'):
        with app.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return app.reorder_day(c,dict(date=day,ticker=ticker,ids=ids,expected_ids=expected))
    def test_reorder_changes_basis_and_realized_profit_and_persists(self):
        self.add('BUY',1000,'2025-01-01');sale=self.add('SELL',1500);buy=self.add('BUY',2000)
        r=self.move([buy,sale],[sale,buy]);self.assertEqual(r['holdings'][0]['average'],150);self.assertEqual(r['annual'][0]['profit'],0)
        with app.connect() as c:
            r=app.portfolio_report(app.rows(c));self.assertEqual(r['holdings'][0]['basis'],1500)
            self.assertEqual([t['id'] for t in r['transactions'][:2]],[sale,buy])
        r=self.move([sale,buy],[buy,sale]);self.assertEqual(r['annual'][0]['profit'],500);self.assertEqual(r['holdings'][0]['average'],200)
    def test_negative_holdings_roll_back_whole_change(self):
        buy=self.add('BUY',1000);sale=self.add('SELL',1500)
        with self.assertRaisesRegex(ValueError,'exceeds available'):
            self.move([sale,buy],[buy,sale])
        with app.connect() as c:
            self.assertEqual([t['id'] for t in app.rows(c)],[buy,sale]);self.assertEqual(app.portfolio_report(app.rows(c))['annual'][0]['profit'],500)
    def test_bad_ids_and_stale_order_rejected(self):
        a=self.add('BUY',1000);b=self.add('BUY',2000);other=self.add('BUY',500,ticker='XYZ');otherdate=self.add('BUY',3000,'2025-01-03')
        for ids,expected in [([a,a],[a,b]),([a],[a,b]),([a,other],[a,b]),([a,otherdate],[a,b]),([b,a],[b,a]),(['1',b],[a,b])]:
            with self.assertRaises(ValueError):self.move(ids,expected)
    def test_other_tickers_keep_their_order(self):
        a=self.add('BUY',1000);x=self.add('BUY',500,ticker='XYZ');b=self.add('BUY',2000)
        self.move([b,a],[a,b])
        with app.connect() as c:self.assertEqual([t['id'] for t in app.rows(c)],[b,x,a])
