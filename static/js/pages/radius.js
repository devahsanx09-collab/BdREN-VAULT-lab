/* VAULT - pages/radius.js
   RADIUS / AAA pages: AAA Users (/radius/users), NAS Clients (/radius/nas) and Authentication Audit (/radius/audit).
   Loaded by templates/base.html on every screen; all scripts share one global scope (see core/helpers.js). */

/* ============================================================================
   RADIUS Admin (side menu -> RADIUS Admin): users, devices (NAS) and audit.
   Pages: templates/radius/index.html. Data: /api/radius/* (apps/radius/views.py), administrators only.
   Buttons inside the tables use data-rad-* attributes because inline onclick is blocked by the Content-Security-Policy.
   ============================================================================ */
let radUsers=[],radLevels=[],radNas=[],radVendors=[],radRoles=[],radEvents=[],radLogins=[];
let radDevices=[];          /* RADIUS devices a user can be limited to: [{name, ip, single, role}] */
/* "Device type" suggestions (Core router, ... + any custom label already in use) shared by every such
   field: typing still accepts anything, the list is only a convenience (see <datalist id="radRoleList">). */
function paintRadRoleList(){$("#radRoleList").innerHTML=radRoles.map(r=>`<option value="${esc(r)}">`).join("")}
const radShown=new Set();   /* ids of the devices whose shared secret is currently visible */
const radSecrets=new Map(); /* shared secrets fetched on request (never part of the device list): id -> secret */
let radDown="";             /* last "RADIUS database not reachable" message; pop-ups are not opened while it is set */
async function radSecret(id){
  if(!radSecrets.has(id))radSecrets.set(id,(await api(`/api/radius/nas/${id}/secret`,{method:"POST"})).secret);
  return radSecrets.get(id);
}
const RAD_LEVEL_NOTE={"super-admin":"Full control","read-write":"Limited changes","read-only":"View only"};
const radFail=(sel,what,e)=>{radDown=e&&e.message||"The RADIUS pages could not load.";$(sel).innerHTML=errorState(`Could not load ${what}`,e)};
const radKpis=(sel,items)=>{$(sel).innerHTML=items.map(x=>`<div class="kpi"><span>${esc(x[0])}</span><strong class="${x[3]||""}">${x[1]}</strong><small>${esc(x[2])}</small></div>`).join("")};
/* access levels are stored in lower case (the FreeRADIUS group name); shown as "Super-admin", "Read-only" */
const lvLabel=l=>l==="-"||!l?"No level":l.charAt(0).toUpperCase()+l.slice(1);
const lvOptions=()=>radLevels.map(l=>`<option value="${esc(l)}">${esc(lvLabel(l))}</option>`).join("");
const lvPill=l=>`<span class="pill lv lv-${esc(l)}">${esc(lvLabel(l))}</span>`;
const radOptions=(items)=>items.map(o=>`<option value="${esc(o.key??o)}">${esc(o.label??o)}</option>`).join("");

/* ---- RADIUS users ---- */
async function loadRadUsers(){
  try{
    const d=await api("/api/radius/users");radDown="";radUsers=d.users;radLevels=d.levels;radDevices=d.devices||[];radRoles=d.roles||radRoles;radViolations=d.limit_violations||[];
    const f=$("#radLevel"),keep=f.value;
    f.innerHTML=`<option value="ALL">All access levels</option>`+lvOptions();
    f.value=radLevels.includes(keep)?keep:"ALL";
    $("#rufrm").elements.level.innerHTML=lvOptions();
    paintRadRoleList();
    renderRadUsers();
  }catch(e){radFail("#radUserList","RADIUS users",e)}
}
/* logins FreeRADIUS accepted on devices outside a user's allowed list (last 24 h) -> the limit is not enforced */
let radViolations=[];
function paintRadViolations(){
  let box=$("#radLimitWarn");
  if(!box){box=document.createElement("div");box.id="radLimitWarn";$("#radUserList").before(box)}
  box.innerHTML=radViolations.length?`<div class="rad-note"><b>Device limits are not being enforced.</b> In the last 24 hours FreeRADIUS accepted these logins on devices the user is not allowed to use:
    <ul>${radViolations.map(v=>`<li><b>${esc(v.username)}</b> on ${esc(v.device||"unknown device")} <span class="m">(${esc(v.ip)})</span> - ${v.count} login${v.count===1?"":"s"}, last at ${esc(v.last)}</li>`).join("")}</ul>
    (An entry disappears as soon as FreeRADIUS refuses that user on that device, and after 24 hours at the latest.)<br>
    Usually the "where this user can log in" rule is not installed in FreeRADIUS. Install it once on the server (this also checks and restarts FreeRADIUS):
    <code>sudo bash /opt/vault/deploy/install.sh</code>If the rule is installed, the device sends its requests from a different address than the one in NAS Clients: register that address.</div>`:"";
}
function renderRadUsers(){
  paintRadViolations();
  const q=$("#radQ").value.trim().toLowerCase(),lv=$("#radLevel").value;
  const list=radUsers.filter(u=>(lv==="ALL"||u.level===lv)&&(!q||u.username.toLowerCase().includes(q)));
  radKpis("#radUserKpis",[["RADIUS users",radUsers.length,"All access levels"],...radLevels.map(l=>[lvLabel(l),radUsers.filter(u=>u.level===l).length,RAD_LEVEL_NOTE[l]||"Access level"])]);
  $("#radUserCount").textContent=`${list.length} of ${radUsers.length} users`;
  const {rows,bar}=paginate("radUsers",list);
  $("#radUserList").innerHTML=list.length?`<div class="tbl"><table><thead><tr><th>Username</th><th>Access level</th><th>Can log in on</th><th></th></tr></thead><tbody>`+
    rows.map(u=>`<tr><td><span class="dn">${esc(u.username)}</span></td><td>${lvPill(u.level)}</td><td>${radScope(u)}</td>
     <td class="acts"><button class="link" type="button" data-rad-edit="${esc(u.username)}">Edit</button><button class="link d" type="button" data-rad-del="${esc(u.username)}">Delete</button></td></tr>`).join("")+`</tbody></table></div>`+bar
    :`<div class="empty"><b>${radUsers.length?"No matching users":"No RADIUS users yet"}</b>${radUsers.length?"Try changing the search or the access level.":"Use Add user to create the first device login."}</div>`;
}
/* Access is granted by device TYPE (follows the type: a device of that type added later is included at once)
   and/or by individual device. Both empty = every device. Types compare without case, like the server. */
