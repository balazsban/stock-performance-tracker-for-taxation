import unittest, tempfile, json
from unittest.mock import patch
from pathlib import Path
from decimal import Decimal
import app, fx

class DKKTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=app.DB; app.DB=Path(self.tmp.name)/'db.sqlite3'; self.c=app.connect()
    def tearDown(self):
        self.c.close(); app.DB=self.old; self.tmp.cleanup()
    def entry(self, i, **changes):
        raw=dict(date='2025-01-02',ticker='ABC',currency='USD',side='BUY',quantity='10',price='100',fees='10',note='',broker='IBKR',fx_mode='manual',dkk_total='7000')
        raw.update(changes)
        return dict(id=i,**app.prepare(raw,self.c))
    def test_final_amount_not_double_charged_and_mixed_currencies(self):
        purchase=self.entry(1,fees='500',currency='DKK',broker='Danish broker')
        sale=self.entry(2,side='SELL',quantity='5',dkk_total='4000',fees='200',date='2026-01-01')
        r=app.portfolio_report([purchase,sale])
        self.assertEqual(r['holdings'][0]['basis'],3500)
        self.assertEqual(r['holdings'][0]['average'],700)
        self.assertEqual(r['annual'][0]['profit'],500)
        self.assertEqual(r['annual'][0]['currency'],'DKK')
    def test_manual_dkk_only_no_fabricated_foreign_price(self):
        t=self.entry(1,price='',fees='',currency='DKK')
        self.assertEqual(t['price'],''); self.assertEqual(t['fees'],'')
        self.assertEqual(app.portfolio_report([t])['holdings'][0]['basis'],7000)
    def test_each_transaction_uses_its_own_rate(self):
        with patch('fx.lookup',return_value=dict(rate='7',rate_date='2025-01-02',source=fx.SOURCE)):
            buy=self.entry(1,fx_mode='auto',fees='0')
        with patch('fx.lookup',return_value=dict(rate='6',rate_date='2025-01-03',source=fx.SOURCE)):
            sale=self.entry(2,fx_mode='auto',side='SELL',price='120',fees='0',date='2025-01-03')
        self.assertEqual(app.portfolio_report([buy,sale])['annual'][0]['profit'],200)
    def test_edit_preserves_saved_rate(self):
        with patch('fx.lookup',return_value=dict(rate='7',rate_date='2025-01-02',source=fx.SOURCE)):
            old=self.entry(1,fx_mode='auto',fees='0')
        with patch('fx.lookup',side_effect=AssertionError('Should use stored quote')):
            changed=app.prepare(dict(old,price='110',note='edited'),self.c,old)
        self.assertEqual(Decimal(changed['dkk_total']),7700)
    def test_missing_legacy_dkk_blocks_report(self):
        legacy=dict(id=1,**app.validate(dict(date='2025-01-02',ticker='ABC',currency='USD',side='BUY',quantity='1',price='10',fees='0',note='')))
        r=app.portfolio_report([legacy]);self.assertEqual(r['missing_dkk'],[1]);self.assertEqual(r['holdings'],[])
        legacy['currency']='DKK';r=app.portfolio_report([legacy]);self.assertEqual(r['holdings'][0]['basis'],10)
    def test_oversell_across_brokers(self):
        with self.assertRaises(ValueError):app.portfolio_report([self.entry(1),self.entry(2,side='SELL',quantity='11')])
    def test_invalid_manual_total(self):
        for total in ['','NaN','-1','Infinity']:
            with self.assertRaises(ValueError):self.entry(1,dkk_total=total)
    def test_rate_scaling_weekend_and_cache(self):
        info={'variables':[{'id':'VALUTA','values':[{'id':'USD'}]},{'id':'Tid','values':[{'id':'2025M01D03'}]}]}
        response='VALUTA;KURTYP;TID;INDHOLD\nUSD;KBH;2025M01D03;724.3300\n'
        with patch('fx.fetch',side_effect=[json.dumps(info),response]) as mock:
            q=fx.lookup('USD','2025-01-05',self.c)
            self.assertEqual(q['rate'],'7.2433'); self.assertEqual(q['rate_date'],'2025-01-03')
            self.assertEqual(fx.lookup('USD','2025-01-05',self.c),q);self.assertEqual(mock.call_count,2)
    def test_missing_banking_day_not_silently_replaced(self):
        info={'variables':[{'id':'VALUTA','values':[{'id':'USD'}]},{'id':'Tid','values':[{'id':'2025M01D02'}]}]}
        with patch('fx.fetch',return_value=json.dumps(info)):
            with self.assertRaisesRegex(ValueError,'not been published'):fx.lookup('USD','2025-01-03',self.c)
    def test_future_and_unsupported(self):
        with self.assertRaises(ValueError):fx.lookup('USD','2099-01-01',self.c)
        with self.assertRaises(ValueError):fx.lookup('badcode','2025-01-01',self.c)
    def test_migration_preserves_existing_records(self):
        self.c.close();app.DB=Path(self.tmp.name)/'old.sqlite3'
        import sqlite3
        c=sqlite3.connect(app.DB);c.execute('CREATE TABLE transactions (id INTEGER PRIMARY KEY,date TEXT,ticker TEXT,currency TEXT,side TEXT,quantity TEXT,price TEXT,fees TEXT,note TEXT)')
        c.execute("INSERT INTO transactions VALUES (1,'2025-01-01','ABC','USD','BUY','10','20','1','old note')");c.commit();c.close()
        self.c=app.connect();r=app.rows(self.c);self.assertEqual(r[0]['note'],'old note');self.assertIsNone(r[0]['dkk_total'])
if __name__=='__main__':unittest.main()
