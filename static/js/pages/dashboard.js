/* VAULT - pages/dashboard.js
   Dashboard page: KPI cards and the SVG charts.
   Loaded by templates/base.html on every screen; all scripts share one global scope (see core/helpers.js). */

/* ---- dashboard: graphs are plain SVG (no library), colours come from the CSS variables so dark mode works ---- */
async function loadDashboard(){
  clearTimeout(dashTimer);
  try{renderDashboard(await api("/api/dashboard"))}catch(e){toast(e.message,{type:"error",title:"Dashboard could not refresh"})}
  dashTimer=setTimeout(()=>{if(!document.hidden)loadDashboard()},30000);
}
$o("#dashRefresh").onclick=loadDashboard;
// Dashboard KPI shortcuts: make key totals useful navigation targets.
$o("#kpis").addEventListener("click",e=>{const card=e.target.closest("[data-go]");if(card)showTab(card.dataset.go)});
const noData=t=>`<div class="nodata">${t}</div>`;
function barChart(days){
  const W=640,H=210,L=30,B=26,T=10,n=days.length,max=Math.max(4,...days.map(d=>d.ok+d.same+d.bad)),bw=(W-L)/n;
  if(!days.some(d=>d.ok+d.same+d.bad))return noData("No backups in the last 14 days");
  let g="";
  for(let i=0;i<=4;i++){const y=T+(H-T-B)*(1-i/4);g+=`<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" class="gl"/><text x="${L-6}" y="${y+4}" class="ax" text-anchor="end">${Math.round(max*i/4)}</text>`}
  days.forEach((d,i)=>{
    const x=L+i*bw+bw*.18,w=bw*.64;let y=H-B;
    [["ok",d.ok],["same",d.same],["bad",d.bad]].forEach(([k,v])=>{if(!v)return;const h=v/max*(H-T-B);y-=h;g+=`<rect x="${x}" y="${y}" width="${w}" height="${h}" class="s-${k}" rx="2"><title>${d.d}: ${v} ${k==="ok"?"saved":k==="same"?"unchanged":"failed"}</title></rect>`});
    if(i%2===0||n<8)g+=`<text x="${x+w/2}" y="${H-8}" class="ax" text-anchor="middle">${d.d.slice(5)}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Backups per day" style="width:100%;height:auto">${g}</svg>`;
}
function donut(st,total){
  if(!total)return noData("No devices yet");
  const parts=[["SUCCESS","Saved","var(--ok)"],["UNCHANGED","Unchanged","var(--info)"],["FAILED","Failed","var(--bad)"],["NONE","Not run","var(--idle)"]];
  const r=52,C=2*Math.PI*r;let off=0,arcs="";
  parts.forEach(([k,,c])=>{const v=st[k];if(!v)return;const len=v/total*C;arcs+=`<circle cx="70" cy="70" r="${r}" fill="none" stroke="${c}" stroke-width="18" stroke-dasharray="${len} ${C-len}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)"/>`;off+=len});
  const done=st.SUCCESS+st.UNCHANGED;
  return `<div class="donut"><svg viewBox="0 0 140 140" width="150" height="150" role="img" aria-label="Backup result per device"><circle cx="70" cy="70" r="${r}" fill="none" stroke="var(--line)" stroke-width="18"/>${arcs}
    <text x="70" y="68" text-anchor="middle" class="dn1">${Math.round(done/total*100)}%</text><text x="70" y="86" text-anchor="middle" class="ax">healthy</text></svg>
    <ul>${parts.map(([k,l,c])=>`<li><i style="background:${c}"></i>${l}<b>${st[k]}</b></li>`).join("")}</ul></div>`;
}
function lineChart(ping){
  if(ping.length<2)return noData("Collecting data. The first points appear after a couple of minutes.");
  const W=640,H=210,L=40,B=26,T=10,n=ping.length,pts=ping.map((p,i)=>[L+i/(n-1)*(W-L-6),T+(H-T-B)*(1-(p.total?p.up/p.total:0))]);
  let g="";
  [0,25,50,75,100].forEach(v=>{const y=T+(H-T-B)*(1-v/100);g+=`<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" class="gl"/><text x="${L-6}" y="${y+4}" class="ax" text-anchor="end">${v}%</text>`});
  const line=pts.map((p,i)=>(i?"L":"M")+p[0].toFixed(1)+" "+p[1].toFixed(1)).join(" ");
  g+=`<path d="${line} L${pts[n-1][0]} ${H-B} L${pts[0][0]} ${H-B}Z" class="area"/><path d="${line}" class="ln" pathLength="1"/>`;
  [0,Math.floor(n/2),n-1].forEach(i=>g+=`<text x="${pts[i][0]}" y="${H-8}" class="ax" text-anchor="${i===0?"start":i===n-1?"end":"middle"}">${bdClock(ping[i].ts)}</text>`);
  pts.forEach((p,i)=>g+=`<circle cx="${p[0]}" cy="${p[1]}" r="6" fill="transparent"><title>${bdClock(ping[i].ts)}: ${ping[i].up}/${ping[i].total} online${ping[i].avg_ms!=null?", avg "+ping[i].avg_ms+" ms":""}</title></circle>`);
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Devices online over 24 hours" style="width:100%;height:auto">${g}</svg>`;
}
let wasRunning=null;
function renderDashboard(d){
  if(wasRunning&&!d.job_running&&!manualJob)sfx.play("done");wasRunning=d.job_running;
  const ok=d.status.SUCCESS+d.status.UNCHANGED,last=d.ping[d.ping.length-1];
  const up24=d.ping.length?(d.ping.reduce((a,p)=>a+(p.total?p.up/p.total:0),0)/d.ping.length*100).toFixed(1)+"%":"-";
  const completed=Math.min(d.total, d.status.SUCCESS+d.status.UNCHANGED);
  const notCompleted=Math.max(0, d.total-completed);
  const failed=d.status.FAILED||0, neverRun=d.status.NONE||0;
  setHTML("#kpis",`<button type="button" class="kpi kpi-link" data-go="devices" aria-label="View all devices"><span class="kpi-top"><small>Total devices</small><span class="kpi-arrow" aria-hidden="true">↗</span></span><strong>${d.total}</strong><span class="d">All configured devices</span></button>
   <div class="kpi"><small>Online (last check)</small><strong class="g">${last?last.up+" / "+last.total:"-"}</strong><span class="d">Reachable by ping</span></div>
   <div class="kpi"><small>Uptime, 24 h</small><strong>${up24}</strong><span class="d">Average monitored availability</span></div>
   <button type="button" class="kpi kpi-link kpi-link-success" data-go="backups" aria-label="View backups"><span class="kpi-top"><small>Backup completed</small><span class="kpi-arrow" aria-hidden="true">↗</span></span><strong class="g">${completed} / ${d.total}</strong><span class="d">Saved or unchanged</span></button>
   <div class="kpi"><small>Backup not completed</small><strong class="${notCompleted?"r":"g"}">${notCompleted}</strong><span class="d">${failed} failed · ${neverRun} not run</span></div>
   <div class="kpi"><small>Auto backup</small><strong class="sm2">${d.job_running?"Running now":d.sched_on?"Next: "+esc(fmtBdDateTime(d.next_run)):"Off"}</strong><span class="d">Scheduled status</span></div>`);
  setHTML("#chDays",barChart(d.days));
  setHTML("#chDonut",donut(d.status,d.total));
  setHTML("#chUp",lineChart(d.ping));
  $("#upSub").textContent=d.ping_seconds?`Last 24 hours, checked every ${d.ping_seconds} s in the background`:"Background ping monitor is off";
  const mx=Math.max(1,...d.vendors.map(v=>v[1]));
  setHTML("#chVendor",d.vendors.length?`<div class="hb">`+d.vendors.map(([n,c])=>`<div><span>${esc(n)}</span><div class="bar2"><i class="v-${slug(n)}" style="width:${c/mx*100}%"></i></div><b>${c}</b></div>`).join("")+`</div>`:noData("No devices yet"));
  const h=d.health||{},disk=h.disk||{};
  const fmtBytes=n=>{n=Number(n||0);if(n<1024)return n+" B";const u=["KB","MB","GB","TB"];let i=-1;do{n/=1024;i++}while(n>=1024&&i<u.length-1);return n.toFixed(1)+" "+u[i]};
  const diskLabel=disk.status==="critical"?"Critical":disk.status==="warning"?"Low space":disk.status==="ok"?"Healthy":"Unknown";
  const diskClass=disk.status==="critical"?"r":disk.status==="warning"?"sm2":"g";
  setHTML("#systemHealth",`<div class="kpi"><small>Disk status</small><strong class="${diskClass}">${esc(diskLabel)}</strong><span class="d">${disk.free_bytes?esc(fmtBytes(disk.free_bytes))+" free of "+esc(fmtBytes(disk.total_bytes)):"Could not read disk capacity"}</span></div>
   <div class="kpi"><small>Disk used</small><strong>${disk.used_percent==null?"-":esc(disk.used_percent)+"%"}</strong><span class="d">Warning below 15% free; critical below 5% or 2 GB</span></div>
   <div class="kpi"><small>Database size</small><strong>${h.database_bytes==null?"Unavailable":esc(fmtBytes(h.database_bytes))}</strong><span class="d">${esc(h.database_engine||"Database")}${h.database_name?" · "+esc(h.database_name):""} (data + indexes)</span></div>
   <div class="kpi"><small>Backup storage</small><strong class="${h.backup_dir_exists?"g":"r"}">${h.backup_dir_exists?"Available":"Missing"}</strong><span class="d">Configured backup directory</span></div>
   <div class="kpi"><small>Last successful backup</small><strong class="sm2">${esc(h.last_success&&h.last_success!=="Never"?fmtBdDateTime(h.last_success):"Never")}</strong><span class="d">Saved or unchanged</span></div>
   <div class="kpi"><small>Failures, last 24 h</small><strong class="${h.failed_24h?"r":"g"}">${Number(h.failed_24h||0)}</strong><span class="d">From backup logs</span></div>`);
  /* charts animate in on the first draw only; later 30-second refreshes update quietly (see app.css "Motion") */
  if(!renderDashboard.drawn){renderDashboard.drawn=true;setTimeout(()=>$("#dashboard").classList.add("charts-ready"),1600)}
}