const radDevName=ip=>(radDevices.find(d=>d.ip===ip)||{}).name||ip;
const radTypeKey=t=>String(t||"Other").trim().toLowerCase();
const radDevsOfType=t=>radDevices.filter(d=>d.single&&radTypeKey(d.role)===radTypeKey(t));
const radPlural=(n,w)=>`${n} ${w}${n===1?"":"s"}`;
/* "Can log in on" column: the types (with how many devices they cover now), then single devices */
function radScope(u){
  const types=u.types||[],ips=u.devices||[];
  if(!types.length&&!ips.length)return '<span class="none">All devices</span>';
  const tags=types.map(t=>`<span class="tag ty" title="Every ${esc(t)}, including ones added later">${esc(t)} &middot; ${radDevsOfType(t).length}</span>`)
    .concat(ips.map(ip=>`<span class="tag" title="${esc(ip)}">${esc(radDevName(ip))}</span>`));
  const now=u.effective||[];
  const none=types.length&&!now.length?' <span class="none" title="No device of these types is registered yet">no device yet</span>':"";
  return tags.slice(0,4).join(" ")+(tags.length>4?` <span class="none">+${tags.length-4} more</span>`:"")+none;
}
/* the "Where this user can log in" drop-down: search, "All devices", device types, individual devices.
   A device covered by a ticked type shows ticked + "via <type>" and cannot be unticked on its own.
   Network entries (10.0.0.0/24) cannot be picked one by one. */
