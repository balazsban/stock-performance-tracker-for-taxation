import json, sqlite3, re, os, csv, io
from pathlib import Path
from decimal import Decimal, InvalidOperation, getcontext, DefaultContext
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import storage
import logging
DefaultContext.prec = 40
getcontext().prec = 40
ROOT = Path(__file__).resolve().parent
DB = storage.database_path()

def connect():
    if DB == storage.database_path():
        storage.prepare_database(DB, ROOT / 'ledger.sqlite3' if not os.environ.get('LEDGER_DB') else None)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    storage.migrate_dkk_schema(c, DB)
    return c

def validate(d):
    out = {k: str(d.get(k, '')).strip() for k in ['date','ticker','side','quantity','dkk_total','note','broker']}
    if date.fromisoformat(out['date']).isoformat() != out['date']: raise ValueError('Use a valid YYYY-MM-DD date.')
    out['ticker'] = out['ticker'].upper()
    if not re.fullmatch(r'[A-Z0-9.^:_/-]{1,24}', out['ticker']): raise ValueError('Enter a valid ticker (up to 24 characters).')
    if out['side'] not in ['BUY','SELL']: raise ValueError('Choose buy or sell.')
    for k in ['quantity','dkk_total']:
        try: n = Decimal(out[k])
        except InvalidOperation: raise ValueError('Enter shares and the final DKK amount.')
        limit=Decimal('1e18') if k=='quantity' else Decimal('1e24')
        if not n.is_finite() or n<0 or n>limit or (k=='quantity' and n==0) or n.as_tuple().exponent < -12:
            raise ValueError(f'Invalid {k}: use a positive share quantity and a nonnegative DKK amount, with up to 12 decimals.')
        out[k]=str(n)
    if len(out['note'])>500: raise ValueError('Notes must be at most 500 characters.')
    if len(out['broker'])>100: raise ValueError('Broker name must be at most 100 characters.')
    return out

def calculate(rows):
    positions, annual, realized, history = {}, {}, {}, []
    for raw in sorted(rows, key=lambda t:(t['date'],t.get('sort_order') if t.get('sort_order') is not None else t['id'],t['id'])):
        t = dict(raw); key = (t['ticker'], 'DKK')
        p = positions.setdefault(key, {'ticker':key[0], 'currency':key[1], 'quantity':Decimal(0), 'basis':Decimal(0)})
        q = Decimal(t['quantity'])
        avg = p['basis'] / p['quantity'] if p['quantity'] else Decimal(0)
        gain = None
        total = Decimal(t.get('dkk_total') or '0')
        if t['side'] == 'BUY': p['quantity'] += q; p['basis'] += total
        else:
            if q > p['quantity']: raise ValueError(f"{t['date']}: sale of {q} {key[0]} exceeds available {p['quantity']} shares ({key[1]}).")
            cost = avg*q; gain = total-cost
            p['quantity'] -= q; p['basis'] = p['basis']-cost if p['quantity'] else Decimal(0)
            yearkey = (t['date'][:4], *key)
            a = annual.setdefault(yearkey, {'year':yearkey[0], 'ticker':key[0], 'currency':key[1], 'proceeds':Decimal(0),'cost':Decimal(0),'profit':Decimal(0)})
            a['proceeds'] += total; a['cost'] += cost; a['profit'] += gain
            realized[key] = realized.get(key, Decimal(0))+gain
        t.update(profit=gain, remaining=p['quantity'], average=p['basis']/p['quantity'] if p['quantity'] else Decimal(0))
        history.append(t)
    holdings = [dict(p, average=p['basis']/p['quantity'], profit=realized.get(k, Decimal(0))) for k,p in positions.items() if p['quantity']]
    return {'holdings':holdings,'annual':list(annual.values()),'realized':[{'ticker':k[0],'currency':k[1],'profit':v} for k,v in realized.items()], 'transactions':list(reversed(history))}

def prepare(d, c, previous=None):
    return validate(d)

def portfolio_report(records):
    missing=[t['id'] for t in records if t.get('dkk_total') is None]
    report=calculate(records)
    report['missing_dkk']=missing
    if missing:
        report.update(holdings=[],annual=[],realized=[])
        for t in report['transactions']: t.update(profit=None,average=None)
    return report


def rows(c): return [dict(r) for r in c.execute('SELECT * FROM transactions ORDER BY date,sort_order,id')]

