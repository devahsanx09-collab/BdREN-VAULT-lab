/* VAULT - pages/devices.js
   Devices page: the table, filters and selection, live ping, Add / Edit / Import pop-ups, saved logins, row Action menu.
   Loaded by templates/base.html on every screen; all scripts share one global scope (see core/helpers.js). */

/* ---- devices table ---- */
/* VENDORS comes from the server (app.py VENDORS table): label, vendor name and hint per platform */
const VENDORS=JSON.parse(document.getElementById("vendors-data").textContent);
const vInfo=t=>VENDORS[t]||{label:t,group:"",hint:""};
const slug=g=>g.toLowerCase().replace(/[^a-z0-9]+/g,"-");
/* Type column: shows the vendor name only (Cisco, Huawei ...), the full platform name is the tooltip */
const VENDOR_LOGO={Cisco:"cisco.svg",Huawei:"huawei.svg",Juniper:"juniper.svg",MikroTik:"mikrotik.svg",Fortinet:"fortinet.svg"};
const brandMark=t=>{const g=vInfo(t).group||t;if(VENDOR_LOGO[g])return `<img src="/static/img/vendors/${VENDOR_LOGO[g]}" alt="${esc(g)} logo" loading="lazy">`;const marks={Cisco:"cisco",Huawei:"H",Juniper:"J",BDCOM:"BD", "V-SOL":"VS", "TP-Link Omada":"TP",MikroTik:"M",Arista:"A",HPE:"HPE",Fortinet:"F",Other:"SSH"};return marks[g]||String(g).slice(0,3).toUpperCase()};
const vBadge=(t,d)=>{const v=vInfo(t),g=v.group||t,st=d?(devBad(d)?"st-bad":"st-ok"):"";return `<span class="vt v-${slug(g)} ${st}"${d?` data-vid="${d.id}"`:""} title="${esc(v.label)}">${esc(g==="Other"?v.label:g)}</span>`};
let devs=[];
/* the five numbers above the table */
let devFilter="all",devSort={k:"priority",dir:1};
const isOk=d=>d.last_status==="SUCCESS"||d.last_status==="UNCHANGED";
const pUp=d=>pingMap[d.id]&&pingMap[d.id].up,pDown=d=>pingMap[d.id]&&!pingMap[d.id].up;
/* status square: red when the device is down (ping) or its last backup failed, green otherwise */
const devBad=d=>d.last_status==="FAILED"||!!pDown(d);
const FILTERS=[["all","All",()=>true],["online","Online",pUp],["offline","Offline",pDown],["failed","Backup failed",d=>d.last_status==="FAILED"]];
/* the KPI cards above the table */
function renderStats(){
  const ok=devs.filter(isOk).length,bad=devs.filter(d=>d.last_status==="FAILED").length;
  const last=devs.map(d=>d.last_run).filter(Boolean).sort().pop();
  morph($("#stats"),`<div class="kpi"><small>Total devices</small><strong>${devs.length}</strong></div>
   <div class="kpi"><small>Online now</small><strong class="g" id="onlineNow" data-morph-skip>-</strong></div>
   <div class="kpi"><small>Backup succeeded</small><strong class="g">${ok}</strong></div>
   <div class="kpi"><small>Backup failed</small><strong class="${bad?"r":""}">${bad}</strong></div>
   <div class="kpi"><small>Last run</small><strong class="sm2">${last?fmtWhen(last):"Never"}</strong></div>`);
  paintPing();
}
/* filter chips with live counts */
function paintChips(){
  const box=$("#devChips");if(!box)return;
  if(!box.children.length)box.innerHTML=FILTERS.map(([k,l])=>`<button type="button" class="chip" data-f="${k}">${l}<small data-c="${k}"></small></button>`).join("");
  box.querySelectorAll(".chip").forEach(c=>c.classList.toggle("on",c.dataset.f===devFilter));
  FILTERS.forEach(([k,,fn])=>{const el=box.querySelector(`[data-c="${k}"]`);if(el){const v=k==="all"?devs.length:(k==="online"||k==="offline")&&!Object.keys(pingMap).length?"":devs.filter(fn).length;if(el.textContent!==String(v))el.textContent=v}});
}
const SORTERS={name:d=>(d.name||"\uffff").toLowerCase(),ip:d=>devs.indexOf(d),ping:d=>pingMap[d.id]?(pingMap[d.id].up?pingMap[d.id].ms||0:-1):-2,status:d=>d.last_status||"",when:d=>d.last_run||""};
const SRV='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/></svg>';
const th=(k,l)=>`<th class="sortable" data-sort="${k}" aria-sort="${devSort.k===k?(devSort.dir>0?"ascending":"descending"):"none"}">${l}</th>`;
/* draw the devices table (search + filter chip + sort) */
function renderDevices(){
  closeMenu();paintChips();
  const q=$("#q").value.trim().toLowerCase(),fn=FILTERS.find(f=>f[0]===devFilter)[2];
  const found=devs.filter(d=>fn(d)&&(!q||[d.name,d.ip,d.device_type,vInfo(d.device_type).label,d.username].some(v=>(v||"").toLowerCase().includes(q))));
  if(devSort.k==="priority"){
    /* Default order: failed devices first (oldest failed first); remaining devices newest-added first. */
    found.sort((a,b)=>{
      const af=a.last_status==="FAILED",bf=b.last_status==="FAILED";
      if(af!==bf)return af?-1:1;
      if(af)return (a.id||0)-(b.id||0);
      return (b.id||0)-(a.id||0);
    });
  }else{
    const sf=SORTERS[devSort.k];found.sort((a,b)=>{const x=sf(a),y=sf(b);return (x<y?-1:x>y?1:0)*devSort.dir});
  }
  const {rows:list,bar}=paginate("devices",found);
  morph($("#devList"),found.length?`<div class="mcheck"><label class="ck"><input type="checkbox" id="allM"> Select all on this page</label></div><div class="tbl cards"><table class="dt"><thead><tr><th class="c"><input type="checkbox" id="all" aria-label="Select all"></th>${th("name","Device")}${th("ip","IP address")}${th("ping","Ping")}<th>User</th><th>Added by</th>${th("status","Backup status")}${th("when","Last backup")}<th class="ac">Action</th></tr></thead><tbody>`+
  list.map(d=>`<tr data-key="${d.id}" class="${d.last_status==="FAILED"?"bad":""}"><td class="c"><input type="checkbox" class="sel" value="${d.id}"${selected.has(d.id)?" checked":""} aria-label="Select ${esc(d.ip)}"></td>
   <td class="dv" data-device-backups="${d.id}" title="Click to open this device's backup folders"><div class="dcell"><span class="brand-logo v-${slug(vInfo(d.device_type).group||d.device_type)}" title="${esc(vInfo(d.device_type).group||d.device_type)}" aria-label="${esc(vInfo(d.device_type).group||d.device_type)} logo">${brandMark(d.device_type)}</span><div>${d.name?`<span class="dn">${esc(d.name)}</span>`:'<span class="none">Awaiting first backup</span>'}<span class="sub">${vBadge(d.device_type,d)}</span></div></div></td>
   <td class="m ip">${esc(d.ip)}<span class="port">:${d.port}</span></td><td class="ping pg" data-id="${d.id}" data-morph-skip></td>
   <td class="usr" data-l="User">${esc(d.username||"-")}</td>
   <td class="added-by" data-l="Added by" title="${esc(d.created_at||"")}">${esc(d.created_by||"Legacy / unknown")}</td>
   <td class="st">${pill(d.last_status)}</td><td class="when" data-l="Last backup" title="${esc(d.last_run||"")}">${fmtWhen(d.last_run)}</td>
   <td class="acts"><button type="button" class="menu-btn op" data-id="${d.id}" aria-haspopup="menu" aria-label="Actions for ${esc(d.ip)}">Action <i aria-hidden="true">&#9662;</i></button></td></tr>`).join("")+`</tbody></table></div>`+bar
  :`<div class="empty"><b>${devs.length?"No matching devices":"No devices yet"}</b>${devs.length?"Try a different search or filter.":"Add a device: one IP adds one device, several IPs separated by commas add them all."}</div>`);
  updSel();
  paintPing();
  pingVisibleSoon();
}
$o("#devChips").addEventListener("click",e=>{const c=e.target.closest(".chip");if(!c)return;devFilter=c.dataset.f;PAGES.devices=1;renderDevices()});
$o("#devList").addEventListener("click",e=>{const h=e.target.closest("th.sortable");if(!h)return;const k=h.dataset.sort;devSort=devSort.k===k?{k,dir:-devSort.dir}:{k,dir:1};PAGES.devices=1;renderDevices()});
$o("#devList").addEventListener("click",e=>{const cell=e.target.closest("td[data-device-backups]");if(!cell)return;openDevice(cell.dataset.deviceBackups)});   /* opens the device's own page (see "device page" below) */
$o("#clrSel").onclick=()=>{selected.clear();document.querySelectorAll(".sel").forEach(c=>c.checked=false);updSel()};
function fmtWhen(s){
  if(!s)return '<span class="none">Never</span>';
  const t=parseBdDate(s);if(!t)return esc(s);
  const diff=Math.round((Date.parse(bdDateKey(new Date()))-Date.parse(bdDateKey(t)))/864e5),clock=bdClock(s);
  /* date and time as two spans: one line normally, a tidy date-over-time pair inside table cells (app.css .tm) */
  const day=diff===0?"Today":diff===1?"Yesterday":fmtBdDateTime(s).split(", ")[0];
  return `<span class="dd">${esc(day)}</span><span class="tm">${esc(clock)}</span>`;
}
/* ids of the selected devices; kept when you move to another page */
const selected=new Set();
function updSel(){
  const rows=[...document.querySelectorAll(".sel")],n=rows.filter(c=>c.checked).length;
  $("#selCount").textContent=selected.size+" selected";$("#selBar").hidden=!selected.size;
  ["#all","#allM"].forEach(i=>{const a=$(i);if(a){a.checked=n>0&&n===rows.length;a.indeterminate=n>0&&n<rows.length}})   /* "all" = this page */
}
$o("#devList").addEventListener("change",e=>{
  if(e.target.id==="all"||e.target.id==="allM")document.querySelectorAll(".sel").forEach(c=>{c.checked=e.target.checked;e.target.checked?selected.add(+c.value):selected.delete(+c.value)});
  else if(e.target.classList.contains("sel"))e.target.checked?selected.add(+e.target.value):selected.delete(+e.target.value);
  updSel();
});
async function loadDevices(){
  /* show the last list at once from the browser cache, then refresh it */
  const hit=localStorage.getItem("devListCache");
  if(hit&&!devs.length&&PAGE==="devices"){try{devs=JSON.parse(hit);renderStats();renderDevices()}catch(e){}}
  devs=await api("/api/devices");
  try{localStorage.setItem("devListCache",JSON.stringify(devs))}catch(e){}
  [...selected].forEach(i=>{if(!devs.some(d=>d.id===i))selected.delete(i)});
  if(PAGE!=="devices")return;      /* other screens only need the data (search, capacity planner) */
  renderStats();renderDevices();if(!Object.keys(pingMap).length){pingVisible();pingNow()}
}
/* Automatically refresh device names/status after background initial backups finish. */
let deviceAutoRefreshBusy=false;
setInterval(async()=>{
  if(PAGE!=="devices"||manualJob||document.querySelector("dialog[open]")||deviceAutoRefreshBusy)return;
  deviceAutoRefreshBusy=true;
  try{await loadDevices()}catch(_e){}finally{deviceAutoRefreshBusy=false}
},15000);  /* refresh inventory less often; avoids repeated full-database reads */

