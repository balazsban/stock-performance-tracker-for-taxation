let portfolio, editId=null;
const $=id=>document.getElementById(id), esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(n,d=2)=>Number(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const gain=n=>`<span class="${Number(n)>=0?'positive':'negative'}">${Number(n)>0?'+':''}${num(n)}</span>`;
const empty=(n,s)=>`<tr><td colspan="${n}" class="empty">${s}</td></tr>`;
async function request(path,method='GET',body){const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
function render(){
 $('missing').textContent=portfolio.missing_dkk.length?`${portfolio.missing_dkk.length} existing transaction(s) need a DKK amount or conversion. Edit the entries marked Missing DKK below. Final reports are withheld until all entries are complete.`:'';
 const currencies=[...new Set([...portfolio.holdings,...portfolio.realized].map(x=>x.currency))].sort();
 $('summary').innerHTML=currencies.length?currencies.map(c=>{const basis=portfolio.holdings.filter(x=>x.currency===c).reduce((a,x)=>a+Number(x.basis),0),profit=portfolio.realized.filter(x=>x.currency===c).reduce((a,x)=>a+Number(x.profit),0);return `<div class="card"><div class="label">Current cost basis · ${esc(c)}</div><strong>${num(basis)}</strong><small>Capital in your remaining shares</small></div><div class="card"><div class="label">Realized P/L · ${esc(c)}</div><strong>${gain(profit)}</strong><small>All-time returns after fees</small></div>`}).join(''):'<div class="card"><div class="label">Your portfolio starts here</div><strong>Make your first entry.</strong><small>Add a purchase to start tracking your holdings and returns.</small></div>';
 $('count').textContent=portfolio.missing_dkk.length?'Awaiting DKK amounts':`${portfolio.holdings.length} positions`;
 $('positions').innerHTML=portfolio.holdings.map(x=>`<tr><td>${esc(x.ticker)}</td><td>${esc(x.currency)}</td><td>${num(x.quantity,6)}</td><td>${num(x.average,4)}</td><td>${num(x.basis)}</td></tr>`).join('')||empty(5,'No holdings yet. Add your first purchase above.');
 const selected=$('year').value;
 $('year').innerHTML='<option value="">All years</option>'+[...new Set(portfolio.annual.map(x=>x.year))].sort().reverse().map(y=>`<option>${esc(y)}</option>`).join('');
 if([...$('year').options].some(x=>x.value===selected))$('year').value=selected;
 renderReports();renderHistory();
}
function renderReports(){ $('reportexport').href='/api/report'+($('year').value?'?year='+encodeURIComponent($('year').value):''); $('reportexport').hidden=portfolio.missing_dkk.length>0; const data=portfolio.annual.filter(x=>!$('year').value||x.year===$('year').value).sort((a,b)=>b.year.localeCompare(a.year)||a.ticker.localeCompare(b.ticker));
 $('returns').innerHTML=data.map(x=>`<tr><td>${esc(x.ticker)}</td><td>${esc(x.currency)}</td><td>${x.year}</td><td>${num(x.proceeds)}</td><td>${num(x.cost)}</td><td>${gain(x.profit)}</td></tr>`).join('')||empty(6,'Realized returns will appear when you record a sale.');
 const totals={};for(const x of data)totals[x.currency]=(totals[x.currency]||0)+Number(x.profit);
 const tickers={};for(const x of data){const k=x.ticker+' · '+x.currency;tickers[k]=(tickers[k]||0)+Number(x.profit);}
 $('totals').innerHTML=Object.keys(totals).length?'Period totals: '+Object.entries(totals).map(([c,v])=>`${esc(c)} ${gain(v)}`).join(' &nbsp; / &nbsp; ')+(! $('year').value?'<br>All-time by ticker: '+Object.entries(tickers).map(([c,v])=>`${esc(c)} ${gain(v)}`).join(' &nbsp; / &nbsp; '):''):'';
}
function rateLabel(x){
 if(x.dkk_total===null||x.dkk_total===undefined)return 'Missing DKK — edit this entry';
 if(x.fx_mode==='manual')return 'Broker final amount<small>Fees already included</small>';
 if(x.currency==='DKK')return 'DKK · no conversion';
 return `<a href="https://nationalbanken.statbank.dk/DNVALD" target="_blank" rel="noopener">Nationalbank · ${esc(x.fx_date)}</a><small>1 ${esc(x.currency)} = ${num(x.fx_rate,6)} DKK${x.fx_date!==x.date?' · prior banking day':''}</small>`;
}
function renderHistory(){const data=portfolio.transactions.filter(x=>x.ticker.includes($('search').value.trim().toUpperCase()));$('transactions').innerHTML=data.map(x=>`<tr><td>${esc(x.date)}</td><td title="${esc(x.note)}">${esc(x.ticker)} <small>${esc(x.currency)}</small><small style="display:block;font-weight:400">${esc(x.broker||'')}</small></td><td><span class="badge ${x.side==='SELL'?'sell':''}">${x.side}</span></td><td>${num(x.quantity,6)}</td><td>${x.price===''?'—':num(x.price,4)}</td><td>${x.fees===''?'—':num(x.fees)}</td><td>${x.dkk_total==null?'—':num(x.dkk_total)}</td><td class="source">${rateLabel(x)}</td><td>${x.average===null?'—':num(x.average,4)}</td><td>${x.profit===null?'—':gain(x.profit)}</td><td><button class="secondary" data-edit="${x.id}">Edit</button><button class="secondary" data-delete="${x.id}">Delete</button></td></tr>`).join('')||empty(11,'No transactions to show.');}
let quoteVersion=0;
function formMode(){
 const f=$('form').elements, manual=f.fx_mode.value==='manual';
 document.querySelectorAll('.auto-only').forEach(el=>el.hidden=manual);
 $('dkkfield').hidden=!manual; f.dkk_total.required=manual; f.dkk_total.disabled=!manual;
 f.price.required=!manual; f.price.disabled=manual; f.fees.required=!manual; f.fees.disabled=manual;
 $('dkklab').textContent=f.side.value==='BUY'?'Final DKK amount paid':'Final DKK amount received';
 $('modehint').textContent=manual?'Enter the full amount paid for a buy, or net amount received for a sale, after all fees. Commission is already included: do not add it again. If you only know DKK, leave original currency as DKK.':'Enter the price and fees in the same original currency. Nationalbank’s rate converts the purchase total or net sale proceeds to DKK. If fees use another currency, use a final DKK amount instead.';
}
function openForm(t){editId=t?.id??null;$('form').reset();$('formerror').textContent='';$('quote').textContent='';quoteVersion++;$('formtitle').textContent=t?'Edit transaction':'Add transaction';if(t){for(const k of ['date','ticker','currency','side','quantity','price','fees','note','broker','dkk_total'])$('form').elements[k].value=t[k]??'';$('fxmode').value=t.fx_mode==='manual'?'manual':'auto';if(t.fx_rate)$('quote').textContent=`Saved rate: 1 ${t.currency} = ${t.fx_rate} DKK · ${t.fx_date}. Kept when date and currency are unchanged.`;}else{const d=new Date();$('form').elements.date.value=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}formMode();$('modal').showModal();}
$('fxmode').onchange=()=>{formMode();};$('form').elements.side.onchange=formMode;
$('form').addEventListener('input',()=>{quoteVersion++;$('quote').textContent='';});
$('previewrate').onclick=async()=>{
 const f=$('form').elements, version=++quoteVersion;
 $('quote').textContent='Looking up Nationalbank’s historical rate…';$('previewrate').disabled=true;
 try{
  const previous=portfolio.transactions.find(x=>x.id===editId);
  const q=previous?.fx_mode==='auto'&&previous.fx_rate&&previous.date===f.date.value&&previous.currency===f.currency.value.toUpperCase()?{rate:previous.fx_rate,rate_date:previous.fx_date}:await request('/api/fx?currency='+encodeURIComponent(f.currency.value)+'&date='+encodeURIComponent(f.date.value));
  if(version!==quoteVersion)return;
  const total=(Number(f.quantity.value)*Number(f.price.value)+(f.side.value==='BUY'?1:-1)*Number(f.fees.value))*Number(q.rate);
  $('quote').textContent=`1 ${f.currency.value.toUpperCase()} = ${q.rate} DKK · rate date ${q.rate_date}${q.rate_date!==f.date.value?' (previous banking day)':''}.`+(f.quantity.value&&f.price.value?`\nFinal amount: ${num(total)} DKK. Shown rounded; the full precision is saved.`:'');
 }catch(e){if(version===quoteVersion)$('quote').textContent=e.message;}finally{$('previewrate').disabled=false;}
};
$('add').onclick=()=>openForm();$('close').onclick=()=>$('modal').close();$('year').onchange=renderReports;$('search').oninput=renderHistory;
$('form').onsubmit=async e=>{e.preventDefault();$('save').disabled=true;$('save').textContent='Saving…';try{portfolio=await request('/api/transactions'+(editId?'/'+editId:''),editId?'PUT':'POST',Object.fromEntries(new FormData(e.target)));render();$('modal').close();$('error').textContent='';}catch(e){$('formerror').textContent=e.message;}finally{$('save').disabled=false;$('save').textContent='Save transaction';}};
$('transactions').onclick=async e=>{const edit=e.target.dataset.edit,del=e.target.dataset.delete;if(edit)openForm(portfolio.transactions.find(x=>x.id===Number(edit)));if(del&&confirm('Delete this transaction? The entire history will be recalculated.')){try{portfolio=await request('/api/transactions/'+del,'DELETE');render();$('error').textContent='';}catch(e){$('error').textContent=e.message;}}};
request('/api/portfolio').then(d=>{portfolio=d;render()}).catch(e=>$('error').textContent='Could not load the ledger: '+e.message);
