/* VAULT - core/start.js
   Runs last, when every other script is loaded: fills the open screen with data, follows a running backup,
   and starts the idle sign-out timer.

   PAGE_INIT maps each screen (body[data-page], set by the server from apps/core/pages.py) to the function
   that loads its data. Adding a screen = one line here. */

const PAGE_INIT={
  dashboard:loadDashboard,
  devices:loadDevices,
  device:()=>loadDevicePage(Number(document.body.dataset.deviceId)),
  backups:loadBackups,
  reports:loadReport,
  jobs:loadJobs,
  logs:loadLogs,
  users:loadUsers,
  settings:loadSettings,
  "radius-users":loadRadUsers,
  "radius-nas":loadRadNas,
  "radius-audit":loadRadAudit,
  "radius-setup":loadRadSetup,
};
/* load (or reload, from a "Try again" button) the data of the open screen */
function initPage(){const f=PAGE_INIT[PAGE];if(f)Promise.resolve().then(f).catch(e=>console.error(e))}

/* Links saved from the older one-page version (/#devices, /#device/12, /#radius-users) open the new address. */
(()=>{
  const h=location.hash.slice(1);if(!h)return;
  const m=/^device\/(\d+)$/.exec(h),to=m?"/devices/"+m[1]:PAGE_URL[h];
  if(to)location.replace(to);
})();

if(!document.body.dataset.denied)initPage();
loadMe().catch(()=>{});
resumeJob();

/* Automatic sign-out after real inactivity (background refreshes do not count as activity). */
(()=>{
  const timeout=Math.max(5*60*1000,Number(document.body.dataset.idleTimeoutMs)||15*60*1000);
  let timer=null,loggingOut=false;
  const activityEvents=["pointerdown","keydown","touchstart","scroll","click"];
  const logoutForIdle=async()=>{
    if(loggingOut)return;loggingOut=true;
    try{await fetch("/logout?reason=idle",{method:"POST",headers:{"X-CSRFToken":csrfToken(),"X-Requested-With":"XMLHttpRequest"},credentials:"same-origin",keepalive:true})}catch(e){}
    location.replace("/login?reason=idle");
  };
  const reset=()=>{if(loggingOut)return;clearTimeout(timer);timer=setTimeout(logoutForIdle,timeout)};
  activityEvents.forEach(ev=>addEventListener(ev,reset,{passive:true}));
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)reset()});
  reset();
})();

/* Heartbeat: tells the server once a minute that this browser is still open, so User Management can show who
   is signed in right now ("Active") on every screen, not only on the ones that refresh their data. It does
   not count as activity: the idle sign-out above still happens after real inactivity. */
setInterval(()=>{if(navigator.onLine!==false)fetch("/api/me",{credentials:"same-origin",headers:{"X-Requested-With":"XMLHttpRequest"}}).catch(()=>{})},60000);

/* Close buttons of the pop-ups (inline onclick is blocked by the Content-Security-Policy). */
document.addEventListener("click",e=>{const b=e.target.closest("[data-close-dlg]");if(b)document.getElementById(b.dataset.closeDlg).close()});