/* ---- live ping, designed to feel smooth ----
   1. The rows on screen are pinged every 3 s (a small, fast request); all devices every 15 s for the "Online now" count.
   2. A device that was Online needs two failed checks in a row before it turns Offline (one lost packet is ignored).
   3. Cells are updated in place, so the colour fades instead of the badge being redrawn. */
let pingMap={},pingFails={},pingBusy=false,pingBusyVis=false;   /* pingMap = state shown on screen, id -> {up, ms} */
function pingState(id){
  const p=pingMap[id];
  if(!p)return{cls:"chk",text:"Checking"};
  return p.up?{cls:"UP",text:p.ms!=null?Math.round(p.ms*10)/10+" ms":"Online"}:{cls:"DOWN",text:"Offline"};
}
/* merge a ping result into what is shown */
function applyPing(res){
  const before=devFilter==="online"||devFilter==="offline"?devs.filter(d=>pingMap[d.id]&&pingMap[d.id].up).map(d=>d.id).join():"";
  for(const id in res){
    const r=res[id],prev=pingMap[id];
    if(r.up){pingFails[id]=0;pingMap[id]=r}
    else{pingFails[id]=(pingFails[id]||0)+1;if(!prev||!prev.up||pingFails[id]>=2)pingMap[id]=r}
  }
  if(before!==""||devFilter==="online"||devFilter==="offline"){if(before!==devs.filter(d=>pingMap[d.id]&&pingMap[d.id].up).map(d=>d.id).join())setTimeout(renderDevices,0)}
}
function paintPing(){
  document.querySelectorAll("td.ping").forEach(td=>{
    const s=pingState(td.dataset.id);let sp=td.firstElementChild;
    if(!sp){sp=document.createElement("span");td.append(sp)}
    const cls="pill "+s.cls;if(sp.className!==cls)sp.className=cls;if(sp.textContent!==s.text)sp.textContent=s.text;
  });
  const byId=new Map(devs.map(d=>[String(d.id),d]));
  document.querySelectorAll(".vt[data-vid]").forEach(el=>{const d=byId.get(el.dataset.vid);if(!d)return;const bad=devBad(d);if(el.classList.contains("st-bad")!==bad){el.classList.toggle("st-bad",bad);el.classList.toggle("st-ok",!bad)}});
  paintChips();
  const el=$("#onlineNow");if(el)el.textContent=Object.keys(pingMap).length?devs.filter(d=>pingMap[d.id]&&pingMap[d.id].up).length+" / "+devs.length:"-";
}
const pingActive=()=>PAGE==="devices"&&!!$("#pingOn")?.checked&&!document.hidden;
async function pingVisible(){   /* only the rows on screen */
  const ids=[...document.querySelectorAll("td.ping")].map(td=>td.dataset.id);
  if(pingBusyVis||!ids.length)return;pingBusyVis=true;
  try{applyPing(await api("/api/ping?ids="+ids.join(",")));paintPing()}catch(e){}
  pingBusyVis=false;
}
async function pingNow(){   /* every device */
  if(pingBusy||!devs.length)return;pingBusy=true;
  try{applyPing(await api("/api/ping"));paintPing()}catch(e){}
  pingBusy=false;
}
let pingSoon=0;
const pingVisibleSoon=()=>{clearTimeout(pingSoon);pingSoon=setTimeout(()=>{if(pingActive())pingVisible()},250)};   /* after a page change or search */
(function loopVisible(){if(pingActive())pingVisible();setTimeout(loopVisible,15000)})();
(function loopAll(){if(pingActive())pingNow();setTimeout(loopAll,devs.length>50?180000:60000)})();
document.addEventListener("visibilitychange",()=>{if(pingActive()){pingVisible();pingNow()}});
$o("#pingOn").onchange=e=>{if(e.target.checked){pingVisible();pingNow()}};
$o("#q").oninput=()=>{PAGES.devices=1;renderDevices()};

