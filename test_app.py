import unittest, tempfile
from pathlib import Path
from decimal import Decimal
import app

def t(i,side,q,p,fees='0',day='2025-01-01',ticker='ABC',currency='USD'):
    total=Decimal(str(q))*Decimal(str(p))+(Decimal(fees) if side=='BUY' else -Decimal(fees))
    return dict(id=i,sort_order=i,**app.validate(dict(date=day,ticker=ticker,side=side,quantity=str(q),dkk_total=str(total),note='')))
class AccountingTests(unittest.TestCase):
    def test_weighted_average_and_sale_fees(self):
        r=app.calculate([t(1,'BUY',10,100,'10'),t(2,'BUY',10,200),t(3,'SELL',5,180,'5')])
        self.assertEqual(r['holdings'][0]['average'],Decimal('150.5'))
        self.assertEqual(r['holdings'][0]['basis'],Decimal('2257.5'))
        self.assertEqual(r['annual'][0]['profit'],Decimal('142.5'))
    def test_close_reopen_and_years(self):
        r=app.calculate([t(1,'BUY',2,10),t(2,'SELL',2,8),t(3,'BUY',3,30,day='2026-01-01'),t(4,'SELL',1,40,day='2026-02-01')])
        self.assertEqual(r['holdings'][0]['average'],30)
        self.assertEqual([x['profit'] for x in r['annual']],[Decimal(-4),Decimal(10)])
    def test_backdated_replay(self):
        r=app.calculate([t(1,'BUY',10,100,day='2025-02-01'),t(2,'SELL',10,100,day='2025-03-01'),t(3,'BUY',10,50)])
        self.assertEqual(r['annual'][0]['profit'],250)
    def test_oversell(self):
        with self.assertRaises(ValueError): app.calculate([t(1,'BUY',1,10),t(2,'SELL',2,20)])
    def test_fractional_and_invalid_numbers(self):
        r=app.calculate([t(1,'BUY','.1','0.1'),t(2,'SELL','.1','.2')])
        self.assertEqual(r['annual'][0]['profit'],Decimal('.01'))
        self.assertEqual(r['holdings'],[])
        for val in ['NaN','Infinity','-1']:
            with self.assertRaises(ValueError): t(1,'BUY',val,1)
    def test_persistence_and_rollback(self):
        old=app.DB
        with tempfile.TemporaryDirectory() as tmp:
            app.DB=Path(tmp)/'test.sqlite3'
            try:
                with app.connect() as c:
                    d=t(1,'BUY',10,10);c.execute('INSERT INTO transactions ('+','.join(d)+') VALUES ('+','.join('?' for _ in d)+')',list(d.values()))
                with app.connect() as c: self.assertEqual(len(app.rows(c)),1)
                with self.assertRaises(ValueError):
                    with app.connect() as c:
                        c.execute('DELETE FROM transactions');raise ValueError('rollback')
                with app.connect() as c: self.assertEqual(len(app.rows(c)),1)
            finally: app.DB=old
if __name__=='__main__': unittest.main()
