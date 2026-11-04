"""Mac menu-bar launcher. Database lives outside the application bundle."""
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time
from http.server import HTTPServer

import storage


def acquire_instance(database):
    lock = Path(str(database) + '.instance.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock, None
    except BlockingIOError:
        for _ in range(30):
            lock.seek(0)
            try:
                state=json.load(lock)
                port=int(state['port'])
                if 1 <= port <= 65535:
                    lock.close()
                    return None, f'http://127.0.0.1:{port}/'
            except (ValueError, KeyError):
                pass
            time.sleep(.1)
        lock.close()
        raise RuntimeError('Stock Ledger is already starting. Try opening it again in a few seconds.')


def make_server(handler, preferred=8765):
    try:
        return HTTPServer(('127.0.0.1', preferred), handler)
    except OSError as error:
        import errno
        if error.errno != errno.EADDRINUSE:
            raise
        return HTTPServer(('127.0.0.1', 0), handler)


def open_browser(url):
    from AppKit import NSWorkspace
    from Foundation import NSURL
    if not NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url)):
        raise RuntimeError('Could not open the default browser. Open ' + url + ' manually.')


def main():
    import rumps
    import app
    database = app.DB
    # For source launches, discover the old database next to app.py. Packaged
    # apps may migrate a ledger.sqlite3 placed alongside the .app on first run.
    legacy = app.ROOT / 'ledger.sqlite3'
    if getattr(sys, 'frozen', False):
        legacy = Path(sys.executable).resolve().parents[3] / 'ledger.sqlite3'
    storage.prepare_database(database, legacy if not os.environ.get('LEDGER_DB') else None)
    log_handler=RotatingFileHandler(database.parent / 'stock-ledger.log', maxBytes=1_000_000, backupCount=2)
    logging.basicConfig(level=logging.INFO, handlers=[log_handler])
    lock, existing = acquire_instance(database)
    if existing:
        open_browser(existing)
        return
    server = None
    cleaned = False
    def cleanup():
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        if server:
            server.shutdown(); server.server_close()
        lock.seek(0); lock.truncate(); lock.flush(); lock.close()
    rumps.events.before_quit.register(cleanup)
    # Rumps has no public reopen event. Its pinned delegate is extended so
    # opening an already-running .app in Finder brings the browser back.
    from rumps import rumps as rumps_impl
    class LedgerDelegate(rumps_impl.NSApp):
        def applicationShouldHandleReopen_hasVisibleWindows_(self, application, visible):
            open_browser(url)
            return False
    rumps_impl.NSApp = LedgerDelegate
    try:
        with app.connect():
            pass
        server = make_server(app.Handler, int(os.environ.get('PORT','8765')))
        url=f'http://127.0.0.1:{server.server_port}/'
        lock.seek(0); lock.truncate(); json.dump({'port':server.server_port},lock); lock.flush()
        worker=threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        class LedgerMenu(rumps.App):
            def __init__(self):
                super().__init__('Stock Ledger', title='◈ Ledger', quit_button=None,
                    menu=['Open Stock Ledger', 'Show Data Folder', 'Quit Stock Ledger'])
            @rumps.clicked('Open Stock Ledger')
            def open_ledger(self, _):
                open_browser(url)
            @rumps.clicked('Show Data Folder')
            def show_data(self, _):
                from AppKit import NSWorkspace
                NSWorkspace.sharedWorkspace().selectFile_inFileViewerRootedAtPath_(str(database), str(database.parent))
            @rumps.clicked('Quit Stock Ledger')
            def quit_ledger(self, _):
                rumps.quit_application()
        open_browser(url)
        LedgerMenu().run()
    finally:
        cleanup()

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        logging.exception('Could not start Stock Ledger')
        import rumps
        rumps.alert('Stock Ledger could not start', str(error))
        raise SystemExit(1)
