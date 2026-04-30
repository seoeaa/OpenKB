"""Graph visualization for the OpenKB wiki.

Generates an interactive force-directed graph of wikilinks connections.
"""
from __future__ import annotations

import re
from pathlib import Path

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_EXCLUDED = {"AGENTS.md", "SCHEMA.md", "log.md"}


def _extract_links(text: str) -> list[str]:
    return [link.split("|")[0].strip() for link in _WIKILINK_RE.findall(text)]


def _read_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _build_graph(wiki: Path) -> tuple[dict[str, dict], list[tuple[str, str]]]:
    nodes: dict[str, dict] = {}
    edges: list[tuple[str, str]] = set()

    for md in sorted(wiki.rglob("*.md")):
        if md.name in _EXCLUDED:
            continue
        if "sources" in md.relative_to(wiki).parts:
            continue
        rel = str(md.relative_to(wiki).with_suffix("")).replace("\\", "/")
        text = _read_md(md)
        frontmatter_brief = ""

        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                fm = text[:end + 3]
                body = text[end + 3:]
                for line in fm.split("\n"):
                    if line.startswith("brief:"):
                        frontmatter_brief = line[len("brief:"):].strip()
                        break
            else:
                body = text
        else:
            body = text

        title = md.stem.replace("-", " ").title()

        rel_parts = rel.split("/")
        node_type = rel_parts[0] if len(rel_parts) > 1 else "other"

        nodes[rel] = {
            "id": rel,
            "label": title,
            "type": node_type,
            "brief": frontmatter_brief,
        }

        for target in _extract_links(text):
            target_norm = target.strip().strip("/")
            if target_norm != rel:
                edges.add((rel, target_norm))

    return nodes, list(edges)


_GRAPH_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenKB Knowledge Graph</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }}
  #controls {{ position: fixed; top: 16px; left: 16px; z-index: 10; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px 16px; }}
  #controls h3 {{ font-size: 14px; margin-bottom: 8px; color: #58a6ff; }}
  #controls label {{ display: block; font-size: 12px; margin-bottom: 4px; }}
  #controls input[type=checkbox] {{ margin-right: 6px; }}
  #stats {{ position: fixed; top: 16px; right: 16px; z-index: 10; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px 16px; font-size: 12px; }}
  #info {{ position: fixed; bottom: 16px; left: 16px; z-index: 10; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px 16px; max-width: 400px; display: none; }}
  #info h4 {{ color: #58a6ff; margin-bottom: 4px; }}
  #info p {{ font-size: 12px; color: #8b949e; }}
  canvas {{ display: block; }}
</style>
</head>
<body>
<div id="controls">
  <h3>OpenKB Graph</h3>
  <label><input type="checkbox" id="show-concepts" checked> Concepts</label>
  <label><input type="checkbox" id="show-summaries" checked> Summaries</label>
  <label><input type="checkbox" id="show-explorations" checked> Explorations</label>
  <label><input type="checkbox" id="show-other" checked> Other</label>
</div>
<div id="stats"></div>
<div id="info"><h4 id="info-title"></h4><p id="info-brief"></p></div>
<script>
const DATA = {data_json};
const TYPE_COLORS = {{ concepts: "#7ee787", summaries: "#79c0ff", explorations: "#d2a8ff", reports: "#ffa657", other: "#8b949e" }};

let canvas, ctx, width, height;
let nodes = [], edges = [];
let dragging = null, hovered = null, offsetX = 0, offsetY = 0;
let scale = 1;

function init() {{
  canvas = document.getElementById('canvas');
  ctx = canvas.getContext('2d');
  resize();
  window.addEventListener('resize', resize);

  let i = 0;
  const nodeMap = {{}};
  for (const [id, n] of Object.entries(DATA.nodes)) {{
    const angle = (i / Object.keys(DATA.nodes).length) * 2 * Math.PI;
    const r = 200 + Math.random() * 200;
    const node = {{ ...n, x: width/2 + Math.cos(angle) * r, y: height/2 + Math.sin(angle) * r, vx: 0, vy: 0 }};
    nodes.push(node);
    nodeMap[id] = node;
    i++;
  }}
  for (const [src, tgt] of DATA.edges) {{
    if (nodeMap[src] && nodeMap[tgt]) edges.push([nodeMap[src], nodeMap[tgt]]);
  }}

  canvas.addEventListener('mousedown', onMouseDown);
  canvas.addEventListener('mousemove', onMouseMove);
  canvas.addEventListener('mouseup', onMouseUp);
  canvas.addEventListener('wheel', onWheel);

  document.querySelectorAll('#controls input').forEach(cb => cb.addEventListener('change', updateStats));

  updateStats();
  animate();
}}

function resize() {{ width = canvas.width = window.innerWidth; height = canvas.height = window.innerHeight; }}

function isVisible(node) {{
  const type = node.type || 'other';
  const el = document.getElementById('show-' + type);
  return el ? el.checked : true;
}}

