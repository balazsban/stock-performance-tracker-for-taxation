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
                if not {'id','date','ticker','side','quantity','price','fees'}.issubset(columns):
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
