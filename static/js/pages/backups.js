/* VAULT - pages/backups.js
   Configuration Backups page (/backups), one device's own backup page (/devices/<id>), and the viewer / compare pop-up.
   Loaded by templates/base.html on every screen; all scripts share one global scope (see core/helpers.js). */

/* ---- backups tab: every saved version per device; view, compare (diff), download or delete ---- */
/* one row = one saved version; prev = the file before it (for "Compare with previous"), "" if none */
const bkAttr=(a,d,f)=>`data-a="${a}" data-d="${esc(d)}" data-f="${esc(f)}"`;
function bkRow(d,f,prev,latest){
  return `<div class="row"><span class="n">${esc(f.name||f.file)}${latest?' <span class="tag">Latest</span>':""}</span><span class="t">${esc(fmtBdDateTime(f.time))} &middot; ${(f.size/1024).toFixed(1)} KB</span>
    <span><button class="link" ${bkAttr("view",d,f.file)}>View</button>
    <a class="link" href="/api/backups/${encodeURIComponent(d)}/${f.file.split("/").map(encodeURIComponent).join("/")}?download=1">Download</a>
    ${prev?`<button class="link" ${bkAttr("diff",d,f.file)} data-p="${esc(prev)}">Compare with previous</button>`:""}
    <button class="link d adm" ${bkAttr("del",d,f.file)}>Delete</button></span></div>`;
}
/* Backups tab: every device shows only its latest backup; older versions load when asked */
let bkData=[],selBk=new Set(),targetBackupDevice=null;
/* bkFocus = folder name of the ONE device opened from the Devices list (null = show every device) */
let bkFocus=null;
const bkVisible=()=>{const q=($("#bkSearch")?.value||"").trim().toLocaleLowerCase();
  return bkData.filter(d=>(!bkFocus||d.name===bkFocus)&&(!q||String(d.name||"").toLocaleLowerCase().includes(q)||String(d.latest?.time||"").toLocaleLowerCase().includes(q)))};