/* ---- delete one device (asks first) ---- */
window.delDev=async id=>{
  const d=devs.find(x=>x.id===id);
  if(await confirmAction({title:"Delete this device?",message:"Saved backup files stay on disk.",detail:d?(d.name?d.name+"  -  ":"")+d.ip:"",confirm:"Delete device",run:()=>api("/api/devices/"+id,{method:"DELETE"})})){toast("The device was removed from the inventory. Its saved backup files stay on disk.",{title:"Device deleted"});sfx.play("del");loadDevices()}
};

/* ---- Add / Edit device: two pop-ups (#addDlg takes one IP or a comma-separated list, #editDlg).
        Their HTML is built from one template macro; the small helpers below are shared. ---- */
const DEVFORMS={};   /* mode -> device form state */
/* "10.0.0.1, 10.0.0.2 10.0.0.3" -> ["10.0.0.1","10.0.0.2","10.0.0.3"] (commas, semicolons, spaces or new lines) */
const splitIps=v=>[...new Set(String(v||"").split(/[\s,;]+/).map(x=>x.trim()).filter(Boolean))];
/* Add device: live note under the IP field - "3 devices will be added" - and the Name field only for one device */
function ipCountNote(frm){
  const note=frm.querySelector("[data-ipcount]");if(!note)return;
  const n=splitIps(frm.elements.ip.value).length,name=frm.elements.name;
  note.textContent=n>1?`${n} devices will be added with the same type and login. Names are read from each device's configuration.`:"";
  note.hidden=n<2;if(name){name.disabled=n>1;name.placeholder=n>1?"Read from each device":"Detected from config"}
}
let creds=[];        /* saved credential profile metadata; passwords are fetched only on explicit selection */
const groupOf=k=>vInfo(k).group;

