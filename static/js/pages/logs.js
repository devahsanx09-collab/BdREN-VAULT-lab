/* VAULT - pages/logs.js
   Logs page: device activity log with search, filters and CSV export, plus the administrative audit trail.
   Loaded by templates/base.html on every screen; all scripts share one global scope (see core/helpers.js). */

/* ---- Device activity & backup audit log ---- */
let logData=[],logSum=null;
const LOG_LIMIT=2000;            /* newest matching rows sent to the browser; search and filters run on the server */
const logParams=()=>new URLSearchParams({status:$("#logStatus")?.value||"ALL",period:$("#logPeriod")?.value||"ALL",q:($("#logSearch")?.value||"").trim()});
async function fetchLogs(){
  const p=logParams();
  try{
    [logData,logSum]=await Promise.all([api(`/api/logs?${p}&limit=${LOG_LIMIT}`),api(`/api/logs/summary?${p}`)]);
    renderLogs();
  }catch(e){$("#logList").innerHTML=errorState("Could not load the activity log",e);}
}
async function loadLogs(){await fetchLogs();await loadAudit()}
let auditRows=[];
async function loadAudit(){
  const panel=$("#auditPanel");
  if(!panel||!ME||ME.role!=="admin")return;
  try{
    auditRows=await api("/api/audit?limit=1000");
    renderAudit();
  }catch(e){$("#auditList").innerHTML=errorState("Could not load the audit trail",e);}
}
function renderAudit(){
  const host=$("#auditList");if(!host)return;
  if(!auditRows.length){host.innerHTML=`<div class="empty">No audit events recorded yet.</div>`;return}
  const {rows,bar}=paginate("audit",auditRows);
  host.innerHTML=`<div class="tbl"><table><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Device / target</th><th>Details</th><th>Source IP</th></tr></thead><tbody>`+
    rows.map(r=>`<tr><td class="when">${esc(r.ts||"-")}</td><td><strong>${esc(r.username||"System")}</strong></td><td>${esc(r.action||"-")}</td><td>${esc(r.target||"-")}</td><td class="log-message">${esc(r.detail||"-")}</td><td class="m">${esc(r.remote_addr||"-")}</td></tr>`).join("")+
    `</tbody></table></div>`+bar;
}
$("#auditRefresh")?.addEventListener("click",loadAudit);
function logFiltered(){return logData}      /* already filtered by the server (status, period, search) */
function renderLogKpis(){
  const s=logSum||{today:0,saved:0,unchanged:0,failed:0};
  morph($("#logKpis"),[["Events today",s.today,"Matching the filters"],["Saved configurations",s.saved,"A change was stored"],["Unchanged",s.unchanged,"No new file required"],["Failed attempts",s.failed,"Review message details"]].map((x,i)=>`<div class="kpi"><span>${x[0]}</span><strong class="${i===3&&x[1]?"bad":""}">${Number(x[1]).toLocaleString("en-US")}</strong><small>${x[2]}</small></div>`).join(""));
}
/* shown when a log entry was stored without its own message */
const LOG_DEFAULT={
  SUCCESS:"Configuration saved: a change was detected and a new version was stored.",
  UNCHANGED:"Configuration checked: nothing changed since the last saved version, so no new file was needed.",
  FAILED:"Backup failed without a recorded reason. Check that the device is reachable and its login details are correct."
};
function renderLogs(){
  const filtered=logFiltered();renderLogKpis();
  const total=logSum?logSum.total:filtered.length;
  $("#logResultCount").textContent=total>filtered.length?`Newest ${filtered.length.toLocaleString("en-US")} of ${total.toLocaleString("en-US")} matching events (narrow the filters to see older ones)`:`${total.toLocaleString("en-US")} matching events`;
  const {rows:l,bar}=paginate("logs",filtered);
  $("#logList").innerHTML=filtered.length?`<div class="tbl log-table"><table><thead><tr><th>Timestamp</th><th>Device</th><th>Management IP</th><th>Result</th><th>Event details</th></tr></thead><tbody>`+
  l.map(r=>`<tr class="lg-${esc(r.status||"NONE")}"><td class="m lg-ts">${esc(r.ts?fmtBdDateTime(r.ts,true):"-")}</td><td class="lg-dev"><strong>${esc(r.name||"Unnamed device")}</strong></td><td class="m lg-ip">${esc(r.ip||"-")}</td><td class="lg-res">${pill(r.status)}</td><td class="log-message">${esc(r.message||LOG_DEFAULT[r.status]||"No details were recorded for this event.")}</td></tr>`).join("")+`</tbody></table></div>`+bar:`<div class="empty"><b>${logParams().get("q")||logParams().get("status")!=="ALL"||logParams().get("period")!=="ALL"?"No matching events":"No activity recorded yet"}</b>${logParams().get("q")||logParams().get("status")!=="ALL"||logParams().get("period")!=="ALL"?"Try changing the search or filters.":"Backup and device activity will appear here when events are recorded."}</div>`;
}
let logDebounce=0;
["logSearch","logStatus","logPeriod"].forEach(id=>document.getElementById(id)?.addEventListener(id==="logSearch"?"input":"change",()=>{PAGES.logs=1;clearTimeout(logDebounce);logDebounce=setTimeout(fetchLogs,id==="logSearch"?350:0)}));
document.getElementById("logRefresh")?.addEventListener("click",fetchLogs);
document.getElementById("logExport")?.addEventListener("click",()=>{
  const rows=logFiltered(),cols=["ts","name","ip","status","message"];
  const csv=[cols.join(","),...rows.map(r=>cols.map(k=>csvCell(k==="ts"?fmtBdDateTime(r[k],true):r[k])).join(","))].join("\r\n");
  const url=URL.createObjectURL(new Blob(["\ufeff",csv],{type:"text/csv;charset=utf-8;"})),a=document.createElement("a");a.href=url;a.download=`dbms-logs-${new Date().toISOString().slice(0,10)}.csv`;a.click();URL.revokeObjectURL(url);
});