async function loadBackups(){bkData=await api("/api/backups");[...selBk].forEach(n=>{if(!bkData.some(d=>d.name===n))selBk.delete(n)});renderBackups()}
async function renderDeviceTree(tree, box){
  box.innerHTML='<div class="row">Loading dated folders…</div>';
  try{
    if(!tree.years.length){box.innerHTML='<div class="empty"><b>No backup folders yet</b>Run a backup for this device. Scheduled folders will be created on configured dates.</div>';return}
    // Normalize legacy/API data into a consistent Year > short Month > Day hierarchy.
    // This also repairs display when an older cached API shape returns YYYY-MM-DD entries.
    const monthNames=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const normalizedYears=tree.years.map(y=>{
      const groups=new Map();
      (y.months||[]).forEach(m=>{
        const mnum=Number(m.month_number)||monthNames.indexOf(String(m.month))+1;
        if(!mnum||mnum<1||mnum>12)return;
        if(!groups.has(mnum))groups.set(mnum,{month:monthNames[mnum-1],month_number:mnum,days:[]});
        (m.days||[]).forEach(d=>groups.get(mnum).days.push(d));
      });
      (y.days||[]).forEach(d=>{
        const date=String(d.date||""); const match=date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        const mnum=match?Number(match[2]):0;
        if(mnum>=1&&mnum<=12){if(!groups.has(mnum))groups.set(mnum,{month:monthNames[mnum-1],month_number:mnum,days:[]});groups.get(mnum).days.push(d)}
      });
      return {...y,months:[...groups.values()].sort((a,b)=>b.month_number-a.month_number).map(m=>({...m,days:m.days.sort((a,b)=>String(b.date||`${y.year}-${String(m.month_number).padStart(2,"0")}-${a.day}`).localeCompare(String(a.date||`${y.year}-${String(m.month_number).padStart(2,"0")}-${b.day}`)))}))};
    });
    // The Latest marker must follow the newest SAVED configuration file, not the
    // most recent check date. An unchanged run may create a day folder/run.json
    // without creating a new configuration snapshot.
    const allFiles=normalizedYears.flatMap(y=>(y.months||[]).flatMap(m=>(m.days||[]).flatMap(d=>(d.files||[]))));
    const stampOf=f=>{const m=String(f.name||f.file||"").match(/_(\d{8})_(\d{6})\.txt$/i);return m?m[1]+m[2]:""};
    allFiles.sort((a,b)=>stampOf(b).localeCompare(stampOf(a)) || String(b.file||"").localeCompare(String(a.file||"")));
    const latestFilePath=allFiles.length?String(allFiles[0].file||""):"";
    box.innerHTML=normalizedYears.map(y=>`<details class="tree-year"><summary>📁 ${esc(y.year)}</summary>`+
      (y.months||[]).map(m=>`<details class="tree-month"><summary>📁 ${esc(m.month)}</summary>`+
        (m.days||[]).map(d=>{
          const meta=d.metadata||{},files=d.files||[],fullDate=d.date||`${y.year}-${String(m.month_number).padStart(2,"0")}-${d.day}`;
          const sortedFiles=files.slice().sort((a,b)=>String(b.time||b.name).localeCompare(String(a.time||a.name)));
          const isLatest=sortedFiles.some(f=>String(f.file||"")===latestFilePath);
          // Do not show an old configuration-change timestamp under an unchanged date folder.
          const runStatus = String(meta.status || "").toUpperCase();
          const noChange = runStatus === "UNCHANGED" || files.length === 0;
          const changeDate = String(meta.last_change_date || "").slice(0, 10);
          const changedOnThisDay = !noChange && files.length > 0 && changeDate === fullDate;
          const changeLabel = noChange
            ? '<span class="tag nochg">No change</span>'
            : (changedOnThisDay
                ? `<span class="t">Configuration changed: ${esc(meta.last_change_date)}</span>`
                : '<span class="t">Configuration saved on this date</span>');
          return `<div class="tree-day"><div class="tree-day-title">📁 ${esc(d.day)} ${isLatest?'<span class="tag latest-tag">Latest</span>':""}${changeLabel}</div>`+
            (sortedFiles.length?sortedFiles.map(f=>`<div class="row tree-file${String(f.file||"")===latestFilePath?' latest-jump-target':""}"${String(f.file||"")===latestFilePath?' data-latest-file="1"':""}><span class="n">${esc(f.name)}${String(f.file||"")===latestFilePath?' <span class="tag latest-tag">Latest</span>':""}</span><span class="t">${(f.size/1024).toFixed(1)} KB · ${esc(fmtBdDateTime(f.time))}</span><span><button class="link" ${bkAttr("view",tree.device,f.file)}>View</button><a class="link" data-seen="${esc(f.file)}" href="/api/backups/${encodeURIComponent(tree.device)}/${f.file.split("/").map(encodeURIComponent).join("/")}?download=1">Download</a><button class="link d adm" ${bkAttr("del",tree.device,f.file)}>Delete</button></span></div>`).join(""):`<div class="row tree-file"><span class="t">No new configuration file was needed. ${meta.last_change_file ? `Last saved version: ${esc(meta.last_change_file)}` : 'No configuration has been saved yet.'}</span></div>`)+`</div>`;
        }).join("")+`</details>`).join("")+`</details>`).join("");
  }catch(err){box.innerHTML=errorState("Could not load the backup folders",err)}
}

