"""Official DNVALD/KBH quotes: DKK per 100 foreign currency units."""
import csv, io, json, re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.error import URLError
SOURCE = 'https://nationalbanken.statbank.dk/DNVALD'

def fetch(url, payload=None):
    req = Request(url, data=json.dumps(payload).encode() if payload else None,
                  headers={'Content-Type':'application/json','User-Agent':'LocalStockLedger/1.0'})
    try:
        with urlopen(req, timeout=20) as response: return response.read().decode('utf-8-sig')
    except (URLError, TimeoutError, OSError) as e:
        raise ValueError('Nationalbank rates are unavailable. Try again later or enter your broker’s final DKK amount.') from e

def easter(y):
    a=y%19; b=y//100; c=y%100; d=b//4; e=b%4; f=(b+8)//25; g=(b-f+1)//3
    h=(19*a+b-d-g+15)%30; i=c//4; k=c%4; l=(32+2*e+2*i-h-k)%7; m=(a+11*h+22*l)//451
    return date(y,(h+l-7*m+114)//31,(h+l-7*m+114)%31+1)

def closed(day):
    fixed={(1,1),(5,1),(6,5),(12,24),(12,25),(12,26),(12,31)}
    offsets=[-3,-2,1,39,40,50]+([26] if day.year<2024 else [])
    return day.weekday()>4 or (day.month,day.day) in fixed or day in {easter(day.year)+timedelta(days=n) for n in offsets}

def lookup(currency, trade_date, c):
    currency=currency.upper(); day=date.fromisoformat(trade_date)
    if day>date.today(): raise ValueError('Historical rates are unavailable for future dates.')
    if not re.fullmatch('[A-Z]{3}',currency): raise ValueError('Use a three-letter currency code.')
    if currency=='DKK': return dict(rate='1',rate_date=trade_date,source='DKK (no conversion)',currency=currency,trade_date=trade_date)
    cached=c.execute('SELECT rate,rate_date,source FROM fx_cache WHERE currency=? AND trade_date=?',(currency,trade_date)).fetchone()
    if cached: return dict(cached,currency=currency,trade_date=trade_date)
    try:
        info=json.loads(fetch('https://api.statbank.dk/v1/tableinfo/DNVALD?format=JSON&lang=en'))
        variables={v['id'].upper():v['values'] for v in info['variables']}
        if currency not in {v['id'] for v in variables['VALUTA']}: raise ValueError('Currency is not supported by Nationalbank. Enter a final DKK amount instead.')
        dates=sorted(date.fromisoformat(v['id'].replace('M','-').replace('D','-')) for v in variables['TID'])
        expected=day
        while closed(expected): expected-=timedelta(days=1)
        if expected>dates[-1]: raise ValueError('The rate for this banking day has not been published in StatBank yet (normally available the next banking morning). Try later or enter a final DKK amount.')
        candidates=[d for d in dates if d<=day]
        if not candidates or (day-candidates[-1]).days>10: raise ValueError('No recent historical rate is available for this date.')
        effective=candidates[-1]; period=effective.strftime('%YM%mD%d')
        payload={'table':'DNVALD','format':'CSV','lang':'en','valuePresentation':'Code','variables':[{'code':'VALUTA','values':[currency]},{'code':'KURTYP','values':['KBH']},{'code':'Tid','values':[period]}]}
        records=list(csv.DictReader(io.StringIO(fetch('https://api.statbank.dk/v1/data',payload)),delimiter=';'))
        record=next(r for r in records if r['VALUTA']==currency and r['KURTYP']=='KBH' and r['TID']==period)
        rate=Decimal(record['INDHOLD'].replace(',','.'))/100
        if not rate.is_finite() or rate<=0: raise ValueError('No valid rate is available for this currency and date. Enter a final DKK amount.')
    except (KeyError,StopIteration,InvalidOperation,json.JSONDecodeError) as e:
        raise ValueError('Nationalbank returned no usable rate for this date/currency. Enter a final DKK amount or try later.') from e
    result=dict(rate=str(rate),rate_date=effective.isoformat(),source=SOURCE,currency=currency,trade_date=trade_date)
    c.execute('INSERT OR IGNORE INTO fx_cache VALUES (?,?,?,?,?)',(currency,trade_date,result['rate_date'],result['rate'],SOURCE))
    return result
