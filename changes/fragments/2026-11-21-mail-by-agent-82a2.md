---
id: 2026-11-21-mail-by-agent-82a2
type: changed
scope: mail
summary:
  en: "Email: applications by email sent from your mailbox, how often mail is checked a setting, the agent places emails"
  zh: "邮件：通过邮件投递的申请从你的邮箱发出，检查邮件的频率可设置，邮件对应哪份申请由 Agent 判定"
  fr: "Courriels : candidatures par courriel envoyées de votre boîte mail, fréquence de relève réglable, l’agent rattache les courriels"
---

- **How often new mail is looked for is a setting** (*Settings → Automation → Schedule*), next to the pass over the last days that stands behind it. Where the mailbox is asked every few minutes what is new, no separate looks for one application's confirmation are queued; those that are queued are dropped once the application is confirmed.
- **An application that goes by e-mail is sent as one.** The agent reads the posting for the address, the subject and what to attach, writes the mail, and hands it to the program, which sends it from your own mailbox - after you have looked at it (the default: you can change the recipient, the subject and the text first), or by itself if you set so (*Settings → Automation → How the agent works*). The mailbox's own record of the sent mail is the evidence that the application went out. Needs Gmail connected through the API and authorized once more: sending is a permission the program did not have.
- **A mailbox whose authorization ran out says so**: a card to authorize Gmail again, instead of sign-in cards for every employer that was waiting for a mail.
- **Which application an e-mail is about** is settled by the agent reading your list of applications on the employer's site - signing in again if the saved sign-in has run out. It is sent there whether or not a sign-in is saved; what the program has to get in with is said to it.
