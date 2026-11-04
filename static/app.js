let portfolio, editId=null;
const $=id=>document.getElementById(id), esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(n,d=2)=>Number(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const gain=n=>`<span class="${Number(n)>=0?'positive':'negative'}">${Number(n)>0?'+':''}${num(n)}</span>`;
const empty=(n,s)=>`<tr><td colspan="${n}" class="empty">${s}</td></tr>`;
async function request(path,method='GET',body){const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
function render(){
 $('symbols').innerHTML=[...new Set(portfolio.transactions.map(t=>t.ticker))].sort().map(t=>`<option value="${esc(t)}"></option>`).join('');
 $('missing').textContent=portfolio.missing_dkk.length?`${portfolio.missing_dkk.length} existing transaction(s) need a DKK amount. Edit the entries marked Missing DKK below. Final reports are withheld until all entries are complete.`:'';
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
function renderHistory(){const data=portfolio.transactions.filter(x=>x.ticker.includes($('search').value.trim().toUpperCase()));$('transactions').innerHTML=data.map(x=>`<tr><td>${esc(x.date)}</td><td title="${esc(x.note)}">${esc(x.ticker)}<small style="display:block;font-weight:400">${esc(x.broker||'')}</small></td><td><span class="badge ${x.side==='SELL'?'sell':''}">${x.side}</span></td><td>${num(x.quantity,6)}</td><td>${x.dkk_total==null?'Missing DKK':num(x.dkk_total)}</td><td>${x.average===null?'—':num(x.average,4)}</td><td>${x.profit===null?'—':gain(x.profit)}</td><td><button class="secondary" data-order="${x.id}" ${portfolio.transactions.filter(t=>t.date===x.date&&t.ticker===x.ticker).length<2?'disabled':''}>Order day</button><button class="secondary" data-edit="${x.id}">Edit</button><button class="secondary" data-delete="${x.id}">Delete</button></td></tr>`).join('')||empty(8,'No transactions to show.');}
function formMode(){
 $('dkklab').textContent=$('form').elements.side.value==='BUY'?'Final DKK amount paid (including fees)':'Net DKK amount received (after fees)';
}
function openForm(t){
 editId=t?.id??null;$('form').reset();$('formerror').textContent='';$('formtitle').textContent=t?'Edit transaction':'Add transaction';
 if(t){for(const k of ['date','ticker','side','quantity','note','broker','dkk_total'])$('form').elements[k].value=t[k]??'';}
 else{const d=new Date();$('form').elements.date.value=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
 formMode();$('modal').showModal();
}
$('form').elements.side.onchange=formMode;
$('add').onclick=()=>openForm();$('close').onclick=()=>$('modal').close();$('year').onchange=renderReports;$('search').oninput=renderHistory;
$('form').onsubmit=async e=>{e.preventDefault();$('save').disabled=true;$('save').textContent='Saving…';try{portfolio=await request('/api/transactions'+(editId?'/'+editId:''),editId?'PUT':'POST',Object.fromEntries(new FormData(e.target)));render();$('modal').close();$('error').textContent='';}catch(e){$('formerror').textContent=e.message;}finally{$('save').disabled=false;$('save').textContent='Save transaction';}};
$('transactions').onclick=async e=>{const edit=e.target.dataset.edit,del=e.target.dataset.delete,order=e.target.dataset.order;if(order)openOrder(Number(order));if(edit)openForm(portfolio.transactions.find(x=>x.id===Number(edit)));if(del&&confirm('Delete this transaction? The entire history will be recalculated.')){try{portfolio=await request('/api/transactions/'+del,'DELETE');render();$('error').textContent='';}catch(e){$('error').textContent=e.message;}}};
request('/api/portfolio').then(d=>{portfolio=d;render()}).catch(e=>$('error').textContent='Could not load the ledger: '+e.message);

let orderedTrades=[], originalOrder=[], orderGroup=null;
function openOrder(id){
 const trade=portfolio.transactions.find(t=>t.id===id);
 orderGroup={date:trade.date,ticker:trade.ticker};
 orderedTrades=portfolio.transactions.filter(t=>t.date===trade.date&&t.ticker===trade.ticker).sort((a,b)=>(a.sort_order??a.id)-(b.sort_order??b.id)||a.id-b.id);
 originalOrder=orderedTrades.map(t=>t.id);
 $('ordertitle').textContent=`${trade.ticker} · ${trade.date}`;
 $('ordererror').textContent='';renderOrder();$('ordermodal').showModal();
}
function renderOrder(){
 $('orderlist').innerHTML=orderedTrades.map((t,i)=>`<li><span><b>${i+1}. ${esc(t.side)} ${num(t.quantity,6)} shares</b><small>${t.dkk_total==null?'Missing DKK':num(t.dkk_total)+' DKK'} · ${esc(t.broker||'No broker')} · Trade #${t.id}</small></span><span><button class="secondary" data-position="${i}" data-step="-1" aria-label="Move trade ${t.id} earlier" ${i===0?'disabled':''}>↑ Earlier</button><button class="secondary" data-position="${i}" data-step="1" aria-label="Move trade ${t.id} later" ${i===orderedTrades.length-1?'disabled':''}>↓ Later</button></span></li>`).join('');
}
$('orderlist').onclick=e=>{if(e.target.dataset.position===undefined)return;const i=Number(e.target.dataset.position),j=i+Number(e.target.dataset.step);if(j<0||j>=orderedTrades.length)return;[orderedTrades[i],orderedTrades[j]]=[orderedTrades[j],orderedTrades[i]];renderOrder();$('ordererror').textContent='';};
$('orderclose').onclick=()=>$('ordermodal').close();
$('ordersave').onclick=async()=>{
 $('ordersave').disabled=true;$('orderclose').disabled=true;$('orderlist').inert=true;
 try{portfolio=await request('/api/transactions/reorder','POST',{...orderGroup,ids:orderedTrades.map(t=>t.id),expected_ids:originalOrder});render();$('ordermodal').close();$('error').textContent='';}
 catch(e){$('ordererror').textContent=e.message;}
 finally{$('ordersave').disabled=false;$('orderclose').disabled=false;$('orderlist').inert=false;}
};
