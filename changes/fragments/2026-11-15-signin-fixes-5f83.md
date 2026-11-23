---
id: 2026-11-15-signin-fixes-5f83
type: fixed
scope: accounts
summary:
  en: "Sign-ins: found from another address, refused passwords counted, sign-in cards closed once signed in"
  zh: "登录：从其他地址进入也能找到已保存的登录，被拒的密码计入失败次数，登录后关闭登录卡片"
  fr: "Connexions : retrouvées depuis une autre adresse, mots de passe refusés comptés, cartes fermées une fois connecté"
---

- A card that asks you to sign in to a site is closed as soon as the program is signed in there, however that came
  about. A draft that is built clears the "failed" note of the attempt before it.
- A saved sign-in is found when the same employer's sign-in page is reached from another address. An employer whose
  postings appear under two addresses (a careers site and its own domain) was asked for a new sign-in under the
  second one, although the sign-in page - and the saved account - was the same. The account is now found by the host
  of the sign-in page (exactly that host), and both addresses share its saved session and password.
- A password the site itself refuses counts towards "failed twice" again, so that a wrong stored password is not sent
  over and over; a sign-in page the program could not work still does not count.
