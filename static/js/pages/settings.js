/* VAULT - pages/settings.js
   Settings page: backup schedule, parallel sessions, log retention, notification sounds.
   Loaded by templates/base.html on every screen; all scripts share one global scope (see core/helpers.js). */

/* ---------- settings: schedule ---------- */
const sfrm=$("#sfrm")||document.createElement("form");     /* placeholder form on the other screens */
const schedDaysInput=sfrm.elements.sched_days;
const schedDatePicker=$("#schedDatePicker");
function selectedSchedDays(){return String(schedDaysInput.value||"1,15").split(",").map(v=>Number(v.trim())).filter(v=>Number.isInteger(v)&&v>=1&&v<=31)}
function updateSchedDays(){
  const selected=selectedSchedDays();
  schedDatePicker.querySelectorAll("button[data-day]").forEach(btn=>{const on=selected.includes(Number(btn.dataset.day));btn.classList.toggle("selected",on);btn.setAttribute("aria-pressed",on?"true":"false")});
  $("#schedDaysSummary").textContent=selected.length?selected.map(d=>d+(d===1?"st":d===2?"nd":d===3?"rd":"th")).join(", ")+" selected":"Choose at least one day";
}
function buildSchedDatePicker(){
  if(!schedDatePicker||schedDatePicker.dataset.ready)return;
  schedDatePicker.dataset.ready="1";
  for(let day=1;day<=31;day++){const btn=document.createElement("button");btn.type="button";btn.dataset.day=String(day);btn.textContent=String(day);btn.title=`Run backup on day ${day} of each month`;btn.setAttribute("aria-label",`Day ${day}`);btn.setAttribute("aria-pressed","false");btn.onclick=()=>{let days=selectedSchedDays();days=days.includes(day)?days.filter(d=>d!==day):[...days,day].sort((a,b)=>a-b);schedDaysInput.value=days.join(",");updateSchedDays()};schedDatePicker.appendChild(btn)}
  updateSchedDays();
}
function schedUi(){
  const m=sfrm.elements.sched_mode.value, label=$("#lEvery"), input=sfrm.elements.sched_every;
  label.hidden=m==="daily"||m==="semimonthly";
  $("#lAt").hidden=!(m==="daily"||m==="semimonthly");
  $("#lDays").hidden=m!=="semimonthly";
  const help=$("#schedModeHelp");
  if(m==="days"){
    label.firstChild.textContent="Repeat every (days)";input.min="1";input.max="3650";input.value=Math.max(1,Number(input.value)||1);
    help.textContent="Run a backup at a fixed interval measured in days.";
  } else if(m==="interval"){
    label.firstChild.textContent="Repeat every (minutes)";input.min="5";input.max="10080";input.value=Math.max(5,Number(input.value)||60);
    help.textContent="Use a minute-based interval for frequent backup checks. Minimum interval: 5 minutes.";
  } else if(m==="daily"){
    help.textContent="Run one scheduled backup every day at the selected local time.";
  } else {
    input.value="60";help.textContent="Choose one or more calendar dates. The backup runs at the selected local time on each chosen date.";
  }
}
if($("#sfrm")){buildSchedDatePicker();sfrm.elements.sched_mode.onchange=schedUi}
/* ---- settings tab (admin only): performance and schedule ---- */
async function loadSettings(){
  const s=await api("/api/settings"),f=sfrm.elements;
  f.workers.value=s.workers;f.sched_on.checked=s.sched_on==="1";f.sched_mode.value=s.sched_mode;f.sched_every.value=s.sched_every;f.sched_at.value=format12hTime(s.sched_at);f.sched_days.value=s.sched_days||"1,15";f.sched_catchup.checked=s.sched_catchup!=="0";f.log_retention_months.value=s.log_retention_months||"0";updateSchedDays();
  $("#schedLast").textContent=s.sched_last_text?"Last scheduled run: "+fmtBdDateTime(s.sched_last_text,true)+(s.running?" (a backup is running now)":""):"Schedule is ready. The interval starts when you enable it.";
  $("#schedState").textContent=s.sched_on==="1"?(s.running?"Enabled · backup in progress":"Enabled · waiting for next run"):"Disabled";
  $("#schedNextText").textContent=(s.next_run?fmtBdDateTime(s.next_run):"Enable scheduling to calculate the next run");
  $("#schedLastText").textContent=(s.sched_last_text?fmtBdDateTime(s.sched_last_text,true):"No scheduled run yet");
  schedUi();
  loadCapacity();
}
/* ---- capacity planner (Performance card): how long a full backup takes with N parallel SSH sessions ----
   Uses the real average time per device of recent jobs; 25 s is assumed until a job has run. */
