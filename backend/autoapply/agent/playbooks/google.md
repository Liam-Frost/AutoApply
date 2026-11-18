hosts: google.com

# Google Careers

- Signed in with a Google account; the sign-in itself is the applicant's.
- The "Apply" button on a posting is named by its aria-label. It opens /applications/apply/<id>/form.
- Four steps: Careers profile, Role information, Voluntary self-identification, Review & apply. The first ends with
  "Submit profile & continue" - that saves the profile, which is shared by all of the person's applications there,
  and opens the next step; it does not send the application.
- The profile step parses the résumé: it turns projects into jobs and leaves stray entries among the skills. Remove
  what the applicant's profile contradicts ("REMOVE THIS JOB" under the last job block).
- Lists are custom: they open on a click or a key press; skill and location pickers show suggestions only after
  the last keystroke.
- After the application is sent there is no thank-you page: the dashboard lists it under Applications, "Submitted".
- A banner says how many applications may be sent in 30 days.
