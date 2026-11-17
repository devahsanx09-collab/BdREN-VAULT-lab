/* VAULT - pages/jobs.js
   Backup Jobs page (/jobs): history of backup runs (last 200) with result counts, duration, throughput and
   the devices that need attention, 10 / 50 / 100 per page. Data: /api/jobs/history (stored job summaries).
   Refreshes itself every 4 s while a job runs. Loaded by templates/base.html on every screen. */

let jobsData=null,jobsTimer=0;
const fmtDur=s=>{if(s==null)return "-";s=Math.round(s);if(s<60)return s+" s";const m=Math.floor(s/60);if(m<60)return `${m} min ${s%60} s`;return `${Math.floor(m/60)} h ${m%60} min`};

async function loadJobs(){
  clearTimeout(jobsTimer);
  try{jobsData=await api("/api/jobs/history");renderJobs()}
  catch(e){$("#jobsKpis").innerHTML="";$("#jobsList").innerHTML=errorState("Could not load the backup jobs",e)}
  if(jobsData&&jobsData.jobs.some(j=>!j.finished))jobsTimer=setTimeout(()=>{if(!document.hidden)loadJobs()},4000);
}
$o("#jobsRefresh").onclick=loadJobs;
$o("#jobsRunAll").onclick=()=>runBackup([]);     /* the same job flow as Run backup on Device Inventory */

function jobState(j){
  const c=j.counts||{};
  if(!j.finished)return ["run","Running"];
  if(c.CANCELLED)return ["stop","Stopped"];
  if(c.FAILED&&!((c.SUCCESS||0)+(c.UNCHANGED||0)))return ["bad","Failed"];
  if(c.FAILED)return ["warn","Completed with failures"];
  return ["ok","Completed"];
}

function renderJobKpis(){
  const done=jobsData.jobs.filter(j=>j.finished),last=done[0],c=last?last.counts:{};
  const avg=done.map(j=>j.avg_device_s).find(v=>v!=null);
  const okRate=last?Math.round(((c.SUCCESS||0)+(c.UNCHANGED||0))/Math.max(1,last.total)*100):null;
  morph($("#jobsKpis"),
    `<div class="kpi"><small>Last run</small><strong class="sm2">${last?esc(fmtBdDateTime(last.started)):"Never"}</strong><span class="d">${last?esc(last.reason_label):"No backup has run yet"}</span></div>
     <div class="kpi"><small>Last run success</small><strong class="${okRate==null?"":okRate===100?"g":okRate>=90?"w":"r"}">${okRate==null?"-":okRate+"%"}</strong><span class="d">${last?`${(c.SUCCESS||0)+(c.UNCHANGED||0)} of ${last.total} devices`:"Saved or unchanged"}</span></div>
     <div class="kpi"><small>Last run duration</small><strong>${last?fmtDur(last.duration_s):"-"}</strong><span class="d">${last&&last.duration_s?`${(last.total/Math.max(1,last.duration_s)*60).toFixed(1)} devices per minute`:"Start to finish"}</span></div>
     <div class="kpi"><small>Average per device</small><strong>${avg!=null?avg+" s":"-"}</strong><span class="d">SSH login + configuration read</span></div>
     <div class="kpi"><small>Parallel SSH sessions</small><strong>${jobsData.workers}</strong><span class="d">Change in System Settings</span></div>`);
}

