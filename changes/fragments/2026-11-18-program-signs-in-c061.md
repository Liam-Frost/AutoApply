---
id: 2026-11-18-program-signs-in-c061
type: fixed
scope: accounts
summary:
  en: "The program signs in by itself: unconfirmed accounts, the co-op portal, a password on another address"
  zh: "程序自行登录：未验证邮箱的账号、Co-op 门户、在另一个地址输入密码的网站"
  fr: "Le programme se connecte seul : comptes non confirmés, portail co-op, mot de passe sur une autre adresse"
---

- **An account whose e-mail address is not confirmed is confirmed by the program, whenever it is met.** Workday shows
  "An email has been sent to you. Please verify your account." in the banner it also uses for errors, so a registration
  that had worked was filed as failed. From then on every run tried the password, was told to verify the account first,
  and asked you to sign in - to an account nobody could sign in to - while the site's mail, with a link on the site's
  own address, lay unopened. "Not confirmed yet" is now a state of the account: after registering, at a later sign-in
  and after a submission the same thing happens - the site's mail is looked for back to when the account was made, its
  link is opened, and the program signs in. If that link no longer works, the site is asked for another mail. Only when
  all of that fails are you asked, and then to open the mail, not to sign in. Accounts that were stuck this way are
  put back in line when the program starts.
  - Mail that carries a code or a link for an account is recognised by more subjects ("Verify your candidate
    account", "Confirm your ... email address") and, as before, never summarised or shown to a model.
  - A link read from an HTML mail is kept as a browser would follow it ("&amp;" in its address was left in).
- **The co-op portal is signed in to by the program; only the approval on your phone is yours.** The portal's sign-in
  used to be handed to you whole, every time its session ran out. Save your CWL login name and password for it on the
  Accounts page, and the program goes through the portal's sign-in itself: the password is typed on the university's
  login address only, you get a message when Duo waits for your approval, and the program waits three minutes for it.
  An approval that did not come is not asked for again behind your back - the card waits for you. A password the
  university refuses is not sent a third time. The scan signs in the same way an application does; before, it made a
  card without going near the sign-in.
- **A site that keeps its sign-in on another address gets its password there.** Amazon's careers site asks for the
  e-mail on its own page and sends the window to another Amazon address for the password. The program took that for
  "another site, with its own account", found no password for it and stopped at the password box, with the right
  password saved. A sign-in that begins on the site's own pages and is led on by the site is the site's sign-in; the
  address is remembered once the password has worked there (also when you sign in by hand). A sign-in that begins on
  another address still gets nothing typed.
- **A sign-in through an institution is gone through again before you are asked.** The co-op portal's own session
  lasts about an hour, the university login behind it longer: when the portal's has run out, the program follows the
  portal's sign-in link once - nothing is typed - and asks you only if a password or a second factor is wanted.
  The card for such a site no longer offers to register an account.