/* Device type shows vendor names only. A device saved earlier with a sub-platform (NX-OS, ASA, Huawei OLT)
   keeps it as long as the vendor is not changed. */
const chosenType=f=>{const v=f.frm.elements.vendor.value;return f.origType&&groupOf(f.origType)===groupOf(v)?f.origType:v};
async function fillLogin(f,c){
  /* Choosing a saved login does NOT bring its password to the browser: the form sends only the saved
     login's id (credential_id) and the server applies that password itself. An administrator who really
     needs to see it clicks "Show" (revealSavedPassword below); that request is audited. */
  f.credRequest=(f.credRequest||0)+1;
  f.selectedCred=c||null;
  const u=f.frm.elements.username,p=f.frm.elements.password,ci=f.frm.elements.credential_id;
  u.value=c?c.username:"";p.value="";ci.value=c?String(c.credential_id):"";
  p.placeholder=c?"Saved password will be used (hidden)":"Enter password or select a saved username";
  p.dispatchEvent(new Event("input",{bubbles:true}));
  u.dispatchEvent(new Event("input",{bubbles:true}));
}
/* "Show" next to a saved (hidden) password: administrators may reveal it on purpose; others are told why not */
async function revealSavedPassword(f){
  const p=f.frm.elements.password,ci=f.frm.elements.credential_id;
  if(p.value||!ci.value)return;                     /* typed password, or no saved login: just show / hide */
  if(!ME||ME.role!=="admin"){
    toast("Saved device passwords stay hidden. Only an administrator can reveal them; the saved password is still used when you save.",{type:"info",title:"Password hidden"});
    return;
  }
  const requestId=f.credRequest;
  try{
    const r=await api("/api/credentials/password",J("POST",{credential_id:Number(ci.value)}));
    if(f.credRequest!==requestId)return;
    p.value=r.password||"";p.placeholder="Enter password or select a saved username";
    p.dispatchEvent(new Event("input",{bubbles:true}));
  }catch(err){toast(err.message,{type:"error",title:"Could not reveal the password"})}
}

