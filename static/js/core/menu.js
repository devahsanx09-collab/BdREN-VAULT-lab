/* VAULT - core/menu.js
   The side menu and the top bar. Menu items are ordinary links (/dashboard, /devices, ...); the server renders
   the menu for the signed-in role and highlights the open screen (templates/base.html, apps/core/pages.py).
   This file only adds: the phone drawer, the minimise button, the RADIUS / AAA drop-down and the account menu. */

/* ---- side menu on phones and tablets: slides in over the page, closes on outside tap or Esc ---- */
function closeSide(){document.body.classList.remove("nav-open");$("#menuBtn").setAttribute("aria-expanded","false")}
$("#menuBtn").onclick=()=>{const o=document.body.classList.toggle("nav-open");$("#menuBtn").setAttribute("aria-expanded",o)};
$("#scrim").onclick=closeSide;
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeSide()});

/* ---- minimise / expand the side menu on desktop (icons only when minimised); remembered in this browser ---- */
function setMin(on){document.body.classList.toggle("side-min",on);const b=$("#colBtn");b.setAttribute("aria-pressed",on);const t=on?"Expand menu":"Minimize menu";b.title=t;b.setAttribute("aria-label",t);try{localStorage.setItem("nb_side_min",on?"1":"0")}catch(e){}}
$("#colBtn").onclick=()=>setMin(!document.body.classList.contains("side-min"));
setMin(document.body.classList.contains("side-min"));

/* ---- RADIUS / AAA drop-down: opens on click and remembers it; always open while one of its pages is shown ---- */
document.querySelectorAll(".side .dd").forEach(dd=>{
  const t=dd.querySelector(".dd-t"),m=dd.querySelector(".dd-m"),key="nb_dd_"+(dd.dataset.dd||"");
  const set=(open,remember=true)=>{m.hidden=!open;t.setAttribute("aria-expanded",open);if(remember)try{localStorage.setItem(key,open?"1":"0")}catch(e){}};
  t.onclick=()=>set(m.hidden);
  let saved=false;try{saved=localStorage.getItem(key)==="1"}catch(e){}
  set(dd.classList.contains("has-on")||saved,false);
});

/* ---- account menu in the top bar (sound, change password, sign out) ---- */
const userMenu=$("#userMenu");
document.addEventListener("click",e=>{
  if(!userMenu.open)return;
  if(!userMenu.contains(e.target)||e.target.closest("#pwBtn,#outBtn"))userMenu.open=false;   /* the sound switch keeps the menu open */
});
document.addEventListener("keydown",e=>{if(e.key==="Escape")userMenu.open=false});

/* timers and state shared by several page scripts, declared here because this file loads first */
let dashTimer=0;      /* refresh timer of the dashboard */
let devPageId=null;   /* id of the device shown on its own page (/devices/<id>) */