function jobCard(j,isOpen){
  const [cls,label]=jobState(j),c=j.counts||{},total=Math.max(1,j.total);
  const seg=k=>Math.round((c[k]||0)/total*100),ok=(c.SUCCESS||0)+(c.UNCHANGED||0);
  const failed=c.FAILED||0,shown=j.problems||[];
  const facts=`<div class="job-facts">
      <span><small>Saved (changed)</small><b class="plus">${c.SUCCESS||0}</b></span><span><small>Unchanged</small><b>${c.UNCHANGED||0}</b></span>
      <span><small>Failed</small><b class="minus">${failed}</b></span><span><small>Stopped</small><b>${c.CANCELLED||0}</b></span>
      <span><small>Avg per device</small><b>${j.avg_device_s!=null?j.avg_device_s+" s":"-"}</b></span><span><small>Job ID</small><b class="mono">${esc(j.id)}</b></span></div>`;
  const problems=shown.length?`<div class="job-fh"><b>Devices that need attention (${failed+(c.CANCELLED||0)})</b>
      ${j.failed_ids&&j.failed_ids.length?`<button type="button" class="b op" data-job-retry="${esc(j.id)}">Retry ${j.failed_ids.length} failed device${j.failed_ids.length===1?"":"s"}</button>`:""}</div>
    <div class="tbl"><table><thead><tr><th>Device</th><th>IP address</th><th>Result</th><th>Reason</th></tr></thead><tbody>${shown.map(f=>`<tr><td><strong>${esc(f.name||f.ip)}</strong></td><td class="m">${esc(f.ip)}</td><td><span class="pill ${f.status==="FAILED"?"FAILED":""}">${f.status==="FAILED"?"Failed":"Stopped"}</span></td><td class="log-message">${esc(f.message||"No reason recorded")}</td></tr>`).join("")}</tbody></table></div>
    ${failed+(c.CANCELLED||0)>shown.length?`<p class="rep-note">Showing the first ${shown.length}. Activity Logs lists every failure with its reason.</p>`:""}`
    :`<p class="rep-note">${!j.finished?`Running: ${j.done} of ${j.total} devices done.`:c.CANCELLED?"The job was stopped; devices that had not finished were skipped and nothing was saved for them.":"Every device in this run finished successfully."}</p>`;
  return `<details class="job ${cls}" data-job="${esc(j.id)}"${isOpen?" open":""}>
    <summary>
      <span class="job-st"><i></i>${esc(label)}</span>
      <span class="job-main"><b>${esc(j.reason_label)}</b><small>${esc(fmtBdDateTime(j.started))} · by ${esc(j.started_by)}</small></span>
      <span class="job-bar" title="${c.SUCCESS||0} saved, ${c.UNCHANGED||0} unchanged, ${failed} failed, ${c.CANCELLED||0} stopped">
        ${j.finished?`<i class="s" style="width:${seg("SUCCESS")}%"></i><i class="u" style="width:${seg("UNCHANGED")}%"></i><i class="f" style="width:${seg("FAILED")}%"></i><i class="c" style="width:${seg("CANCELLED")}%"></i>`:`<i class="p" style="width:${Math.round(j.done/total*100)}%"></i>`}
      </span>
      <span class="job-n">${j.finished?`<b>${ok}</b>/${j.total} ok`:`<b>${j.done}</b>/${j.total} done`}</span>
      <span class="job-d">${fmtDur(j.duration_s)}</span>
      <svg class="rep-chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
    </summary>
    <div class="job-body">${facts}${problems}</div></details>`;
}

/* devices that wait for an automatic retry (offline, or a temporary failure): docs/BACKUP_RELIABILITY.md */
const RETRY_LABEL={offline:"Offline",transient:"Temporary failure",auth:"Login rejected"};
function renderRetryQueue(){
  const q=jobsData.retry_queue||[],box=$("#jobsRetry");if(!box)return;
  if(!q.length){box.innerHTML="";return}
  const {rows,bar}=paginate("retry",q);
  morph(box,`<section class="card retry-card">
    <div class="job-fh"><b>Waiting to retry (${q.length})</b><span class="d">VAULT tries these again by itself: offline devices as soon as they answer ping, temporary failures after a short wait.</span></div>
    <div class="tbl"><table><thead><tr><th>Device</th><th>IP address</th><th>Why</th><th>Tries</th><th>Waiting since</th><th>Next check</th></tr></thead><tbody>${rows.map(r=>`<tr>
      <td><strong>${esc(r.name)}</strong></td><td class="m">${esc(r.ip)}</td>
      <td><span class="pill retry-${esc(r.kind)}">${esc(RETRY_LABEL[r.kind]||r.kind)}</span><span class="sub" title="${esc(r.message)}">${esc(r.why)}</span></td>
      <td>${r.kind==="offline"?"-":r.attempts}</td><td class="when">${esc(r.since?fmtBdDateTime(r.since):"-")}</td><td class="when">${esc(r.next?fmtBdDateTime(r.next):"-")}</td></tr>`).join("")}</tbody></table></div>${bar}</section>`);
}

function renderJobs(){
  if(!jobsData)return;
  renderJobKpis();
  renderRetryQueue();
  const jobs=jobsData.jobs;
  if(!jobs.length){$("#jobsList").innerHTML='<div class="empty"><b>No backup jobs yet</b>Run "Back up all devices" or wait for the schedule; each run is listed here.</div>';return}
  const open=new Set([...document.querySelectorAll("#jobsList details[open]")].map(d=>d.dataset.job));
  const {rows,bar}=paginate("jobs",jobs);
  morph($("#jobsList"),`<div class="job-list">${rows.map(j=>jobCard(j,open.has(j.id))).join("")}</div>`+bar);
}

$o("#jobsList").addEventListener("click",async e=>{
  const b=e.target.closest("[data-job-retry]");if(!b)return;
  const job=jobsData.jobs.find(j=>j.id===b.dataset.jobRetry);if(!job)return;
  const ids=[...new Set(job.failed_ids||[])];
  if(!ids.length)return toast("These devices are no longer in the inventory.",{type:"warning",title:"Nothing to retry"});
  await runBackup(ids);          /* backup-jobs.js: starts the job and shows its progress */
  setTimeout(loadJobs,800);
});
