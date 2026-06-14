"""Self-contained, read-only administration page (design/15 §21).

A single static HTML page with inline JS. The browser holds the admin JWT in
memory only (entered by the operator) and calls ``/v1/admin/overview`` with it;
the page stores nothing and mutates nothing. Intentionally minimal — not a
general web UI.
"""

ADMIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Beagle service — admin</title>
<style>
  body { font: 14px/1.5 system-ui, sans-serif; margin: 2rem; max-width: 60rem; color: #1a1a1a; }
  h1 { font-size: 1.3rem; }
  input { padding: .4rem; width: 28rem; max-width: 100%; }
  button { padding: .4rem .8rem; cursor: pointer; }
  table { border-collapse: collapse; margin-top: 1rem; width: 100%; }
  th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid #e3e3e3; }
  .cards { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 1rem; }
  .card { border: 1px solid #e3e3e3; border-radius: 8px; padding: .8rem 1.2rem; }
  .card b { font-size: 1.4rem; display: block; }
  .muted { color: #777; }
  .err { color: #b00020; }
</style>
</head>
<body>
<h1>Beagle service — admin overview</h1>
<p class="muted">Read-only. Paste an admin token (needs <code>admin:identity</code>).</p>
<p>
  <input id="token" type="password" placeholder="Bearer token">
  <button onclick="load()">Load</button>
</p>
<p id="error" class="err"></p>
<div id="cards" class="cards"></div>
<div id="repos"></div>
<div id="audit"></div>
<script>
async function load() {
  const token = document.getElementById('token').value.trim();
  const err = document.getElementById('error');
  err.textContent = '';
  try {
    const res = await fetch('/v1/admin/overview', {
      headers: { 'Authorization': 'Bearer ' + token }
    });
    if (!res.ok) { err.textContent = 'Request failed: ' + res.status; return; }
    render((await res.json()).overview);
  } catch (e) { err.textContent = String(e); }
}
function render(o) {
  const c = o.counts;
  document.getElementById('cards').innerHTML =
    card('Users', c.users) + card('Repositories', c.repositories) +
    card('Active tokens', c.active_tokens) + card('Sessions', c.sessions);
  document.getElementById('repos').innerHTML =
    '<h2>Repositories</h2>' + table(['slug','name','state','commits','snapshots'],
      o.repositories.map(r => [r.slug, r.name, r.ingestion_state, r.commits, r.snapshots]));
  document.getElementById('audit').innerHTML =
    '<h2>Recent activity</h2>' + table(['time','action','user','repository'],
      o.recent_audit.map(a => [a.timestamp, a.action, a.user_id || '-', a.repository_id || '-']));
}
function card(label, value) {
  return '<div class="card"><b>' + value + '</b>' + label + '</div>';
}
function table(headers, rows) {
  const head = '<tr>' + headers.map(h => '<th>' + h + '</th>').join('') + '</tr>';
  const body = rows.map(r => '<tr>' + r.map(c => '<td>' + esc(c) + '</td>').join('') + '</tr>').join('');
  return '<table>' + head + body + '</table>';
}
function esc(s) {
  return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
}
</script>
</body>
</html>
"""
