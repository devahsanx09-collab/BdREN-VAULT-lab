/* VAULT - core/account.js
   The signed-in account, on every page: who you are (ME), sign out, change your own password,
   and the Show / Hide button of every password field.
   The role is rendered by the server as a class on <body> (r-admin / r-operator / r-viewer); CSS hides
   buttons the role may not use (.adm = administrator only, .op = operator and administrator). */

let ME={};
const ROLE_LABEL={admin:"Administrator",operator:"Operator",viewer:"Viewer"};
async function loadMe(){
  ME=await api("/api/me");
  document.body.classList.remove("r-admin","r-operator","r-viewer");document.body.classList.add("r-"+ME.role);
  $("#meName").textContent=ME.username;$("#meAv").textContent=(ME.username||"?")[0].toUpperCase();$("#meRole").textContent=ROLE_LABEL[ME.role];
}
$("#outBtn").onclick=async()=>{
  try{const r=await fetch("/logout",{method:"POST",headers:headers(false)});if(!r.ok)throw new Error()}catch(e){toast("Your session could not be closed. Check the connection and try again.",{type:"error",title:"Sign out failed"});return}
  location.href="/login?reason=signed-out";
};
document.addEventListener("click",e=>{
  if(!e.target.classList.contains("eye"))return;
  const i=e.target.previousElementSibling,hide=i.type==="password";i.type=hide?"text":"password";e.target.textContent=hide?"Hide":"Show";
});

const mdlg=$("#mdlg"),mfrm=$("#mfrm");
$("#pwBtn").onclick=()=>{mfrm.reset();mfrm.elements.newpw.type="password";mdlg.querySelector(".eye").textContent="Show";mdlg.showModal()};
mfrm.onsubmit=async e=>{
  e.preventDefault();const f=mfrm.elements;
  if(f.newpw.value!==f.confirm.value)return toast("The new password and its confirmation are different. Type the same password in both fields.",{type:"warning",title:"Passwords do not match"});
  try{await api("/api/me/password",J("POST",{current:f.current.value,new:f.newpw.value}));sfx.play("ok");mdlg.close();toast("Use the new password the next time you sign in.",{title:"Password changed"})}
  catch(err){toast(err.message,{type:"error"})}
};
