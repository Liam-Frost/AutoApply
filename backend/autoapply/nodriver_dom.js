// DOM queries used by the native CDP backend. Re-evaluated on each operation.
(function () {
  const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const clean = s => String(s || '').replace(/\s+/g, ' ').trim();
  const match = (text, spec) => spec.regex !== undefined
    ? new RegExp(spec.regex, spec.flags).test(text)
    : spec.exact ? clean(text) === clean(spec.text) : clean(text).includes(clean(spec.text));
  const name = e => {
    const labelled = e.getAttribute('aria-labelledby');
    if (labelled) return clean(labelled.split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' '));
    return clean(e.getAttribute('aria-label') || Array.from(e.labels || []).map(x => x.textContent).join(' ') || e.getAttribute('alt') || (e.matches('input[type=button], input[type=submit]') ? e.value : e.textContent) || e.title);
  };
  const role = e => e.getAttribute('role') || ({BUTTON:'button', SELECT:e.multiple ? 'listbox':'combobox', TEXTAREA:'textbox', OPTION:'option', FIELDSET:'group'}[e.tagName]) ||
    (e.tagName === 'A' && e.hasAttribute('href') ? 'link' : '') ||
    (e.tagName === 'INPUT' ? ({checkbox:'checkbox', radio:'radio', submit:'button', button:'button', search:'searchbox', number:'spinbutton'}[e.type] || 'textbox') : '') ||
    (/^H[1-6]$/.test(e.tagName) ? 'heading' : '');
  function css(root, selector) {
    if (selector === '..' || selector === 'xpath=..') return root.parentElement ? [root.parentElement] : [];
    if (selector.startsWith('xpath=')) {
      const result = document.evaluate(selector.slice(6), root, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      return Array.from({length:result.snapshotLength}, (_, i) => result.snapshotItem(i));
    }
    // :visible can occur on an ancestor as well as the final element.
    const texts = [];
    const filtered = selector.replace(/:has-text\((['"])(.*?)\1\)/g, (_, quote, text) => { texts.push(text); return ''; }).replace(/:visible/g, ':not([hidden])');
    let result = [...root.querySelectorAll(filtered)];
    if (selector.includes(':visible')) result = result.filter(visible);
    if (texts.length) result = result.filter(e => texts.every(text => clean(e.textContent).includes(clean(text))));
    for (const host of root.querySelectorAll('*')) if (host.shadowRoot) result.push(...css(host.shadowRoot, selector));
    return result;
  }
  function query(steps, root = document) {
    let nodes = [root];
    for (const step of steps) {
      switch (step.kind) {
        case 'css': nodes = nodes.flatMap(n => css(n, step.selector)); break;
        case 'role': nodes = nodes.flatMap(n => css(n, '*')).filter(e => role(e) === step.role && (step.include_hidden || visible(e)) && (!step.name || match(name(e), step.name))); break;
        case 'label': nodes = nodes.flatMap(n => css(n, 'input,select,textarea,button,[role]')).filter(e => match(name(e), step.text)); break;
        case 'text': nodes = nodes.flatMap(n => css(n, '*')).filter(e => match(e.textContent, step.text) && ![...e.children].some(c => match(c.textContent, step.text))); break;
        case 'nth': nodes = nodes.length ? [nodes.at(step.index)].filter(Boolean) : []; break;
        case 'filter': nodes = nodes.filter(e => (!step.text || match(e.textContent, step.text)) && (!step.has || query(step.has, e).length)); break;
        case 'or': nodes = [...new Set([...nodes, ...query(step.steps, root)])]; break;
        default: throw new Error('Unsupported locator operation ' + step.kind);
      }
      nodes = [...new Set(nodes)];
    }
    return nodes;
  }
  return {query, visible};
})()
