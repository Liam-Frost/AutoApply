hosts: pdportal.apsc.ubc.ca, orbiscommunities.ca

# University co-op portals on Orbis (UBC PD Portal and its kind)

- Signed in through the university's own login, usually with a second factor on the applicant's phone: theirs to
  approve. A session lasts a few hours; "Not Logged In" means it is over.
- Postings: the co-op postings page lists every faculty's postings. Narrow it to the applicant's programme first (see
  below); a keyword search is not that (and the placeholder "Keyword" is not a keyword: a filter chip with it shows
  nothing - remove it). Each row's button carries the form data that opens the posting.
- A posting has no address of its own: the program names it "...postings.htm#posting=<id>", which opens the
  postings page and nothing more. Open it from the list: take the object in a row button's
  onclick="...buildForm({...})" and submit it with that posting's id, in this tab -
  orbisAppSr.buildForm({...obj, postingId: '<id>'}, '', '_self').submit()
- A posting says how to apply ("Application Receipt Procedure"): through the portal ("Online via system"), on the
  employer's own website (with its address), or by e-mail; and which documents it requires.
- Employer-website postings: the application is made on the employer's site; in the portal the applicant only
  expresses the intention to apply.
- Online via system: "APPLY" on the posting, then "Create a customized application package", choose each required
  document from the applicant's documents (a cover letter is per posting; résumé, transcript and others as listed),
  give the package a name, "Submit Application". The page then says the application has been submitted for the
  posting (with its job ID). Check it under Applications: a first attempt can fail without a word.
- Documents are uploaded under My Documents, "Upload Document" (a name, a type, the file). After choosing the file
  the upload link may need pressing twice: check that the page has left "Upload a Document".
- Deadlines are in the portal's time zone, not the viewer's.

## Reading the postings for the applicant's programme (what worked on UBC's PD Portal)

All postings are some thousand; those for one programme (Computer) about two hundred. On the postings page, open the
"For My Program" search (or any list of postings); its QUICK FILTERS have "Filter by Program" - a list box
(`select[name=programId]`) of the programmes - and "Apply Filters". Select only the applicant's programme(s) (the brief
names them; "Computer Engineering" is "Computer"), apply, and check the count the page states. Then this script, given
to `save_postings`, reads the ids from every page of that list and fetches the text of the postings that are new - the
detail page is a POST with the object from a row's button. If paging loses the filter (the count grows to everything),
page with the list's own page links instead. Only when no programme of the applicant's is offered: submit the search
form with an empty keyword (`#widgetSearch`, field `widget1Keyword`) and read everything.

```js
async (known) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const grab = () => [...new Set([...document.querySelectorAll('[onclick*=postingId]')]
      .map(e => (e.getAttribute('onclick').match(/postingId[^0-9]{1,6}(\d{5,7})/) || [])[1]).filter(Boolean))];
  const el = document.querySelector('[onclick*=postingId][onclick*=infoForPostings]');
  const obj = (0, eval)('(' + el.getAttribute('onclick').match(/buildForm\((\{[\s\S]*?\})\s*,/)[1] + ')'); delete obj.postingId;
  const all = new Set(grab());
  const pages = [...document.querySelectorAll('a')].map(a => (a.getAttribute('onclick') || '')
      .match(/loadPostingTable\([^)]*?'(\d+)'\s*,\s*'advanced'/)).filter(Boolean).map(m => +m[1]);
  for (let p = 2; p <= Math.max(1, ...pages); p++) {
    window.loadPostingTable('', 'ID', 'Reverse', String(p), 'advanced', '', null); await sleep(3500); grab().forEach(i => all.add(i));
  }
  const postings = [];
  for (const id of [...all].filter(i => !known.includes(i))) {
    const r = await fetch('/myAccount/co-op/postings.htm', {method: 'POST', body: new URLSearchParams({...obj, postingId: id})});
    const d = document.createElement('div'); d.innerHTML = await r.text();
    postings.push({id, text: (d.querySelector('main') || d).innerText.replace(/[ \t]+/g, ' ').slice(0, 40000)});
  }
  return {listed: [...all], postings};
}
```

A posting's text has lines the program reads by itself when you give only the text: "Job Title:", "Organization:",
"Application Deadline:", "Application Receipt Procedure:" (Online via system = applied for in the portal; otherwise
"If by Website, go to:" has the employer's address), "Application Documents Required:", "Co-op Work Term:", "Length
of Work Term:", "Job Location:", "Salary ($):", "Job Description:". If the portal has changed and this no longer
holds, read the fields yourself and give them with each posting.

