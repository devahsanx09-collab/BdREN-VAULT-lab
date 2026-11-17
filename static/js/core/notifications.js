/* VAULT - core/notifications.js
   The top-bar notifications bell: shows problems that need attention (failed backups, devices waiting to
   retry, RADIUS device limits not enforced), grouped with a count each. Loaded on every app screen.
   Data: GET /api/notifications (apps/backups/views.py). The bell is in templates/base.html. */

const NOTIF_IC={
  backup:'<path d="M21 12a9 9 0 1 1-6.2-8.5"/><path d="M21 3v6h-6"/>',
  retry:'<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>',
  shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  offline:'<path d="M12 20h.01"/><path d="M8.5 16.4a5 5 0 0 1 7 0"/><path d="M5 12.9a10 10 0 0 1 14 0"/><path d="m2 2 20 20"/>',
};
const NOTIF_CHEV='<svg class="notif-go" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>';

function renderNotifications(items){
  const badge=$("#notifBadge"),list=$("#notifList"),menu=$("#notifMenu");
  const n=items.length;
  if(badge){badge.hidden=!n;badge.textContent=n>9?"9+":String(n)}
  if(menu)menu.classList.toggle("has",n>0);
  if(!list)return;
  if(!items.length){
    list.innerHTML=`<div class="notif-empty"><span class="notif-ok"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span><b>All clear</b><span>No problems need your attention right now.</span></div>`;
    return;
  }
  list.innerHTML=items.map(it=>`<button class="notif-it sev-${esc(it.severity)}" type="button" data-notif-go="${esc(it.page)}">
    <span class="notif-ic"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${NOTIF_IC[it.icon]||NOTIF_IC.backup}</svg></span>
    <span class="notif-tx"><b>${esc(it.title)}</b>${it.detail?`<small>${esc(it.detail)}</small>`:""}</span>${NOTIF_CHEV}</button>`).join("");
}

let notifBusy=false;
async function loadNotifications(){
  if(notifBusy)return;notifBusy=true;
  try{renderNotifications((await api("/api/notifications")).items||[])}
  catch(e){/* the bell must never nag: a failed poll is ignored */}
  finally{notifBusy=false}
}

/* a notification opens the page that shows the problem in full */
document.addEventListener("click",e=>{
  const b=e.target.closest("[data-notif-go]");if(!b)return;
  $("#notifMenu")?.removeAttribute("open");
  showTab(b.dataset.notifGo);
});
$o("#notifRefresh").addEventListener("click",e=>{e.preventDefault();loadNotifications()});
/* refresh when the panel is opened, and every 60 s while the tab is visible */
$o("#notifMenu").addEventListener("toggle",e=>{if(e.target.open)loadNotifications()});
document.addEventListener("click",e=>{const m=$("#notifMenu");if(m&&m.open&&!m.contains(e.target))m.removeAttribute("open")});
setInterval(()=>{if(!document.hidden)loadNotifications()},60000);
loadNotifications();
