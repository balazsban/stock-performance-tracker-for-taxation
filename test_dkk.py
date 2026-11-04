import sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import app

class DKKMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=app.DB; app.DB=Path(self.tmp.name)/'ledger.sqlite3'
    def tearDown(self):
        app.DB=self.old;self.tmp.cleanup()
    def legacy(self):
        c=sqlite3.connect(app.DB)
        c.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,ticker TEXT,currency TEXT,side TEXT,quantity TEXT,price TEXT,fees TEXT,note TEXT,dkk_total TEXT,fx_mode TEXT,fx_rate TEXT,fx_date TEXT,fx_source TEXT,broker TEXT,sort_order INTEGER,currency_total TEXT)")
        c.execute("CREATE TABLE fx_cache(currency TEXT,rate TEXT)")
        c.execute("INSERT INTO fx_cache VALUES ('USD','7')")
        c.execute("INSERT INTO transactions VALUES (4,'2025-01-01','ABC','USD','BUY','10','100','10','original note','7070','total','7','2025-01-01','Nationalbank','IBKR',5,'1010')")
        c.execute("INSERT INTO transactions VALUES (7,'2025-01-02','ABC','EUR','SELL','5','','','','4000','manual',NULL,NULL,'Broker final DKK amount','Broker',8,NULL)")
        c.execute("UPDATE sqlite_sequence SET seq=20 WHERE name='transactions'")
        c.commit();c.close()
    def test_migration_preserves_accounting_and_order_removes_fx_and_backs_up(self):
        self.legacy()
        with app.connect() as c:
            records=app.rows(c);r=app.portfolio_report(records)
            self.assertEqual(r['holdings'][0]['basis'],3535)
            self.assertEqual(r['annual'][0]['profit'],465)
            self.assertEqual([t['sort_order'] for t in records],[5,8])
            self.assertEqual(records[0]['note'],'original note')
            self.assertEqual(records[0]['broker'],'IBKR')
            self.assertEqual(set(records[0]),{'id','date','ticker','side','quantity','dkk_total','broker','note','sort_order'})
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='fx_cache'").fetchone())
            self.assertEqual(c.execute("SELECT seq FROM sqlite_sequence WHERE name='transactions'").fetchone()[0],20)
        backups=list(Path(self.tmp.name).glob('*.before-dkk-only-*.sqlite3'))
        self.assertEqual(len(backups),1)
        with sqlite3.connect(backups[0]) as c:
            self.assertEqual(c.execute('SELECT currency FROM transactions WHERE id=4').fetchone()[0],'USD')
            self.assertEqual(c.execute('SELECT count(*) FROM fx_cache').fetchone()[0],1)
        with app.connect() as c:self.assertEqual(len(app.rows(c)),2)
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.before-dkk-only-*.sqlite3'))),1)
    def test_missing_dkk_not_guessed_and_legacy_dkk_total_derived(self):
        self.legacy()
        with sqlite3.connect(app.DB) as c:
            c.execute("UPDATE transactions SET dkk_total=NULL,currency='DKK' WHERE id=4")
            c.execute("UPDATE transactions SET dkk_total=NULL WHERE id=7")
        with app.connect() as c:
            records=app.rows(c)
            self.assertEqual(records[0]['dkk_total'],'1010')
            r=app.portfolio_report(records)
            self.assertEqual(r['missing_dkk'],[7]);self.assertEqual(r['holdings'],[])
            self.assertTrue(all(t['profit'] is None for t in r['transactions']))
    def test_failed_backup_keeps_old_schema(self):
        self.legacy()
        with patch('storage.sqlite3.connect',side_effect=OSError('backup unavailable')):
            with self.assertRaises(OSError):
                c=sqlite3.connect  # patched connection is not used to open the app connection below
                # Use a connection created by the saved module's real function via a separate fixture.
                import _sqlite3
                conn=_sqlite3.connect(app.DB);conn.row_factory=sqlite3.Row
                try: app.storage.migrate_dkk_schema(conn,app.DB)
                finally: conn.close()
        with sqlite3.connect(app.DB) as c:
            self.assertIn('currency',[r[1] for r in c.execute('PRAGMA table_info(transactions)')])
            self.assertEqual(c.execute('SELECT count(*) FROM transactions').fetchone()[0],2)
    def test_validation_requires_final_dkk_amount(self):
        base=dict(date='2025-01-01',ticker='abc',side='BUY',quantity='10',dkk_total='1234')
        self.assertEqual(app.validate(base)['ticker'],'ABC')
        for amount in ['',None,'NaN','Infinity','-1','1e25','0.0000000000001']:
            with self.assertRaises(ValueError):app.validate(dict(base,dkk_total=amount))