function radPickList(access){
  const types=[...radRoles];
  (access.types||[]).forEach(t=>{if(!types.some(x=>radTypeKey(x)===radTypeKey(t)))types.push(t)});
  const wantT=new Set((access.types||[]).map(radTypeKey)),wantD=new Set(access.devices||[]);
  $("#ruPickQ").value="";
  $("#ruTypeList").innerHTML=types.map(t=>{const n=radDevsOfType(t).length;
    return `<label class="ck" data-q="${esc(t.toLowerCase())}"><input type="checkbox" data-type="${esc(t)}"${wantT.has(radTypeKey(t))?" checked":""}> <span>${esc(t)}</span><small>${n?radPlural(n,"device"):"none yet"}</small></label>`}).join("");
  $("#ruDevList").innerHTML=radDevices.length?radDevices.map(d=>`<label class="ck${d.single?"":" off"}" data-q="${esc(`${d.name} ${d.ip} ${d.role||""}`.toLowerCase())}"><input type="checkbox" value="${esc(d.ip)}" data-role="${esc(d.role||"Other")}" data-explicit="${wantD.has(d.ip)?1:0}"${d.single?"":" disabled"}> <span>${esc(d.name)}</span><small>${esc(d.ip)}${d.single?"":" (network entry)"}</small></label>`).join("")
    :'<p class="pk-none">No RADIUS devices yet. Add them under Devices (NAS) first.</p>';
  $("#ruPick").open=false;radPickFilter();radPickPaint();
}
const radPickedTypes=()=>[...$("#ruTypeList").querySelectorAll("input[data-type]:checked")].map(i=>i.dataset.type);
/* devices picked one by one (those also covered by a ticked type are left out: the type already gives them) */
const radPicked=()=>[...$("#ruDevList").querySelectorAll("input[value]")].filter(i=>i.dataset.explicit==="1"&&!i.dataset.via).map(i=>i.value);
function radPickPaint(){
  const types=radPickedTypes(),keys=new Set(types.map(radTypeKey));
  const live=new Set();
  $("#ruDevList").querySelectorAll("input[value]").forEach(i=>{
    const lb=i.closest("label");if(lb.classList.contains("off"))return;   /* network entry: never pickable */
    const cov=keys.has(radTypeKey(i.dataset.role));
    let via=lb.querySelector(".via");
    if(cov){
      i.dataset.via="1";i.checked=true;i.disabled=true;lb.classList.add("cov");
      if(!via){via=document.createElement("span");via.className="via";lb.querySelector("span").after(via)}
      via.textContent="via "+i.dataset.role;
    }else{
      delete i.dataset.via;if(via)via.remove();
      lb.classList.remove("cov");i.disabled=false;i.checked=i.dataset.explicit==="1";
    }
    if(i.checked)live.add(i.value);
  });
  const ips=radPicked(),all=!types.length&&!ips.length;
  $("#ruPickBody").querySelector("[data-all]").checked=all;
  const parts=[...types,...(ips.length<=2?ips.map(radDevName):[radPlural(ips.length,"device")])];
  $("#ruPickTx").textContent=all?"All devices":parts.join(", ");
  const note=$("#ruAccessNote");
  note.classList.toggle("warn",!all&&!live.size);
  note.textContent=all?"No limit: this user can log in on every RADIUS device, including ones added later."
    :!live.size?"No device of the chosen type is registered yet, so this user cannot log in anywhere until one is added."
    :`Can log in on ${radPlural(live.size,"device")} now`+(types.length?`; new ${types.join(" / ")} devices are included automatically.`:".");
}
/* search filters both lists; a section with no match is hidden */
function radPickFilter(){
  const q=$("#ruPickQ").value.trim().toLowerCase();let shown=0;
  [["#ruTypeSec","#ruTypeList"],["#ruDevSec","#ruDevList"]].forEach(([sec,list])=>{
    let n=0;$(list).querySelectorAll("label[data-q]").forEach(lb=>{const ok=!q||lb.dataset.q.includes(q);lb.hidden=!ok;if(ok)n++});
    $(sec).hidden=!!q&&!n;shown+=n;
  });
  $("#ruPickBody").querySelector("[data-all]").closest("label").hidden=!!q;
  $("#ruPickNone").hidden=!q||!!shown;
}
$("#ruPickQ").addEventListener("input",radPickFilter);
$("#ruPickQ").addEventListener("keydown",e=>{if(e.key==="Enter")e.preventDefault()});   /* Enter must not submit the user form */
$("#ruPickBody").addEventListener("change",e=>{
  const t=e.target;if(t.id==="ruPickQ")return;
  if(t.matches("[data-all]")){
    if(t.checked){$("#ruTypeList").querySelectorAll("input:checked").forEach(i=>i.checked=false);$("#ruDevList").querySelectorAll("input[value]").forEach(i=>i.dataset.explicit="0")}
    else t.checked=true;                                         /* "All" cannot be cleared on its own */
  }else if(t.matches("input[value]"))t.dataset.explicit=t.checked?"1":"0";
  radPickPaint();
});
document.addEventListener("click",e=>{const p=$("#ruPick");if(p.open&&!p.contains(e.target))p.open=false});   /* click outside closes the drop-down */
const rudlg=$("#rudlg"),rufrm=$("#rufrm");let radEdit=null;
function openRadUser(u){
  radEdit=u?u.username:null;rufrm.reset();const f=rufrm.elements;
  $("#ruTitle").textContent=u?"Edit RADIUS user":"Add RADIUS user";
  f.username.value=u?u.username:"";f.username.readOnly=!!u;
  const want=u?u.level:"read-only";if(radLevels.includes(want))f.level.value=want;
  f.password.required=!u;f.password.type="password";f.password.placeholder=u?"Leave empty to keep the current password":"At least 8 characters";
  rudlg.querySelector(".eye").textContent="Show";
  radPickList({types:u&&u.types||[],devices:(u&&u.devices||[]).filter(ip=>radDevices.some(d=>d.ip===ip&&d.single))});
  rudlg.showModal();
}
$o("#radAddUser").onclick=()=>radDown?toast(radDown):openRadUser();
$o("#radUserRefresh").onclick=loadRadUsers;
$o("#radQ").oninput=$o("#radLevel").onchange=()=>{PAGES.radUsers=1;renderRadUsers()};
rufrm.onsubmit=async e=>{
  e.preventDefault();const f=rufrm.elements;
  const b={username:f.username.value.trim(),level:f.level.value,password:f.password.value,devices:radPicked(),types:radPickedTypes()};   /* both [] = all devices */
  try{
    await api(radEdit?"/api/radius/users/"+encodeURIComponent(radEdit):"/api/radius/users",J(radEdit?"PUT":"POST",b));
    sfx.play(radEdit?"ok":"add");rudlg.close();toast(radEdit?"The changes apply to the next device login.":"The new login can be used on the selected devices.",{title:radEdit?"RADIUS user updated":"RADIUS user added"});loadRadUsers();
  }catch(err){toast(err.message,{type:"error"})}
};