function renderBackups(){
  if(bkFocus&&!bkData.some(d=>d.name===bkFocus))bkFocus=null;      /* folder vanished (deleted) -> back to the full list */
  const filtered=bkVisible();
  const {rows:g,bar}=paginate("backups",filtered);
  const focusBar=bkFocus?`<div class="row" style="background:var(--soft);border:1px solid var(--line);border-radius:8px;margin-bottom:12px;padding:10px 16px;gap:10px;align-items:center"><span>Showing backups of only <b>${esc(bkFocus)}</b></span><span class="sp"></span><button type="button" class="b" data-a="unfocus">Show all devices</button></div>`:"";
  $("#bkList").innerHTML=focusBar+(filtered.length?g.map(d=>{
    const older=d.count-1;
    return `<div class="group"><h3><input type="checkbox" class="bksel" value="${esc(d.name)}"${selBk.has(d.name)?" checked":""} aria-label="Select ${esc(d.name)}"><button class="link tree-open" ${bkAttr("tree",d.name,"")}>📁 ${esc(d.name)}</button><span>${d.count} saved version${d.count===1?"":"s"} &middot; last backup ${esc(fmtBdDateTime(d.latest.time))}</span><button class="link d adm" style="margin-left:auto" ${bkAttr("delall",d.name,"")}>Delete all versions</button></h3>`
      +(d.count?bkRow(d.name,d.latest,d.previous,true):`<div class="row"><span class="t">No configuration backup saved yet.</span></div>`)+`<div class="older"></div><div class="device-tree" data-tree="${esc(d.name)}" hidden></div>`
      +(older?`<div class="row"><button class="link" ${bkAttr("more",d.name,"")} data-n="${older}">Show older versions (${older})</button></div>`:"")+`</div>`;
  }).join("")+bar
  :(bkData.length?`<div class="empty"><b>No matching backups</b>Try another device name or backup date.</div>`:`<div class="empty"><b>No devices yet</b>Add a device first, then its dated backup folders will appear here.</div>`));
  updBk();
  if(targetBackupDevice!==null){
    const device=devs.find(x=>x.id===targetBackupDevice);targetBackupDevice=null;
    if(device){api("/api/backup-tree/"+device.id).then(async tree=>{
      // Ensure the target device is visible even if the Backups tab had a search/filter active.
      if(bkSearchInput && bkSearchInput.value){bkSearchInput.value="";}
      /* show ONLY the clicked device (other devices are hidden until "Show all devices") */
      if(bkData.some(x=>x.name===tree.device)){bkFocus=tree.device;selBk.clear();PAGES.backups=1;renderBackups()}
      const group=[...document.querySelectorAll("#bkList .group")].find(g=>g.querySelector(".tree-open")?.dataset.d===tree.device);
      if(group){
        const box=group.querySelector(".device-tree");
        box.hidden=false;box.dataset.loaded="1";
        await renderDeviceTree(tree,box);
        const latestFile=box.querySelector("[data-latest-file='1']");
        if(latestFile){
          for(let el=latestFile.closest("details");el;el=el.parentElement?.closest("details"))el.open=true;
          latestFile.classList.add("latest-jump-highlight");
          latestFile.scrollIntoView({behavior:"smooth",block:"center"});
          window.setTimeout(()=>latestFile.classList.remove("latest-jump-highlight"),3500);
        }else{
          group.scrollIntoView({behavior:"smooth",block:"start"});
        }
      }
    }).catch(err=>toast(err.message,{type:"error"}))}
  }
}
const bkSearchInput=$("#bkSearch");
if(bkSearchInput){bkSearchInput.addEventListener("input",()=>{bkFocus=null;PAGES.backups=1;renderBackups()});}
const bkSearchClear=$("#bkSearchClear");
if(bkSearchClear){bkSearchClear.addEventListener("click",()=>{if(bkSearchInput)bkSearchInput.value="";bkFocus=null;PAGES.backups=1;renderBackups();bkSearchInput?.focus()});}
/* show or hide the older versions of one device (the list is fetched only the first time it is opened) */
async function toggleOlder(btn,d){
  const box=btn.closest(".group").querySelector(".older"),n=btn.dataset.n;
  if(box.innerHTML){box.innerHTML="";btn.textContent=`Show older versions (${n})`;return}
  const files=await api("/api/backups/"+encodeURIComponent(d));
  box.innerHTML=files.slice(1).map((f,i)=>bkRow(d,f,files[i+2]?files[i+2].file:"",false)).join("");
  btn.textContent="Hide older versions";
}
function bkClick(e){
  const b=e.target.closest("button[data-a]");if(!b)return;
  const {a,d,f,p}=Object.assign({},b.dataset);
  if(a==="tree"){
    const box=b.closest(".group").querySelector(".device-tree");
    if(box.dataset.loaded==="1"){box.hidden=!box.hidden;return}
    const row=bkData.find(x=>x.name===d),deviceId=row&&row.device_id;
    if(!deviceId){toast("This backup folder does not belong to a device in the inventory (it may have been deleted or renamed).",{type:"warning",title:"No device for this folder"});return}
    box.hidden=false;box.dataset.loaded="1";api("/api/backup-tree/"+deviceId).then(tree=>renderDeviceTree(tree,box)).catch(err=>toast(err.message,{type:"error"}));return;
  }
  Promise.resolve(({view:()=>viewFile(d,f),diff:()=>diffFile(d,p,f),del:()=>delFile(d,f),delall:()=>delDevBk(d),more:()=>toggleOlder(b,d),unfocus:()=>{bkFocus=null;PAGES.backups=1;renderBackups()}})[a]()).catch(err=>toast(err.message,{type:"error"}));
}
$o("#bkList").addEventListener("click",bkClick);
$("#devBkDlg").addEventListener("click",e=>{if(e.target===e.currentTarget)e.currentTarget.close();else bkClick(e)});   /* dark area = close */
const E=encodeURIComponent;
/* after a delete: reload the list; if one device is in focus, reopen its dated folders so the file is gone from the tree */
async function afterBkDelete(){
  if(PAGE==="device"&&devPageId!==null)loadDevicePage(devPageId);
  if($("#devBkDlg").open)refreshDeviceBackups();
  if(PAGE!=="backups")return;          /* the list below exists only on the Configuration Backups screen */
  await loadBackups();
  if(!bkFocus)return;
  const row=bkData.find(x=>x.name===bkFocus),box=document.querySelector("#bkList .device-tree");
  if(row&&row.device_id&&box){box.hidden=false;box.dataset.loaded="1";try{renderDeviceTree(await api("/api/backup-tree/"+row.device_id),box)}catch(err){toast(err.message,{type:"error"})}}
}
window.delFile=async(d,f)=>{if(await confirmAction({title:"Delete this backup file?",message:"This version will be removed from disk and cannot be restored.",detail:d+"  /  "+f,confirm:"Delete backup",run:()=>api(`/api/backups/${E(d)}/${f.split("/").map(E).join("/")}`,{method:"DELETE"})})){toast("The selected version was removed from disk.",{title:"Backup deleted"});sfx.play("del");afterBkDelete()}};
window.delDevBk=async d=>{if(await confirmAction({title:"Delete all versions?",message:"Every saved backup of this device will be removed from disk. This cannot be undone.",detail:d,confirm:"Delete all versions",run:()=>api(`/api/backups/${E(d)}`,{method:"DELETE"})})){toast("Every saved version of this device was removed from disk.",{title:"Backups deleted"});sfx.play("del");afterBkDelete()}};
/* select devices in the Backups tab, then download their files as a zip or delete them */
function updBk(){
  const n=[...selBk].filter(name=>bkData.some(d=>d.name===name&&d.count>0)).length;$("#bkCount").textContent=n?n+" selected":"";
  {const v=bkVisible();$("#bkAll").checked=!!v.length&&v.every(d=>selBk.has(d.name))}
  ["#bkDlSel","#bkDlAll","#bkDelSel"].forEach(i=>$(i).disabled=!n);
  $("#bkBar").hidden=!bkData.length;
}
$o("#bkList").addEventListener("change",e=>{if(!e.target.classList.contains("bksel"))return;e.target.checked?selBk.add(e.target.value):selBk.delete(e.target.value);updBk()});
$o("#bkAll").onchange=e=>{bkVisible().forEach(d=>e.target.checked?selBk.add(d.name):selBk.delete(d.name));renderBackups()};
async function dlZip(all){
  const names=[...selBk].filter(name=>bkData.some(d=>d.name===name&&d.count>0));
  if(!names.length)return toast("Tick one or more devices that have saved backups, then download again.",{type:"warning",title:"No backups selected"});
  const button=all?$("#bkDlAll"):$("#bkDlSel");
  const oldLabel=button.textContent;button.disabled=true;button.textContent="Preparing ZIP…";
  try{
    const r=await fetch("/api/backups/download",{method:"POST",headers:headers(true),body:JSON.stringify({names,all})});
    if(r.status===401){location.href="/login";return}
    if(!r.ok){let m="";try{m=(await r.json()).error}catch(e){}throw new Error(m||`Download failed (HTTP ${r.status})`)}
    const blob=await r.blob();
    if(!blob.size)throw new Error("The server returned an empty ZIP. Check that selected devices have saved backups.");
    const cd=r.headers.get("content-disposition")||"";
    const m=cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)/i);
    const filename=m?decodeURIComponent(m[1]||m[2]):(all?"Selected_All_Backups.zip":"Selected_Latest_Backups.zip");
    const url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download=filename;a.style.display="none";document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),15000);
    toast(`ZIP ready: ${filename}`);
  }catch(e){toast(e&&e.message||"The download failed. Please try again.",{type:"error"});console.error("VAULT ZIP download failed",e)}
  finally{button.disabled=false;button.textContent=oldLabel;updBk()}
}
$o("#bkDlSel").onclick=()=>dlZip(false);
$o("#bkDlAll").onclick=()=>dlZip(true);
$o("#bkDelSel").onclick=async()=>{
  if(!selBk.size)return;
  let r;const names=[...selBk];
  if(await confirmAction({title:`Delete backups of ${names.length} device${names.length===1?"":"s"}?`,message:"Every saved version of the selected devices will be removed from disk. This cannot be undone.",detail:names.length>6?names.slice(0,6).join(", ")+` and ${names.length-6} more`:names.join(", "),confirm:"Delete backups",run:async()=>{r=await api("/api/backups/delete",J("POST",{names}))}})){selBk.clear();toast(r.deleted+" backup file(s) deleted");sfx.play("del");loadBackups()}
};
$o("#delBk").onclick=async()=>{let r;if(await confirmAction({title:"Delete ALL backup files?",message:"Every backup of every device will be removed from disk. This cannot be undone.",confirm:"Delete everything",typed:"DELETE",run:async()=>{r=await api("/api/backups/delete-all",{method:"POST"})}})){selBk.clear();toast(r.deleted+" backup file(s) deleted");sfx.play("del");loadBackups()}};
/* ---- device backup pop-up (#devBkDlg): click a device name in the Devices list to see ONLY that device's dated backup folders ---- */
let popDevId=null;
async function refreshDeviceBackups(){
  const box=$("#devBkBody");if(popDevId===null)return;
  try{
    const tree=await api("/api/backup-tree/"+popDevId);
    const files=tree.years.flatMap(y=>(y.months||[]).flatMap(m=>(m.days||[]).flatMap(d=>d.files||[])));
    $("#devBkMeta").textContent=files.length?`${files.length} saved version${files.length===1?"":"s"}`:"No saved versions";
    const da=$("#devBkDelAll");da.hidden=!files.length;da.dataset.a="delall";da.dataset.d=tree.device;da.dataset.f="";
    await renderDeviceTree(tree,box);
    const latest=box.querySelector("[data-latest-file='1']");if(latest)latest.scrollIntoView({block:"nearest"});
  }catch(err){box.innerHTML=errorState("Could not load this device's backups",err)}
}
function openDeviceBackups(id){
  const d=devs.find(x=>x.id===id);popDevId=id;
  $("#devBkTitle").textContent=d?(d.name||d.ip):"Device backups";$("#devBkMeta").textContent="";
  $("#devBkDelAll").hidden=true;$("#devBkBody").innerHTML='<div class="row">Loading dated folders…</div>';
  const dlg=$("#devBkDlg");if(!dlg.open)dlg.showModal();
  refreshDeviceBackups();
}
$("#devBkClose").onclick=()=>$("#devBkDlg").close();
$("#devBkDlg").addEventListener("close",()=>{popDevId=null});
/* ---- device page (/devices/<id>, templates/devices/detail.html): ONE device's backups ----
   Shows: summary cards, then one card like the Backups page (latest version blinking, "Compare with previous",
   dated folder tree, older versions). The page is opened with openDevice(id) (helpers.js). */