async function loadCreds(){
  try{creds=await api("/api/credentials")}catch(e){creds=[]}
}

/* wire each pop-up once: close buttons, username autofill, submit */
["add","edit"].forEach(mode=>{   /* Add device takes one IP or several (the old "Import IP list" pop-up is merged into it) */
  const dlg=$("#"+mode+"Dlg"),frm=dlg.querySelector("form"),f=DEVFORMS[mode]={mode,dlg,frm,origType:null,editId:null,autoPw:"",groupIds:[]};
  dlg.querySelectorAll("[data-close]").forEach(b=>b.onclick=()=>dlg.close());
  frm.elements.username.addEventListener("input",()=>{
    const selected=f.selectedCred;
    if(selected&&selected.username!==frm.elements.username.value.trim()){
      f.selectedCred=null;f.credRequest=(f.credRequest||0)+1;frm.elements.credential_id.value="";
      frm.elements.password.value="";frm.elements.password.placeholder="Enter password or select a saved username";
    }
  });
  frm.onsubmit=e=>{e.preventDefault();submitDevice(f)};
  frm.addEventListener("click",e=>{if(e.target.classList.contains("eye")&&e.target.closest(".pwwrap")?.querySelector("[name=password]"))revealSavedPassword(f)});
  if(mode==="add"){
    /* a pasted list (one IP per line, e.g. from Excel) would lose its line breaks in a one-line field: turn them into commas */
    frm.elements.ip.addEventListener("paste",e=>{
      const t=(e.clipboardData||window.clipboardData)?.getData("text")||"";if(!/[\r\n\t]/.test(t))return;
      e.preventDefault();const el=e.target,list=splitIps(t).join(", ");
      el.setRangeText((el.value.slice(0,el.selectionStart).trim()&&!/[,\s]$/.test(el.value.slice(0,el.selectionStart))?", ":"")+list,el.selectionStart,el.selectionEnd,"end");
      ipCountNote(frm);
    });
    frm.elements.ip.addEventListener("input",()=>ipCountNote(frm));frm.addEventListener("reset",()=>setTimeout(()=>ipCountNote(frm)))}
});

