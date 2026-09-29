from __future__ import annotations

from agentic.dashboard_cn import CLINIC_HTML

LOGIN_CSS = """
    body:not(.auth-ready) #loginShell,body:not(.auth-ready) #appMain{display:none}
    body:not(.authed) #appMain{display:none}
    body.authed #loginShell{display:none}
    #authPending{display:none;min-height:42vh;place-items:center;color:var(--muted);font-size:14px;letter-spacing:.04em}
    body:not(.auth-ready) #authPending{display:grid}
    #loginShell{max-width:1320px;margin:0 auto;padding:48px 24px 72px}
    .account-box{display:none;align-items:center;gap:12px}
    body.authed .account-box{display:flex}
    .account-box .who{color:var(--brand-deep);font-size:13px;font-weight:650;white-space:nowrap}
    .account-box .secondary{height:40px;padding:0 14px}
    .login-hero{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(340px,460px);gap:56px;align-items:center}
    .login-brief h1{max-width:11em}
    .login-points{list-style:none;margin:28px 0 0;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .login-points li{min-height:92px;padding:16px 18px;border:1px solid var(--line);border-radius:16px;background:#fff;box-shadow:0 8px 22px rgba(53,35,37,.05)}
    .login-points strong{display:block;color:var(--brand-deep);font-size:15px}
    .login-points span{display:block;margin-top:5px;color:var(--muted);font-size:13px;line-height:1.45}
    #loginShell .login-panel{width:100%;max-width:none;padding:32px 28px 28px}
    #loginShell .login-panel .primary{width:100%;margin-top:8px}
    #loginShell input{width:100%;min-width:0;height:48px;border:1px solid #d9cbce;border-radius:11px;background:#fff;color:var(--ink);padding:12px 13px}
    #loginShell .login-err{min-height:22px;margin:12px 0 0;color:var(--brand);font-size:13px}
    @media(max-width:900px){
      .login-hero{grid-template-columns:1fr;gap:28px;align-items:stretch}
      .login-brief h1{max-width:none}
    }
    @media(max-width:560px){.login-points{grid-template-columns:1fr}}
"""

LOGIN_MARKUP = """
    <div class="account-box" id="accountBox">
      <span id="who" class="who">未登录</span>
      <button id="logoutBtn" class="secondary" type="button">退出</button>
    </div>
  </div>
</header>
<div id="authPending">正在进入工作台…</div>
<section id="loginShell">
  <div class="login-hero">
    <div class="login-brief">
      <p class="eyebrow">FETAL BRAIN MRI ANALYSIS</p>
      <h1>胎儿脑 MRI 重建与定量分析</h1>
      <ul class="login-points">
        <li><strong>重建</strong><span>多栈 BTFE 三维重建</span></li>
        <li><strong>配准</strong><span>孕周图谱空间对齐</span></li>
        <li><strong>分割</strong><span>组织标签与脑区划分</span></li>
        <li><strong>质控</strong><span>分步技术检查与报告</span></li>
      </ul>
    </div>
    <section class="composer login-panel">
      <div class="module-heading">
        <span class="module-kicker">SIGN IN</span>
        <h2>登录</h2>
      </div>
      <label class="field">用户名<input id="username" autocomplete="username"></label>
      <label class="field">密码<input id="password" type="password" autocomplete="current-password"></label>
      <button id="loginBtn" class="primary" type="button">进入工作台</button>
      <p id="loginErr" class="login-err" role="alert"></p>
    </section>
  </div>
</section>
<main id="appMain">
"""

AUTH_API = r"""let token=sessionStorage.getItem("gatewayToken")||"";
async function api(path,body){
  const headers={"Content-Type":"application/json"};
  if(token) headers.Authorization="Bearer "+token;
  const r=await fetch(path,{method:body?"POST":"GET",credentials:"include",headers,body:body?JSON.stringify(body):undefined});
  const text=await r.text();let data={};try{data=JSON.parse(text)}catch(_){data={error:text}}
  if(r.status===401 && path!=="/api/login"){showLogin(true); throw new Error(data.error||"请先登录");}
  if(!r.ok) throw new Error(data.error||data.detail||"请求失败");
  return data;
}"""

