/* AutoApply: import PD Portal postings from YOUR browser.
   Runs on pdportal.apsc.ubc.ca while you are signed in (as a bookmarklet or pasted into the console).
   It reads the postings list and the details of postings AutoApply does not know yet, and sends them
   to AutoApply running on this computer (__APP__). Nothing is sent anywhere else. */
(async () => {
  const APP = '__APP__';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let box = document.getElementById('__aa_box');
  if (!box) {
    box = document.createElement('div');
    box.id = '__aa_box';
    box.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:999999;background:#14233b;color:#fff;padding:12px 16px;border-radius:10px;font:14px/1.5 system-ui,sans-serif;max-width:380px;box-shadow:0 8px 30px rgba(0,0,0,.35)';
    document.body.appendChild(box);
  }
  let closeTimer = null;
  const shut = () => { clearTimeout(closeTimer); box.remove(); };
  // every message keeps a close button; a finished run (ok or not) also goes away by itself
  const say = (t, final) => {
    clearTimeout(closeTimer);
    box.textContent = '';
    const x = document.createElement('button');
    x.textContent = '×'; x.title = '关闭'; x.setAttribute('aria-label', '关闭');
    x.style.cssText = 'float:right;margin:-4px -6px 0 10px;border:0;background:transparent;color:#fff;opacity:.75;font:20px/1 system-ui;cursor:pointer;padding:2px 6px';
    x.onclick = shut;
    box.appendChild(x);
    box.appendChild(document.createTextNode('AutoApply：' + t));
    if (final) {
      closeTimer = setTimeout(shut, final);
      box.onmouseenter = () => clearTimeout(closeTimer);
      box.onmouseleave = () => { closeTimer = setTimeout(shut, 4000); };
    }
  };
  // Two ways to reach AutoApply on this computer:
  //  1. direct requests (Chrome asks once whether this site may reach the local network - choose Allow);
  //  2. if that is refused, a small AutoApply window is opened and the data is handed to it with postMessage.
  let bridge = null, seq = 0;
  const waiting = {};
  window.addEventListener('message', (ev) => {
    if (ev.origin !== APP || !ev.data || !ev.data.aa) return;
    const w = waiting[ev.data.id];
    if (w) { delete waiting[ev.data.id]; ev.data.error ? w.reject(new Error(ev.data.error)) : w.resolve(ev.data.result); }
  });
  const viaBridge = (path, body) => new Promise((resolve, reject) => {
    const id = ++seq;
    waiting[id] = { resolve, reject };
    bridge.postMessage({ aa: 1, id, path, body }, APP);
    setTimeout(() => { if (waiting[id]) { delete waiting[id]; reject(new Error('AutoApply 窗口没有回应')); } }, 60000);
  });
  const openBridge = async () => {
    bridge = window.open(APP + '/pdportal-bridge', 'aa_bridge', 'width=420,height=260');
    if (!bridge) throw new Error('浏览器拦截了弹出窗口，请允许这个网站弹出窗口后再点一次');
    for (let i = 0; i < 40; i++) {  // wait until the window answers
      try { await Promise.race([viaBridge('ping', null), sleep(500).then(() => { throw new Error('wait'); })]); return; } catch (e) { /* not ready yet */ }
    }
    throw new Error('没能打开 AutoApply 窗口');
  };
  const once = async (method, path, body) => {
    if (bridge) return viaBridge(path, body);
    const r = await fetch(APP + path, method === 'GET' ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error('AutoApply 返回 ' + r.status);
    return r.json();
  };
  const call = async (method, path, body) => {  // AutoApply may be busy for a moment (a scan writing): try again
    for (let i = 0; ; i++) {
      try { return await once(method, path, body); } catch (e) {
        if (i >= 3 || !/50\d|没有回应/.test(String(e && e.message))) throw e;
        say('AutoApply 正忙，稍等再试…');
        await sleep(4000 * (i + 1));
      }
    }
  };
  const post = (path, body) => call('POST', path, body);
  try {
    if (!/pdportal\.apsc\.ubc\.ca$/.test(location.hostname)) { say('请在 PD Portal 的页面上使用。', 15000); return; }
    if (!document.querySelector('[onclick*=postingId]')) {
      const f = document.getElementById('widgetSearch');
      if (!f) { say('请先打开 Job Postings 页面（需要已登录），再点一次。', 20000); return; }
      say('正在列出全部岗位…列表出来后请再点一次书签。');
      f.widget1Keyword.value = ''; setTimeout(() => f.submit(), 400);
      return;
    }
    say('正在连接本机的 AutoApply…');
    let knownIds;
    try { knownIds = (await call('GET', '/api/import/pdportal/known')).ids; } catch (e) {
      say('浏览器没有允许直接连接，改用一个小窗口传数据…');
      await openBridge();
      knownIds = (await call('GET', '/api/import/pdportal/known')).ids;
    }
    const known = new Set(knownIds);

    say('正在读取岗位列表…');
    const grab = () => [...new Set([...document.querySelectorAll('[onclick*=postingId]')]
      .map((e) => (e.getAttribute('onclick').match(/postingId[^0-9]{1,6}(\d{5,7})/) || [])[1]).filter(Boolean))];
    const el = document.querySelector('[onclick*=postingId][onclick*=infoForPostings]');
    const m = el.getAttribute('onclick').match(/buildForm\((\{[\s\S]*?\})\s*,/);
    const obj = (0, eval)('(' + m[1] + ')'); delete obj.postingId;
    const all = new Set(grab());
    const pages = [...document.querySelectorAll('a')].map((a) => (a.getAttribute('onclick') || '').match(/loadPostingTable\([^)]*?'(\d+)'\s*,\s*'advanced'/)).filter(Boolean).map((x) => +x[1]);
    const last = Math.max(1, ...pages);
    for (let p = 2; p <= last; p++) {
      say(`正在读取岗位列表…第 ${p} / ${last} 页`);
      window.loadPostingTable('', 'ID', 'Reverse', String(p), 'advanced', '', null);
      await sleep(3500);
      grab().forEach((i) => all.add(i));
    }
    const ids = [...all];
    const fresh = ids.filter((i) => !known.has(i));
    let sent = 0;
    for (let k = 0; k < fresh.length; k += 8) {
      const details = [];
      for (const id of fresh.slice(k, k + 8)) {
        say(`正在读取新岗位 ${sent + details.length + 1} / ${fresh.length}…`);
        try {
          const r = await fetch('/myAccount/co-op/postings.htm', { method: 'POST', body: new URLSearchParams({ ...obj, postingId: id }) });
          const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
          doc.querySelectorAll('script,style,noscript').forEach((e) => e.remove());
          const d = document.createElement('div');
          d.style.cssText = 'position:fixed;left:-99999px;top:0;width:1100px';
          d.appendChild(document.importNode(doc.querySelector('main') || doc.body, true));
          document.body.appendChild(d);
          const text = d.innerText.replace(/[ \t]+/g, ' ').slice(0, 40000);
          d.remove();
          if (text.trim()) details.push({ id, text });
        } catch (e) { /* skip this one; it will be picked up next time */ }
        await sleep(350);
      }
      await post('/api/import/pdportal', { details });
      sent += details.length;
    }
    const res = await post('/api/import/pdportal', { details: [], all_ids: ids, done: true });
    if (bridge) { try { bridge.close(); } catch (e) { /* already closed */ } }
    say(`完成。门户上共 ${ids.length} 个岗位，新增 ${res.new} 个，下线 ${res.offline} 个。`, 12000);
    const a = document.createElement('a');
    a.href = APP + '/jobs'; a.target = '_blank'; a.textContent = ' 打开 AutoApply';
    a.style.cssText = 'color:#7fe3da;margin-left:6px';
    box.appendChild(a);
  } catch (e) {
    say('没有成功：' + (e && e.message ? e.message : e) + '。请确认 AutoApply 正在本机运行。', 30000);
  }
})();