def reorder_day(c, payload):
    day, ticker = payload.get('date'), payload.get('ticker')
    current = [dict(r) for r in c.execute(
        'SELECT * FROM transactions WHERE date=? AND ticker=? ORDER BY sort_order,id', (day,ticker))]
    before = [r['id'] for r in current]
    requested = payload.get('ids')
    if (not isinstance(requested,list) or any(type(i) is not int for i in requested)
            or len(requested)!=len(before) or set(requested)!=set(before) or not before):
        raise ValueError('Include every trade for this ticker and date exactly once. Reload and try again.')
    if payload.get('expected_ids') != before:
        raise ValueError('This day’s trades changed since you opened the order editor. Close it and try again.')
    # Slot values are unique after migration/new entry. Other tickers keep their slots.
    slots = sorted(r['sort_order'] for r in current)
    for ident, slot in zip(requested, slots):
        c.execute('UPDATE transactions SET sort_order=? WHERE id=?', (slot,ident))
    # The enclosing transaction rolls back all slots if any historical balance is negative.
    return portfolio_report(rows(c))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logging.info(fmt, *args)
    def send(self, status, body, content='application/json'):
        data = (json.dumps(body, default=str) if content == 'application/json' else body).encode()
        self.send_response(status); self.send_header('Content-Type', content+'; charset=utf-8'); self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/portfolio':
            with connect() as c: self.send(200,portfolio_report(rows(c)))
        elif path == '/api/report':
            with connect() as c: report=portfolio_report(rows(c))
            if report['missing_dkk']: return self.send(400,{'error':'Complete the missing DKK amounts before exporting the report.'})
            year=parse_qs(urlparse(self.path).query).get('year',[''])[0]
            f=io.StringIO(); w=csv.DictWriter(f,fieldnames=['year','ticker','currency','proceeds','cost','profit']); w.writeheader()
            w.writerows(r for r in report['annual'] if not year or r['year']==year)
            self.send(200,f.getvalue(),'text/csv')
        elif path == '/api/export':
            with connect() as c: data = rows(c)
            f=io.StringIO(); w=csv.DictWriter(f,fieldnames=['id','date','ticker','side','quantity','dkk_total','broker','note','sort_order']); w.writeheader(); w.writerows(data)
            self.send(200,f.getvalue(),'text/csv')
        elif path in ['/','/app.js','/style.css']:
            name = 'index.html' if path=='/' else path[1:]
            self.send(200,(ROOT/'static'/name).read_text(),{'index.html':'text/html','app.js':'text/javascript','style.css':'text/css'}[name])
        else: self.send(404,{'error':'Not found'})
    def mutate(self):
        try:
            origin = self.headers.get('Origin')
            if origin and origin != 'http://'+self.headers.get('Host',''): raise ValueError('Cross-origin changes are not allowed.')
            path=urlparse(self.path).path
            if path == '/api/transactions/reorder':
                if self.command != 'POST': return self.send(405,{'error':'Use POST to reorder trades.'})
                length=int(self.headers.get('Content-Length','0'))
                if length > 100000: raise ValueError('Request too large.')
                payload=json.loads(self.rfile.read(length))
                with connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    result=reorder_day(c,payload)
                return self.send(200,result)
            ident=None
            if path != '/api/transactions':
                m=re.fullmatch(r'/api/transactions/(\d+)',path)
                if not m: return self.send(404,{'error':'Not found'})
                ident=int(m[1])
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if self.command in ['PUT','DELETE']:
                    if ident is None or not c.execute('SELECT id FROM transactions WHERE id=?',(ident,)).fetchone(): return self.send(404,{'error':'Transaction not found'})
                if self.command == 'DELETE': c.execute('DELETE FROM transactions WHERE id=?',(ident,))
                else:
                    length=int(self.headers.get('Content-Length','0'))
                    if length > 10000: raise ValueError('Request too large.')
                    previous=dict(c.execute('SELECT * FROM transactions WHERE id=?',(ident,)).fetchone()) if ident else None
                    d=prepare(json.loads(self.rfile.read(length)),c,previous)
                    if self.command=='POST':
                        d['sort_order']=c.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM transactions').fetchone()[0]
                    if self.command=='POST': c.execute('INSERT INTO transactions ('+','.join(d)+') VALUES ('+','.join('?' for _ in d)+')',list(d.values()))
                    else: c.execute('UPDATE transactions SET '+','.join(k+'=?' for k in d)+' WHERE id=?',list(d.values())+[ident])
                result=portfolio_report(rows(c))
            self.send(200,result)
        except (ValueError,InvalidOperation,KeyError,TypeError,AttributeError) as e: self.send(400,{'error':str(e) or 'Invalid transaction'})
    do_POST=mutate
    do_PUT=mutate
    do_DELETE=mutate

if __name__ == '__main__':
    with connect(): pass
    port=int(os.environ.get('PORT','8765'))
    server = HTTPServer(('127.0.0.1',port),Handler)
    print(f'Stock Ledger running at http://127.0.0.1:{server.server_port}',flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
