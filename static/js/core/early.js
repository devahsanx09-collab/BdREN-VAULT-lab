/* Runs before the page is drawn: restore the collapsed-sidebar choice (kept outside the main scripts so the CSP can forbid inline scripts). */
try{if(localStorage.getItem("nb_side_min")==="1")document.body.classList.add("side-min")}catch(e){}
/* Cross-page fade (app.css @view-transition): when the browser skips it (slow page, busy tab) it rejects the
   transition's promises and the console shows "Transition was aborted". Skipping is harmless: catch them. */
addEventListener("pagereveal",e=>{const t=e.viewTransition;if(!t)return;t.ready.catch(()=>{});t.finished.catch(()=>{});t.updateCallbackDone.catch(()=>{})});
addEventListener("pageswap",e=>{const t=e.viewTransition;if(!t)return;t.ready.catch(()=>{});t.finished.catch(()=>{})});