function showDevicePage(id){openDevice(id)}
/* bytes -> "47.1 KB" / "3.2 MB" / "1.4 GB" */
function dpBytes(n){const u=["B","KB","MB","GB"];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return (i?n.toFixed(1):n)+" "+u[i]}
async function loadDevicePage(id){
  devPageId=id;
  $("#dpTitle").textContent="Loading…";$("#dpSub").textContent="";
  $("#dpKpis").innerHTML="";$("#dpGroup").innerHTML="";
  try{
    if(!devs.length)devs=await api("/api/devices");
    if(devPageId!==id)return;
    const d=devs.find(x=>x.id===id);
    if(!d){toastNextPage("That device is no longer in the inventory; it may have been deleted.",{type:"warning",title:"Device not found"});showTab("devices");return}
    $("#dpTitle").textContent=d.name||d.ip;
    $("#dpSub").textContent=`${d.ip} · ${vInfo(d.device_type).label||d.device_type}`;
    { const lg=$("#dpLogo"); const grp=vInfo(d.device_type).group||d.device_type; lg.className="brand-logo v-"+slug(grp); lg.title=grp; lg.innerHTML=brandMark(d.device_type); }
    const tree=await api("/api/backup-tree/"+id),folder=tree.device;
    const files=await api("/api/backups/"+E(folder));      /* newest first */
    if(devPageId!==id)return;
    const latest=files[0],prev=files[1];
    $("#dpKpis").innerHTML=
      `<div class="kpi"><small>Saved versions</small><strong>${files.length}</strong></div>`+
      `<div class="kpi"><small>Latest backup</small><strong class="sm2">${latest?esc(fmtBdDateTime(latest.time)):"Never"}</strong></div>`+
      `<div class="kpi"><small>Total backup size</small><strong>${files.length?dpBytes(files.reduce((n,f)=>n+(f.size||0),0)):"-"}</strong></div>`+
      `<div class="kpi"><small>Last backup status</small><strong class="sm2">${pill(d.last_status)}</strong></div>`;

    /* --- this device only, laid out exactly like a device card in the Backups tab:
           header, latest version, dated folder tree, then "Show older versions" --- */
    $("#dpDelAll").hidden=!files.length;$("#dpDelAll").dataset.a="delall";$("#dpDelAll").dataset.d=folder;$("#dpDelAll").dataset.f="";
    const older=files.length-1;
    let latestRow=files.length?bkRow(folder,latest,prev?prev.file:"",true):`<div class="row"><span class="t">No configuration backup saved yet.</span></div>`;
    if(latest&&isUnread(latest.file)){latestRow=latestRow.replace('class="row"','class="row latest-blink"').replace('<span class="tag">','<span class="tag blink-tag">')}
    $("#dpGroup").innerHTML=`<div class="group"><h3><span class="tree-open" style="font-weight:700;color:var(--blue)">📁 ${esc(folder)}</span><span>${files.length} saved version${files.length===1?"":"s"}${latest?` &middot; last backup ${esc(fmtBdDateTime(latest.time))}`:""}</span>`+
      (files.length?`<button class="link d adm" style="margin-left:auto" ${bkAttr("delall",folder,"")}>Delete all versions</button>`:"")+`</h3>`+
      latestRow+`<div class="older"></div><div class="device-tree" id="dpTree"></div>`+
      (older>0?`<div class="row"><button class="link" ${bkAttr("more",folder,"")} data-n="${older}">Show older versions (${older})</button></div>`:"")+`</div>`;
    await renderDeviceTree(tree,$("#dpTree"));
    /* every year/month folder starts CLOSED and stays closed until the user opens it */
    const tbox=$("#dpTree");tbox.querySelectorAll("details").forEach(x=>x.open=false);
  }catch(err){
    if(err.status===403){$("#dpGroup").innerHTML='<div class="empty"><b>Saved configurations are for operators</b>Configurations can contain passwords and keys, so the Viewer role cannot open them. Ask an administrator for the Operator role if you need them.</div>';return}
    $("#dpGroup").innerHTML=errorState("Could not load this device's backups",err);
  }
}
$o("#dpBack").onclick=()=>showTab("devices");
$o("#devpage").addEventListener("click",e=>{if(e.target.closest("button[data-a]"))bkClick(e)});

