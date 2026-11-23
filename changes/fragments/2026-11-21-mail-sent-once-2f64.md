---
id: 2026-11-21-mail-sent-once-2f64
type: fixed
scope: mail
summary:
  en: "An email is sent through a connection that drops, and not twice"
  zh: "连接中断时邮件仍能发出，且不会重复发送"
  fr: "Un courriel part malgré une connexion qui coupe, et pas deux fois"
---

**A mail is sent through a connection that drops, and not twice.** One cut connection left a reply unsent. Reading is asked again; a mail that may or may not have gone out is looked for in the mailbox by its own id before it is sent again. What you are told when it still fails is a sentence, not the error's text.
