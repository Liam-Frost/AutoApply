"""One application, one agent.

The agent is given everything - the posting, the applicant's profile and files, what is known about the site, what
was done on this application before - and a browser. It reads the pages, decides what a step is and which button
leads where, fills the form, and reports what it did. The program around it keeps the queue, the files, the secrets
and the evidence; it does not decide anything about a page.

    hands.py    the browser, as tools: look, read, the controls of the page, click, type, choose, upload, script
    brief.py    what the agent is told: the whole context of one application
    run.py      one run of the agent on one application: its journal, its record, how it ended

What is NOT here, on purpose: a notion of "form structure", of steps, of which button may be pressed, a list of
phrases that mean "submitted". See docs: the four limits of an application are in ``brief.LIMITS``.
"""
