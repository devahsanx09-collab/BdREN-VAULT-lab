/* VAULT - core/responsive.js
   Loaded last by templates/base.html. On phones (static/css/app.css, max-width 760px) every data table
   is shown as a list of cards, one per row, with the column name in front of each value.
   This file copies each column heading onto its cells (data-l="Time") and marks the table wrapper
   with .stack, so the pages that build tables (logs.js, users.js, radius.js) need no changes.
   The Devices table (.dt) has its own card layout and is left alone. */
(()=>{
  let queued=false;
  function label(){
    queued=false;
    document.querySelectorAll(".tbl table:not(.dt)").forEach(t=>{
      const heads=[...t.querySelectorAll("thead th")].map(th=>th.textContent.trim());
      t.querySelectorAll("tbody tr").forEach(tr=>{
        [...tr.children].forEach((td,i)=>{if(heads[i]&&!td.hasAttribute("data-l"))td.setAttribute("data-l",heads[i])});
      });
      const wrap=t.closest(".tbl");if(wrap&&!wrap.classList.contains("stack"))wrap.classList.add("stack");
    });
  }
  const main=document.querySelector("main");
  if(main)new MutationObserver(()=>{if(!queued){queued=true;setTimeout(label,0)}}).observe(main,{childList:true,subtree:true});
  label();
})();