/* ---- RADIUS devices (NAS) ---- */
async function loadRadNas(){
  try{
    const d=await api("/api/radius/nas");radDown="";radNas=d.devices;radVendors=d.vendors;radRoles=d.roles||radRoles;
    /* new / removed switches only take effect after FreeRADIUS restarts: warn if the app is not allowed to restart it */
    let warn=$("#radReloadWarn");if(!warn){warn=document.createElement("div");warn.id="radReloadWarn";$("#radNasList").before(warn)}
    warn.innerHTML=d.reload_ok===false?`<div class="rad-note"><b>New switches will not work until FreeRADIUS is restarted by hand.</b>
      FreeRADIUS reads this list only when it starts, and this application is not allowed to restart it. Allow it once on the server:
      <code>sudo bash /opt/vault/deploy/install.sh</code>(or install deploy/radius/sudoers-dbms.example as /etc/sudoers.d/vault-radius). Until then run <i>sudo systemctl restart freeradius</i> after adding or removing a switch.</div>`:"";
    $("#rnfrm").elements.vendor.innerHTML=radOptions(radVendors);
    paintRadRoleList();
    renderRadNas();
  }catch(e){radFail("#radNasList","RADIUS devices",e)}
}
function renderRadNas(){
  const vendor=k=>(radVendors.find(v=>v.key===k)||{}).label||k||"-";
  const q=$("#radNasQ").value.trim().toLowerCase();
  const list=radNas.filter(d=>!q||`${d.name} ${d.nasname} ${vendor(d.vendor)} ${d.role||""} ${d.description}`.toLowerCase().includes(q));
  $("#radNasCount").textContent=`${list.length} of ${radNas.length} devices`;
  const {rows,bar}=paginate("radNas",list);
  $("#radNasList").innerHTML=list.length?`<div class="tbl"><table><thead><tr><th>Name</th><th>IP / network</th><th>Vendor</th><th>Device type</th><th>Shared secret</th><th>Description</th><th></th></tr></thead><tbody>`+
    rows.map(d=>{const on=radShown.has(d.id);return `<tr><td><span class="dn">${esc(d.name)}</span></td><td class="m">${esc(d.nasname)}</td><td><select class="rad-type" data-rad-vendor="${d.id}" aria-label="Vendor of ${esc(d.name)}">${radVendors.map(v=>`<option value="${esc(v.key)}"${v.key===d.vendor?" selected":""}>${esc(v.label)}</option>`).join("")}${radVendors.some(v=>v.key===d.vendor)?"":`<option selected>${esc(vendor(d.vendor))}</option>`}</select></td>
     <td><input class="rad-role-edit" data-rad-role="${d.id}" list="radRoleList" autocomplete="off" maxlength="50" aria-label="Device type of ${esc(d.name)}" value="${esc(d.role||"Other")}"></td>
     <td class="rad-sec">${on?`<code>${esc(radSecrets.get(d.id)||"")}</code>`:`<span class="dots" aria-label="Hidden">&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;</span>`}<button class="link" type="button" data-rad-show="${d.id}">${on?"Hide":"Show"}</button><button class="link" type="button" data-rad-copy="${d.id}">Copy</button></td>
     <td>${d.description?esc(d.description):'<span class="none">-</span>'}</td>
     <td class="acts"><button class="link d" type="button" data-rad-nasdel="${d.id}">Remove</button></td></tr>`}).join("")+`</tbody></table></div>`+bar
    :`<div class="empty"><b>${radNas.length?"No matching devices":"No RADIUS devices yet"}</b>${radNas.length?"Try changing the search.":"Use Add device to register the first switch, router or firewall."}</div>`;
}
/* vendor / device type are changed in place; vendor applies from the next login (FreeRADIUS reads nas.type on
   every request, e.g. Huawei levels 0-3); device type is a VAULT-only grouping, nothing to reload either way */
