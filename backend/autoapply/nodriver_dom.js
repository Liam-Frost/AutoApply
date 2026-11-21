// DOM queries used by the native CDP backend. Re-evaluated on each operation.
//
// These read a selector the way the automated browser does, for the shapes the program's own code writes - no more
// (tests/test_browser_contract.py runs each of them in both browsers against one expected answer):
//   css, lists of css, :visible, :has-text('…'), xpath=…, "..", visible=true, text=…, by role / label / text.
// Text is compared as the automated browser compares it: without regard to case and anywhere in the element's text,
// unless it is asked for exactly - then the whole text, case and all.
(function () {
  const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const clean = s => String(s || '').replace(/\s+/g, ' ').trim();
  const fold = s => clean(s).toLowerCase();
  const match = (text, spec) => spec.regex !== undefined
    ? new RegExp(spec.regex, spec.flags).test(text)
    : spec.exact ? clean(text) === clean(spec.text) : fold(text).includes(fold(spec.text));
  // text=…: /a regular expression/flags, "exactly this", or a part of the text
  const textSpec = t => {
    const re = /^\/(.*)\/([a-z]*)$/.exec(t);
    if (re) return {regex: re[1], flags: re[2]};
    const quoted = /^(['"])(.*)\1$/.exec(t);
    return quoted ? {text: quoted[2], exact: true} : {text: t, exact: false};
  };
  // the smallest elements whose text it is (not every one of their ancestors as well)
  const withText = (root, spec) => css(root, '*').filter(e => match(e.textContent, spec) && ![...e.children].some(c => match(c.textContent, spec)));
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
    if (selector === 'visible=true' || selector === 'visible=false') return root.nodeType === 1 && visible(root) === selector.endsWith('true') ? [root] : [];
    if (selector.startsWith('text=')) return withText(root, textSpec(selector.slice(5)));
    if (selector.startsWith('xpath=')) {
      const result = document.evaluate(selector.slice(6), root, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      return Array.from({length:result.snapshotLength}, (_, i) => result.snapshotItem(i));
    }
    // :visible can occur on an ancestor as well as the final element.
    const texts = [];
    const filtered = selector.replace(/:has-text\((['"])(.*?)\1\)/g, (_, quote, text) => { texts.push(text); return ''; }).replace(/:visible/g, ':not([hidden])');
    let result = [...root.querySelectorAll(filtered)];
    if (selector.includes(':visible')) result = result.filter(visible);
    if (texts.length) result = result.filter(e => texts.every(text => fold(e.textContent).includes(fold(text))));
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
        case 'text': nodes = nodes.flatMap(n => withText(n, step.text)); break;
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