AUTH_PUT = (
    "function putUploadHeaders(){\n"
    '  const headers={"Content-Type":"application/octet-stream"};\n'
    '  if(token) headers.Authorization="Bearer "+token;\n'
    "  return headers;\n"
    "}"
)

AUTH_BOOT = r"""
function showLogin(on){
  document.body.classList.toggle("authed", !on);
  document.body.classList.add("auth-ready");
}
async function doLogin(){
  $("loginErr").textContent="";
  try{
    const data=await api("/api/login",{username:$("username").value,password:$("password").value});
    token=data.token; sessionStorage.setItem("gatewayToken", token);
    $("password").value="";
    window.__clinicUser=data.username;
    $("who").textContent=data.username;
    document.body.classList.add("authed");
    document.body.classList.remove("auth-ready");
    await boot();
  }catch(err){$("loginErr").textContent=err.message}
  document.body.classList.add("auth-ready");
}
async function doLogout(){
  try{await api("/api/logout",{ok:true})}catch(_){}
  token=""; sessionStorage.removeItem("gatewayToken");
  window.__clinicUser="";
  $("who").textContent="未登录";
  showLogin(true);
}
async function gatewayBoot(){
  try{
    const me=await api("/api/me");
    window.__clinicUser=me.username;
    $("who").textContent=me.username;
    document.body.classList.add("authed");
    await boot();
  }catch(_){
    token=""; sessionStorage.removeItem("gatewayToken");
    window.__clinicUser="";
    document.body.classList.remove("authed");
    showLogin(true);
  }
  document.body.classList.add("auth-ready");
}
$("loginBtn").addEventListener("click",doLogin);
$("logoutBtn").addEventListener("click",doLogout);
$("password").addEventListener("keydown",event=>{if(event.key==="Enter")doLogin()});
gatewayBoot();
"""


def build_index_html() -> str:
    html = CLINIC_HTML
    html = html.replace("  </style>\n</head>", LOGIN_CSS + "  </style>\n</head>", 1)
    html = html.replace(
        '    <div class="product-copy"><strong>AutoRecon</strong><span>SmileLab</span></div>\n'
        "  </div>\n</header>\n<main>",
        '    <div class="product-copy"><strong>AutoRecon</strong><span>SmileLab</span></div>\n' + LOGIN_MARKUP,
        1,
    )
    html = html.replace(
        "async function api(path,body){\n"
        '  const r=await fetch(path,{method:body?"POST":"GET",headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});\n'
        "  const text=await r.text();let data={};try{data=JSON.parse(text)}catch(_){data={error:text}}\n"
        '  if(!r.ok) throw new Error(data.error||"请求失败");\n'
        "  return data;\n"
        "}",
        AUTH_API,
        1,
    )
    html = html.replace(
        "function putUploadHeaders(){\n"
        '  const headers={"Content-Type":"application/octet-stream"};\n'
        '  if(typeof token==="string"&&token) headers.Authorization="Bearer "+token;\n'
        "  return headers;\n"
        "}",
        AUTH_PUT,
        1,
    )
    html = html.replace(
        "$(\"viewerDialog\").addEventListener(\"click\",event=>{if(event.target===$(\"viewerDialog\"))closeViewer()});\nboot();",
        "$(\"viewerDialog\").addEventListener(\"click\",event=>{if(event.target===$(\"viewerDialog\"))closeViewer()});"
        + AUTH_BOOT,
        1,
    )
    if "gatewayBoot" not in html or "sessionRunKey" not in html or "进入工作台" not in html or 'id="appMain"' not in html or "putUploadChunk" not in html or 'id="authPending"' not in html:
        raise RuntimeError("failed to attach the test login gate to dashboard_cn")
    return html


INDEX_HTML = build_index_html()
