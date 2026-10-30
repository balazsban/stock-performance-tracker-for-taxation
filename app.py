import json, sqlite3, re, os, csv, io
from pathlib import Path
from decimal import Decimal, InvalidOperation, getcontext
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import fx
getcontext().prec = 40
ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('LEDGER_DB', str(ROOT / 'ledger.sqlite3')))

def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, ticker TEXT NOT NULL, currency TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL, price TEXT NOT NULL, fees TEXT NOT NULL, note TEXT NOT NULL)')
    columns={r['name'] for r in c.execute('PRAGMA table_info(transactions)')}
    for name in ['dkk_total','fx_mode','fx_rate','fx_date','fx_source','broker']:
        if name not in columns: c.execute(f'ALTER TABLE transactions ADD COLUMN {name} TEXT')
    c.execute('CREATE TABLE IF NOT EXISTS fx_cache (currency TEXT, trade_date TEXT, rate_date TEXT, rate TEXT, source TEXT, PRIMARY KEY(currency,trade_date))')
    c.commit()
    return c

def validate(d):
    out = {k: str(d.get(k, '')).strip() for k in ['date','ticker','currency','side','quantity','price','fees','note']}
    if date.fromisoformat(out['date']).isoformat() != out['date']: raise ValueError('Use a valid YYYY-MM-DD date.')
    out['ticker'] = out['ticker'].upper(); out['currency'] = out['currency'].upper()
    if not re.fullmatch(r'[A-Z0-9.^:_/-]{1,24}', out['ticker']): raise ValueError('Enter a valid ticker (up to 24 characters).')
    if not re.fullmatch(r'[A-Z]{3}', out['currency']): raise ValueError('Currency must have three letters, e.g. USD.')
    if out['side'] not in ['BUY','SELL']: raise ValueError('Choose buy or sell.')
    for k in ['quantity','price','fees']:
        n = Decimal(out[k] or '0')
        if not n.is_finite() or n < 0 or n > Decimal('1e18') or (k == 'quantity' and n == 0) or n.as_tuple().exponent < -12: raise ValueError(f'Invalid {k}: use a positive quantity and nonnegative prices/fees, with up to 12 decimals.')
        out[k] = str(n)
    if len(out['note']) > 500: raise ValueError('Notes must be at most 500 characters.')
    return out

def calculate(rows):
    positions, annual, realized, history = {}, {}, {}, []
    for raw in sorted(rows, key=lambda t:(t['date'],t['id'])):
        t = dict(raw); key = (t['ticker'], t['currency'])
        p = positions.setdefault(key, {'ticker':key[0], 'currency':key[1], 'quantity':Decimal(0), 'basis':Decimal(0)})
        q, price, fee = (Decimal(t[k]) for k in ['quantity','price','fees'])
        avg = p['basis'] / p['quantity'] if p['quantity'] else Decimal(0)
        gain = None
        total = Decimal(t['_total']) if t.get('_total') is not None else (q*price+fee if t['side']=='BUY' else q*price-fee)
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
    mode=d.get('fx_mode','auto')
    if mode not in ['auto','manual']: raise ValueError('Choose final DKK amount or automatic conversion.')
    normalized=dict(d)
    if mode=='manual':
        normalized['currency']=normalized.get('currency') or 'DKK'
        # Foreign-price fields are optional in final-DKK mode; never fabricate them.
        normalized['price']=normalized.get('price') or '0'
        normalized['fees']=normalized.get('fees') or '0'
    out=validate(normalized)
    broker=str(d.get('broker','')).strip()
    if len(broker)>100: raise ValueError('Broker name must be at most 100 characters.')
    out.update(broker=broker,fx_mode=mode)
    if mode=='manual':
        try: total=Decimal(str(d.get('dkk_total','')))
        except InvalidOperation: raise ValueError('Enter the final amount in DKK.')
        if not total.is_finite() or total<0 or total>Decimal('1e24') or total.as_tuple().exponent < -12: raise ValueError('Enter a nonnegative final DKK amount with at most 12 decimals.')
        out.update(dkk_total=str(total),fx_rate=None,fx_date=None,fx_source='Broker final DKK amount')
        if not d.get('price'): out['price']=''
        if not d.get('fees'): out['fees']=''
    else:
        if str(d.get('price','')).strip()=='': raise ValueError('Enter the original price per share for automatic conversion.')
        if previous and previous.get('fx_mode')=='auto' and previous.get('fx_rate') and previous['date']==out['date'] and previous['currency']==out['currency']:
            quote=dict(rate=previous['fx_rate'],rate_date=previous['fx_date'],source=previous['fx_source'])
        else: quote=fx.lookup(out['currency'],out['date'],c)
        gross=Decimal(out['quantity'])*Decimal(out['price']); fees=Decimal(out['fees'])
        total=(gross+fees if out['side']=='BUY' else gross-fees)*Decimal(quote['rate'])
        out.update(dkk_total=str(total),fx_rate=quote['rate'],fx_date=quote['rate_date'],fx_source=quote['source'])
    return out

