/* VAULT - pages/reports.js
   Change Reports page (/reports): what changed on each device in a chosen month range.
   Data: /api/reports/changes?from=YYYY-MM&to=YYYY-MM (apps/backups/reports.py). Uses diffFile() / viewFile() from backups.js
   to open the changes, and paginate() / morph() from helpers.js.
   Loaded by templates/base.html on every screen; all scripts share one global scope (see core/helpers.js). */

let repData=null;
/* month range "YYYY-MM": defaults to the last three months (two months ago -> this month), remembered in this browser */
const ym=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`;
const MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
(()=>{
  const now=new Date(),thisMonth=ym(now),start=ym(new Date(now.getFullYear(),now.getMonth()-2,1));
  let from=start,to=thisMonth;
  try{const s=JSON.parse(localStorage.getItem("dbms_report_range")||"null");if(s&&/^\d{4}-\d{2}$/.test(s.from)&&/^\d{4}-\d{2}$/.test(s.to)){from=s.from;to=s.to}}catch(e){}
  if(!$("#repFrom"))return;      /* not the Change Reports screen */
  setMonth($("#repFrom"),from);setMonth($("#repTo"),to);
})();

/* ---- month calendar: a year header with arrows and a 12-month grid; the chosen range is highlighted ---- */
function setMonth(input,v){input.dataset.v=v;const [y,m]=v.split("-").map(Number);input.value=`${MONTHS[m-1]} ${y}`}
function getMonth(input){return input.dataset.v||""}
const mcal=document.createElement("div");
mcal.className="mcal";mcal.hidden=true;mcal.setAttribute("role","dialog");mcal.setAttribute("aria-label","Choose a month");
document.body.append(mcal);
let mcalFor=null,mcalYear=0;
function openMcal(input){
  mcalFor=input;mcalYear=+(getMonth(input)||ym(new Date())).slice(0,4);drawMcal();mcal.hidden=false;
  const r=input.getBoundingClientRect(),w=mcal.offsetWidth,h=mcal.offsetHeight;
  mcal.style.left=Math.max(8,Math.min(r.left,innerWidth-w-8))+"px";
  mcal.style.top=(r.bottom+6+h<=innerHeight?r.bottom+6:Math.max(8,r.top-h-6))+"px";
  mcal.querySelector(".on,button.m:not(:disabled)")?.focus();
}
function drawMcal(){
  const now=ym(new Date()),from=getMonth($("#repFrom")),to=getMonth($("#repTo")),cur=getMonth(mcalFor);
  const isFrom=mcalFor.id==="repFrom";
  mcal.innerHTML=`<div class="mcal-h"><button type="button" class="mcal-nav" data-y="-1" aria-label="Previous year">‹</button><b>${mcalYear}</b>
    <button type="button" class="mcal-nav" data-y="1" aria-label="Next year"${mcalYear>=+now.slice(0,4)?" disabled":""}>›</button></div>
    <p class="mcal-t">${isFrom?"Start of the report":"End of the report"}</p>
    <div class="mcal-g">${MONTHS.map((n,i)=>{const v=`${mcalYear}-${String(i+1).padStart(2,"0")}`;
      const cls=[v===cur?"on":"",from&&to&&v>=from&&v<=to?"in":"",v===now?"now":""].join(" ");
      return `<button type="button" class="m ${cls}" data-v="${v}"${v>now?" disabled":""} aria-pressed="${v===cur}">${n}</button>`}).join("")}</div>
    <div class="mcal-f"><button type="button" class="link" data-v="${now}">This month</button><button type="button" class="link" data-close>Close</button></div>`;
}
function closeMcal(){mcal.hidden=true;if(mcalFor)mcalFor.focus();mcalFor=null}
mcal.addEventListener("click",e=>{
  const nav=e.target.closest("[data-y]");if(nav){mcalYear+=+nav.dataset.y;drawMcal();return}
  if(e.target.closest("[data-close]"))return closeMcal();
  const b=e.target.closest("[data-v]");if(!b||b.disabled)return;
  const v=b.dataset.v,f=$("#repFrom"),t=$("#repTo");
  setMonth(mcalFor,v);
  if(mcalFor===f&&getMonth(t)<v)setMonth(t,v);          /* keep the range in order */
  if(mcalFor===t&&getMonth(f)>v)setMonth(f,v);
  closeMcal();
});
["#repFrom","#repTo"].forEach(s=>{const el=$(s);if(!el)return;
  el.addEventListener("click",()=>mcal.hidden||mcalFor!==el?openMcal(el):closeMcal());
  el.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "||e.key==="ArrowDown"){e.preventDefault();openMcal(el)}});
});
document.addEventListener("click",e=>{if(!mcal.hidden&&!mcal.contains(e.target)&&!e.target.closest(".mpick"))closeMcal()});
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!mcal.hidden)closeMcal()});
addEventListener("resize",()=>{if(!mcal.hidden)closeMcal()});
const repPeriodText=()=>repData?`${fmtBdDateTime(repData.from).split(",")[0]} – ${fmtBdDateTime(repData.to).split(",")[0]}`:"";

async function loadReport(){
  const from=getMonth($("#repFrom")),to=getMonth($("#repTo"));
  if(!/^\d{4}-\d{2}$/.test(from)||!/^\d{4}-\d{2}$/.test(to))
    return toast("Pick both months, for example 2026-01 to 2026-03.",{type:"warning",title:"Choose a month range"});
  if(from>to)return toast("The From month must be the same as or before the To month.",{type:"warning",title:"Month range is reversed"});
  try{localStorage.setItem("dbms_report_range",JSON.stringify({from,to}))}catch(e){}
  if(!repData)$("#repList").innerHTML='<div class="loading-block"><span class="spin"></span>Building the change report…</div>';
  try{repData=await api(`/api/reports/changes?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);renderReport()}
  catch(e){repData=null;$("#repKpis").innerHTML="";$("#repRange").textContent="";$("#repList").innerHTML=errorState("Could not build the change report",e)}
}
$o("#repForm").onsubmit=e=>{e.preventDefault();PAGES.reports=1;loadReport()};
$o("#repRefresh").onclick=loadReport;
$o("#repQ").oninput=$o("#repOnly").onchange=()=>{PAGES.reports=1;renderReport()};

