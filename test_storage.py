import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import storage

class StorageTests(unittest.TestCase):
    def test_mac_path_is_independent_of_working_directory(self):
        with patch.dict(os.environ, {}, clear=True), patch('storage.sys.platform','darwin'), patch('storage.Path.home',return_value=Path('/Users/example')):
            self.assertEqual(storage.database_path(), Path('/Users/example/Library/Application Support/Stock Ledger/ledger.sqlite3'))
    def test_relative_override_is_rejected(self):
        with patch.dict(os.environ, {'LEDGER_DB':'ledger.sqlite3'}):
            with self.assertRaises(ValueError): storage.database_path()
    def test_migration_survives_restarts_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); old=root/'old.sqlite3'; target=root/'persistent'/'ledger.sqlite3'
            with sqlite3.connect(old) as c:
                c.execute('CREATE TABLE transactions (id INTEGER,date TEXT,ticker TEXT,side TEXT,quantity TEXT,price TEXT,fees TEXT)')
                c.execute("INSERT INTO transactions VALUES (1,'2025-01-01','ABC','BUY','10','100','1')")
            self.assertTrue(storage.prepare_database(target,old))
            self.assertTrue(old.exists())
            with sqlite3.connect(target) as c: c.execute("UPDATE transactions SET quantity='20'")
            self.assertFalse(storage.prepare_database(target,old))
            with sqlite3.connect(target) as c: self.assertEqual(c.execute('SELECT quantity FROM transactions').fetchone()[0],'20')
            with sqlite3.connect(old) as c: self.assertEqual(c.execute('SELECT quantity FROM transactions').fetchone()[0],'10')
    def test_invalid_source_does_not_create_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'invalid.sqlite3'; source.write_text('not a database')
            target=root/'persistent'/'ledger.sqlite3'
            with self.assertRaises(sqlite3.DatabaseError): storage.prepare_database(target,source)
            self.assertFalse(target.exists())
    @unittest.skipUnless(sys.platform == 'darwin', 'Mac launcher test')
    def test_menu_instance_lock_and_busy_port(self):
        import desktop
        from http.server import BaseHTTPRequestHandler
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger.sqlite3'
            lock,_=desktop.acquire_instance(path)
            lock.write('{"port":8765}');lock.flush()
            second,url=desktop.acquire_instance(path)
            self.assertIsNone(second);self.assertEqual(url,'http://127.0.0.1:8765/')
            lock.close()
            second,url=desktop.acquire_instance(path);self.assertIsNotNone(second);second.close()
        server=desktop.make_server(BaseHTTPRequestHandler,0)
        try:
            fallback=desktop.make_server(BaseHTTPRequestHandler,server.server_port)
            self.assertNotEqual(fallback.server_port,server.server_port);fallback.server_close()
        finally:server.server_close()

    def test_http_save_survives_process_restart(self):
        import subprocess, json, urllib.request
        script = Path(__file__).resolve().parent / 'app.py'
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'durable' / 'ledger.sqlite3'
            env = dict(os.environ, LEDGER_DB=str(db), PORT='0')
            for run in range(2):
                process = subprocess.Popen([sys.executable, str(script)], cwd=tmp, env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    url = process.stdout.readline().strip().split()[-1]
                    if run == 0:
                        transaction=dict(date='2025-01-01',ticker='RESTART',currency='DKK',side='BUY',quantity='2',fx_mode='manual',dkk_total='1234',note='restart check')
                        request=urllib.request.Request(url+'/api/transactions',data=json.dumps(transaction).encode(),headers={'Content-Type':'application/json'})
                        with urllib.request.urlopen(request,timeout=5) as response:
                            self.assertEqual(response.status,200)
                    with urllib.request.urlopen(url+'/api/portfolio',timeout=5) as response:
                        data=json.load(response)
                    self.assertEqual(data['holdings'][0]['basis'],'1234')
                    self.assertEqual(data['holdings'][0]['average'],'617')
                finally:
                    process.terminate(); process.communicate(timeout=5)