document.addEventListener("change",async e=>{
  const sel=e.target.closest("[data-rad-vendor],[data-rad-role]");if(!sel)return;
  const isRole=sel.dataset.radRole!==undefined;
  const d=radNas.find(x=>x.id===Number(isRole?sel.dataset.radRole:sel.dataset.radVendor));if(!d)return;
  const prev=isRole?d.role:d.vendor;
  const value=isRole?sel.value.trim()||"Other":sel.value;
  if(isRole&&value===prev)return;
  try{
    await api("/api/radius/nas/"+d.id,J("PATCH",isRole?{role:value}:{vendor:value}));
    const label=isRole?value:sel.options[sel.selectedIndex].text;
    if(isRole){d.role=value;sel.value=value;if(!radRoles.includes(value)){radRoles.push(value);paintRadRoleList()}}else d.vendor=value;
    toast(`${d.name} is now "${label}".`+(isRole?"":" Applies from the next login, no restart needed."),{title:isRole?"Device type changed":"Vendor changed"});
  }catch(err){sel.value=prev;toast(err.message,{type:"error"})}
});
const RAD_RESTART_FAILED="but the FreeRADIUS restart failed. Run: systemctl restart freeradius";
const rndlg=$("#rndlg"),rnfrm=$("#rnfrm");
$o("#radAddNas").onclick=()=>{if(radDown)return toast(radDown);rnfrm.reset();rnCount();rndlg.showModal()};
/* one device or several: comma-separated IPs and names, in the same order (the server checks them again) */
const rnList=v=>String(v||"").split(/[,;\n]+/).map(x=>x.trim()).filter(Boolean);
const RN_HELP="One device: one IP and one name. Several: separate them with commas, names in the same order as the IPs. Leave Name empty to use the IPs as names.";
function rnCount(){
  const f=rnfrm.elements,ips=rnList(f.nasname.value),names=rnList(f.name.value),box=$("#rnCount"),btn=$("#rnSubmit");
  const dup=ips.length-new Set(ips).size;
  let text=RN_HELP,bad=false;
  if(ips.length>1||names.length>1){
    bad=names.length>0&&names.length!==ips.length;
    text=`${ips.length} IP address${ips.length===1?"":"es"} · ${names.length?names.length+" name"+(names.length===1?"":"s"):"names = the IPs"}`+
         (bad?` - give one name per IP, in the same order.`:"")+(dup?` · ${dup} listed twice (added once).`:"");
  }
  box.textContent=text;box.classList.toggle("bad",bad);
  btn.textContent=ips.length>1?`Add ${ips.length} devices`:"Add device";
}
["nasname","name"].forEach(n=>rnfrm.elements[n].addEventListener("input",rnCount));
$o("#radNasRefresh").onclick=loadRadNas;
$o("#radNasQ").oninput=()=>{PAGES.radNas=1;renderRadNas()};
rnfrm.onsubmit=async e=>{
  e.preventDefault();const f=rnfrm.elements;
  const b={name:f.name.value.trim(),nasname:f.nasname.value.trim(),vendor:f.vendor.value,role:f.role.value,secret:f.secret.value.trim(),description:f.description.value.trim()};
  const ips=rnList(b.nasname),names=rnList(b.name);
  if(names.length&&names.length!==ips.length)return toast(`You entered ${ips.length} IP addresses and ${names.length} names. Give one name per IP, in the same order, or leave Name empty.`,{type:"warning",title:"Names do not match the IPs"});
  try{
    const r=await api("/api/radius/nas",J("POST",b));
    const added=r.added||[{id:r.id}],n=added.length;
    added.forEach(d=>{radSecrets.set(d.id,r.secret);radShown.add(d.id)});   /* show the shared secret so it can be copied to the devices */
    sfx.play(r.reloaded?"add":"warn");rndlg.close();
    const what=n===1?"The device":`All ${n} devices`;
    toast(!r.reloaded?`${n===1?"Device":n+" devices"} added, `+RAD_RESTART_FAILED:
          (r.restarted?"FreeRADIUS restarted; ":"")+`${what} can log users in right away. Configure the shared secret shown in the list on ${n===1?"the switch":"each switch"}.`,
          {type:r.reloaded?"success":"warning",title:r.reloaded?(n===1?"Device added":`${n} devices added`):"Added - action needed"});
    if(r.skipped&&r.skipped.length)toast(r.skipped.slice(0,6).map(x=>`${x.nasname}: ${x.reason}`).join("; ")+(r.skipped.length>6?` and ${r.skipped.length-6} more`:"")+".",
          {type:"warning",title:`${r.skipped.length} skipped`});
    loadRadNas();
  }catch(err){toast(err.message,{type:"error"})}
};
async function radCopy(text){
  try{await navigator.clipboard.writeText(text);toast("Paste it into the RADIUS settings of the device.",{type:"info",title:"Shared secret copied"})}
  catch(e){toast("Copy is not available here. Use Show and copy it by hand.")}
}
document.addEventListener("click",async e=>{
  const t=e.target.closest("[data-rad-edit],[data-rad-del],[data-rad-show],[data-rad-copy],[data-rad-nasdel]");if(!t)return;
  const ds=t.dataset;
  if(ds.radEdit!==undefined){const u=radUsers.find(x=>x.username===ds.radEdit);if(u)openRadUser(u);return}
  if(ds.radDel!==undefined){
    const name=ds.radDel;
    if(await confirmAction({title:"Delete this RADIUS user?",message:"They will no longer be able to log in to the network devices.",detail:name,confirm:"Delete user",run:()=>api("/api/radius/users/"+encodeURIComponent(name),{method:"DELETE"})})){toast("The login was removed; it can no longer sign in to network devices.",{title:"RADIUS user deleted"});sfx.play("del");loadRadUsers()}
    return;
  }
  const d=radNas.find(x=>x.id===Number(ds.radShow??ds.radCopy??ds.radNasdel));if(!d)return;
  if(ds.radShow!==undefined){
    if(radShown.has(d.id))radShown.delete(d.id);
    else{try{await radSecret(d.id)}catch(err){return toast(err.message,{type:"error"})}radShown.add(d.id)}
    renderRadNas();return;
  }
  if(ds.radCopy!==undefined){try{radCopy(await radSecret(d.id))}catch(err){toast(err.message,{type:"error"})}return}
  let res=null;
  if(await confirmAction({title:"Remove this RADIUS device?",message:"It will no longer be able to authenticate logins against this server. FreeRADIUS restarts.",detail:`${d.name} (${d.nasname})`,confirm:"Remove device",run:async()=>{res=await api("/api/radius/nas/"+d.id,{method:"DELETE"})}})){
    radShown.delete(d.id);radSecrets.delete(d.id);sfx.play("del");toast(res&&res.reloaded===false?"Device removed, "+RAD_RESTART_FAILED:"Device removed. FreeRADIUS restarted.");loadRadNas();
  }
});

/* ---- Device Setup (/radius/setup): copy-ready RADIUS configuration per vendor ----
   Filled with this server's address and, on request, the chosen device's shared secret (the secret is fetched
   only when "Insert" is pressed, through the same audited endpoint as Show / Copy on NAS Clients). */
