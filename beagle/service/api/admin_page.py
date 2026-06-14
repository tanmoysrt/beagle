"""Self-contained admin web UI (design/15 §21).

A single static HTML page (inline CSS + vanilla JS) served at ``/admin``. The
operator signs in with the admin password (``BEAGLE_ADMIN_PASSWORD``), which is
exchanged for an admin JWT held in the browser. From there the page creates
users, registers and syncs repositories, and generates ready-to-paste access
instructions (bridge + MCP) for any user — so the CLI is never required.

Monochrome, frappe-ui-flavoured: neutral grays, subtle borders, one dark
primary action.
"""

ADMIN_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Beagle · admin</title>
<style>
  :root {
    --bg: #f4f4f5; --surface: #ffffff; --ink: #18181b; --muted: #71717a;
    --line: #e4e4e7; --line-strong: #d4d4d8; --accent: #18181b; --ok: #16a34a;
    --radius: 8px; --shadow: 0 1px 2px rgba(0,0,0,.04), 0 1px 3px rgba(0,0,0,.06);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 14px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Inter, sans-serif;
  }
  a { color: inherit; }
  .wrap { max-width: 60rem; margin: 0 auto; padding: 1.5rem 1.25rem 4rem; }
  header.top {
    display: flex; align-items: center; justify-content: space-between;
    padding: .9rem 1.25rem; background: var(--surface); border-bottom: 1px solid var(--line);
  }
  .brand { font-weight: 600; letter-spacing: -.01em; }
  .brand small { color: var(--muted); font-weight: 400; margin-left: .5rem; }
  h2 { font-size: .95rem; font-weight: 600; margin: 2rem 0 .75rem; }
  .card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
          box-shadow: var(--shadow); }
  .card.pad { padding: 1.1rem 1.2rem; }
  .grid { display: grid; gap: .9rem; grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr)); }
  .stat { padding: .9rem 1rem; }
  .stat b { display: block; font-size: 1.5rem; letter-spacing: -.02em; }
  .stat span { color: var(--muted); font-size: .8rem; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: .55rem .8rem; border-bottom: 1px solid var(--line); font-size: .86rem; }
  th { color: var(--muted); font-weight: 500; }
  tr:last-child td { border-bottom: 0; }
  .row { display: flex; gap: .6rem; flex-wrap: wrap; align-items: flex-end; }
  label { display: block; font-size: .78rem; color: var(--muted); margin-bottom: .25rem; }
  input, select {
    font: inherit; padding: .5rem .6rem; border: 1px solid var(--line-strong);
    border-radius: 6px; background: #fff; color: var(--ink); min-width: 12rem;
  }
  input:focus, select:focus { outline: 2px solid var(--ink); outline-offset: -1px; }
  button {
    font: inherit; font-weight: 500; padding: .5rem .9rem; border-radius: 6px;
    border: 1px solid var(--line-strong); background: #fff; color: var(--ink); cursor: pointer;
  }
  button:hover { background: #fafafa; }
  button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  button.primary:hover { opacity: .92; }
  button.small { padding: .3rem .6rem; font-size: .8rem; }
  .muted { color: var(--muted); }
  .err { color: #b91c1c; min-height: 1.2em; font-size: .85rem; }
  .hidden { display: none !important; }
  pre { background: #fafafa; border: 1px solid var(--line); border-radius: 6px;
        padding: .8rem .9rem; overflow: auto; font-size: .8rem; }
  /* Login */
  .login { max-width: 22rem; margin: 6rem auto; }
  .login .card { padding: 1.5rem; }
  .login input { width: 100%; }
  .login button { width: 100%; margin-top: .8rem; }
  .pill { font-size: .72rem; padding: .1rem .5rem; border: 1px solid var(--line-strong);
          border-radius: 999px; color: var(--muted); }
</style>
</head>
<body>

<!-- LOGIN -->
<div id="login" class="login">
  <div class="brand" style="text-align:center;margin-bottom:1rem;font-size:1.25rem;">
    beagle <small>admin</small>
  </div>
  <div class="card">
    <label for="pw">Admin password</label>
    <input id="pw" type="password" placeholder="BEAGLE_ADMIN_PASSWORD" autofocus
           onkeydown="if(event.key==='Enter')signIn()">
    <button class="primary" onclick="signIn()">Sign in</button>
    <p id="loginErr" class="err"></p>
  </div>
</div>

<!-- APP -->
<div id="app" class="hidden">
  <header class="top">
    <div class="brand">beagle <small>admin</small></div>
    <div><span id="whoami" class="pill"></span>
      <button class="small" onclick="signOut()">Sign out</button></div>
  </header>

  <div class="wrap">
    <h2>Overview</h2>
    <div id="stats" class="grid"></div>

    <h2>Repositories</h2>
    <div class="card pad">
      <div class="row">
        <div><label>Name</label><input id="repoName" placeholder="Press"></div>
        <div><label>Slug</label><input id="repoSlug" placeholder="press"></div>
        <div><label>Git remote URL (optional)</label>
          <input id="repoUrl" placeholder="https://github.com/org/repo" style="min-width:20rem"></div>
        <button class="primary" onclick="addRepo()">Register &amp; sync</button>
      </div>
      <p id="repoErr" class="err"></p>
    </div>
    <div class="card" style="margin-top:.8rem;overflow:hidden">
      <table><thead><tr>
        <th>Slug</th><th>Name</th><th>State</th><th>Commits</th><th>Snapshots</th><th></th>
      </tr></thead><tbody id="repoRows"></tbody></table>
    </div>

    <h2>Users</h2>
    <div class="card pad">
      <div class="row">
        <div><label>Username</label><input id="userName" placeholder="alice"></div>
        <div><label>Email (optional)</label><input id="userEmail" placeholder="alice@example.com"></div>
        <button class="primary" onclick="addUser()">Add user</button>
      </div>
      <p id="userErr" class="err"></p>
    </div>
    <div class="card" style="margin-top:.8rem;overflow:hidden">
      <table><thead><tr><th>Username</th><th>Email</th><th></th></tr></thead>
        <tbody id="userRows"></tbody></table>
    </div>

    <h2>Grant access</h2>
    <div class="card pad">
      <p class="muted" style="margin-top:0">
        Generate a token and copy-paste setup for a user. With it, the bridge
        auto-discovers the repository; Claude Code talks to the service over MCP.
      </p>
      <div class="row">
        <div><label>User</label><select id="grantUser"></select></div>
        <button class="primary" onclick="generate()">Generate setup</button>
      </div>
      <p id="grantErr" class="err"></p>
      <div id="instructions" class="hidden" style="margin-top:1rem"></div>
    </div>
  </div>
</div>

<script>
const KEY = 'beagle_admin_token';
let token = localStorage.getItem(KEY);
const origin = window.location.origin;

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { signOut(); throw new Error('session expired'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || ('error ' + res.status));
  return data;
}

async function signIn() {
  const pw = document.getElementById('pw').value;
  const err = document.getElementById('loginErr'); err.textContent = '';
  try {
    const res = await fetch('/v1/admin/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { err.textContent = data.message || 'Sign-in failed'; return; }
    token = data.token; localStorage.setItem(KEY, token);
    show();
  } catch (e) { err.textContent = String(e); }
}

function signOut() {
  token = null; localStorage.removeItem(KEY);
  document.getElementById('app').classList.add('hidden');
  document.getElementById('login').classList.remove('hidden');
}

async function show() {
  document.getElementById('login').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  await refresh();
}

async function refresh() {
  const { overview } = await api('GET', '/v1/admin/overview');
  const c = overview.counts;
  document.getElementById('stats').innerHTML =
    stat('Users', c.users) + stat('Repositories', c.repositories) +
    stat('Active tokens', c.active_tokens) + stat('Sessions', c.sessions);
  document.getElementById('repoRows').innerHTML = overview.repositories.map(r =>
    `<tr><td><b>${esc(r.slug)}</b></td><td>${esc(r.name)}</td>
     <td><span class="pill">${esc(r.ingestion_state)}</span></td>
     <td>${r.commits}</td><td>${r.snapshots}</td>
     <td style="text-align:right"><button class="small" onclick="syncRepo('${r.id}')">Sync</button></td></tr>`
  ).join('') || emptyRow(6);

  const { users } = await api('GET', '/v1/users');
  document.getElementById('userRows').innerHTML = users.map(u =>
    `<tr><td><b>${esc(u.username)}</b></td><td>${esc(u.email)}</td><td></td></tr>`
  ).join('') || emptyRow(3);
  document.getElementById('grantUser').innerHTML =
    users.map(u => `<option value="${esc(u.username)}">${esc(u.username)}</option>`).join('');
  document.getElementById('whoami').textContent = origin;
}

async function addRepo() {
  const err = document.getElementById('repoErr'); err.textContent = '';
  const name = val('repoName'), slug = val('repoSlug'), url = val('repoUrl');
  if (!name || !slug) { err.textContent = 'Name and slug are required.'; return; }
  try {
    const { repository } = await api('POST', '/v1/repositories',
      { slug, name, remote_url: url || null });
    if (url) await api('POST', `/v1/repositories/${repository.id}/sync`);
    ['repoName','repoSlug','repoUrl'].forEach(id => document.getElementById(id).value = '');
    await refresh();
  } catch (e) { err.textContent = String(e); }
}

async function syncRepo(id) {
  try { await api('POST', `/v1/repositories/${id}/sync`); await refresh(); }
  catch (e) { alert(e); }
}

async function addUser() {
  const err = document.getElementById('userErr'); err.textContent = '';
  const username = val('userName'), email = val('userEmail');
  if (!username) { err.textContent = 'Username is required.'; return; }
  try {
    await api('POST', '/v1/users', { username, email });
    document.getElementById('userName').value = '';
    document.getElementById('userEmail').value = '';
    await refresh();
  } catch (e) { err.textContent = String(e); }
}

async function generate() {
  const err = document.getElementById('grantErr'); err.textContent = '';
  const user = document.getElementById('grantUser').value;
  if (!user) { err.textContent = 'Create a user first.'; return; }
  try {
    const r = await api('POST', '/v1/admin/tokens', { user });
    renderInstructions(user, r.token);
  } catch (e) { err.textContent = String(e); }
}

function renderInstructions(user, tok) {
  // Launch via `uv run --project <beagle>` so the command resolves without
  // beagle-service-mcp being on PATH. Replace BEAGLE_DIR with the install path
  // (or, if installed globally with `uv tool install`, use command
  // "beagle-service-mcp" with no args).
  const mcp = JSON.stringify({
    mcpServers: { 'beagle-service': {
      command: 'uv',
      args: ['run', '--project', '/path/to/beagle', 'beagle-service-mcp'],
      env: { BEAGLE_SERVICE_URL: origin, BEAGLE_TOKEN: tok }
    } }
  }, null, 2);
  const bridge =
`export BEAGLE_SERVICE_URL=${origin}
beagle-bridge login --token ${tok}
beagle-bridge sync <repo-slug>      # run inside a checkout`;
  const el = document.getElementById('instructions');
  el.classList.remove('hidden');
  el.innerHTML =
    `<p class="muted">Setup for <b>${esc(user)}</b> — send these to them. The token is a credential; treat it like a password.</p>
     <div class="row" style="justify-content:space-between">
       <strong>1 · Local bridge</strong>
       <button class="small" onclick="copy(this,bridgeText)">Copy</button></div>
     <pre id="bridgeBlock">${esc(bridge)}</pre>
     <div class="row" style="justify-content:space-between">
       <strong>2 · Claude Code (.mcp.json)</strong>
       <button class="small" onclick="copy(this,mcpText)">Copy</button></div>
     <pre id="mcpBlock">${esc(mcp)}</pre>
     <p class="muted">Set <code>/path/to/beagle</code> to where beagle is installed.
     If you ran <code>uv tool install</code>, use <code>"command": "beagle-service-mcp"</code> with no <code>args</code>.</p>`;
  window.bridgeText = bridge; window.mcpText = mcp;
}

function copy(btn, text) {
  navigator.clipboard.writeText(text).then(() => {
    const old = btn.textContent; btn.textContent = 'Copied'; setTimeout(() => btn.textContent = old, 1200);
  });
}

const val = id => document.getElementById(id).value.trim();
const stat = (label, n) => `<div class="card stat"><b>${n}</b><span>${label}</span></div>`;
const emptyRow = n => `<tr><td colspan="${n}" class="muted">None yet.</td></tr>`;
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

if (token) { show().catch(signOut); }
</script>
</body>
</html>
"""