/* Username dropdown: show saved profiles without exposing any password. Selecting a profile
   sends only its opaque ID; the server copies the encrypted password directly from the database. */
function setupLoginList(f){
  const input=f.frm.elements.username,list=f.frm.querySelector(".combo-list");
  const show=filter=>{
    const q=(filter||"").trim().toLowerCase();
    const numbered=creds.map((c,i)=>({...c,_index:i}));
    const totals={};numbered.forEach(c=>totals[c.username]=(totals[c.username]||0)+1);
    const seen={};numbered.forEach(c=>{seen[c.username]=(seen[c.username]||0)+1;c._profileNo=seen[c.username]});
    const rows=numbered.filter(c=>!q||c.username.toLowerCase().includes(q));
    list.innerHTML=rows.map(c=>{
      const profile=totals[c.username]>1?`Password profile ${c._profileNo} · `:"";
      return `<li data-ci="${c._index}" title="${esc(c.username)} credential profile ${c._profileNo}"><span class="cred-user">${esc(c.username)}</span><small>${profile}${c.count} device${c.count===1?"":"s"}</small></li>`;
    }).join("");
    list.hidden=!rows.length;
  };
  const hide=()=>{list.hidden=true};
  input.addEventListener("focus",()=>show(""));
  input.addEventListener("click",()=>show(""));
  input.addEventListener("input",()=>show(input.value));
  input.addEventListener("blur",()=>setTimeout(hide,120));
  input.addEventListener("keydown",e=>{if(e.key==="Escape"&&!list.hidden){e.preventDefault();e.stopPropagation();hide()}});
  list.addEventListener("mousedown",async e=>{   /* mousedown (not click) so it happens before the field loses focus */
    const li=e.target.closest("li");if(!li)return;e.preventDefault();
    const c=creds[Number(li.dataset.ci)];
    if(c){await fillLogin(f,c);input.focus({preventScroll:true});}
    hide();
  });
}
Object.values(DEVFORMS).forEach(setupLoginList);

/* open a pop-up: d = the device to edit (edit mode only) */
async function openDeviceForm(mode,d){
  const f=DEVFORMS[mode],e=f.frm.elements;
  f.frm.reset();f.origType=d?d.device_type:null;f.editId=d?d.id:null;f.autoPw="";f.groupIds=[];f.selectedCred=null;
  e.password.type="password";e.password.value="";e.credential_id.value="";e.password.placeholder="Enter password or select a saved username";f.frm.querySelector(".eye").textContent="Show";
  e.secret.placeholder=d&&d.has_secret?"Saved - leave empty to keep":"";
  await loadCreds();
  if(d){
    for(const k of["ip","name","port","username","command"])if(e[k])e[k].value=d[k]??"";
    const first=[...e.vendor.options].find(o=>groupOf(o.value)===groupOf(d.device_type));
    if(first)e.vendor.value=first.value;
    const g=creds.find(c=>c.ids.includes(d.id));   /* the saved login this device uses */
    if(g){await fillLogin(f,g);f.groupIds=g.ids.filter(i=>i!==d.id)}
    const row=f.frm.querySelector("[data-group]");   /* "apply to the other devices" option, only if others share this login */
    row.hidden=!f.groupIds.length;row.querySelector("input").checked=false;
    row.querySelector("span").textContent=`Also apply this username and password to the other ${f.groupIds.length} device${f.groupIds.length===1?"":"s"} that use the same login`;
  }
  f.dlg.showModal();
}

