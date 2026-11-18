hosts: pdportal.apsc.ubc.ca, orbiscommunities.ca

# University co-op portals on Orbis (UBC PD Portal and its kind)

- Signed in through the university's own login, usually with a second factor on the applicant's phone: theirs to
  approve. A session lasts a few hours; "Not Logged In" means it is over.
- Postings: the co-op postings page, searched with an EMPTY keyword (the placeholder "Keyword" is not a keyword: a
  filter chip with it shows nothing - remove it). Each row's button carries the form data that opens the posting.
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