const SU={dev:null,tab:"cisco",codes:[]};
const SU_SECRET="<SHARED-SECRET>";
const COPY_IC='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>';
const COPY_DONE_IC='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
/* step = [title, explanation, code] ; code "" = text only */
const SU_VENDORS=[
  {key:"cisco",label:"Cisco",match:["cisco"],steps:v=>[
    ["RADIUS server and login order","Run in configuration mode. local = the switch's own accounts, used only when the RADIUS server cannot be reached.",
`aaa new-model
radius server VAULT
 address ipv4 ${v.server} auth-port 1812 acct-port 1813
 key ${v.secret}
aaa group server radius VAULT-GRP
 server name VAULT
aaa authentication login default group VAULT-GRP local
aaa authorization exec default group VAULT-GRP local
aaa accounting exec default start-stop group VAULT-GRP
line vty 0 15
 login authentication default
 authorization exec default`],
    ["Send RADIUS from the registered address",`Only when the switch has several addresses: requests must come from ${v.ip}, the address in NAS Clients. Put the interface that holds it in place of Vlan1.`,
`ip radius source-interface Vlan1`],
    ["Test",`Replace user / password with a VAULT AAA user. Super-admin gets privilege 15, Read-write 7, Read-only 1.`,
`test aaa group VAULT-GRP user password legacy
show aaa servers`]]},
  {key:"huawei",label:"Huawei",match:["huawei","huawei-3"],steps:v=>[
    ["RADIUS template","Run in system-view.",
`radius-server template VAULT
 radius-server shared-key cipher ${v.secret}
 radius-server authentication ${v.server} 1812
 radius-server accounting ${v.server} 1813
 quit`],
    ["Use it for admin logins","radius local = the switch's own accounts only when the RADIUS server does not answer. Newer models have vty 0 14 instead of 0 4.",
`aaa
 authentication-scheme VAULT
  authentication-mode radius local
  quit
 accounting-scheme VAULT
  accounting-mode radius
  quit
 domain default_admin
  authentication-scheme VAULT
  accounting-scheme VAULT
  radius-server VAULT
  quit
 quit
user-interface vty 0 4
 authentication-mode aaa
 quit`],
    ["Test",`Super-admin gets level 15, Read-write 2, Read-only 1. A switch that only has levels 0-3: set its vendor to "Huawei (levels 0-3 only)" in NAS Clients.`,
`test-aaa user password radius-template VAULT`]]},
  {key:"mikrotik",label:"MikroTik",match:["mikrotik"],steps:v=>[
    ["RADIUS server and login","VAULT sends the group full, write or read; these groups exist on every RouterOS.",
`/radius add address=${v.server} secret="${v.secret}" service=login timeout=3s
/user aaa set use-radius=yes default-group=read`],
    ["Good to know","RouterOS checks its local users first: a local user with the same name as a VAULT user hides the RADIUS one. Behind NAT, register the NAT address in NAS Clients. If the server log shows no error but the login still fails, the router is waiting for a Message-Authenticator in the answer:",
`/radius set [find address=${v.server}] require-message-auth=no`],
    ["Test","Log in with a VAULT AAA user (SSH, Winbox or web), then:",`/user active print`]]},
  {key:"fortigate",label:"FortiGate",match:["fortinet"],steps:v=>[
    ["RADIUS server",`source-ip = the address in NAS Clients (${v.ip}).`,
`config user radius
    edit "VAULT"
        set server "${v.server}"
        set secret "${v.secret}"
        set auth-type pap
        set source-ip "${v.ip}"
    next
end`],
    ["Read-only profile","FortiGate has no read-only administrator profile by default.",
`config system accprofile
    edit "vault_ro"
        set secfabgrp read
        set ftviewgrp read
        set authgrp read
        set sysgrp read
        set netgrp read
        set loggrp read
        set fwgrp read
        set vpngrp read
        set utmgrp read
        set wifi read
    next
end`],
    ["Groups and administrators","VAULT sends the group name super_admin, rw_admin or ro_admin; each group lets those users in with the matching profile.",SU_FORTI_GROUPS("prof_admin")],
    ["Test","Keep your local admin session open while testing.",`diagnose test authserver radius VAULT pap user password`]]},
  {key:"fortiswitch",label:"FortiSwitch",match:[],steps:v=>[
    ["RADIUS server","",
`config user radius
    edit "VAULT"
        set server "${v.server}"
        set secret "${v.secret}"
        set auth-type pap
    next
end`],
    ["Profiles","FortiSwitch profile fields differ from FortiGate. vault_rw may change ports, VLANs and routing, not accounts or system settings.",
`config system accprofile
    edit "vault_ro"
        set admingrp read
        set exec-alias-grp read
        set loggrp read
        set netgrp read
        set routegrp read
        set sysgrp read
    next
    edit "vault_rw"
        set admingrp read
        set exec-alias-grp read
        set loggrp read
        set netgrp read-write
        set routegrp read-write
        set sysgrp read
    next
end`],
    ["Groups and administrators","A local account with the same name (for example admin) is always checked locally, never through RADIUS.",SU_FORTI_GROUPS("vault_rw")],
    ["Test","Keep your local admin session open while testing.",`diagnose test authserver radius VAULT pap user password`]]},
  {key:"juniper",label:"Juniper",match:["juniper"],steps:v=>[
    ["RADIUS server and login order","Configuration mode.",
`set system radius-server ${v.server} secret "${v.secret}"
set system radius-server ${v.server} source-address ${v.ip}
set system authentication-order [ radius password ]
set system accounting events [ login interactive-commands ]
set system accounting destination radius`],
    ["Template accounts","VAULT sends the account name super-user, operator or read-only; Junos logs the user in with the rights of that local template account (no password needed on it).",
`set system login user super-user class super-user
set system login user operator class operator
set system login user read-only class read-only
commit`],
    ["Test","Log in with a VAULT AAA user, then:",`show system users`]]},
  {key:"bdcom",label:"BDCOM",match:["bdcom"],check:true,steps:v=>[
    ["RADIUS server and login order","Cisco-style CLI, configuration mode.",
`radius-server host ${v.server} auth-port 1812 acct-port 1813
radius-server key ${v.secret}
aaa authentication login default radius local
aaa authorization exec default radius local
aaa accounting exec default start-stop radius
line vty 0 4
 login authentication default`],
    ["Test","Log in with a VAULT AAA user and check the level you get. VAULT sends the Cisco privilege (15, 7 or 1); if your model ignores it, users land on its default level.",`show privilege`]]},
  {key:"vsol",label:"V-SOL",match:["vsol"],check:true,steps:v=>[
    ["Values to enter",`V-SOL OLTs set RADIUS in the web interface (System / AAA or Management / RADIUS) or the CLI, with names that differ per model. Enter these values:`,
`RADIUS server:      ${v.server}
Authentication port: 1812
Accounting port:     1813
Shared secret:       ${v.secret}
Login order:         RADIUS first, then local accounts`],
    ["Test","Log in with a VAULT AAA user, then check the result on Authentication Audit. Keep a local admin account in case the server cannot be reached.",""]]},
];
function SU_FORTI_GROUPS(rw){
  const grp=(name,match)=>`    edit "${name}"
        set member "VAULT"
        config match
            edit 1
                set server-name "VAULT"
                set group-name "${match}"
            next
        end
    next`;
  const adm=(name,prof)=>`    edit "${name}"
        set remote-auth enable
        set wildcard enable
        set remote-group "${name}"
        set accprofile "${prof}"
    next`;
  return `config user group
${grp("vault-super","super_admin")}
${grp("vault-rw","rw_admin")}
${grp("vault-ro","ro_admin")}
end
config system admin
${adm("vault-super","super_admin")}
${adm("vault-rw",rw)}
${adm("vault-ro","vault_ro")}
end`;
}
async function loadRadSetup(){
  try{
    const d=await api("/api/radius/nas");radDown="";radNas=d.devices;radVendors=d.vendors;radRoles=d.roles||radRoles;
    const sel=$("#suDev"),keep=sel.value;
    sel.innerHTML=`<option value="">Choose a device from NAS Clients...</option>`+radNas.map(n=>`<option value="${n.id}">${esc(n.name)} (${esc(n.nasname)})</option>`).join("");
    sel.value=radNas.some(n=>String(n.id)===keep)?keep:"";
    if(!$("#suServer").value)$("#suServer").value=location.hostname;
    $("#suTabs").innerHTML=SU_VENDORS.map(x=>`<button type="button" class="chip" role="tab" data-su-tab="${x.key}">${esc(x.label)}</button>`).join("");
    suPickDevice();
  }catch(e){radFail("#suBody","the device list",e)}
}
function suPickDevice(){
  SU.dev=radNas.find(n=>String(n.id)===$("#suDev").value)||null;
  $("#suSecret").value="";$("#suSecretBtn").disabled=!SU.dev;
  if(SU.dev){
    const role=(SU.dev.role||"").toLowerCase(),v=SU.dev.vendor;
    const hit=v==="fortinet"&&role.includes("switch")?"fortiswitch":(SU_VENDORS.find(x=>x.match.includes(v))||{}).key;
    if(hit)SU.tab=hit;
  }
  suRender();
}
function suRender(){
  const server=$("#suServer").value.trim()||"<RADIUS-SERVER>",secret=$("#suSecret").value.trim()||SU_SECRET;
  const ip=SU.dev?SU.dev.nasname:"<DEVICE-IP>",vendor=SU_VENDORS.find(x=>x.key===SU.tab)||SU_VENDORS[0];
  $("#suTabs").querySelectorAll("[data-su-tab]").forEach(b=>{const on=b.dataset.suTab===vendor.key;b.classList.toggle("on",on);b.setAttribute("aria-selected",on)});
  $("#suNote").textContent=!SU.dev?"Choose the device first: it must be in NAS Clients with the address its requests come from (behind NAT: the NAT address).":
    secret===SU_SECRET?`Press Insert to put ${SU.dev.name}'s shared secret into the commands, or leave ${SU_SECRET} and paste it yourself.`:"";
  SU.codes=[];
  const lang=vendor.key==="vsol"?"Values":`${vendor.label} CLI`;
  const steps=vendor.steps({server,secret,ip}).map(([title,text,code])=>{
    const i=code?SU.codes.push(code)-1:-1;
    return `<li class="su-step"><div class="su-h"><h4>${esc(title)}</h4></div>
      ${text?`<p>${esc(text)}</p>`:""}
      ${code?`<div class="su-code"><div class="su-code-top"><span class="su-lang">${esc(lang)}</span><button class="su-cp" type="button" data-su-copy="${i}">${COPY_IC}Copy</button></div><pre>${esc(code)}</pre></div>`:""}</li>`}).join("");
  $("#suBody").innerHTML=`<div class="card su-steps-card">
    ${vendor.check?`<div class="rad-note"><b>Check these commands against your firmware.</b> ${esc(vendor.label)} command names differ between models and software versions; the values (server, ports, secret, login order) are what matters.</div>`:""}
    <ol class="su-steps">${steps}</ol>
    <p class="su-foot"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg><span>Keep a local admin account on the device for when the server cannot be reached, never give a VAULT user the same name as a local account, and check each first login on Authentication Audit.</span></p></div>`;
}
$o("#suDev").addEventListener("change",suPickDevice);
$o("#suServer").addEventListener("input",suRender);
$o("#suSecret").addEventListener("input",suRender);
$o("#suTabs").addEventListener("click",e=>{const b=e.target.closest("[data-su-tab]");if(b){SU.tab=b.dataset.suTab;suRender()}});
$o("#suSecretBtn").addEventListener("click",async()=>{
  if(!SU.dev)return;
  try{$("#suSecret").value=await radSecret(SU.dev.id);suRender()}catch(err){toast(err.message,{type:"error"})}
});
$o("#suBody").addEventListener("click",async e=>{
  const b=e.target.closest("[data-su-copy]");if(!b)return;
  const text=SU.codes[Number(b.dataset.suCopy)]||"";
  let ok=false;
  try{await navigator.clipboard.writeText(text);ok=true}
  catch(err){const t=document.createElement("textarea");t.value=text;t.style.cssText="position:fixed;opacity:0";document.body.append(t);t.select();try{ok=document.execCommand("copy")}catch(x){}t.remove()}
  if(ok){b.classList.add("done");b.innerHTML=COPY_DONE_IC+"Copied";setTimeout(()=>{if(b.isConnected){b.classList.remove("done");b.innerHTML=COPY_IC+"Copy"}},1600)}
  else toast("Copy is not available here. Select the text and press Ctrl+C.",{type:"warning",title:"Copy failed"});
});