function repVisible(){
  if(!repData)return [];
  const q=$("#repQ").value.trim().toLowerCase(),only=$("#repOnly").checked;
  return repData.devices.filter(r=>(!only||r.changes)&&(!q||`${r.device} ${r.ip}`.toLowerCase().includes(q)));
}
const fmtNum=n=>Number(n||0).toLocaleString("en-US");

function renderReport(){
  if(!repData)return;
  const s=repData.summary,list=repVisible();
  $("#repRange").innerHTML=`Showing changes from <b>${esc(fmtBdDateTime(repData.from).split(",")[0])}</b> to <b>${esc(fmtBdDateTime(repData.to).split(",")[0])}</b>. Only configurations that changed are saved, so every version below is one real change.`;
  morph($("#repKpis"),
    `<div class="kpi"><small>Devices checked</small><strong>${fmtNum(s.devices)}</strong><span class="d">With at least one saved backup</span></div>
     <div class="kpi"><small>Devices changed</small><strong class="${s.changed?"w":"g"}">${fmtNum(s.changed)}</strong><span class="d">${fmtNum(s.unchanged)} without any change</span></div>
     <div class="kpi"><small>Configuration changes</small><strong>${fmtNum(s.changes)}</strong><span class="d">Saved versions in the period</span></div>
     <div class="kpi"><small>Lines added</small><strong class="g">+${fmtNum(s.added)}</strong><span class="d">Across all changes</span></div>
     <div class="kpi"><small>Lines removed</small><strong class="r">−${fmtNum(s.removed)}</strong><span class="d">Across all changes</span></div>`);
  $("#repCount").textContent=`${list.length} of ${repData.devices.length} devices`;
  if(!list.length){
    $("#repList").innerHTML=`<div class="empty"><b>${repData.devices.length?(s.changed?"No matching devices":"No configuration changes in this period"):"No backups yet"}</b>${repData.devices.length?(s.changed?"Try another search.":`None of the ${repData.devices.length} devices changed between ${esc(repPeriodText())}. Untick "Only devices with changes" to list them all.`):"Run a backup first; changes appear here once a device's configuration is saved twice."}</div>`;
    return;
  }
  const {rows,bar}=paginate("reports",list);
  const open=new Set([...document.querySelectorAll("#repList details[open]")].map(d=>d.dataset.dev));
  morph($("#repList"),rows.map(r=>repCard(r,open.has(r.device))).join("")+bar);
}