/* ---- backup viewer pop-up (#vdlg): shows a config or a comparison, with Copy, Download and line wrap ---- */
const vdlg=$("#vdlg");let vRaw="",vName="backup.txt";
function openViewer(title,meta){vRaw="";vName=title;$("#vTitle").textContent=title;$("#vMeta").textContent=meta||"";$("#vBody").textContent="Loading...";["#vCopy","#vDl"].forEach(i=>$(i).disabled=true);if(!vdlg.open)vdlg.showModal();$("#vBody").scrollTop=0}
function fillViewer(text,html){vRaw=text;const pre=$("#vBody");if(html)pre.innerHTML=html;else pre.textContent=text;pre.scrollTop=0;
  const n=text?text.split("\n").length:0;$("#vMeta").textContent=n.toLocaleString()+" lines - "+(new Blob([text]).size/1024).toFixed(1)+" KB";["#vCopy","#vDl"].forEach(i=>$(i).disabled=!text)}
function viewerError(m){const pre=$("#vBody");pre.textContent=m;$("#vMeta").textContent="Could not load"}
$("#vClose").onclick=()=>vdlg.close();
vdlg.addEventListener("click",e=>{if(e.target===vdlg)vdlg.close()});   /* click on the dark area */
$("#vWrap").onclick=e=>{const on=$("#vBody").classList.toggle("wrap");e.currentTarget.setAttribute("aria-pressed",on)};
$("#vCopy").onclick=async()=>{
  let ok=false;
  try{await navigator.clipboard.writeText(vRaw);ok=true}catch(e){   /* the clipboard API needs HTTPS; plain http://server-ip needs this fallback */
    const t=document.createElement("textarea");t.value=vRaw;t.style.cssText="position:fixed;opacity:0";vdlg.append(t);t.select();try{ok=document.execCommand("copy")}catch(x){}t.remove()}
  toast(ok?"Copied to clipboard":"Copy failed. Select the text and press Ctrl+C")};
$("#vDl").onclick=()=>{const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([vRaw],{type:"text/plain"}));a.download=vName.endsWith(".txt")?vName:vName.replace(/[\\/:*?"<>|]+/g,"_")+".txt";document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000)};
window.viewFile=async(d,f)=>{
  openViewer(f,d);
  try{fillViewer(await api(`/api/backups/${E(d)}/${f.split("/").map(E).join("/")}`))}catch(e){viewerError(e.message)}
};
window.diffFile=async(d,a,b)=>{
  openViewer(`${a}  to  ${b}`,d);
  try{
    const t=await api(`/api/diff/${E(d)}?a=${E(a)}&b=${E(b)}`),L=t.split("\n");
    /* the first two lines are the file headers; after that "+" = added, "-" = removed (so a removed line that starts with "--" is still shown correctly) */
    fillViewer(t,L.map((l,i)=>`<span class="l ${i<2&&L[0].startsWith("---")?"h":l.startsWith("@@")?"k":l[0]==="+"?"a":l[0]==="-"?"r":""}">${esc(l)||" "}</span>`).join(""));
  }catch(e){viewerError(e.message)}
};
