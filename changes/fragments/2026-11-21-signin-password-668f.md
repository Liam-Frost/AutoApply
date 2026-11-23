---
id: 2026-11-21-signin-password-668f
type: fixed
scope: accounts
summary:
  en: "Sign-ins: no empty password sent; “remember the password” kept in the ordinary browser too"
  zh: "登录：不再提交空密码；普通浏览器的登录窗口也能记住你输入的密码"
  fr: "Connexions : plus de mot de passe vide envoyé ; « mémoriser le mot de passe » aussi dans le navigateur ordinaire"
---

- **A sign-in whose button did nothing was sent with an empty password.** The program typed the stored password, pressed the button and emptied the box again; when the press had done nothing (an ordinary browser opens its own list of saved passwords over the form, and the first click only closes it), the agent sent the form itself - empty - and the site answered "invalid login name/password", twice. The program now follows the press: it presses again through the page, then sends the form directly, and tells the agent whether the form went out.
- **"Remember the password I type" is kept in the ordinary browser's sign-in window too.** Every sign-in card offers it; in the window of the ordinary browser (the one used for sites that refuse an automated browser, the co-op portal among them) nothing was ever remembered, whatever was ticked - the applicant signed in, and was asked to again each time the session ran out. The login is now taken from what the sign-in form sends, as the browser reports it: nothing is put into the page, and a form the browser's own password manager filled in is heard as well as one that was typed. A password given at a site's own sign-in on another address (a university's login) is that site's and is kept; one given at Google, Microsoft or LinkedIn during "sign in with" still never is. A card offers to remember only where its window can: a card for a sign-in provider says that only the sign-in is kept, and a card whose window the program does not look into (a site that refuses the automated browser, with the ordinary browser switched off) points to the Accounts page instead.
