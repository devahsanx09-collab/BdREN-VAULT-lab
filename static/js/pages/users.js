/* VAULT - pages/users.js
   User Management page (/users, administrators only): add, edit, disable and delete web users,
   and the sign-in history. The signed-in account itself (ME, sign out, own password) is core/account.js.
   Bindings to this page's elements use $o() (helpers.js), so they are harmless on the other pages. */

let users=[];
/* ---- users tab (admin only): add, edit, disable, delete users ---- */
async function loadUsers(){
  users=await api("/api/users");
  $("#userList").innerHTML=`<div class="tbl"><table><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last sign-in</th><th>Created</th><th></th></tr></thead><tbody>`+
  users.map(u=>`<tr><td><span class="dn">${esc(u.username)}</span>${u.id===ME.id?' <span class="none">(you)</span>':""}</td>
   <td><span class="pill ${u.role}">${ROLE_LABEL[u.role]}</span></td>
   <td>${!u.active?'<span class="pill DOWN" title="This account is disabled and cannot sign in">Disabled</span>'
        :u.online?'<span class="pill UP" title="Signed in right now">Active</span>'
        :'<span class="pill" title="Not signed in at the moment">Inactive</span>'}</td>
   <td class="when" title="${esc(u.last_login_ip||"")}">${fmtWhen(u.last_login)}${u.last_login_ip?`<span class="sub">IP: ${esc(u.last_login_ip)}</span>`:""}</td><td class="when">${esc((u.created||"").slice(0,10))}</td>
   <td class="acts"><button class="link" type="button" data-user-history="${esc(u.username)}">History</button><button class="link" type="button" data-user-edit="${u.id}">Edit</button>${u.id===ME.id?"":`<button class="link d" type="button" data-user-del="${u.id}">Delete</button>`}</td></tr>`).join("")+`</tbody></table></div>`;
  const sel=$("#signinAccount"),keep=sel.value;
  sel.innerHTML=`<option value="">All accounts</option>`+users.map(u=>`<option value="${esc(u.username)}">${esc(u.username)}</option>`).join("");
  sel.value=users.some(u=>u.username===keep)?keep:"";
  loadSignins();
}

/* who is signed in changes by itself: refresh the list every 30 s (not while a pop-up is open) */
setInterval(()=>{if(PAGE==="users"&&!document.hidden&&!document.querySelector("dialog[open]"))loadUsers().catch(()=>{})},30000);

