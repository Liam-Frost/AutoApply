---
id: 2026-11-15-account-sections-links-e6d4
type: fixed
scope: accounts
summary:
  en: "Accounts on forms: only the site’s own confirmation link opened; sign in or register as known"
  zh: "表单中的账号：只打开网站自己的确认链接；按已知情况登录或注册"
  fr: "Comptes dans les formulaires : seul le lien de confirmation du site est ouvert ; connexion ou inscription selon ce qui est connu"
---

- A confirmation link in an e-mail ("confirm your e-mail address to finish signing up") is opened by the program -
  when, and only when, it is the site's own: the program is signing up or in on that site at that moment, the link is
  https and leads to that same site (another domain, a mail service's redirect, a look-alike host, an address with a
  user name, a port or a bare IP in it are not opened), and the address is in the mail word for word. The address,
  which carries a one-time token, is not shown to the model or written to a log. If the link leads away from the site,
  the window goes back and nothing is typed there. A link that is not opened is reported, and the account is marked as
  needing you. The site's password is typed on the site's own pages only.
- A form that creates your account on the site together with the application ("Create a Career Profile account",
  marked optional) gets that section filled: the agent chooses the password option and the program types a generated
  password it keeps for you (never shown to the model). After the submission the site's confirmation e-mail is
  completed under the rules for links, and the account is ready for the next application there; if that does not
  work, the account page says what is missing. Before, the section was left empty and the account stayed "being
  registered".
- A form's account section is handled by what is known: when an account for the site is saved the agent signs in
  ("Already have an account") instead of registering a second time, and falls back to creating one only when the
  site says the account does not exist; with no saved account it creates one. Before, it was told to create one in
  every case.