def portfolio_report(records):
    converted=[]; missing=[]
    for raw in records:
        t=dict(raw); total=t.get('dkk_total')
        if total is None and t['currency']=='DKK':
            gross=Decimal(t['quantity'])*Decimal(t['price']); fees=Decimal(t['fees'])
            total=str(gross+fees if t['side']=='BUY' else gross-fees)
            t.update(dkk_total=total,fx_mode='auto',fx_rate='1',fx_date=t['date'],fx_source='DKK (no conversion)')
        if total is None: missing.append(t['id'])
        converted.append(dict(t,currency='DKK',price='0',fees='0',_total=total or '0',original=t))
    report=calculate(converted) # All currencies and brokers for a ticker share its DKK cost basis.
    history=[]
    for t in report['transactions']:
        history.append(dict(t['original'],profit=t['profit'] if not missing else None,average=t['average'] if not missing else None,remaining=t['remaining']))
    report['transactions']=history
    report['missing_dkk']=missing
    if missing:
        # Never display incomplete figures as final DKK results.
        report.update(holdings=[],annual=[],realized=[])
    return report


def rows(c): return [dict(r) for r in c.execute('SELECT * FROM transactions ORDER BY date,id')]

class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content='application/json'):
        data = (json.dumps(body, default=str) if content == 'application/json' else body).encode()
        self.send_response(status); self.send_header('Content-Type', content+'; charset=utf-8'); self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/portfolio':
            with connect() as c: self.send(200,portfolio_report(rows(c)))
        elif path == '/api/fx':
            try:
                args=parse_qs(urlparse(self.path).query)
                with connect() as c: quote=fx.lookup(args.get('currency',[''])[0],args.get('date',[''])[0],c)
                self.send(200,quote)
            except ValueError as e: self.send(400,{'error':str(e)})
        elif path == '/api/report':
            with connect() as c: report=portfolio_report(rows(c))
            if report['missing_dkk']: return self.send(400,{'error':'Complete the missing DKK amounts before exporting the report.'})
            year=parse_qs(urlparse(self.path).query).get('year',[''])[0]
            f=io.StringIO(); w=csv.DictWriter(f,fieldnames=['year','ticker','currency','proceeds','cost','profit']); w.writeheader()
            w.writerows(r for r in report['annual'] if not year or r['year']==year)
            self.send(200,f.getvalue(),'text/csv')
        elif path == '/api/export':
            with connect() as c: data = rows(c)
            f=io.StringIO(); w=csv.DictWriter(f,fieldnames=['id','date','ticker','currency','side','quantity','price','fees','note','dkk_total','fx_mode','fx_rate','fx_date','fx_source','broker']); w.writeheader(); w.writerows(data)
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
    print(f'Stock Ledger running at http://127.0.0.1:{port}',flush=True)
    HTTPServer(('127.0.0.1',port),Handler).serve_forever()
