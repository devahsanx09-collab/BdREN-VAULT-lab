/* VAULT - core/search.js
   Global search (top bar button, Ctrl+K or "/"): find a device by name, IP or vendor and open its page,
   or jump to any page of the menu. Works the same with 10 or 1000 devices (the device list is already
   in the browser; at most 30 matches are drawn).
   Loaded by templates/base.html on every screen; all scripts share one global scope (see core/helpers.js). */
(()=>{
  const dlg=document.createElement("dialog");
  dlg.className="gs";dlg.setAttribute("aria-label","Search devices and pages");
  dlg.innerHTML=`<div class="gs-in"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
    <input id="gsQ" type="search" placeholder="Search devices by name, IP or vendor, or type a page name" autocomplete="off" spellcheck="false" aria-controls="gsList">
    <kbd>Esc</kbd></div><ul id="gsList" role="listbox"></ul>
    <div class="gs-f"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span></div>`;
  document.body.append(dlg);
  const q=dlg.querySelector("#gsQ"),list=dlg.querySelector("#gsList");
  let items=[],sel=0,loading=false;

  /* the menu is rendered by the server for this role, so every link in it may be opened */
  const pages=()=>[...document.querySelectorAll(".side nav a[data-tab]")]
    .map(a=>({kind:"page",tab:a.dataset.tab,label:a.dataset.title||a.textContent.trim(),group:a.dataset.group||""}));

  async function ensureDevices(){
    if(devs.length||loading)return;
    loading=true;try{devs=await api("/api/devices")}catch(e){}finally{loading=false;draw()}
  }
  function draw(){
    const t=q.value.trim().toLowerCase();
    const pg=pages().filter(p=>!t||p.label.toLowerCase().includes(t)||p.group.toLowerCase().includes(t)).slice(0,t?6:12);
    const dv=t?devs.map(d=>{
      const v=vInfo(d.device_type),hay=[d.name,d.ip,v.group,v.label].map(x=>(x||"").toLowerCase());
      const score=hay[0].startsWith(t)||hay[1].startsWith(t)?0:hay.some(h=>h.includes(t))?1:9;
      return {d,score};
    }).filter(x=>x.score<9).sort((a,b)=>a.score-b.score||(a.d.name||a.d.ip).localeCompare(b.d.name||b.d.ip)).slice(0,30).map(x=>({kind:"device",d:x.d})):[];
    items=[...dv,...pg];sel=Math.min(sel,Math.max(0,items.length-1));
    const head=(txt,n)=>n?`<li class="gs-h" role="presentation">${txt}</li>`:"";
    let i=-1;
    list.innerHTML=(t&&!dv.length&&!pg.length?`<li class="gs-empty">${loading?"Loading devices…":`No device or page matches “${esc(q.value.trim())}”.`}</li>`:"")+
      head(`Devices${dv.length>=30?" (first 30)":""}`,dv.length)+dv.map(x=>{i++;const d=x.d,v=vInfo(d.device_type);
        return `<li role="option" data-i="${i}" aria-selected="${i===sel}"><span class="brand-logo v-${slug(v.group||d.device_type)}">${brandMark(d.device_type)}</span>
          <span class="gs-t"><b>${esc(d.name||d.ip)}</b><small>${esc(d.ip)} · ${esc(v.group||d.device_type)}</small></span>${pill(d.last_status)}</li>`}).join("")+
      head(t?"Pages":"Go to",pg.length)+pg.map(p=>{i++;return `<li role="option" data-i="${i}" aria-selected="${i===sel}"><span class="gs-pg">↳</span>
          <span class="gs-t"><b>${esc(p.label)}</b><small>${esc(p.group)}</small></span></li>`}).join("");
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({block:"nearest"});
  }
  function go(it){
    if(!it)return;dlg.close();
    if(it.kind==="device")openDevice(it.d.id);else showTab(it.tab);
  }
  function open(){if(dlg.open)return;q.value="";sel=0;dlg.showModal();draw();ensureDevices();q.focus()}
  q.addEventListener("input",()=>{sel=0;draw()});
  q.addEventListener("keydown",e=>{
    if(e.key==="ArrowDown"){e.preventDefault();sel=Math.min(items.length-1,sel+1);draw()}
    else if(e.key==="ArrowUp"){e.preventDefault();sel=Math.max(0,sel-1);draw()}
    else if(e.key==="Enter"){e.preventDefault();go(items[sel])}
  });
  list.addEventListener("click",e=>{const li=e.target.closest("[data-i]");if(li)go(items[+li.dataset.i])});
  list.addEventListener("mousemove",e=>{const li=e.target.closest("[data-i]");if(li&&+li.dataset.i!==sel){sel=+li.dataset.i;list.querySelectorAll("[data-i]").forEach(x=>x.setAttribute("aria-selected",String(+x.dataset.i===sel)))}});
  dlg.addEventListener("click",e=>{if(e.target===dlg)dlg.close()});
  $("#gsBtn").onclick=open;
  document.addEventListener("keydown",e=>{
    const typing=/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)||document.activeElement?.isContentEditable;
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();open()}
    else if(e.key==="/"&&!typing&&!document.querySelector("dialog[open]")){e.preventDefault();open()}
  });
})();
