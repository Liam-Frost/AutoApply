// Small, dependency-free Markdown renderer for the profile preview.
// Everything is HTML-escaped first; only the tags produced here reach the page.

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

function inline(raw) {
  const codes = []
  let s = esc(raw).replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000` })
  s = s
    .replace(/\[([^\]]+)\]\(((?:https?:\/\/|mailto:)[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])((?:https?:\/\/)[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?![*\w])/g, '$1<em>$2</em>')
    .replace(/\bTODO\b:?/g, '<span class="tag warn">TODO</span>')
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`)
}

const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/

function list(lines, start) {
  // Consumes a (possibly nested) list beginning at lines[start]; returns [html, nextIndex].
  const base = LIST.exec(lines[start])[1].length
  const ordered = /\d/.test(LIST.exec(lines[start])[2])
  let html = ordered ? '<ol>' : '<ul>'
  let i = start
  while (i < lines.length) {
    const m = LIST.exec(lines[i])
    if (!m) {
      // continuation text indented under the previous item
      if (lines[i].trim() && /^\s+/.test(lines[i]) && lines[i].search(/\S/) > base) { html = html.replace(/<\/li>$/, ' ' + inline(lines[i].trim()) + '</li>'); i++; continue }
      break
    }
    const indent = m[1].length
    if (indent < base) break
    if (indent > base) { const [inner, next] = list(lines, i); html = html.replace(/<\/li>$/, inner + '</li>'); i = next; continue }
    html += `<li>${inline(m[3])}</li>`
    i++
  }
  return [html + (ordered ? '</ol>' : '</ul>'), i]
}

export function renderMarkdown(src) {
  const lines = String(src || '').replace(/\r/g, '').split('\n')
  const out = []
  let para = []
  const flush = () => { if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = [] } }
  for (let i = 0; i < lines.length; ) {
    const ln = lines[i]
    if (!ln.trim()) { flush(); i++; continue }
    if (/^```/.test(ln)) {
      flush()
      const buf = []
      i++
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++])
      i++
      out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`)
      continue
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(ln)
    if (h) { flush(); const n = Math.min(6, h[1].length + 2); out.push(`<h${n}>${inline(h[2])}</h${n}>`); i++; continue }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(ln)) { flush(); out.push('<hr>'); i++; continue }
    if (/^\s*>/.test(ln)) {
      flush()
      const buf = []
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ''))
      out.push(`<blockquote>${buf.map(inline).join('<br>')}</blockquote>`)
      continue
    }
    if (/^\s*\|.*\|\s*$/.test(ln) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      flush()
      const cells = (r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()))
      let t = `<table><thead><tr>${cells(ln).map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>`
      i += 2
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) t += `<tr>${cells(lines[i++]).map((c) => `<td>${c}</td>`).join('')}</tr>`
      out.push(t + '</tbody></table>')
      continue
    }
    if (LIST.test(ln)) { flush(); const [html, next] = list(lines, i); out.push(html); i = next; continue }
    para.push(ln.trim())
    i++
  }
  flush()
  return out.join('\n')
}