/* ---- Sign-in history (User Management): who signed in, from which IP and browser; failed attempts too ---- */
let signinData=null,signinT=0;
async function loadSignins(){
  const p=new URLSearchParams({account:$("#signinAccount").value,result:$("#signinResult").value,q:$("#signinQ").value.trim(),limit:"1000"});
  try{signinData=await api("/api/users/signins?"+p);renderSignins()}
  catch(e){$("#signinList").innerHTML=errorState("Could not load the sign-in history",e)}
}
function renderSignins(){
  const d=signinData,s=d.summary;
  morph($("#signinKpis"),`<div class="kpi"><small>Sign-ins, last 24 h</small><strong>${s.signins_24h}</strong><span class="d">${s.accounts_24h} different account${s.accounts_24h===1?"":"s"}</span></div>
    <div class="kpi"><small>Failed attempts, last 24 h</small><strong class="${s.failed_24h?"r":"g"}">${s.failed_24h}</strong><span class="d">Wrong password or unknown user</span></div>`);
  const IP_FIX={
    setting_off:`<b>Sign-ins show the server's own address (127.0.0.1).</b> The website runs behind nginx, and the app does not trust nginx yet.
      Add this line to /opt/dbms/.env, then restart the service:<code>DBMS_BEHIND_PROXY=1</code>`,
    header_missing:`<b>Sign-ins show 127.0.0.1 because nginx does not pass on the visitor's address.</b> The app is ready (DBMS_BEHIND_PROXY is on).
      In the nginx site for this website, inside <i>location / { … }</i> next to <i>proxy_pass</i>, add these lines, then run <i>sudo nginx -t &amp;&amp; sudo systemctl reload nginx</i>:
      <code>proxy_set_header X-Forwarded-For $remote_addr;<br>proxy_set_header X-Forwarded-Proto $scheme;<br>proxy_set_header X-Forwarded-Host $host;</code>`,
    not_applied:`<b>nginx sends the visitor's address, but the app does not use it yet.</b> Restart the service so the setting takes effect
      (<i>sudo systemctl restart dbms</i>). The service must start the app with <i>manage.py serve</i>, as in deploy/dbms.service.`
  };
  $("#signinNote").innerHTML=IP_FIX[d.ip_diag]?`<div class="rad-note">${IP_FIX[d.ip_diag]}<br>New sign-ins then show the real IP address; older entries keep 127.0.0.1.</div>`:"";
  $("#signinCount").textContent=`${d.rows.length}${d.rows.length>=1000?"+":""} event${d.rows.length===1?"":"s"}`;
  if(!d.rows.length){$("#signinList").innerHTML='<div class="empty"><b>No matching sign-ins</b>Change the account, result or search.</div>';return}
  const {rows,bar}=paginate("signins",d.rows);
  morph($("#signinList"),`<div class="tbl"><table><thead><tr><th>Time</th><th>Account</th><th>Result</th><th>IP address</th><th>Browser</th></tr></thead><tbody>`+
    rows.map(r=>`<tr data-key="${esc([r.ts,r.account,r.result,r.ip].join("|"))}"><td class="when">${fmtWhen(r.ts)}</td><td><strong>${esc(r.account||"-")}</strong></td>
      <td><span class="pill ${r.result==="Signed in"?"UP":r.result==="Failed"?"DOWN":""}">${esc(r.result)}</span>${r.reason?`<span class="sub">${esc(r.reason)}</span>`:""}</td>
      <td class="m">${esc(r.ip||"-")}</td><td>${esc(r.browser||"-")}</td></tr>`).join("")+`</tbody></table></div>`+bar);
}
$o("#signinRefresh").onclick=loadSignins;
$o("#signinAccount").onchange=$o("#signinResult").onchange=()=>{PAGES.signins=1;loadSignins()};
$o("#signinQ").oninput=()=>{clearTimeout(signinT);signinT=setTimeout(()=>{PAGES.signins=1;loadSignins()},350)};
$o("#userList").addEventListener("click",e=>{
  const b=e.target.closest("[data-user-history]");if(!b)return;
  $("#signinAccount").value=b.dataset.userHistory;PAGES.signins=1;loadSignins();
  $("#signinPanel").scrollIntoView({behavior:"smooth",block:"start"});
});
const udlg=$("#udlg"),ufrm=$("#ufrm");let uEdit=null;
function openUser(u){
  uEdit=u?u.id:null;ufrm.reset();const f=ufrm.elements;
  $("#uTitle").textContent=u?"Edit user":"Add user";
  f.username.value=u?u.username:"";f.username.readOnly=!!u;
  f.role.value=u?u.role:"viewer";f.active.checked=u?!!u.active:true;
  f.password.required=!u;f.password.type="password";f.password.placeholder=u?"Leave empty to keep the current password":"At least 12 characters";
  udlg.querySelector(".eye").textContent="Show";
  const self=!!u&&u.id===ME.id;f.role.disabled=self;f.active.disabled=self;   /* you cannot demote or disable yourself */
  udlg.showModal();
}
$o("#addUser").onclick=()=>openUser();
const editUser=id=>openUser(users.find(u=>u.id===id));
const delUser=async id=>{
  const u=users.find(x=>x.id===id);if(!u)return;
  if(await confirmAction({title:"Delete this user?",message:"They will no longer be able to sign in.",detail:u.username,confirm:"Delete user",run:()=>api("/api/users/"+id,{method:"DELETE"})})){toast("The account was removed and can no longer sign in.",{title:"User deleted"});sfx.play("del");loadUsers()}
};
/* Edit / Delete buttons of the users table (inline onclick is blocked by the Content-Security-Policy) */
document.addEventListener("click",e=>{
  const b=e.target.closest("[data-user-edit],[data-user-del]");if(!b)return;
  b.dataset.userEdit!==undefined?editUser(Number(b.dataset.userEdit)):delUser(Number(b.dataset.userDel));
});
ufrm.onsubmit=async e=>{
  e.preventDefault();const f=ufrm.elements;
  const b={username:f.username.value.trim(),role:f.role.value,password:f.password.value,active:f.active.checked};
  try{
    await api(uEdit?"/api/users/"+uEdit:"/api/users",J(uEdit?"PUT":"POST",b));
    sfx.play(uEdit?"ok":"add");udlg.close();toast(uEdit?"The account changes were saved.":"The new account can sign in now.",{title:uEdit?"User updated":"User added"});loadUsers();
  }catch(err){toast(err.message,{type:"error"})}
};
