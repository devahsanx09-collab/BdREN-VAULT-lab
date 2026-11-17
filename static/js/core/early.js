/* Runs before the page is drawn: restore the collapsed-sidebar choice (kept outside the main scripts so the CSP can forbid inline scripts). */
try{if(localStorage.getItem("nb_side_min")==="1")document.body.classList.add("side-min")}catch(e){}