/* Save: send the form to the server, then close the pop-up and refresh the table */
async function submitDevice(f){
  const b=Object.fromEntries(new FormData(f.frm));b.device_type=chosenType(f);delete b.vendor;
  try{
    if(f.mode==="edit"){
      const all=f.frm.querySelector("[data-group] input").checked&&f.groupIds.length;
      if(all&&(!b.username||(!b.password&&!b.credential_id)))return toast("To apply the login to the other devices, choose a saved username or type a username and password.",{type:"warning",title:"Login needed"});
      await api("/api/devices/"+f.editId,J("PUT",b));
      if(all){await api("/api/credentials/apply",J("POST",{ids:f.groupIds,username:b.username,password:b.password,credential_id:b.credential_id}));toast(`The device and ${f.groupIds.length} other device${f.groupIds.length===1?"":"s"} with the same login were updated.`,{title:"Devices updated"})}
      else toast("The device details were saved.",{title:"Device updated"})
    }
    else if(splitIps(b.ip).length>1){
      /* several addresses in the one IP field: add them all with the same type and login */
      const ips=splitIps(b.ip);delete b.name;
      const r=await api("/api/devices/import",J("POST",{...b,lines:ips.join("\n")}));
      const why=(r.skipped_detail||[]).slice(0,4).map(s=>`${s.ip} (${s.reason})`).join("; ");
      sfx.play(r.added?"add":"warn");
      toast(`${r.added} of ${ips.length} devices added`+(r.added?"; their first backups start automatically.":".")+(r.skipped?` Skipped ${r.skipped}: ${why}${r.skipped>4?" and more":""}.`:""),
            {type:!r.added?"warning":r.skipped?"warning":"success",title:r.added?`${r.added} device${r.added===1?"":"s"} added`:"No devices added"});
      if(!r.added)return;
    }
    else{await api("/api/devices",J("POST",b));sfx.play("add");toast("The device was added. Its first backup will read the device name automatically.",{title:"Device added"})}
    if(f.mode==="edit")sfx.play("ok");
    f.dlg.close();loadDevices();
  }catch(err){toast(err.message,{type:"error"})}
}
/* ---- Action menu of a device row: one shared menu (#rowMenu) placed under the clicked button.
        It lives outside the table so the scrolling table never cuts it off. ---- */
const rowMenu=document.createElement("div");
rowMenu.id="rowMenu";rowMenu.hidden=true;rowMenu.setAttribute("role","menu");
rowMenu.innerHTML='<button type="button" role="menuitem" class="op" data-do="edit">Edit</button><button type="button" role="menuitem" class="d adm" data-do="del">Delete</button>';
document.body.append(rowMenu);
let menuId=null,menuAt=0;
const closeMenu=()=>{rowMenu.hidden=true;menuId=null};
function openMenu(btn){
  const id=+btn.dataset.id;
  if(menuId===id)return closeMenu();               /* clicking the same button again closes it */
  menuId=id;menuAt=Date.now();rowMenu.hidden=false;
  const r=btn.getBoundingClientRect(),w=rowMenu.offsetWidth,hgt=rowMenu.offsetHeight;
  const below=r.bottom+4+hgt<=innerHeight;          /* open upwards when there is no room underneath */
  rowMenu.style.left=Math.max(8,Math.min(r.right-w,innerWidth-w-8))+"px";
  rowMenu.style.top=(below?r.bottom+4:r.top-hgt-4)+"px";
}
$o("#devList").addEventListener("click",e=>{const b=e.target.closest(".menu-btn");if(b){e.stopPropagation();openMenu(b)}});
rowMenu.addEventListener("click",e=>{
  const a=e.target.closest("[data-do]");if(!a)return;
  const id=menuId;closeMenu();
  a.dataset.do==="edit"?editDev(id):delDev(id);
});
document.addEventListener("click",e=>{if(!e.target.closest("#rowMenu"))closeMenu()});
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeMenu()});
addEventListener("resize",closeMenu);
addEventListener("scroll",()=>{if(Date.now()-menuAt>250)closeMenu()},true);   /* a scroll right after opening (button scrolled into view) is ignored */

$o("#addBtn").onclick=()=>openDeviceForm("add");
window.editDev=id=>openDeviceForm("edit",devs.find(d=>d.id===id));