function updateStats() {{
  const visible = nodes.filter(isVisible);
  document.getElementById('stats').innerHTML = `<b>${{visible.length}}</b> nodes · <b>${{edges.filter(e => isVisible(e[0]) && isVisible(e[1])).length}}</b> edges`;
}}

function simulate() {{
  const visible = nodes.filter(isVisible);
  for (const node of visible) {{
    node.vx *= 0.9; node.vy *= 0.9;
    for (const other of visible) {{
      if (node === other) continue;
      let dx = other.x - node.x, dy = other.y - node.y;
      let dist = Math.sqrt(dx*dx + dy*dy) || 1;
      if (dist < 300) {{ node.vx -= dx/dist * 0.5; node.vy -= dy/dist * 0.5; }}
    }}
    node.vx += (width/2 - node.x) * 0.0005;
    node.vy += (height/2 - node.y) * 0.0005;
  }}
  for (const [a, b] of edges) {{
    if (!isVisible(a) || !isVisible(b)) continue;
    let dx = b.x - a.x, dy = b.y - a.y;
    let dist = Math.sqrt(dx*dx + dy*dy) || 1;
    a.vx += dx/dist * 0.05; a.vy += dy/dist * 0.05;
    b.vx -= dx/dist * 0.05; b.vy -= dy/dist * 0.05;
  }}
  for (const node of visible) {{
    if (node === dragging) continue;
    node.x += node.vx; node.y += node.vy;
    node.x = Math.max(20, Math.min(width - 20, node.x));
    node.y = Math.max(20, Math.min(height - 20, node.y));
  }}
}}

function draw() {{
  ctx.clearRect(0, 0, width, height);
  for (const [a, b] of edges) {{
    if (!isVisible(a) || !isVisible(b)) continue;
    const highlight = hovered && (hovered === a || hovered === b);
    ctx.strokeStyle = highlight ? '#58a6ff' : '#21262d';
    ctx.lineWidth = highlight ? 2 : 1;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  }}
  for (const node of nodes) {{
    if (!isVisible(node)) continue;
    const color = TYPE_COLORS[node.type] || TYPE_COLORS.other;
    const highlight = node === hovered;
    const r = highlight ? 8 : 5;
    ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = color; ctx.fill();
    if (highlight) {{
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = '#c9d1d9'; ctx.font = '12px sans-serif';
      ctx.fillText(node.label, node.x + 12, node.y + 4);
    }}
  }}
}}

function animate() {{ simulate(); draw(); requestAnimationFrame(animate); }}

function findNode(x, y) {{
  for (const node of nodes) {{
    if (!isVisible(node)) continue;
    const dx = x - node.x, dy = y - node.y;
    if (dx*dx + dy*dy < 100) return node;
  }}
  return null;
}}

function onMouseDown(e) {{
  const node = findNode(e.clientX, e.clientY);
  if (node) {{ dragging = node; offsetX = e.clientX - node.x; offsetY = e.clientY - node.y; }}
}}
function onMouseMove(e) {{
  if (dragging) {{ dragging.x = e.clientX - offsetX; dragging.y = e.clientY - offsetY; dragging.vx = 0; dragging.vy = 0; }}
  hovered = findNode(e.clientX, e.clientY);
  canvas.style.cursor = hovered ? 'pointer' : 'default';
  const info = document.getElementById('info');
  if (hovered) {{
    info.style.display = 'block';
    document.getElementById('info-title').textContent = hovered.label + ' (' + hovered.type + ')';
    document.getElementById('info-brief').textContent = hovered.brief || '';
  }} else {{
    info.style.display = 'none';
  }}
}}
function onMouseUp() {{ dragging = null; }}
function onWheel(e) {{ scale *= e.deltaY > 0 ? 0.95 : 1.05; scale = Math.max(0.1, Math.min(5, scale)); }}

window.onload = init;
</script>
<canvas id="canvas"></canvas>
</body>
</html>
"""


def generate_graph(
    kb_dir: Path,
    html_path: Path,
    md_path: Path | None = None,
) -> None:
    """Generate an interactive graph visualization of the wiki.

    Args:
        kb_dir: Knowledge base root directory.
        html_path: Output path for the HTML file.
        md_path: Optional path to also export a Markdown adjacency list.
    """
    wiki = kb_dir / "wiki"
    nodes, edges = _build_graph(wiki)

    data_json = {
        "nodes": nodes,
        "edges": edges,
    }

    import json
    html = _GRAPH_HTML_TEMPLATE.format(data_json=json.dumps(data_json))
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")

    if md_path:
        lines = ["# Knowledge Base Graph\n"]
        lines.append(f"Nodes: {len(nodes)}, Edges: {len(edges)}\n")
        lines.append("## Adjacency List\n")
        adj: dict[str, list[str]] = {}
        for src, tgt in edges:
            adj.setdefault(src, []).append(tgt)
        for src in sorted(adj):
            targets = ", ".join(f"[[{t}]]" for t in sorted(adj[src]))
            lines.append(f"- **{src}** → {targets}")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text("\n".join(lines), encoding="utf-8")