/* ---- RADIUS audit: panel actions + recent device logins ---- */
let radLoggingOn=true;
async function loadRadAudit(){
  const q=($("#radLoginQ")?.value||"").trim();
  try{const d=await api("/api/radius/audit"+(q?"?q="+encodeURIComponent(q):""));radEvents=d.events;radLogins=d.logins;radLoggingOn=d.device_logging!==false;renderRadEvents();renderRadLogins()}
  catch(e){radFail("#radEventList","the RADIUS audit log",e);$("#radLoginList").innerHTML="";$("#radAuditKpis").innerHTML=""}
}
/* search runs on the server (user, device IP, or a device name from NAS Clients / Device Inventory) */
let radLoginT=0;
$("#radLoginQ")?.addEventListener("input",()=>{clearTimeout(radLoginT);radLoginT=setTimeout(()=>{PAGES.radLogins=1;loadRadAudit()},350)});
$("#radLoginRes")?.addEventListener("change",()=>{PAGES.radLogins=1;renderRadLogins()});
const radAccepted=r=>/accept/i.test(r.reply||"");
function renderRadEvents(){
  const ok=radLogins.filter(radAccepted).length,bad=radLogins.length-ok;
  radKpis("#radAuditKpis",[["Panel actions",radEvents.length,"Most recent changes"],["Recent logins",radLogins.length,"Latest requests"],["Accepted",ok,"Access-Accept","g"],["Rejected",bad,"Access-Reject",bad?"bad":""]]);
  if(!radEvents.length){$("#radEventList").innerHTML=`<div class="empty">No panel actions recorded yet.</div>`;return}
  const {rows,bar}=paginate("radEvents",radEvents);
  $("#radEventList").innerHTML=`<div class="tbl"><table><thead><tr><th>Time</th><th>Admin</th><th>Action</th><th>Target</th><th>Detail</th><th>Source IP</th></tr></thead><tbody>`+
    rows.map(r=>`<tr><td class="when">${esc(r.ts||"-")}</td><td><strong>${esc(r.actor||"-")}</strong></td><td><span class="tag">${esc(r.action||"-")}</span></td><td>${esc(r.target||"-")}</td><td class="log-message">${esc(r.detail||"-")}</td><td class="m">${esc(r.ip||"-")}</td></tr>`).join("")+`</tbody></table></div>`+bar;
}
function renderRadLogins(){
  $("#radLoginNote").innerHTML=radLoggingOn?"":`<div class="rad-note"><b>The device is not recorded yet.</b> FreeRADIUS's standard login table stores only the user, result and time.
    Run this once on the server to record the device of every new login:<code>sudo bash /opt/vault/deploy/radius/enable_login_log.sh</code>Logins before that keep an empty Device column.</div>`;
  const res=$("#radLoginRes")?.value||"ALL";
  const list=radLogins.filter(r=>res==="ALL"||(res==="accept")===radAccepted(r));
  const q=($("#radLoginQ")?.value||"").trim();
  $("#radLoginCount").textContent=radLogins.length?`${list.length} login${list.length===1?"":"s"}${radLogins.length>=500?" (newest 500)":""}`:"";
  if(!list.length){$("#radLoginList").innerHTML=`<div class="empty"><b>${q||res!=="ALL"?"No matching logins":"No device logins recorded yet"}</b>${q||res!=="ALL"?"Try another user, device name or IP.":"Logins appear here when users sign in to the network devices."}</div>`;return}
  const {rows,bar}=paginate("radLogins",list);
  morph($("#radLoginList"),`<div class="tbl"><table><thead><tr><th>Time</th><th>User</th><th>Device</th><th>Result</th></tr></thead><tbody>`+
    rows.map(r=>`<tr data-key="${esc([r.ts,r.username,r.nas_ip,r.reply].join("|"))}"><td class="when">${fmtWhen(r.ts)}</td><td><strong>${esc(r.username||"-")}</strong></td>
      <td>${r.nas_ip||r.device?`<span class="dn">${esc(r.device||r.nas_ip)}</span>${r.nas_ip&&r.device&&r.device!==r.nas_ip?`<span class="sub m">${esc(r.nas_ip)}</span>`:""}`:'<span class="none">Not recorded</span>'}</td>
      <td><span class="pill ${radAccepted(r)?"UP":"DOWN"}">${radAccepted(r)?"Accepted":"Rejected"}</span></td></tr>`).join("")+`</tbody></table></div>`+bar);
}
$o("#radAuditRefresh").onclick=loadRadAudit;
