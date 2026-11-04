"""Stable, per-user data paths and non-destructive legacy migration."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


def data_directory():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Stock Ledger'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'Stock Ledger'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'stock-ledger'


def database_path():
    override = os.environ.get('LEDGER_DB')
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError('LEDGER_DB must be an absolute path so the same database is used on every launch.')
        return path
    return data_directory() / 'ledger.sqlite3'


def prepare_database(target, legacy=None):
    """Back up an old SQLite file atomically; never replace an existing target."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or not legacy or not Path(legacy).is_file() or target == Path(legacy):
        return False
    # Serialize migration separately from SQLite's transaction locking.
    with (target.parent / '.migration.lock').open('a') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); lock.write('0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists():
            return False
        fd, temporary = tempfile.mkstemp(prefix='.migration-', dir=target.parent)
        os.close(fd)
        try:
            with sqlite3.connect(Path(legacy).resolve().as_uri() + '?mode=ro', uri=True) as source:
                if source.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Legacy database integrity check failed; the original has not been changed.')
                columns={r[1] for r in source.execute('PRAGMA table_info(transactions)')}
                if not {'id','date','ticker','side','quantity'}.issubset(columns):
                    raise ValueError('The selected database is not a Stock Ledger database.')
                with sqlite3.connect(temporary) as dest:
                    source.backup(dest)
                    if dest.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('Migrated database integrity check failed.')
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return True


def migrate_dkk_schema(c, database):
    """Preserve saved DKK totals and trade IDs; back up before removing FX data."""
    from decimal import Decimal
    from datetime import datetime
    schema = "CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, ticker TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL, dkk_total TEXT, broker TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL)"
    columns={r[1] for r in c.execute('PRAGMA table_info(transactions)')}
    if not columns:
        c.execute(schema); c.commit(); return
    if not (columns & {'currency','price','fees','fx_mode','fx_rate','fx_date','fx_source','currency_total'}):
        return
    # Hold a write reservation while a separate read connection takes a consistent backup.
    c.execute('BEGIN IMMEDIATE')
    try:
        backup=Path(str(database)+'.before-dkk-only-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
        with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as source:
            with sqlite3.connect(backup) as dest:
                source.backup(dest)
                if dest.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                    raise ValueError('Database backup failed integrity check.')
        old=[dict(r) for r in c.execute('SELECT * FROM transactions')]
        sequence=c.execute("SELECT seq FROM sqlite_sequence WHERE name='transactions'").fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone() else None
        c.execute('ALTER TABLE transactions RENAME TO old_transactions')
        c.execute(schema)
        for t in old:
            total=t.get('dkk_total')
            if total is None and t.get('currency')=='DKK':
                gross=Decimal(t['quantity'])*Decimal(t['price']); fees=Decimal(t.get('fees') or '0')
                total=str(gross+fees if t['side']=='BUY' else gross-fees)
            c.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?)',
                (t['id'],t['date'],t['ticker'],t['side'],t['quantity'],total,t.get('broker') or '',t.get('note') or '',t.get('sort_order') if t.get('sort_order') is not None else t['id']))
        if sequence:
            c.execute("DELETE FROM sqlite_sequence WHERE name='transactions'")
            c.execute("INSERT INTO sqlite_sequence(name,seq) VALUES ('transactions',?)",(max(sequence[0],max((t['id'] for t in old),default=0)),))
        c.execute('DROP TABLE old_transactions')
        c.execute('DROP TABLE IF EXISTS fx_cache')
        c.commit()
    except Exception:
        c.rollback(); raise