let capAvg=null,capMeasured=false;
async function loadCapacity(){
  try{
    const [h,list]=await Promise.all([api("/api/jobs/history?limit=10"),devs.length?Promise.resolve(devs):api("/api/devices")]);
    if(!devs.length)devs=list;
    const v=h.jobs.map(j=>j.avg_device_s).find(x=>x!=null);capMeasured=v!=null;capAvg=v!=null?v:25;
  }catch(e){capAvg=25;capMeasured=false}
  paintCapacity();
}
function paintCapacity(){
  const box=$("#capPlan");if(!box||capAvg==null)return;
  const n=devs.length,w=Math.max(1,Math.min(50,+sfrm.elements.workers.value||1));
  const est=s=>{s=Math.round(s);if(s<90)return s+" seconds";const m=Math.round(s/60);return m<90?m+" minutes":`${Math.floor(m/60)} h ${m%60} min`};
  const dur=w2=>Math.ceil(n/w2)*capAvg;
  const target=30*60,rec=Math.min(50,Math.max(1,Math.ceil(n*capAvg/target)));
  const over=dur(w)>target&&w<rec;
  box.className="planner "+(over?"warn":"ok");
  box.innerHTML=n?`<div class="pl-head"><b>Capacity planner</b><span>${capMeasured?`measured ${capAvg} s per device (recent jobs)`:"estimate: 25 s per device until the first job runs"}</span></div>
    <div class="pl-grid"><span><small>Devices</small><b>${n.toLocaleString("en-US")}</b></span><span><small>Parallel sessions</small><b>${w}</b></span>
    <span><small>Full backup takes about</small><b>${est(dur(w))}</b></span><span><small>Suggested for under 30 min</small><b>${rec}${rec>=50&&dur(50)>target?" (maximum)":""}</b></span></div>
    <p>${over?`With ${w} session${w===1?"":"s"}, backing up all ${n} devices takes about ${est(dur(w))}. Set <b>${rec}</b> to finish in about ${est(dur(rec))}. Check that the server and the devices' AAA can handle that many logins at once.`:
      `With ${w} sessions a full run of ${n} devices finishes in about ${est(dur(w))}. More sessions finish sooner but open more SSH logins at the same time.`}</p>`
    :`<p>Add devices to see how long a full backup will take.</p>`;
}
if($("#sfrm"))sfrm.elements.workers.addEventListener("input",paintCapacity);

sfrm.onsubmit=async e=>{
  e.preventDefault();const f=sfrm.elements;
  try{
    const b={workers:f.workers.value,sched_on:f.sched_on.checked?"1":"0",sched_mode:f.sched_mode.value,sched_every:f.sched_every.value,sched_at:parse12hTime(f.sched_at.value),sched_days:f.sched_days.value,sched_catchup:f.sched_catchup.checked?"1":"0",log_retention_months:f.log_retention_months.value};
    await api("/api/settings",J("PUT",b));toast("Your settings were saved and are now in effect.",{title:"Settings saved"});loadSettings();
  }catch(err){toast(err.message,{type:"error"})}
};
// Event-specific sound preferences are stored locally in this browser.
const soundGroups={backup:"soundBackup",delete:"soundDelete",add:"soundAdd",system:"soundSystem"};
function loadSoundPreferences(){const p=sfx.prefs;Object.entries(soundGroups).forEach(([group,id])=>{const el=$("#"+id);if(el)el.checked=!!p[group]})}
Object.entries(soundGroups).forEach(([group,id])=>{const el=$("#"+id);if(el)el.addEventListener("change",()=>{sfx.setPref(group,el.checked);if(el.checked)sfx.play(({backup:"done",delete:"del",add:"add",system:"ok"})[group]);toast(`${group[0].toUpperCase()+group.slice(1)} sound ${el.checked?"enabled":"disabled"}`)})});
document.querySelectorAll("[data-test-sound]").forEach(btn=>btn.addEventListener("click",()=>{const kind=btn.dataset.testSound,group=({done:"backup",del:"delete",add:"add",ok:"system"})[kind];if(!sfx.on){sfx.set(true);paintSnd()}if(!sfx.prefs[group]){sfx.setPref(group,true);loadSoundPreferences()}sfx.play(kind)}));
loadSoundPreferences();
