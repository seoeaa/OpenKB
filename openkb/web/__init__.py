"""Web UI for browsing and managing the OpenKB knowledge base.

Served by the API server at the root URL. Provides a clean interface
for uploading documents, browsing summaries/concepts/explorations,
running queries, searching, and viewing knowledge graphs.
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
  :root { --bg: #0d1117; --bg-card: #161b22; --border: #30363d; --text: #c9d1d9; --text-muted: #8b949e; --accent: #58a6ff; --accent-green: #7ee787; --accent-purple: #d2a8ff; --accent-orange: #ffa657; --radius: 8px; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
  .container { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
  header { border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }
  h1 { font-size: 24px; color: var(--accent); }
  h2 { font-size: 18px; margin: 24px 0 12px; }
  .stats { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
  .stat { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 16px; min-width: 100px; }
  .stat-value { font-size: 28px; font-weight: 700; color: var(--accent); }
  .stat-label { font-size: 12px; color: var(--text-muted); }
  .upload-zone { border: 2px dashed var(--border); border-radius: var(--radius); padding: 24px; text-align: center; color: var(--text-muted); cursor: pointer; margin-bottom: 12px; transition: border-color 0.2s, background 0.2s; }
  .upload-zone:hover, .upload-zone.drag { border-color: var(--accent); background: #1a2230; }
  .upload-zone input[type=file] { display: none; }
  .upload-zone .icon { font-size: 32px; margin-bottom: 8px; }
  .upload-zone .hint { font-size: 13px; }
  #upload-status { font-size: 13px; margin-bottom: 16px; min-height: 20px; }
  #upload-status .ok { color: var(--accent-green); }
  #upload-status .err { color: #f85149; }
  .query-form { display: flex; gap: 8px; margin-bottom: 16px; }
  .query-form input { flex: 1; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; color: var(--text); font-size: 14px; }
  .query-form input:focus { outline: none; border-color: var(--accent); }
  .query-form button { background: var(--accent-green); color: #000; border: none; border-radius: var(--radius); padding: 10px 20px; cursor: pointer; font-size: 14px; font-weight: 600; }
  .query-form button:hover { opacity: 0.9; }
  #query-answer { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; margin-bottom: 16px; display: none; max-height: 400px; overflow-y: auto; }
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
  .markdown-body li { margin: 4px 0 4px 20px; }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>OpenKB</h1>
    <div class="stats" id="stats"></div>
  </header>

  <div class="upload-zone" id="upload-zone">
    <div class="icon">&#128196; &#128193;</div>
    <div class="hint">Drop PDF, Markdown, Word, PPT, HTML, Excel, CSV files here<br>or <u>click to browse</u></div>
    <input type="file" id="file-input" multiple accept=".pdf,.md,.markdown,.docx,.pptx,.xlsx,.html,.htm,.txt,.csv">
  </div>
  <div id="upload-status"></div>

  <div class="query-form">
    <input type="text" id="query-input" placeholder="Ask anything about your documents...">
    <button id="query-btn">Ask</button>
  </div>
  <div id="query-answer" class="markdown-body"></div>

  <div class="search-box">
    <input type="text" id="search-input" placeholder="Search wiki...">
    <button>Search</button>
  </div>

  <div class="tabs" id="tabs">
    <button class="tab active" data-section="summaries">Summaries</button>
    <button class="tab" data-section="concepts">Concepts</button>
    <button class="tab" data-section="explorations">Explorations</button>
    <button class="tab" data-section="reports">Reports</button>
  </div>

  <div id="loading">Loading...</div>
  <ul class="page-list" id="page-list"></ul>
  <div id="search-results" style="display:none"></div>
</div>

<div class="modal-overlay" id="modal">
  <div class="modal">
    <button class="close" id="modal-close">&times;</button>
    <h2 id="modal-title"></h2>
    <div class="content markdown-body" id="modal-content"></div>
  </div>
</div>

<script>
var currentSection = 'summaries', pages = {};

async function load() {
  try {
    var s = await (await fetch('/api/status')).json();
    document.getElementById('stats').innerHTML = [
      {v: s.documents ? s.documents.length : (s.indexed_documents || 0), l: 'Docs'},
      {v: s.concepts || 0, l: 'Concepts'},
      {v: s.summaries || 0, l: 'Summaries'},
      {v: s.explorations || 0, l: 'Explorations'},
      {v: s.reports || 0, l: 'Reports'}
    ].map(function(x) { return '<div class="stat"><div class="stat-value">' + x.v + '</div><div class="stat-label">' + x.l + '</div></div>'; }).join('');
    pages = await (await fetch('/api/list')).json();
    renderSection();
  } catch(e) { document.getElementById('loading').innerHTML = '<span class="error">Error: ' + e.message + '</span>'; }
}

function renderSection() {
  var list = pages[currentSection] || [];
  var el = document.getElementById('page-list');
  document.getElementById('loading').style.display = 'none';
  document.getElementById('search-results').style.display = 'none';
  el.style.display = '';
  if (!list.length) { el.innerHTML = '<li style="color:var(--text-muted);padding:20px">No pages yet.</li>'; return; }
  el.innerHTML = list.map(function(p) {
    var preview = (p.preview || '').substring(0, 120).replace(/[#*_\\-]/g, ' ').replace(/\\n/g, ' ');
    return '<li class="page-item ' + currentSection.slice(0,-1) + '" data-path="' + currentSection + '/' + p.name + '.md">' +
      '<div class="name">' + p.name.replace(/-/g, ' ') + '</div>' +
      '<div class="preview">' + preview + '</div></li>';
  }).join('');
}

document.getElementById('tabs').addEventListener('click', function(e) {
  if (!e.target.dataset.section) return;
  currentSection = e.target.dataset.section;
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.toggle('active', t === e.target); });
  renderSection();
});

document.getElementById('page-list').addEventListener('click', function(e) {
  var item = e.target.closest('.page-item');
  if (!item || !item.dataset.path) return;
  openPage(item.dataset.path);
});

function openPage(path) {
  var modal = document.getElementById('modal');
  document.getElementById('modal-title').textContent = path;
  document.getElementById('modal-content').innerHTML = '<span style="color:var(--text-muted)">Loading...</span>';
  modal.classList.add('active');
  fetch('/api/read?path=' + encodeURIComponent(path)).then(function(r) {
    if (!r.ok) { document.getElementById('modal-content').innerHTML = '<span class="error">Page not found</span>'; return; }
    return r.json();
  }).then(function(data) {
    var content = data.content || '';
    content = content.replace(/\\[\\[([^\\]]+)\\]\\]/g, function(m, p) {
      var parts = p.split('|'), link = parts[0].trim(), label = parts[1] ? parts[1].trim() : link;
      var segs = link.includes('/') ? link.split('/') : ['summaries', link];
      return '<a href="#" class="wikilink" data-path="' + segs[0] + '/' + segs[1] + '.md">' + label + '</a>';
    });
    content = content.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    content = content.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    content = content.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    content = content.replace(/^- (.+)$/gm, '<li>$1</li>');
    content = content.replace(/`([^`]+)`/g, '<code>$1</code>');
    content = content.replace(/\\n\\n/g, '</p><p>');
    document.getElementById('modal-content').innerHTML = '<p>' + content + '</p>';
  }).catch(function(e) { document.getElementById('modal-content').innerHTML = '<span class="error">Error: ' + e.message + '</span>'; });
}

document.getElementById('modal').addEventListener('click', function(e) {
  if (e.target.dataset.path) { e.preventDefault(); openPage(e.target.dataset.path); return; }
  if (e.target === this || e.target.id === 'modal-close') { this.classList.remove('active'); }
});

document.getElementById('search-input').addEventListener('keydown', function(e) { if (e.key === 'Enter') search(); });
document.getElementById('search-input').nextElementSibling.addEventListener('click', search);

function search() {
  var q = document.getElementById('search-input').value.trim();
  if (!q) { document.getElementById('search-results').style.display = 'none'; renderSection(); return; }
  var pl = document.getElementById('page-list'), sr = document.getElementById('search-results');
  pl.style.display = 'none'; sr.style.display = '';
  sr.innerHTML = '<div id="loading">Searching...</div>';
  fetch('/api/search?q=' + encodeURIComponent(q)).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.matches.length) { sr.innerHTML = '<div style="color:var(--text-muted);padding:20px">No matches.</div>'; return; }
    sr.innerHTML = '<h2>Search: "' + q + '" (' + d.count + ' matches)</h2><ul class="page-list">' +
      d.matches.map(function(m) { return '<li class="page-item" data-path="' + m.file + '"><div class="name">' + m.file + ':' + m.line + '</div><div class="preview">' + m.text + '</div></li>'; }).join('') + '</ul>';
  }).catch(function(e) { sr.innerHTML = '<span class="error">Error: ' + e.message + '</span>'; });
}

document.getElementById('search-results').addEventListener('click', function(e) {
  var item = e.target.closest('.page-item');
  if (!item || !item.dataset.path) return;
  openPage(item.dataset.path);
});

var uploadZone = document.getElementById('upload-zone');
var fileInput = document.getElementById('file-input');
uploadZone.addEventListener('click', function() { fileInput.click(); });
uploadZone.addEventListener('dragover', function(e) { e.preventDefault(); this.classList.add('drag'); });
uploadZone.addEventListener('dragleave', function() { this.classList.remove('drag'); });
uploadZone.addEventListener('drop', function(e) { e.preventDefault(); this.classList.remove('drag'); uploadFiles(e.dataTransfer.files); });
fileInput.addEventListener('change', function() { if (this.files.length) uploadFiles(this.files); });

function uploadFiles(files) {
  if (!files || !files.length) return;
  var st = document.getElementById('upload-status');
  st.innerHTML = '<span style="color:var(--accent)">Uploading ' + files.length + ' file(s)...</span>';
  var form = new FormData();
  for (var i = 0; i < files.length; i++) form.append('files', files[i]);
  fetch('/api/upload', { method: 'POST', body: form }).then(function(r) { return r.json(); }).then(function(d) {
    var html = '';
    if (d.uploaded && d.uploaded.length) {
      html += d.uploaded.map(function(n) { return '<span class="ok">&#10003; ' + n + '</span>'; }).join('<br>');
      if (d.errors && d.errors.length) html += '<br>';
    }
    if (d.errors && d.errors.length) html += d.errors.map(function(e) { return '<span class="err">&#10007; ' + e + '</span>'; }).join('<br>');
    st.innerHTML = html || '<span style="color:var(--text-muted)">Done.</span>';
    setTimeout(load, 1500);
  }).catch(function(e) { st.innerHTML = '<span class="err">Error: ' + e.message + '</span>'; });
}

document.getElementById('query-input').addEventListener('keydown', function(e) { if (e.key === 'Enter') runQuery(); });
document.getElementById('query-btn').addEventListener('click', runQuery);

function runQuery() {
  var q = document.getElementById('query-input').value.trim();
  if (!q) return;
  var ans = document.getElementById('query-answer');
  ans.style.display = 'block';
  ans.innerHTML = '<span style="color:var(--text-muted)">Thinking...</span>';
  fetch('/api/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q }) }).then(function(r) { return r.json(); }).then(function(d) {
    if (d.error) { ans.innerHTML = '<span class="error">' + d.error + '</span>'; return; }
    var content = (d.answer || '');
    content = content.replace(/\\[\\[([^\\]]+)\\]\\]/g, function(m, p) {
      var parts = p.split('|'), link = parts[0].trim(), label = parts[1] ? parts[1].trim() : link;
      var segs = link.includes('/') ? link.split('/') : ['summaries', link];
      return '<a href="#" class="wikilink" data-path="' + segs[0] + '/' + segs[1] + '.md">' + label + '</a>';
    });
    content = content.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    content = content.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    content = content.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    content = content.replace(/^- (.+)$/gm, '<li>$1</li>');
    content = content.replace(/`([^`]+)`/g, '<code>$1</code>');
    content = content.replace(/\\n\\n/g, '</p><p>');
    ans.innerHTML = '<p>' + content + '</p>';
  }).catch(function(e) { ans.innerHTML = '<span class="error">Error: ' + e.message + '</span>'; });
}

document.addEventListener('keydown', function(e) { if (e.key === 'Escape') document.getElementById('modal').classList.remove('active'); });
load();
</script>
</body>
</html>
"""


def get_index_html() -> str:
    return _INDEX_HTML