function repCard(r,isOpen){
  const total=r.added+r.removed||1,addPct=Math.round(r.added/total*100);
  const status=r.changes?`<span class="rep-badge chg">${r.changes} change${r.changes===1?"":"s"}</span>`:
    (r.first_backup_in_period?'<span class="rep-badge new">First backup in period</span>':'<span class="rep-badge same">No change</span>');
  const compare=r.changes&&r.baseline?`<button type="button" class="b" data-rep-diff data-d="${esc(r.device)}" data-a="${esc(r.baseline)}" data-b="${esc(r.latest)}">Compare start → now</button>`:"";
  const tl=r.timeline.map(c=>`<li class="${c.first?"first":""}">
      <div class="rep-when"><b>${esc(fmtBdDateTime(c.time).split(", ")[0])}</b><span>${esc(bdClock(c.time))}</span></div>
      <div class="rep-what">${c.first?`<p class="rep-note">First saved configuration in this period (${fmtNum(c.added)} lines). There is no earlier version to compare with.</p>`:
        `<p class="rep-delta"><span class="plus">+${fmtNum(c.added)} added</span><span class="minus">−${fmtNum(c.removed)} removed</span></p>`+
        (c.preview.length?`<pre class="rep-prev">${c.preview.map(l=>`<span class="l ${l[0]==="+"?"a":"r"}">${esc(l)}</span>`).join("")}</pre>`:`<p class="rep-note">${repData.preview_hidden?"The changed lines are shown to Operators and Administrators only.":"Only formatting or volatile lines changed."}</p>`)}</div>
      <div class="rep-act">${c.first?`<button type="button" class="link" data-rep-view data-d="${esc(r.device)}" data-f="${esc(c.file)}">View</button>`:
        `<button type="button" class="link" data-rep-diff data-d="${esc(r.device)}" data-a="${esc(c.prev)}" data-b="${esc(c.file)}">Full diff</button>`}</div></li>`).join("");
  return `<details class="rep-card${r.changes?" has-chg":""}" data-dev="${esc(r.device)}"${isOpen?" open":""}>
    <summary>
      <span class="rep-dev"><b>${esc(r.device)}</b><small>${esc(r.ip||"Not in the device list")}${r.type?" · "+esc(vInfo(r.type).group||r.type):""}</small></span>
      ${status}
      <span class="rep-bar" title="+${r.added} / −${r.removed} lines"><i class="plus" style="width:${r.changes?addPct:0}%"></i><i class="minus" style="width:${r.changes?100-addPct:0}%"></i></span>
      <span class="rep-lines"><span class="plus">+${fmtNum(r.added)}</span><span class="minus">−${fmtNum(r.removed)}</span></span>
      <span class="rep-last">${r.last_change?`Last change<br> <b>${esc(fmtBdDateTime(r.last_change).split(", ")[0])}</b>`:"No change"}</span>
      <svg class="rep-chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
    </summary>
    <div class="rep-body">
      ${r.timeline.length?`<div class="rep-head"><span>Changes, newest first</span>${compare}</div><ol class="rep-tl">${tl}</ol>`:
        `<p class="rep-note">No configuration was saved for this device between ${esc(repPeriodText())}; its configuration stayed the same. Latest saved version: <code>${esc(r.latest)}</code></p>`}
    </div></details>`;
}

$o("#repList").addEventListener("click",e=>{
  const d=e.target.closest("[data-rep-diff]");if(d){e.preventDefault();diffFile(d.dataset.d,d.dataset.a,d.dataset.b);return}
  const v=e.target.closest("[data-rep-view]");if(v){e.preventDefault();viewFile(v.dataset.d,v.dataset.f)}
});

$o("#repExport").onclick=()=>{
  if(!repData)return toast("Load the report first, then export it.",{type:"warning",title:"Nothing to export"});
  const cols=["Device","IP","Type","Period","From","To","Changes","Lines added","Lines removed","Last change","Change time","Change +","Change -","Changed lines (preview)"];
  const q=csvCell;
  const out=[cols.map(q).join(",")];
  repVisible().forEach(r=>{
    const base=[r.device,r.ip,r.type,repPeriodText(),repData.from,repData.to,r.changes,r.added,r.removed,r.last_change];
    const real=r.timeline.filter(c=>!c.first);
    if(!real.length)out.push([...base,"","","",""].map(q).join(","));
    real.forEach(c=>out.push([...base,c.time,c.added,c.removed,c.preview.join(" | ")].map(q).join(",")));
  });
  const a=document.createElement("a");a.href=URL.createObjectURL(new Blob(["﻿",out.join("\r\n")],{type:"text/csv;charset=utf-8"}));
  a.download=`dbms-change-report-${repData.from}_to_${repData.to}.csv`;document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),4000);
  toast("The CSV has one row per configuration change.",{type:"info",title:"Report exported"});
};

/* ---- Export PDF: a clean, print-quality report in a new window, saved with the browser's "Save as PDF".
   No PDF library or server change is needed, and the content follows the current month range, search
   and "Only devices with changes" filter (all matching devices, not just the current page). ---- */
