/* VAULT - core/backup-jobs.js
   Starting a backup and following it, on every page: the "Backup running" chip in the top bar, and on
   Device Inventory also the progress bar, the Stop button and the Run / Delete buttons of the toolbar. */

/* ---- backup jobs: start a job, then poll the server for progress until it finishes (ids empty = all devices) ---- */
/* One backup job runs at a time on the server. trackJob() follows it (progress bar + "Backup running" bar with a Stop button),
   whoever started it: this page, another user or the schedule. So "A backup is already running" is never a dead end. */
let jobTracking=null,jobStopping=false;
async function trackJob(job){
  if(jobTracking)return;
  jobTracking=job;jobStopping=false;manualJob=true;
  const bar=$o("#prog"),fill=bar.firstElementChild||bar,jb=$o("#jobBar");bar.style.display="block";fill.style.width="2%";
  $o("#jobTx").textContent="Backup running";$o("#jobStop").disabled=false;jb.hidden=false;
  $("#jobChipTx").textContent="Backup running";$("#jobChip").hidden=false;      /* visible in the top bar on every page */
  try{
    while(true){
      const j=await api("/api/jobs/"+job);fill.style.width=Math.max(2,j.done/j.total*100)+"%";
      /* j.phase: e.g. "Retrying 3 devices that failed" during the job's automatic second pass */
      $o("#jobTx").textContent=jobStopping?"Stopping the backup...":j.phase?`${j.phase} (first pass: ${j.done} of ${j.total} done)`:`Backup running: ${j.done} of ${j.total} devices done`;
      $("#jobChipTx").textContent=jobStopping?"Stopping backup":j.phase?j.phase.replace(/ that failed.*/,""):`Backup ${j.done} / ${j.total}`;
      if(j.finished){
        const c=s=>j.results.filter(r=>r.status===s).length;
        const bad=c("FAILED"),good=c("SUCCESS")+c("UNCHANGED"),skipped=c("CANCELLED");sfx.play(!bad&&!skipped?"done":good?"warn":"error");
        toast(`${c("SUCCESS")} saved with changes, ${c("UNCHANGED")} unchanged, ${bad} failed`+(skipped?`, ${skipped} skipped because the job was stopped`:"")+".",
              {type:!bad&&!skipped?"success":good?"warning":"error",title:!bad&&!skipped?"Backup completed":good?"Backup finished with problems":"Backup failed",
               action:bad?{label:"See why in Backup Jobs",run:()=>showTab("jobs")}:null});break}
      await new Promise(r=>setTimeout(r,1000));
    }
  }catch(err){toast(err.message,{type:"error"})}
  jobTracking=null;manualJob=false;jb.hidden=true;$("#jobChip").hidden=true;setTimeout(()=>{if(!jobTracking)bar.style.display="none"},800);if(PAGE==="devices")loadDevices();
}
/* follow a backup that is already running on the server (after a page refresh, or one started by someone else) */
async function resumeJob(){
  try{const a=await api("/api/jobs/active");if(a.job){trackJob(a.job);return true}}catch(e){}
  return false;
}
async function runBackup(ids){
  if(jobTracking)return toast("A backup is running. Wait for it to finish, or stop it with Stop backup.");
  try{const {job}=await api("/api/backup",J("POST",{ids}));trackJob(job)}
  catch(err){
    if(err.status===409&&await resumeJob())toast("A backup is already running. Its progress is shown here: wait for it, or stop it.");
    else toast(err.message,{type:"error"});
  }
}
$("#jobChip").onclick=()=>showTab("devices");
$o("#jobStop").onclick=async()=>{
  if(await confirmAction({title:"Stop the running backup?",message:"Devices that have not started yet are skipped. Sessions already in progress finish on their own.",confirm:"Stop backup",danger:false,run:()=>api("/api/jobs/cancel",{method:"POST"})})){
    jobStopping=true;$o("#jobStop").disabled=true;$o("#jobTx").textContent="Stopping the backup...";
  }
};
$o("#delSel").onclick=async()=>{
  const ids=[...selected];
  if(!ids.length)return toast("Tick the box next to one or more devices first.",{type:"warning",title:"No device selected"});
  let r;
  if(await confirmAction({title:`Delete ${ids.length} selected device${ids.length===1?"":"s"}?`,message:"Saved backup files stay on disk.",confirm:"Delete",run:async()=>{r=await api("/api/devices/delete",J("POST",{ids}))}})){toast(r.deleted+" device(s) deleted");sfx.play("del");loadDevices()}
};
$o("#delAll").onclick=async()=>{
  if(!devs.length)return toast("The device list is already empty.",{type:"info",title:"Nothing to delete"});
  let r;
  if(await confirmAction({title:`Delete ALL ${devs.length} devices?`,message:"This cannot be undone. Saved backup files stay on disk.",confirm:"Delete all devices",typed:"DELETE",run:async()=>{r=await api("/api/devices/delete",J("POST",{ids:[]}))}})){pingMap={};toast(r.deleted+" device(s) deleted");sfx.play("del");loadDevices()}
};
$o("#runAll").onclick=()=>runBackup([]);
$o("#runSel").onclick=()=>{const ids=[...selected];ids.length?runBackup(ids):toast("Tick the box next to one or more devices first.",{type:"warning",title:"No device selected"})};
$o("#retryFailed").onclick=()=>{
  const failed=devs.filter(d=>String(d.last_status||"").toUpperCase()==="FAILED");
  if(!failed.length)return toast("Every device's last backup succeeded, so there is nothing to retry.",{type:"info",title:"Nothing to retry"});
  runBackup(failed.map(d=>d.id));
};
