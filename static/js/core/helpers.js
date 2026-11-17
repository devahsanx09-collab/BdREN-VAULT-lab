/* VAULT - core/helpers.js
   Shared tools used by every other file: $ / $o / esc / toast, page navigation, notification sounds,
   api() calls to the server, Bangladesh-time date helpers, the confirmation pop-up, pagination and the status pill.

   How the scripts fit together (see docs/ARCHITECTURE.md):
   - templates/base.html loads every script on every page, in a fixed order; they share one global scope,
     so a function from an earlier file can be used directly.
   - Each screen is its own URL. The server marks the open screen on <body data-page="devices">.
   - core/start.js runs the open screen's loader (PAGE_INIT), so only that screen fetches its data.
   - Page scripts bind their buttons with $o("#id"): on another screen the element is not there and
     $o() returns a detached placeholder, so the binding is harmless. */

/* ---- helpers: $ = find element, esc = make text safe for HTML, toast = small message, api = call the server ---- */
const $=s=>document.querySelector(s), esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
/* $o = an element that only exists on one screen: the element, or a detached placeholder when this is another screen */
const $o=s=>document.querySelector(s)||document.createElement("div");
/* ---- pages: which screen is open, and how to open another one ---- */
const PAGE=document.body.dataset.page||"";
const PAGE_URL=JSON.parse(document.getElementById("page-urls")?.textContent||"{}");
function showTab(key){location.href=PAGE_URL[key]||PAGE_URL.dashboard||"/"}      /* open a screen by its key, e.g. showTab("devices") */
function openDevice(id){location.href="/devices/"+Number(id)}                   /* one device's own backup page */
/* ---- live updates without redrawing: morph(el, html) changes ONLY the parts of `el` that differ from `html`.
   Unchanged rows, charts and inputs stay untouched (no flicker, no lost hover / focus / scroll), and a value that
   changed gets a short highlight (.upd) so the eye sees what moved. Elements marked data-morph-skip keep their
   own children (for example ping cells that devices.js updates in place). */
function morph(el,html){
  const t=document.createElement("template");t.innerHTML=html;
  const first=!el.firstChild;
  morphKids(el,t.content,first);
}
function morphKids(a,b,quiet){
  const an=[...a.childNodes],bn=[...b.childNodes];
  bn.forEach((y,i)=>{const x=an[i];if(!x)a.appendChild(y);else morphNode(x,y,quiet)});
  for(let i=bn.length;i<an.length;i++)an[i].remove();
}
function morphNode(x,y,quiet){
  if(x.nodeType!==y.nodeType||x.nodeName!==y.nodeName){x.replaceWith(y);return}
  if(x.nodeType!==1){
    if(x.nodeValue!==y.nodeValue){x.nodeValue=y.nodeValue;if(!quiet&&x.nodeType===3&&y.nodeValue.trim())flashChange(x.parentElement)}
    return;
  }
  for(const {name,value} of [...y.attributes])if(x.getAttribute(name)!==value)x.setAttribute(name,value);
  for(const {name} of [...x.attributes])if(!y.hasAttribute(name))x.removeAttribute(name);
  if(x.tagName==="INPUT"){if(x.type==="checkbox"||x.type==="radio")x.checked=y.hasAttribute("checked");else if(x!==document.activeElement)x.value=y.getAttribute("value")??""}
  if(x.hasAttribute("data-morph-skip"))return;
  morphKids(x,y,quiet);
}
function flashChange(el){
  if(!el||el.closest("svg"))return;
  el.classList.remove("upd");void el.offsetWidth;el.classList.add("upd");
  clearTimeout(el._upd);el._upd=setTimeout(()=>el.classList.remove("upd"),1600);
}
const setHTML=(selector,html)=>{const el=$(selector);if(el)morph(el,html);else console.warn("VAULT: missing dashboard element",selector)};
const SEEN_KEY="nb_seen_backups";
const seenSet=()=>{try{return new Set(JSON.parse(localStorage.getItem(SEEN_KEY)||"[]"))}catch(e){return new Set()}};
const isUnread=file=>!!file&&!seenSet().has(file);
function markSeen(file){
  if(!file)return;
  const s=seenSet();s.add(file);
  try{localStorage.setItem(SEEN_KEY,JSON.stringify([...s].slice(-500)))}catch(e){}
  document.querySelectorAll(".latest-blink").forEach(r=>{if(r.querySelector("[data-f]")?.dataset.f===file)r.classList.remove("latest-blink")});
}
document.addEventListener("click",e=>{const el=e.target.closest("[data-seen],[data-a='view']");if(el)markSeen(el.dataset.seen||el.dataset.f)});
/* ---- notifications: toast(message) or toast(message, {type, title, action}) ----
   type   = "success" | "error" | "warning" | "info". When it is not given it is read from the wording, so the
            existing toast(err.message) calls show as errors and "... saved" calls as successes.
   action = {label:"Open Activity Logs", run:()=>showTab("logs")}: a button inside the notification.
   Errors stay until they are closed and are announced to screen readers at once; the others fade out
   (hovering pauses them). The same message is not shown twice within a moment.
   toastNextPage(message, options) shows a notification on the next page that opens (after a redirect). */