let repPdfHtml="";     /* the last generated PDF document (kept for checking the layout) */
$o("#repPdf").onclick=()=>{
  if(!repData)return toast("Load the report first, then export it.",{type:"warning",title:"Nothing to export"});
  const rows=repVisible(),s=repData.summary,period=repPeriodText();
  const who=(typeof ME!=="undefined"&&ME&&(ME.username||ME.name))||"";
  const now=new Date(),stamp=now.toLocaleString("en-GB",{timeZone:"Asia/Dhaka",day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"});
  const n=v=>Number(v||0).toLocaleString("en-US");
  const day=t=>esc(fmtBdDateTime(t).split(", ")[0]);
  const table=rows.map((r,i)=>`<tr><td>${i+1}</td><td><b>${esc(r.device)}</b></td><td class="m">${esc(r.ip||"-")}</td><td>${esc(r.type?(vInfo(r.type).group||r.type):"-")}</td>
    <td class="c">${r.changes?`<span class="chg">${r.changes}</span>`:'<span class="none">0</span>'}</td><td class="c add">+${n(r.added)}</td><td class="c del">−${n(r.removed)}</td><td>${r.last_change?day(r.last_change):"No change"}</td></tr>`).join("");
  const details=rows.filter(r=>r.changes).map(r=>`<section class="dev"><h3>${esc(r.device)} <small>${esc(r.ip||"")}${r.type?" · "+esc(vInfo(r.type).group||r.type):""}</small></h3>
    <p class="meta">${r.changes} change${r.changes===1?"":"s"} · <span class="add">+${n(r.added)}</span> / <span class="del">−${n(r.removed)}</span> lines${r.baseline?` · compared with the version saved before the period (${esc(r.baseline.split("/").pop())})`:""}</p>
    ${r.timeline.filter(c=>!c.first).map(c=>`<div class="chgrow"><div class="when"><b>${day(c.time)}</b><span>${esc(bdClock(c.time))}</span></div>
      <div class="what"><p class="delta"><span class="add">+${n(c.added)} added</span> <span class="del">−${n(c.removed)} removed</span></p>
      ${c.preview.length?`<pre>${c.preview.map(l=>`<span class="${l[0]==="+"?"a":"r"}">${esc(l)}</span>`).join("\n")}</pre>${c.added+c.removed>c.preview.length?`<p class="more">… ${n(c.added+c.removed-c.preview.length)} more changed line(s); see the full comparison in the application.</p>`:""}`:`<p class="more">${repData.preview_hidden?"The changed lines are shown to Operators and Administrators only.":"Only formatting or volatile lines changed."}</p>`}</div></div>`).join("")}</section>`).join("");
  const html=`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Configuration Change Report ${esc(repData.from)} to ${esc(repData.to)}</title><style>
    @page{size:A4;margin:16mm 14mm 18mm}
    @page{@bottom-right{content:"Page " counter(page) " of " counter(pages);font:9px Arial,sans-serif;color:#64748b}@bottom-left{content:"VAULT - Configuration Change Report";font:9px Arial,sans-serif;color:#64748b}}
    *{box-sizing:border-box}body{margin:0;font:11px/1.45 "Segoe UI",Arial,sans-serif;color:#0f1b2d;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    .bar{height:6px;background:linear-gradient(90deg,#2f5bea,#0ea5c6);border-radius:3px;margin-bottom:14px}
    header{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;padding-bottom:10px;border-bottom:1px solid #d8e0ec;margin-bottom:14px}
    h1{margin:0;font-size:20px;letter-spacing:-.02em}header p{margin:3px 0 0;color:#5b6b82}
    .ids{text-align:right;color:#5b6b82;font-size:10px;line-height:1.6}.ids b{color:#0f1b2d}
    .kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:16px}
    .kpi{border:1px solid #d8e0ec;border-top:3px solid #2f5bea;border-radius:6px;padding:7px 9px}.kpi small{display:block;color:#5b6b82;font-size:9.5px}.kpi b{font-size:16px}
    .kpi:nth-child(2){border-top-color:#8b5cf6}.kpi:nth-child(3){border-top-color:#0ea5c6}.kpi:nth-child(4){border-top-color:#0e9566}.kpi:nth-child(5){border-top-color:#d63447}
    h2{font-size:13px;margin:18px 0 8px;padding-bottom:4px;border-bottom:2px solid #2f5bea;color:#1e3a8a}
    table{width:100%;border-collapse:collapse;font-size:10.5px}th{background:#eef2f9;color:#334155;text-align:left;font-weight:700;padding:6px 7px;border-bottom:1px solid #cfd8e6}
    td{padding:5px 7px;border-bottom:1px solid #e6ebf3;vertical-align:top}tr{break-inside:avoid}tbody tr:nth-child(even) td{background:#f8fafc}
    .m{font-family:Consolas,monospace}.c{text-align:center}.add{color:#0e9566;font-weight:700}.del{color:#d63447;font-weight:700}
    .chg{display:inline-block;min-width:20px;padding:1px 6px;border-radius:9px;background:#ede9fe;color:#6d28d9;font-weight:700}.none{color:#94a3b8}
    .dev{break-inside:avoid-page;margin:0 0 12px;padding:9px 11px;border:1px solid #d8e0ec;border-left:4px solid #8b5cf6;border-radius:6px}
    .dev h3{margin:0;font-size:12.5px}.dev h3 small{font-weight:400;color:#5b6b82;font-family:Consolas,monospace}.meta{margin:2px 0 6px;color:#5b6b82}
    .chgrow{display:grid;grid-template-columns:82px 1fr;gap:10px;padding:6px 0;border-top:1px dashed #d8e0ec;break-inside:avoid}
    .when b{display:block}.when span{color:#5b6b82;font-size:10px}.delta{margin:0 0 4px}
    pre{margin:0;padding:5px 8px;background:#0b1222;color:#d4deec;border-radius:4px;font:9.5px/1.5 Consolas,monospace;white-space:pre-wrap;word-break:break-word}
    pre .a{color:#7be0a8}pre .r{color:#ff9aa2}.more{margin:3px 0 0;color:#5b6b82;font-size:9.5px}
    .note{margin-top:16px;padding:8px 10px;border-radius:6px;background:#f1f5fb;color:#475569;font-size:9.5px}
    @media screen{body{max-width:900px;margin:24px auto;padding:0 20px}.tip{position:sticky;top:0;margin:-24px -20px 16px;padding:10px 20px;background:#0f1a30;color:#e7eefc;font-size:12px}}
    @media print{.tip{display:none}}
  </style></head><body>
  <div class="tip">To save as PDF: in the print window choose <b>Destination: Save as PDF</b>, then Save.</div>
  <div class="bar"></div>
  <header><div><h1>Configuration Change Report</h1><p>VAULT · ${esc(period)}</p></div>
    <div class="ids">Generated <b>${esc(stamp)}</b> (Bangladesh time)${who?`<br>By <b>${esc(who)}</b>`:""}<br>Devices in report <b>${n(rows.length)}</b>${$("#repQ").value.trim()?`<br>Search “${esc($("#repQ").value.trim())}”`:""}</div></header>
  <div class="kpis"><div class="kpi"><small>Devices checked</small><b>${n(s.devices)}</b></div><div class="kpi"><small>Devices changed</small><b>${n(s.changed)}</b></div>
    <div class="kpi"><small>Configuration changes</small><b>${n(s.changes)}</b></div><div class="kpi"><small>Lines added</small><b class="add">+${n(s.added)}</b></div><div class="kpi"><small>Lines removed</small><b class="del">−${n(s.removed)}</b></div></div>
  <h2>Summary by device</h2>
  ${rows.length?`<table><thead><tr><th>#</th><th>Device</th><th>IP address</th><th>Vendor</th><th class="c">Changes</th><th class="c">Added</th><th class="c">Removed</th><th>Last change</th></tr></thead><tbody>${table}</tbody></table>`:"<p>No devices match the current filters.</p>"}
  ${details?`<h2>Change details</h2>${details}`:`<p class="note">No configuration changes were recorded for these devices between ${esc(period)}.</p>`}
  <p class="note">Only configurations that changed are saved, so every entry is one real change. Timestamps and other volatile lines (for example the IOS XR clock line) are ignored. Up to 8 changed lines are shown per change; the full comparison is available in the application under Change Reports.</p>
  </body></html>`;
  /* print from a hidden frame inside this page: no new window, so pop-up blockers cannot stop it */
  repPdfHtml=html;
  document.getElementById("repPdfFrame")?.remove();
  const f=document.createElement("iframe");
  f.id="repPdfFrame";f.title="Change report for printing";f.setAttribute("aria-hidden","true");
  f.style.cssText="position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
  document.body.append(f);
  const d=f.contentWindow.document;d.open();d.write(html);d.close();
  toast("Choose “Save as PDF” as the destination in the print window.",{type:"info",title:"Preparing the PDF"});
  setTimeout(()=>{try{f.contentWindow.focus();f.contentWindow.print()}catch(e){toast("The print window could not open. Use Ctrl+P on the report instead.",{type:"error",title:"PDF export failed"})}},350);
};