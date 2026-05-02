"""Agent harness web routes (traces + HITL queue).

Mounted under /api/agent. The harness UI is a single self-contained
HTML page served from ``/api/agent/viewer`` -- it talks to the JSON
endpoints below and avoids the Vue build cycle so the viewer ships
without re-running ``npm run build``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from src.agent.trace.store import TraceStore

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/traces")
def list_traces(limit: int = 50) -> dict:
    """Return the most recent agent traces as summaries (no step bodies)."""
    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit must be between 1 and 500.")
    store = TraceStore()
    return {"traces": [r.summary() for r in store.list(limit=limit)]}


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str) -> dict:
    """Return one full trace including every step body."""
    store = TraceStore()
    try:
        record = store.load(trace_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return record.to_dict()


@router.get("/viewer", response_class=HTMLResponse)
def viewer() -> HTMLResponse:
    """Minimal trace replay UI -- no JS framework, just fetch + DOM."""
    return HTMLResponse(_VIEWER_HTML)


_VIEWER_HTML = """<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<title>AutoApply -- Agent Traces</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 0;
         display: grid; grid-template-columns: 320px 1fr; height: 100vh; }
  aside { border-right: 1px solid #8884; overflow-y: auto; padding: 12px; }
  main  { overflow-y: auto; padding: 16px 24px; }
  h1 { font-size: 16px; margin: 0 0 12px; }
  ul { list-style: none; padding: 0; margin: 0; }
  li.trace { padding: 8px 6px; border-radius: 6px; cursor: pointer;
             border: 1px solid transparent; }
  li.trace:hover { background: #8881; }
  li.trace.active { border-color: #5b9bd599; background: #5b9bd522; }
  li.trace .goal { font-size: 12.5px; line-height: 1.35;
                   overflow: hidden; text-overflow: ellipsis;
                   display: -webkit-box; -webkit-line-clamp: 2;
                   -webkit-box-orient: vertical; }
  li.trace .meta { font-size: 11px; color: #888; margin-top: 4px;
                   display: flex; gap: 8px; }
  .ok    { color: #2a8a3a; }
  .fail  { color: #c0392b; }
  .step  { border: 1px solid #8884; border-radius: 8px;
           margin-bottom: 12px; padding: 10px 12px; }
  .step h3 { margin: 0 0 4px; font-size: 13px; }
  .step .thought { font-style: italic; color: #666; margin: 4px 0; }
  pre { background: #8881; padding: 8px 10px; border-radius: 6px;
        overflow-x: auto; font-size: 12px; white-space: pre-wrap; }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 999px;
          font-size: 11px; background: #8882; }
  .pill.err { background: #c0392b33; color: #c0392b; }
  .empty { color: #888; }
</style>
</head>
<body>
<aside>
  <h1>Agent traces</h1>
  <ul id=\"list\"><li class=\"empty\">Loading...</li></ul>
</aside>
<main id=\"detail\"><p class=\"empty\">Select a trace on the left.</p></main>
<script>
const $list = document.getElementById('list');
const $detail = document.getElementById('detail');

function fmtMs(ms) {
  if (ms == null) return '';
  if (ms < 1000) return ms + 'ms';
  return (ms / 1000).toFixed(1) + 's';
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]
  ));
}

async function loadList() {
  const r = await fetch('/api/agent/traces');
  if (!r.ok) { $list.innerHTML = '<li class=\"empty\">Failed to load.</li>'; return; }
  const { traces } = await r.json();
  if (!traces.length) {
    $list.innerHTML = '<li class=\"empty\">No traces yet.</li>'; return;
  }
  $list.innerHTML = '';
  for (const t of traces) {
    const li = document.createElement('li');
    li.className = 'trace';
    li.dataset.id = t.id;
    const status = t.finished
      ? '<span class=\"pill ok\">finished</span>'
      : `<span class=\"pill err\">${escapeHtml(t.stop_reason || 'failed')}</span>`;
    li.innerHTML = `
      <div class=\"goal\">${escapeHtml(t.goal || '(no goal)')}</div>
      <div class=\"meta\">${status}
        <span>${escapeHtml(t.step_count)} steps</span>
        <span>${escapeHtml(fmtMs(t.elapsed_ms))}</span></div>`;
    li.addEventListener('click', () => loadDetail(t.id));
    $list.appendChild(li);
  }
}

async function loadDetail(id) {
  for (const el of $list.querySelectorAll('li.trace')) {
    el.classList.toggle('active', el.dataset.id === id);
  }
  $detail.innerHTML = '<p class=\"empty\">Loading...</p>';
  const r = await fetch(`/api/agent/traces/${encodeURIComponent(id)}`);
  if (!r.ok) { $detail.innerHTML = '<p class=\"empty\">Not found.</p>'; return; }
  const t = await r.json();
  const head = `
    <h2 style=\"margin-top:0\">${escapeHtml(t.goal || '(no goal)')}</h2>
    <p><span class=\"pill ${t.finished ? 'ok' : 'err'}\">
      ${escapeHtml(t.finished ? 'finished' : (t.stop_reason || 'failed'))}
    </span>
    <span class=\"pill\">${escapeHtml(t.step_count)} steps</span>
    <span class=\"pill\">${escapeHtml(fmtMs(t.elapsed_ms))}</span>
    <span class=\"pill\">${escapeHtml(t.started_at)}</span></p>
    ${t.answer ? `<p><b>Answer:</b> ${escapeHtml(t.answer)}</p>` : ''}
    <p><b>Tools:</b> ${
      (t.tools_allowed || [])
        .map(x => `<code>${escapeHtml(x)}</code>`)
        .join(', ') || '(none)'
    }</p>`;
  const stepsHtml = (t.steps || []).map(s => `
    <div class=\"step\">
      <h3>Step ${escapeHtml(s.index)}: <code>${escapeHtml(s.action_name || '(none)')}</code>
        ${s.is_error ? '<span class=\"pill err\">error</span>' : ''}
        <span class=\"pill\">${escapeHtml(fmtMs(s.latency_ms))}</span></h3>
      ${s.thought ? `<p class=\"thought\">${escapeHtml(s.thought)}</p>` : ''}
      <details><summary>Args</summary>
        <pre>${escapeHtml(JSON.stringify(s.action_args || {}, null, 2))}</pre></details>
      <details open><summary>Observation</summary>
        <pre>${escapeHtml(s.observation)}</pre></details>
      <details><summary>Raw response</summary>
        <pre>${escapeHtml(s.raw_response)}</pre></details>
    </div>`).join('');
  $detail.innerHTML = head + (stepsHtml || '<p class=\"empty\">No steps recorded.</p>');
}

loadList();
</script>
</body>
</html>
"""
