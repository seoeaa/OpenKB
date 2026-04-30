"""Web UI for browsing and managing the OpenKB knowledge base.

Served by the API server at the root URL. Provides a clean interface
for browsing summaries, concepts, explorations, running queries,
and viewing knowledge graphs.
"""
from __future__ import annotations

_INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenKB — Knowledge Base</title>
<style>
  :root {
    --bg: #0d1117;
    --bg-card: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --accent-green: #7ee787;
    --accent-purple: #d2a8ff;
    --accent-orange: #ffa657;
    --radius: 8px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
  .container { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
  header { border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }
  h1 { font-size: 24px; color: var(--accent); }
  h2 { font-size: 18px; margin: 24px 0 12px; }
  .stats { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
  .stat { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 16px; min-width: 100px; }
  .stat-value { font-size: 28px; font-weight: 700; color: var(--accent); }
  .stat-label { font-size: 12px; color: var(--text-muted); }
  .search-box { display: flex; gap: 8px; margin-bottom: 24px; }
  .search-box input { flex: 1; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; color: var(--text); font-size: 14px; }
  .search-box input:focus { outline: none; border-color: var(--accent); }
  .search-box button { background: var(--accent); color: #fff; border: none; border-radius: var(--radius); padding: 10px 20px; cursor: pointer; font-size: 14px; }
  .search-box button:hover { opacity: 0.9; }
  .tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
  .tab { padding: 8px 16px; cursor: pointer; border-bottom: 2px solid transparent; color: var(--text-muted); font-size: 14px; background: none; border-top: none; border-left: none; border-right: none; }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab:hover { color: var(--text); }
  .page-list { list-style: none; }
  .page-item { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 16px; margin-bottom: 8px; cursor: pointer; transition: border-color 0.15s; }
  .page-item:hover { border-color: var(--accent); }
  .page-item .name { font-weight: 600; color: var(--accent); }
  .page-item .preview { color: var(--text-muted); font-size: 13px; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .page-item.summary .name { color: var(--accent); }
  .page-item.concept .name { color: var(--accent-green); }
  .page-item.exploration .name { color: var(--accent-purple); }
  .page-item.report .name { color: var(--accent-orange); }
  .modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 100; }
  .modal-overlay.active { display: flex; align-items: flex-start; justify-content: center; padding-top: 40px; }
  .modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; width: 90%; max-width: 800px; max-height: 80vh; overflow-y: auto; padding: 24px; }
  .modal h2 { margin-top: 0; }
  .modal .content { margin-top: 16px; }
  .modal .content a { color: var(--accent); }
  .modal .close { float: right; background: none; border: none; color: var(--text-muted); font-size: 24px; cursor: pointer; }
  .modal .close:hover { color: var(--text); }
  #loading { text-align: center; padding: 40px; color: var(--text-muted); }
  .error { color: #f85149; }
  .markdown-body h1, .markdown-body h2, .markdown-body h3 { color: var(--text); border-bottom: 1px solid var(--border); padding-bottom: 4px; margin: 16px 0 8px; }
  .markdown-body p { margin: 8px 0; }
  .markdown-body code { background: #1c2128; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
  .markdown-body pre { background: #1c2128; padding: 12px; border-radius: var(--radius); overflow-x: auto; }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>OpenKB</h1>
    <div class="stats" id="stats"></div>
  </header>

  <div class="search-box">
    <input type="text" id="search-input" placeholder="Search wiki..." onkeydown="if(event.key==='Enter')search()">
    <button onclick="search()">Search</button>
  </div>

  <div class="tabs" id="tabs">
    <button class="tab active" onclick="showSection('summaries')">Summaries</button>
    <button class="tab" onclick="showSection('concepts')">Concepts</button>
    <button class="tab" onclick="showSection('explorations')">Explorations</button>
    <button class="tab" onclick="showSection('reports')">Reports</button>
  </div>

  <div id="loading">Loading...</div>
  <ul class="page-list" id="page-list"></ul>
  <div id="search-results" style="display:none"></div>
</div>

<div class="modal-overlay" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <button class="close" onclick="closeModal()">&times;</button>
    <h2 id="modal-title"></h2>
    <div class="content markdown-body" id="modal-content"></div>
  </div>
</div>

<script>
let currentSection = 'summaries';
let pages = {};

async function load() {
  try {
    const r1 = await fetch('/api/status');
    const stats = await r1.json();
    document.getElementById('stats').innerHTML = [
      {v: stats.documents?.length || stats.indexed_documents || 0, l: 'Docs'},
      {v: stats.concepts || 0, l: 'Concepts'},
      {v: stats.summaries || 0, l: 'Summaries'},
      {v: stats.explorations || 0, l: 'Explorations'},
      {v: stats.reports || 0, l: 'Reports'},
    ].map(s => `<div class="stat"><div class="stat-value">${s.v}</div><div class="stat-label">${s.l}</div></div>`).join('');

    const r2 = await fetch('/api/list');
    pages = await r2.json();
    renderSection();
  } catch(e) {
    document.getElementById('loading').innerHTML = `<span class="error">Error loading: ${e.message}</span>`;
  }
}

function renderSection() {
  const list = pages[currentSection] || [];
  const el = document.getElementById('page-list');
  document.getElementById('loading').style.display = 'none';
  document.getElementById('search-results').style.display = 'none';
  el.style.display = '';

  if (!list.length) {
    el.innerHTML = '<li style="color:var(--text-muted);padding:20px">No pages yet.</li>';
    return;
  }
  el.innerHTML = list.map(p => {
    const preview = (p.preview || '').replace(/[#*_\\-\\n]/g, ' ').substring(0, 120);
    return `<li class="page-item ${currentSection.slice(0,-1)}" onclick="openPage('${currentSection}/${p.name}.md')">
      <div class="name">${p.name.replace(/-/g, ' ')}</div>
      <div class="preview">${preview}</div>
    </li>`;
  }).join('');
}

function showSection(section) {
  currentSection = section;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => {
    if (t.textContent.toLowerCase().startsWith(section.slice(0,-1))) t.classList.add('active');
  });
  renderSection();
}

async function openPage(path) {
  const modal = document.getElementById('modal');
  document.getElementById('modal-title').textContent = path;
  document.getElementById('modal-content').innerHTML = '<span style="color:var(--text-muted)">Loading...</span>';
  modal.classList.add('active');
  try {
    const r = await fetch('/api/read?path=' + encodeURIComponent(path));
    if (!r.ok) { document.getElementById('modal-content').innerHTML = '<span class="error">Page not found</span>'; return; }
    const data = await r.json();
    let content = data.content || '';
    content = content.replace(/\[\[([^\]]+)\]\]/g, (m, p) => {
      const parts = p.split('|');
      const link = parts[0].trim();
      const label = parts[1] ? parts[1].trim() : link;
      const [dir, name] = link.includes('/') ? link.split('/') : ['summaries', link];
      return `<a href="#" onclick="event.preventDefault();openPage('${dir}/${name}.md')">${label}</a>`;
    });
    content = content.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    content = content.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    content = content.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    content = content.replace(/^- (.+)$/gm, '<li>$1</li>');
    content = content.replace(/`([^`]+)`/g, '<code>$1</code>');
    content = content.replace(/\\n\\n/g, '</p><p>');
    content = '<p>' + content + '</p>';
    document.getElementById('modal-content').innerHTML = content;
  } catch(e) {
    document.getElementById('modal-content').innerHTML = `<span class="error">Error: ${e.message}</span>`;
  }
}

function closeModal() { document.getElementById('modal').classList.remove('active'); }

async function search() {
  const q = document.getElementById('search-input').value.trim();
  if (!q) { document.getElementById('search-results').style.display = 'none'; renderSection(); return; }
  const el = document.getElementById('page-list');
  const sr = document.getElementById('search-results');
  el.style.display = 'none';
  sr.style.display = '';
  sr.innerHTML = '<div id="loading">Searching...</div>';
  try {
    const r = await fetch('/api/search?q=' + encodeURIComponent(q));
    const data = await r.json();
    if (!data.matches.length) {
      sr.innerHTML = '<div style="color:var(--text-muted);padding:20px">No matches.</div>';
      return;
    }
    sr.innerHTML = `<h2>Search: "${q}" (${data.count} matches)</h2><ul class="page-list">` +
      data.matches.map(m => `<li class="page-item" onclick="openPage('${m.file}')">
        <div class="name">${m.file}:${m.line}</div>
        <div class="preview">${m.text}</div>
      </li>`).join('') + '</ul>';
  } catch(e) {
    sr.innerHTML = `<span class="error">Error: ${e.message}</span>`;
  }
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
load();
</script>
</body>
</html>
"""


def get_index_html() -> str:
    return _INDEX_HTML