const TOAST_KIND={
  success:{title:"Success",ms:4200,icon:'<path d="M20 6 9 17l-5-5"/>'},
  error:{title:"Action failed",ms:0,icon:'<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>'},
  warning:{title:"Attention needed",ms:6500,icon:'<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'},
  info:{title:"Notice",ms:4200,icon:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>'}
};
/* errors that came back from the server, so toast(err.message) is ALWAYS shown as an error, whatever its wording */
const API_ERRS=new Map();      /* message -> {status, at} */
function rememberApiError(message,status){
  API_ERRS.set(message,{status,at:Date.now()});
  if(API_ERRS.size>50)API_ERRS.delete(API_ERRS.keys().next().value);
}
function apiErrorTitle(status){
  return status===0?"Connection problem":status===401||status===403?"Not allowed":status===404?"Not found":
         status===409?"Cannot do this now":status>=500?"Server error":"Action failed";
}
function toastKind(m){
  const s=String(m||"");
  const known=API_ERRS.get(s);if(known&&Date.now()-known.at<120000)return "error";
  if(/restart failed|skipped|select at least|choose at least|already running|a backup is running|no failed devices|no devices to|not available here|wait for it/i.test(s))return "warning";
  if(/fail|error|could not|cannot|can't|unable|not found|denied|invalid|unavailable|not reachable|do not match|timed? ?out|forbidden|refused|incorrect|expired|too many|not allow|permission|missing|already exists?|(?:is|are) required|must /i.test(s))return "error";
  if(/sound (enabled|disabled)|copied|ready/i.test(s))return "info";
  return "success";
}
const TOAST_RECENT=new Map();   /* "type|message" -> time shown, to drop repeats */
function toast(m,opt={}){
  const type=TOAST_KIND[opt.type]?opt.type:toastKind(m),k=TOAST_KIND[type];
  const known=API_ERRS.get(String(m||""));
  if(!opt.title&&type==="error"&&known)opt={...opt,title:apiErrorTitle(known.status)};
  const key=type+"|"+(opt.title||"")+"|"+m,now=Date.now();
  if(now-(TOAST_RECENT.get(key)||0)<1500)return;
  TOAST_RECENT.set(key,now);if(TOAST_RECENT.size>30)TOAST_RECENT.delete(TOAST_RECENT.keys().next().value);
  let box=$("#toasts");
  if(!box){box=document.createElement("div");box.id="toasts";box.setAttribute("aria-live","polite");}
  (document.querySelector("dialog[open]")||document.body).append(box);   /* inside an open pop-up, or it would be hidden behind it */
  const el=document.createElement("div");el.className="toast "+type+(k.ms?"":" sticky");el.setAttribute("role",type==="error"?"alert":"status");
  if(k.ms)el.style.setProperty("--ms",k.ms+"ms");
  const act=opt.action&&opt.action.label?`<button type="button" class="toast-act">${esc(opt.action.label)}</button>`:"";
  el.innerHTML=`<span class="toast-ic" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${k.icon}</svg></span>
    <div class="toast-tx"><b>${esc(opt.title||k.title)}</b><span>${esc(m||"")}</span>${act}</div>
    <button type="button" class="toast-x" aria-label="Dismiss notification">&times;</button><i class="toast-bar" aria-hidden="true"></i>`;
  const close=()=>{if(el.classList.contains("out"))return;el.classList.add("out");setTimeout(()=>el.remove(),260)};
  el.querySelector(".toast-x").onclick=close;
  if(act)el.querySelector(".toast-act").onclick=()=>{close();try{opt.action.run()}catch(e){console.error(e)}};
  let timer=k.ms?setTimeout(close,k.ms):0;
  el.addEventListener("mouseenter",()=>{clearTimeout(timer);el.classList.add("hold")});
  el.addEventListener("mouseleave",()=>{el.classList.remove("hold");if(k.ms)timer=setTimeout(close,2000)});
  box.append(el);
  while(box.children.length>4)box.firstElementChild.remove();   /* never more than four on screen */
}
/* a notification for the next page that opens (the current one is about to be left) */
function toastNextPage(m,opt={}){try{sessionStorage.setItem("dbms_toast_next",JSON.stringify({m,opt:{type:opt.type,title:opt.title}}))}catch(e){}}
(()=>{try{const s=sessionStorage.getItem("dbms_toast_next");if(!s)return;sessionStorage.removeItem("dbms_toast_next");const {m,opt}=JSON.parse(s);setTimeout(()=>toast(m,opt),300)}catch(e){}})();
/* a section that could not load: what failed, why, and a "Try again" button that reloads the current page section */
const errorState=(what,e)=>`<div class="empty err" role="alert"><b>${esc(what)}</b><span class="why">${esc(e&&e.message||"Something went wrong. Please try again.")}</span><button type="button" class="b" data-retry>Try again</button></div>`;
document.addEventListener("click",e=>{if(e.target.closest("[data-retry]"))initPage()});   /* initPage(): core/start.js */
/* plain-language text for server answers that came without their own message */
const HTTP_TEXT={
  400:"The request was not accepted. Check the values you entered and try again.",
  403:"You do not have permission to do this. Ask an administrator if you need access.",
  404:"The item was not found. It may have been deleted or renamed; refresh the page.",
  409:"This conflicts with work that is already in progress. Wait for it to finish and try again.",
  413:"The upload is too large for the server.",
  429:"Too many requests in a short time. Wait a moment and try again.",
  500:"The server hit an unexpected problem. Try again; if it keeps happening, check the server log.",
  502:"The server is not answering (bad gateway). Check that the service is running.",
  503:"This service is temporarily unavailable. Check that the database and services are running, then try again.",
  504:"The server took too long to answer. Try again in a moment."
};

/* ---- notification sounds: short tones made with the Web Audio API (no audio files to download).
   Played when a backup finishes, when something is deleted, added or saved. The side menu has an on/off button; the choice is kept in the browser. ---- */
const sfx=(()=>{
  let ctx=null,on=true;
  const defaults={backup:true,delete:true,add:true,system:true};
  let prefs={...defaults};
  try{on=localStorage.getItem("nb_sound")!=="0";prefs={...defaults,...JSON.parse(localStorage.getItem("nb_sound_prefs")||"{}")}}catch(e){}
  const AC=window.AudioContext||window.webkitAudioContext;
  const engine=()=>{if(!AC)return null;if(!ctx)ctx=new AC();if(ctx.state==="suspended")ctx.resume();return ctx};
  ["pointerdown","keydown"].forEach(ev=>addEventListener(ev,engine,{once:true,passive:true}));   /* browsers allow sound only after a first click or tap */
  function note(c,f,t,d,o={}){
    const osc=c.createOscillator(),g=c.createGain(),v=o.gain==null?.2:o.gain;
    osc.type=o.type||"sine";osc.frequency.setValueAtTime(f,t);if(o.to)osc.frequency.exponentialRampToValueAtTime(o.to,t+d);
    g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(v,t+.012);g.gain.exponentialRampToValueAtTime(.0001,t+d);   /* soft attack, smooth fade: no clicks */
    osc.connect(g);g.connect(c.destination);osc.start(t);osc.stop(t+d+.03);
  }
  const sounds={
    done :c=>{const t=c.currentTime+.02;note(c,659.25,t,.32);note(c,987.77,t+.14,.5);note(c,1975.5,t+.14,.5,{gain:.04})},          /* backup finished: bright two-note chime */
    ok   :c=>{const t=c.currentTime+.02;note(c,880,t,.22,{gain:.16});note(c,1318.5,t+.07,.28,{gain:.08})},                              /* saved / updated: single soft ping */
    add  :c=>{const t=c.currentTime+.02;note(c,520,t,.13,{to:780,gain:.18});note(c,1046.5,t+.1,.26,{gain:.13})},                       /* added: rising pop */
    del  :c=>{const t=c.currentTime+.02;note(c,420,t,.2,{to:160,gain:.2});note(c,110,t,.09,{type:"triangle",gain:.1})},                /* deleted: soft falling swoosh */
    warn :c=>{const t=c.currentTime+.02;note(c,587.33,t,.2,{type:"triangle"});note(c,440,t+.17,.36,{type:"triangle"})},               /* finished with some failures */
    error:c=>{const t=c.currentTime+.02;note(c,311.13,t,.26,{type:"triangle"});note(c,233.08,t+.18,.46,{type:"triangle"})}             /* failed */
  };
  return{
    sounds,
    get on(){return on},
    set(v){on=!!v;try{localStorage.setItem("nb_sound",on?"1":"0")}catch(e){}},
    get prefs(){return {...prefs}},
    setPref(group,value){prefs[group]=!!value;try{localStorage.setItem("nb_sound_prefs",JSON.stringify(prefs))}catch(e){}},
    play(kind){const group=({done:"backup",warn:"backup",error:"backup",del:"delete",add:"add",ok:"system"})[kind]||"system";if(!on||!prefs[group]||!sounds[kind])return;try{const c=engine();if(c)sounds[kind](c)}catch(e){}}
  };
})();
let manualJob=false;   /* true while a backup started from this page is running (so the dashboard does not play a second sound) */
/* Django CSRF: every request sends the token from the csrftoken cookie in the X-CSRFToken header */
const csrfToken=()=>(document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)||[])[1]||"";
const headers=(json)=>({"X-CSRFToken":csrfToken(),...(json?{"Content-Type":"application/json"}:{})});
async function api(u,o){
  let r;
  try{r=await fetch(u,{...(o||{}),headers:headers(o&&o.body)})}
  catch(e){const m="Cannot reach the server. Check your network connection and that the service is running.";rememberApiError(m,0);throw Object.assign(new Error(m),{status:0})}
  if(r.status===401){location.href="/login?next="+encodeURIComponent(location.pathname);return new Promise(()=>{})}   /* session ended: come back here after signing in */
  if(!r.ok){
    let m="";try{m=(await r.json()).error}catch(e){}
    /* make short server messages self-explanatory */
    if(r.status===403&&/role does not allow/i.test(m||""))m="Your role does not allow this action. Ask an administrator if you need it.";
    m=m||HTTP_TEXT[r.status]||`The server answered with an unexpected error (HTTP ${r.status}). Please try again.`;
    rememberApiError(m,r.status);
    throw Object.assign(new Error(m),{status:r.status});
  }
  const ct=r.headers.get("content-type")||"";return ct.includes("json")?r.json():r.text()
}
const J=(m,b)=>({method:m,body:JSON.stringify(b)});
/* one CSV cell, safe to open in Excel: quoted, and a leading = + - @ (or tab / CR) is neutralised so a
   device name or log message can never run as a formula ("CSV injection") */
const csvCell=v=>{let s=String(v??"");if(/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'};
/* All timestamps returned by the server are Bangladesh-local wall time (Asia/Dhaka).
   Parse them explicitly as UTC+06:00 so browser/host time-zone settings cannot shift them. */
function parseBdDate(s){
  const m=String(s||"").match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/);
  if(!m)return null;
  return new Date(Date.UTC(+m[1],+m[2]-1,+m[3],(+m[4]||0)-6,+m[5]||0,+m[6]||0));
}
function bdDateKey(d){
  const parts=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Dhaka",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(d);
  const v=Object.fromEntries(parts.map(p=>[p.type,p.value]));return `${v.year}-${v.month}-${v.day}`;
}
function bdClock(s,seconds=false){
  const m=String(s||"").match(/[ T](\d{2}):(\d{2})(?::(\d{2}))?/);if(!m)return String(s||"");
  const h=+m[1],ampm=h>=12?"PM":"AM",h12=h%12||12;
  return `${String(h12).padStart(2,"0")}:${m[2]}${seconds&&m[3]?":"+m[3]:""} ${ampm}`;
}
function fmtBdDateTime(s,seconds=false){
  const m=String(s||"").match(/^(\d{4})-(\d{2})-(\d{2})/);if(!m)return String(s||"");
  const d=new Date(Date.UTC(+m[1],+m[2]-1,+m[3]));
  const date=d.toLocaleDateString("en-GB",{timeZone:"UTC",day:"2-digit",month:"short",year:"numeric"});
  return `${date}, ${bdClock(s,seconds)}`;
}
function format12hTime(value){
  const m=String(value||"").match(/^(\d{2}):(\d{2})$/);if(!m)return value||"";
  const h=+m[1];return `${String(h%12||12).padStart(2,"0")}:${m[2]} ${h>=12?"PM":"AM"}`;
}
function parse12hTime(value){
  const m=String(value||"").trim().match(/^(0?[1-9]|1[0-2]):([0-5]\d)\s*(AM|PM)$/i);
  if(!m)throw new Error("Enter schedule time as 02:00 AM or 02:00 PM (Bangladesh time)");
  let h=+m[1]%12;if(m[3].toUpperCase()==="PM")h+=12;return `${String(h).padStart(2,"0")}:${m[2]}`;
}
/* ---- confirmation pop-up: replaces the browser's plain confirm() box.
   confirmAction({title,message,detail,confirm,danger,typed,run}) resolves true when the action was confirmed AND `run` succeeded.
   While `run` works the buttons are locked (no double clicks); if it fails the error shows inside the pop-up and it stays open.
   `typed` makes the person type that word first. Every dangerous (delete) action now defaults to typing DELETE. ---- */
const cfm=$("#cfm");let cfmEnd=null,cfmBusy=false;
function confirmAction({title,message,detail="",confirm:label="Delete",danger=true,typed:typedIn="",run}){
  const typed=typedIn||(danger?"DELETE":"");   /* every delete must be confirmed by typing DELETE */
  return new Promise(res=>{
    const yes=$("#cfmYes"),no=$("#cfmNo"),err=$("#cfmE"),ty=$("#cfmTy");
    $("#cfmT").textContent=title;$("#cfmM").textContent=message;
    $("#cfmX").textContent=detail;$("#cfmX").hidden=!detail;
    err.hidden=true;err.textContent="";ty.value="";$("#cfmTyL").hidden=!typed;$("#cfmTyT").textContent=typed?`Type ${typed} to confirm`:"";
    cfm.classList.toggle("safe",!danger);
    const ready=()=>{yes.disabled=cfmBusy||(!!typed&&ty.value.trim()!==typed)};
    yes.className="b "+(danger?"dg":"p");yes.textContent=label;no.disabled=false;cfmBusy=false;ready();
    ty.oninput=ready;
    const end=ok=>{cfmEnd=null;cfmBusy=false;if(cfm.open)cfm.close();res(ok)};
    cfmEnd=end;
    no.onclick=()=>{if(!cfmBusy)end(false)};
    yes.onclick=async()=>{
      if(cfmBusy||yes.disabled)return;
      cfmBusy=true;yes.disabled=no.disabled=true;yes.textContent="Working...";err.hidden=true;
      try{if(run)await run();end(true)}
      catch(e){sfx.play("error");cfmBusy=false;no.disabled=false;yes.textContent=label;ready();err.textContent=e&&e.message||"Something went wrong. Please try again.";err.hidden=false}
    };
    cfm.showModal();(typed?ty:no).focus();   /* Cancel has the focus: Enter never deletes by accident */
  });
}
cfm.addEventListener("cancel",e=>{if(cfmBusy)e.preventDefault()});                  /* Esc is ignored while working */
cfm.addEventListener("close",()=>{if(cfmEnd)cfmEnd(false)});                         /* Esc = Cancel */
cfm.addEventListener("click",e=>{if(e.target===cfm&&!cfmBusy)cfm.close()});          /* click on the dark area = Cancel */
const askDelete=(o)=>confirmAction(o);

/* ---- pagination for the Devices, Backups and Logs lists ----
   Each list has its own current page AND its own rows-per-page choice (10, 20 or 50), remembered in this browser. */
const PAGE_SIZES=[10,50,100],PAGES={devices:1,backups:1,logs:1,audit:1,radUsers:1,radNas:1,radEvents:1,radLogins:1,reports:1,signins:1,jobs:1,retry:1},SIZES={};
for(const k of Object.keys(PAGES)){const v=+localStorage.getItem("dbms_page_size_"+k);SIZES[k]=PAGE_SIZES.includes(v)?v:10}
/* the slice of items to show for list `key`, plus the pager bar HTML (empty when everything fits on one page) */
function paginate(key,items){
  const size=SIZES[key];
  const pages=Math.max(1,Math.ceil(items.length/size));
  PAGES[key]=Math.min(Math.max(1,PAGES[key]),pages);
  const p=PAGES[key],from=(p-1)*size;
  /* always shown when there is something to list, so "Rows per page" (10 / 50 / 100) is always available */
  const bar=!items.length?"":`<div class="pager" data-pager="${key}">
    <span class="pg-info">Showing ${from+1}&ndash;${Math.min(from+size,items.length)} of ${items.length}</span><span class="sp"></span>
    <label class="pg-size"><span>Rows per page</span><select aria-label="Rows per page">${PAGE_SIZES.map(n=>`<option${n===size?" selected":""}>${n}</option>`).join("")}</select></label>
    <button type="button" class="b" data-go="${p-1}"${p<=1?" disabled":""}>Previous</button>
    <span class="pg-num">Page ${p} of ${pages}</span>
    <button type="button" class="b" data-go="${p+1}"${p>=pages?" disabled":""}>Next</button></div>`;
  return {rows:items.slice(from,from+size),bar};
}
const REDRAW={devices:()=>renderDevices(),backups:()=>renderBackups(),logs:()=>renderLogs(),audit:()=>renderAudit(),radUsers:()=>renderRadUsers(),radNas:()=>renderRadNas(),radEvents:()=>renderRadEvents(),radLogins:()=>renderRadLogins(),reports:()=>renderReport(),signins:()=>renderSignins(),jobs:()=>renderJobs(),retry:()=>renderRetryQueue()};
document.addEventListener("click",e=>{
  const b=e.target.closest(".pager [data-go]");if(!b||b.disabled)return;
  const key=b.closest(".pager").dataset.pager;PAGES[key]=+b.dataset.go;REDRAW[key]();
});
document.addEventListener("change",e=>{
  if(!e.target.matches(".pager select"))return;
  const key=e.target.closest(".pager").dataset.pager;
  SIZES[key]=+e.target.value;localStorage.setItem("dbms_page_size_"+key,SIZES[key]);
  PAGES[key]=1;REDRAW[key]();
});

/* status text and pill for the "Status" column */
const LABEL={SUCCESS:"Saved",UNCHANGED:"Unchanged",FAILED:"Failed"};
const pill=s=>`<span class="pill ${s||""}">${LABEL[s]||"Not run"}</span>`;

const SND_ON='<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',SND_OFF='<path d="M11 5 6 9H2v6h4l5 4z"/><path d="m22 9-6 6M16 9l6 6"/>';
function paintSnd(){const on=sfx.on,b=$("#sndBtn");$("#sndIc").innerHTML=on?SND_ON:SND_OFF;$("#sndTx").textContent=on?"Sound on":"Sound off";b.setAttribute("aria-pressed",on);b.title=on?"Notification sound is on (click to mute)":"Notification sound is off (click to turn on)"}
$("#sndBtn").onclick=()=>{sfx.set(!sfx.on);paintSnd();sfx.play("ok")};
paintSnd();
