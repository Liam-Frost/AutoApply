---
id: 2026-11-18-signin-browser-5146
type: fixed
scope: accounts
summary:
  en: "A sign-in stays in the browser it was made in, and the card says whose sign-in is missing"
  zh: "登录会话留在建立它的浏览器里，卡片会说明缺的是哪家的登录"
  fr: "Une connexion reste dans le navigateur où elle a été faite, et la carte dit quelle connexion manque"
---

- The sign-in window in the ordinary browser now keeps a sign-in on a site nothing can check (no driver, no known address) when the applicant closes the window, as the automated browser's window does; it used to say "window closed before sign-in was verified" every time. The two windows also agree now on what a finished sign-in leaves behind: its card is closed, and a sign-in provider's session is not listed as a site account.
- **A card that asks you to sign in to Google (or another provider) finishes when you have.** The card's button opened
  the window without the provider's own check for "signed in", so the window could be signed in and nothing noticed:
  the session was not kept and the tasks that waited went on waiting.
- **Forgetting a sign-in forgets which browser it was made in.** After a sign-in was removed, the next one was still
  opened in the browser of the one that no longer existed, whatever the rules said.
- **A sign-in carried over from another computer replaces the one that is there.** The ordinary browser kept using the
  cookies of the session that was being replaced, while the import said it had worked.
- **A sign-in stays in the browser it was made in.** Which browser does a site's work used to be decided by the kind
  of work, so a site you had signed in to in the ordinary browser was read or filled in the automated one, with the
  cookies carried over - where the site showed you as signed out and asked for a sign-in you already had (Google's
  careers site; the university portal before). Now the browser is decided per site, by where its sign-in is: reading,
  filling, scanning and signing in all happen there. Where each sign-in was made is recorded when it is saved; a site
  that signs in through a provider follows the provider; and a provider's sign-in is no longer shown to the other
  browser at all, which is what could make the provider sign the real one out.
- **The ordinary browser is always a window.** Hidden, it calls itself `HeadlessChrome` - not the browser you signed
  in with - and the university portal's firewall, which lets the window in, turned every hidden scan away (the card
  then advised switching on what was already on). A sign-in made in a window is now used in a window: where nobody
  has to look it opens and closes by itself (on a server, on the virtual screen). A site that turns the hidden
  browser away is remembered the same way for every caller, the firewall's own check is given time to pass, and if a
  window is refused too the card asks for the sign-in that renews the pass.
- **The card says whose sign-in is missing.** When the run stopped on a provider's own sign-in page - or the site's
  sign-in is the provider's, as with Google's careers site - there is one card for the provider ("sign in to Google
  again"), not a card per posting offering "use my Google account" for Google itself.
