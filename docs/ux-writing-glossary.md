# UX writing glossary

How AutoApply talks: one word per thing, and a fixed shape per kind of text. It binds every key in
`frontend/src/locales/` (interface) and `frontend/src/locales/server/` (what the server says: stages, next steps,
reasons, cards, notifications). Chinese is written first; English and French say the same thing naturally, not word for
word. Catalogs are changed only with `python frontend/scripts/i18n-apply.py patch.json`.

The calendar's wording (`calendar.*`) is the reference for everything about dated items; other pages follow it.

## 1. Rules per kind of text

| Kind | Rule | Yes | No |
| --- | --- | --- | --- |
| Page title, sidebar item | The thing's name. Sidebar and page title are identical. | 待处理 / Action required | 需要我处理的事 |
| Section or card title | A noun phrase. | 第三方登录 / Third-party sign-in | 用来登录其他网站的账号 |
| Button, menu item | A verb, or verb + object. No "去…", no "…一下", no sentence. | 登录, 清除会话, 重试 / Sign in, Clear session, Retry | 去登录, 让它再做一次 |
| State, badge | A short phrase, no subject, no full stop. Says only what is true. | 会话已保存, 待邮箱验证 / Session saved | 等待确认邮箱; "已登录" for a session that is merely saved |
| Next step (applications) | An imperative for the owner of the step, or "等待… / Waiting for…". | 完成在线测评, 等待雇主回复 | 有笔试 / 测评，按邮件里的安排完成 |
| Column header, field label, filter label | The attribute's name. | 投递日期 / Applied on; 来源 / Source | 投出; 怎么来的; 按在哪里投筛选 |
| Filter option "everything" | 全部 + the attribute's plural. | 全部负责人 / All owners | 下一步是谁的事：都看 |
| Placeholder | An example or the format, never the label repeated. "（可选）/ (optional)". | 例如 62000 CAD / 年 | 可不填 |
| Toast | What happened, past tense or state, no full stop. | 已保存 / Saved | 好的，保存好了 |
| Confirmation (`ask`) | The question, then the consequence in one sentence. | 撤回这份申请？岗位会标为不投递。 | — |
| Empty state | Title: what is absent ("没有… / No …"). Text: at most one sentence on how it fills. | 没有待处理事项 | — |
| Error, reason, diagnosis | Accurate, natural, actionable: what happened, why if known, what to do. Never shortened at the cost of clarity. | 无法连接这家 AI 服务。请检查网络和“设置 → 系统与数据 → 网络连接”。 | 出错了 |
| Security and privacy statement | Says exactly what the code does, no more. Kept visible where the decision is made. | 只保存会话（cookie，加密保存在本机） | "安全存储" |
| Instruction (how to export Chrome passwords, …) | Kept whole, steps in order, tightened. | 设置 → 密码管理器 → 设置 → 导出密码 | — |
| Page subtitle (`PageHead sub`) | Almost never. Only what the reader must know to decide something on this page. | — | a description of the page |
| Helper text | One sentence inline; more goes behind `InfoTip` (a sentence) or `Popover` (several). | — | a paragraph above a table |

Tone: plain and professional. Second person (你 / you / vous). No exclamation marks, no "please" in buttons, no
"we". The program is 程序 / "the app" (or AutoApply) / « le programme »; the AI that works an application is
Agent / "the agent" / « l’agent ».

### English

- Sentence case everywhere: "Action required", "Applied on", "Clear session". Proper names keep their capitals
  (Gmail, PD Portal, Workday); a page referred to in a sentence is capitalised and unquoted: "see Action required".
- "sign in" (verb), "sign-in" (noun, adjective). Never "log in" for a site; "login" only for AutoApply's own account.
- "email" (no hyphen) for a message, "mailbox" for the connected account. Not "mail(s)" as a count noun.
- Contractions are fine in toasts and helper text ("You’ll be notified"), not in states or headers.
- No "(s)" where the catalog has plural forms (`one | other`).
- "Retry", "Select", "Edit", "Delete", "Remove" (from a list, nothing destroyed), "Clear" (a session, a filter).

### Chinese

- 书面、简洁：用“未/已/待/无法/尚未”，不用“还没/没能/做不了/一下”。按钮不带“去”“了”。
- 状态用“已… / 未… / 待…”三种形态：已保存、未保存、待批准。
- 全角标点；中文与数字、拉丁字母之间留一个空格（{n} 份、AI 额度）。量词：申请用“份”，岗位用“个”，邮件用“封”，
  待办用“项”。
- “可选”，不用“可不填”。“重试”，不用“再试一次 / 再做一次”。“停止”，不用“叫停”。

### French

- Vouvoiement, infinitif pour les boutons (« Se connecter », « Réessayer »), apostrophe typographique (’),
  guillemets « », espace avant `: ; ? !`.
- « courriel » pour le message, « boîte mail » pour le compte connecté ; « annonce » pour 岗位 (jamais « offre », réservé
  à l’offre d’embauche) ; « trimestre » pour 学期 (« session » est réservé à la session de connexion).

### Mechanics

Placeholders `{name}` stay identical in every language. Plural forms: `one | other` in en and fr, one form in zh. A
literal `|` or `@` is written `{'|'}` / `{'@'}`. Sentence fragments joined by the page (`…In ` + link + `.`) keep their
edge spaces and punctuation; new keys should be whole sentences with a placeholder instead.

## 2. Pages (sidebar = page title)

| zh | en | fr | key |
| --- | --- | --- | --- |
| 概览 | Overview | Vue d’ensemble | `app.overview` |
| 待处理 | Action required | À traiter | `app.needsYou`, `todos.needsYou` |
| 日程 | Calendar | Agenda | `calendar.nav` |
| 岗位 | Postings | Annonces | `app.postings`, `postings.title` |
| 申请 | Applications | Candidatures | `app.applications`, `applications.title` |
| 个人资料 | Profile | Profil | `app.profile` |
| 材料库 | Files | Documents | `app.files` |
| 人脉与内推 | Contacts & referrals | Contacts et recommandations | `app.contactsReferrals` |
| 网站账号 | Site accounts | Comptes des sites | `app.siteAccounts` |
| 数据分析 | Analytics | Analyse | `app.analytics` |
| 活动记录 | Activity | Activité | `app.activity` |
| 设置 | Settings | Paramètres | `app.settings` |
| 关于 | About | À propos | `about.nav`, `about.title` |
| 来源与关注雇主 (under 岗位) | Sources and watched employers | Sources et employeurs suivis | `sources.sourcesAndWatchedEmployers` |

An item on the Action required page is a 待办 / to-do / tâche. Tabs of Activity: 工作计划 / Plan, 历史 / History,
定时任务 / Scheduled tasks, 通知与机器人 / Notifications and bots. Tabs of Analytics: 求职成效 / Outcomes, 自动化效率 /
Automation, 网站笔记 / Site notes, AI 成本 / AI cost.

## 3. Terms

### Objects

| Concept | zh | en | fr | Not |
| --- | --- | --- | --- | --- |
| A job found in a source | 岗位 | posting | annonce | 职位, job (except "job title", "job description"), listing, offre |
| Its title | 岗位名称 | job title | intitulé du poste | |
| Its text | 岗位说明 | job description | description du poste | JD, 原文 |
| The organisation | 雇主 (as a party) · 公司 (the name, a column) | employer · company | employeur · entreprise | 对方 |
| The user's application | 申请 | application | candidature | |
| What the agent filled in, for approval | 申请记录 | record | dossier | |
| The same before approval, in settings and analytics | 草案 | draft | brouillon | (legacy; new keys say 申请记录 / record) |
| The form on the site | 申请表 | application form | formulaire de candidature | |
| The AI working an application | Agent | the agent | l’agent | 它, AI 助手 |
| The program | 程序 | the app / AutoApply | le programme | the program, 软件 |
| Files for applying | 材料 | materials / files | documents | |
| Résumé as uploaded · rewritten for a posting | 原版简历 · 定制简历 | original résumé · tailored résumé | CV d’origine · CV adapté | 为这个岗位改写的简历 |
| Cover letter | 求职信 | cover letter | lettre de motivation | |
| Where postings come from | 来源 | source | source | |
| Where one applies (employer site, portal, email) | 投递渠道 | application channel (column: Channel) | canal de candidature | 在哪里投 |
| Recruiting software of a site (Workday, …) | 招聘系统 | recruiting system | système de recrutement | ATS in the interface |
| Posting's field | 方向 | field | domaine | direction |
| School term | 学期 | term | trimestre | session (fr) |
| Score · threshold · scoring rules | 评分 · 分数线 · 评分规则 | score · threshold · scoring rules | note · seuil · règles de notation | 打分 |
| Employer marked by the user | 重点雇主 | priority employer | employeur prioritaire | |
| AI usage limit of a service | 额度 | quota (used up: "usage limit reached") | quota | allowance |
| What one application may spend | 预算 | budget | budget | |
| E-mail message · connected account | 邮件 · 邮箱 | email · mailbox | courriel · boîte mail | 信, mail |
| Employer's automatic confirmation | 确认邮件 | confirmation email | courriel de confirmation | 确认信 |
| Saved cookies of a site | 会话 | session | session | 登录状态, sign-in state |
| Sign-in through Google, LinkedIn, … | 第三方登录 · 提供商 | third-party sign-in · provider | connexion tierce · fournisseur | |
| Proof kept after submitting | 投递凭证 | proof of submission | preuve d’envoi | 证据 |
| History of one application | 时间线 | timeline | historique | 经过, story |
| Who has the next step | 负责人 (你 / Agent / 雇主) | owner (you / agent / employer) | responsable | 下一步是谁的事 |
| Person the user knows · referral | 联系人 · 内推 | contact · referral | contact · recommandation | |

### Actions

| Concept | zh | en | fr |
| --- | --- | --- | --- |
| Apply (the whole act) | 投递 | apply | postuler |
| Press Submit on a form | 提交 | submit | envoyer |
| Begin an application for a posting | 开始申请 | start an application | commencer une candidature |
| Decide against a posting | 不投递 (state 已标为不投递) | not applying | ne pas postuler |
| Take an application back | 撤回申请 (state 已撤回) | withdraw | retirer |
| Approve a record | 批准 (待批准, 已批准) | approve | approuver |
| Read the record before approving | 审阅 | review | relire |
| Run again | 重试 · 让 Agent 重试 | retry · have the agent retry | réessayer |
| Give more budget | 追加预算 | add budget | ajouter du budget |
| Stop a run | 停止 | stop | arrêter |
| Read the mailbox for new messages (read-only; updates applications) | 检查邮件 | check mail | relever les courriels |
| Look for one application's confirmation | 查找确认邮件 | find confirmation email | chercher le courriel de confirmation |
| Read sources for new postings | 扫描新岗位 | scan for new postings | rechercher de nouvelles annonces |
| Rewrite the résumé for a posting | 定制简历 | tailor the résumé | adapter le CV |
| Put a to-do off | 稍后提醒 (group 延期待办) | snooze | reporter |
| Hide from everyday lists, keep the record | 归档 / 取消归档 | archive / unarchive | archiver / désarchiver |
| Sign in to a site | 登录 | sign in | se connecter |
| Remove a saved session | 清除会话 | clear session | effacer la session |
| Carry a session to another computer | 迁移会话 | move a session | transférer une session |
| Record something the app did not see | 记录结果 · 更正记录 | record outcome · correct record | consigner le résultat · corriger le dossier |
| Close a record without applying | 作废记录 | discard record | abandonner le dossier |

"检查邮件", not "同步邮件": the action reads application-related messages of the last days and updates applications
from them; nothing is mirrored or written back (`handlers._mail`, `mail.track`).

### Application groups, stages and next steps

Groups of the Applications page: 待处理 Action required / À traiter · 进行中 In progress / En cours · 已投递 Submitted /
Envoyées · 招聘进展 Hiring progress / Recrutement en cours · 已结束 Ended / Terminées · 已归档 Archived / Archivées.

| Stage | zh | en | fr | Next step (zh / en) |
| --- | --- | --- | --- | --- |
| queued | 排队中 | Queued | En file d’attente | — |
| preparing, working | 准备中 · Agent 处理中 | Preparing · Agent working | En préparation · Agent au travail | Agent 正在处理 / The agent is working on it |
| needs_input | 待回答 | Awaiting your answer | En attente de votre réponse | 回答问题 / Answer the questions |
| draft_ready | 待批准 | Awaiting your approval | En attente de votre approbation | 审阅并批准申请记录 / Review and approve the record |
| needs_human | 待处理 | Action required | À traiter | 在“待处理”中处理后继续 |
| approved | 已批准，待提交 | Approved, awaiting submission | Approuvée, à envoyer | 等待 Agent 提交 |
| ready_to_submit | 已填好，待你提交 | Filled in, awaiting your submission | Remplie, en attente de votre envoi | 表单已填好，尚未提交 |
| submitting | 提交中 | Submitting | Envoi en cours | — |
| unknown | 提交结果待确认 | Submission unconfirmed | Envoi non confirmé | 等待确认邮件，或告知程序结果 |
| submitted / sent | 已提交 · 已投递 | Submitted | Envoyée | 等待雇主的确认邮件 |
| confirmed | 已确认收到 | Receipt confirmed | Réception confirmée | 等待雇主回复 / Waiting for the employer’s reply |
| assessment | 在线测评 | Assessment | Évaluation en ligne | 完成在线测评 / Complete the assessment |
| interview | 面试 | Interview | Entretien | 准备面试 / Prepare for the interview |
| offer | Offer (收到 Offer) | Offer (Offer received) | Offre (Offre reçue) | 回复 Offer / Respond to the offer |
| rejected | 被拒 | Rejected | Refusée | 申请未通过 |
| withdrawn | 已撤回 | Withdrawn | Retirée | 你已决定不投递 |
| failed · drifted · budgetUsed | 失败 · 表单已变化 · 预算已用完 | Failed · Form changed · Budget used up | Échec · Formulaire modifié · Budget épuisé | 让 Agent 重试 / 追加预算 |

Posting states: 未投递 Not applied · 不投递 Not applying · 已下线 Taken down (never 下架) · 已截止 Deadline passed ·
已关闭 Closed (taken down or past its deadline) · 待决定 To decide · 已开始 Started.

The three measures of Overview and Analytics: 已投递 Submitted · 收到回执 Acknowledged (anything came back, automatic
confirmation included) · 有实质结果 Substantive response (assessment, interview, offer or rejection).

### Calendar kinds (reference: `calendar.kind.*`)

申请截止 Application deadline / Date limite de candidature · 面试 Interview / Entretien · 在线测评 Assessment /
Évaluation en ligne (never 笔试 / OA / VA / written test) · Offer 回复 Offer response / Réponse à une offre · 补充材料
Additional information / Informations complémentaires · 联系跟进 Follow-up / Relance · 个人日程 Personal event /
Événement personnel · 延期待办 Snoozed tasks / Tâches reportées.

### Site accounts

| Concept | zh | en | fr |
| --- | --- | --- | --- |
| Columns | 网站 · 登录名或邮箱 · 密码 · 状态 · 会话 · 来源 | Site · Username or email · Password · Status · Session · Source | Site · Identifiant ou courriel · Mot de passe · Statut · Session · Source |
| Password / session kept or not | 已保存 · 未保存 | Saved · Not saved | Enregistré · Non enregistré |
| A provider's session is stored | 会话已保存 · 未保存会话 | Session saved · No session saved | Session enregistrée · Aucune session |
| Status `ok` | 支持自动登录 | Auto sign-in ready | Connexion automatique prête |
| Status `needs_human` | 需人工登录 | Manual sign-in required | Connexion manuelle requise |
| Status `pending` | 待邮箱验证 | Email verification pending | Vérification du courriel en attente |
| Status `locked` · `unknown` · `not_needed` | 已锁定 · 从未登录 · 无需登录 | Locked · Never signed in · No sign-in needed | Verrouillé · Jamais connecté · Connexion non requise |
| Source `agent` | 自动注册 | Auto-registered | Inscription automatique |
| Source `takeover` | 手动登录 | Manual sign-in | Connexion manuelle |
| Source `manual` · `chrome_csv` | 手动添加 · Chrome 导入 | Manual entry · Chrome import | Ajout manuel · Import Chrome |
| Browser choice follows the site rule | 站点默认 | Site default | Par défaut du site |
| Buttons | 登录 · 重新登录 · 清除会话 · 添加自定义提供商 | Sign in · Sign in again · Clear session · Add custom provider | Se connecter · Se reconnecter · Effacer la session · Ajouter un fournisseur personnalisé |

"已登录 / Signed in" is said only where a sign-in was just verified (AutoApply's own login, the ChatGPT or Claude
subscription). A stored cookie jar is "会话已保存": it may have expired on the site.

### Common words

| zh | en | fr |
| --- | --- | --- |
| 保存 · 取消 · 删除 · 编辑 · 添加 · 移除 | Save · Cancel · Delete · Edit · Add · Remove | Enregistrer · Annuler · Supprimer · Modifier · Ajouter · Retirer |
| 重试 · 处理 · 打开 · 查看 | Retry · Handle · Open · View | Réessayer · Traiter · Ouvrir · Voir |
| 正在加载… · 加载失败 · 暂无数据 | Loading… · Could not load … · No data | Chargement… · Impossible de charger … · Aucune donnée |
| 全选 · 已选 {n} · 取消选择 | Select all · {n} selected · Clear selection | Tout sélectionner · {n} sélectionnées · Effacer la sélection |
| 更新时间 · 投递日期 · 最新进展 · 下一步 | Last updated · Applied on · Latest update · Next step | Dernière mise à jour · Date de candidature · Dernière nouvelle · Prochaine étape |
| 可选 · 立即生效 · 有未保存的改动 | optional · Takes effect immediately · Unsaved changes | facultatif · Prend effet immédiatement · Modifications non enregistrées |
| 自动运行（已暂停 / 恢复） | auto-run (paused / resume) | exécution automatique |

## 4. What not to do

- No sentence as a button, state, filter or header ("我自己已经投了", "下一步是谁的事：都看", "怎么来的").
- No second name for a thing that has one (投出 / 投了 / 发出去 for 投递; 登录状态 for 会话; 对方 for 雇主; 确认信 for
  确认邮件; posting / job / listing mixed; mail / e-mail / email mixed).
- No claim the code does not keep: a saved session is not "signed in"; "encrypted", "never sent to the AI", "only on
  this computer" are written only where the code guarantees them - read it when unsure.
- No shortening of an error, a warning before something irreversible, or an instruction until it stops being clear.
- No explanation of the page under its title. What a column or a number means goes in an `InfoTip` on that header.
- No "we", no jokes, no exclamation marks, no emoji in catalog values (the bots' icons are added by code).
- No text assembled from fragments in new keys; no Chinese punctuation hard-coded in a template.
- No new wording for calendar items: reuse `calendar.kind.*` terms.

## 5. Known gaps (for the page owners)

- `calendar.*` was left untouched and still says 不投 / 未投 / 已投 / 有进展 ("Sent", "Moving forward") in its filter
  of application states, and "待办页 / to-do page" in `calendar.alarm.hint`; the rest of the program now says 不投递 /
  未投递 / 已投递 / 招聘进展 and 待处理 / Action required.
- 草案 / draft survives in settings, welcome, analytics and several server messages for what the applications pages
  call 申请记录 / record. New keys use 申请记录.
- `accounts.addManually` is one key for a section title and a source value ("手动添加 / Manual entry"); split it when
  the page is rebuilt (`…source.manual`: 手动添加 / Added manually).
- `accounts.manyJobSitesLet` + `accounts.passwordsForTheseAccounts`, `accounts.onceThisIsOpen` + link +
  `accounts.thereIsUsuallyNothing`, `home.usesTheSameThree` …, `runs.theLimitIsChanged` … are fragments joined in
  templates (one with a hard-coded "。"): replace with whole sentences when those pages are rebuilt.
- Long hints of Settings, Welcome and the cost panel were given the term changes only, not rewritten one by one.
- French follows the term table in the keys touched by this pass; values that only needed tightening in zh / en were
  left as they were in fr.

## Appendix A - page subtitles (`PageHead :sub`)

Decisions for the page owners. "delete" = remove the `sub` usage (the key can then be removed); "help" = pass the key
as `help` (an `InfoTip` beside the title); "keep" = stays as `sub`. Texts are already shortened in the catalogs.

| Key | Page | Decision | Text now (zh) |
| --- | --- | --- | --- |
| `home.whatYouNeedTo` | Overview | delete | — |
| `todos.thingsTheAppCant` | Action required | help | 程序无法自行完成、需要你处理的事项。处理后，相关任务会自动继续。 |
| `postings.sub` | Postings | delete | — |
| `applications.sub` | Applications | delete | — |
| `applications.reviewSub` | bulk approval dialog | keep (it states the rule: open questions are not approved) | 每份申请中你还没看过的内容：Agent 不确定的答案、与上一版的差异。仍有问题未回答的申请不会被批准。 |
| `profile.everythingUsedToFill` | Profile | help | 填写申请表、撰写求职信的全部依据。这里没有的内容，程序不会编造。 |
| `files.page.allTheFilesUsed` | Files | delete (or help) | 申请用到的全部文件：你上传的简历、成绩单等材料，以及程序为各岗位生成的求职信。 |
| `contacts.peopleYouKnowAt` | Contacts & referrals | help | 你在目标公司认识的人：谁能内推、和谁聊过、何时跟进。这里只是你的记录，程序不会替你联系任何人。 |
| `accounts.oneEntryPerJob` | Site accounts | help - a security statement, must stay reachable | 密码保存在本机的系统凭据管理器，会话加密保存在本机；两者都不进数据库和日志，也不会发给 AI。 |
| `runs.whatTheProgramIs` | Activity | delete | — |
| `sources.thePostingsAreRead` | Sources | delete | — |
| `about.sub` | About | delete | — |
| `remote.thisIsABrowser` | Remote window | keep (tells what the picture is) | 这是运行 AutoApply 的那台电脑上的浏览器页面。在画面上点击和输入，就像在那台电脑上操作一样。 |
| `analytics.page.whatCameOfThe`, `…howOftenEachKind`, `…whatTheAgentWrote`, `…howManyTokensThe` | Analytics tabs | help on the tab's head - each says by which date it counts | shortened |
| `analytics.auto.theSameDataAs`, `analytics.cost.theSameDataAs`, `analytics.auto.inAllNewestFirst`, `analytics.cost.inAllMostExpensive`, `analytics.cost.inAllLargestFirst`, `analytics.auto.failuresInThisPeriod` | Analytics detail lists | keep (count and order of the list) | unchanged |
| `calendar.sub` | Calendar | not touched (settled) | — |

## Appendix B - always-visible helper paragraphs

Every key of 28 Chinese characters or more that a page shows as running text (`class="muted"`, `class="hint"`,
`card-sub`, `:hint`, `:text`, `:help`), by file, with what the page owner should do with it. Where no decision was
taken by hand the rule is by length: under 45 characters it stays inline as one sentence; up to 110 it moves behind
an `InfoTip` beside the label it explains; longer goes in a popover. Security and privacy statements and real
instructions stay reachable in every case. Lengths are of the Chinese text after this pass.

### `components/AccessPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `settings.access.byDefaultOnlyThis` | 50 | help (InfoTip beside the label) |
| `settings.access.onlyWhenAReverse` | 30 | keep inline (one sentence) |
| `settings.access.autoapplyDoesNotDo` | 91 | help (InfoTip beside the label) |
| `settings.access.whenOnTheLogin` | 33 | keep inline (one sentence) |
| `settings.access.theOnlyAccountOnly` | 46 | help (InfoTip beside the label) |

### `components/AgentJournal.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `journal.spent` | 45 | help (InfoTip beside the label) |
| `journal.howItHears` | 61 | help beside the message box |

### `components/AiPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `settings.ai.usesYourOwnClaude` | 74 | help (InfoTip beside the label) |
| `settings.ai.theAgentThatWorks` | 58 | help (InfoTip beside the label) |
| `settings.ai.usesAnAnthropicApi` | 28 | keep inline (one sentence) |
| `settings.ai.afterChangingTheModel2` | 31 | keep inline (one sentence) |
| `settings.ai.usesYourChatgptSubscription` | 125 | popover (Explain / Popover) |
| `settings.ai.theAgentThatWorks2` | 50 | help (InfoTip beside the label) |
| `settings.ai.forTheMainModel2` | 69 | help (InfoTip beside the label) |
| `settings.ai.whenAServiceRuns` | 105 | help (InfoTip beside the label) |
| `settings.ai.thisProviderIsntSet` | 51 | help (InfoTip beside the label) |
| `settings.ai.checkedEveryMinutesUsage` | 69 | help (InfoTip beside the label) |
| `settings.ai.noBackupServicesYet` | 37 | keep inline (one sentence) |

### `components/BrowserPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `settings.browser.playwrightIsUsedBy` | 57 | help (InfoTip beside the label) |
| `settings.browser.installWithUvSync` | 29 | keep inline (one sentence) |
| `settings.browser.anAccountRuleSays` | 86 | help (InfoTip beside the label) |

### `components/DoctorPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `common.doctor.sub` | 36 | help beside the title |

### `components/EmployersPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `settings.employers.companiesYouWantTo` | 87 | help (InfoTip beside the label) |
| `settings.employers.eachScanUsesThe` | 35 | keep inline (one sentence) |
| `settings.employers.thisIsAJob` | 39 | keep inline (one sentence) |
| `settings.employers.addingRemovingAndThe` | 36 | keep inline (one sentence) |

### `components/MailboxPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `settings.mailbox.readingCodesAndActivation` | 161 | popover (Explain / Popover) |
| `settings.mailbox.authorizingAsksForReading` | 193 | popover (Explain / Popover) |
| `settings.mailbox.authorizationCodesAndTokens` | 68 | help (InfoTip beside the label) |

### `components/NetworkPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `settings.network.theAppGoesOnline` | 75 | help (InfoTip beside the label) |
| `settings.network.withoutAProtocolHttp` | 54 | help (InfoTip beside the label) |
| `settings.network.onlyAppliesWhenUsing` | 33 | keep inline (one sentence) |
| `settings.network.sitesSlowerThanSeconds` | 39 | keep inline (one sentence) |

### `components/PromptsPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `settings.prompts.theInstructionsTheProgram` | 134 | popover (Explain / Popover) |

### `components/RecordPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `record.questionsForYouHow` | 69 | keep (tells what to do next) |
| `record.workAgainWhen` | 28 | keep inline (one sentence) |
| `record.multiHint` | 30 | keep inline (one sentence) |
| `record.tailorNeedsWord` | 45 | help (InfoTip beside the label) |

### `views/AboutView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `about.howUnmanaged` | 32 | keep inline (one sentence) |
| `about.howSwitch` | 68 | help beside "Switch" |
| `about.privacy` | 107 | keep (privacy statement) |

### `views/AccountsView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `accounts.manyJobSitesLet` | 105 | help beside "Third-party sign-in"; keep the last clause (only the session is saved, passwords are not) visible |
| `accounts.afterAddingItClick` | 102 | popover on "Add custom provider" |
| `accounts.theFirstTimeA` | 35 | keep (empty state) |
| `accounts.whichBrowserAnAccount` | 29 | delete (the section's items name themselves) |
| `accounts.onceThisIsOpen` | 43 | help beside the browser select; rewrite as one sentence with the link |
| `accounts.thereIsUsuallyNothing` | 31 | keep inline (one sentence) |
| `accounts.inChromeGoTo` | 76 | keep (instruction) |
| `accounts.someSignInsCannot` | 130 | keep (security warning) - inside the transfer section or its popover |
| `accounts.aWorkdayIdIs` | 129 | popover beside the Site ID field |
| `accounts.theUniversitysCoOp` | 94 | popover beside the Site ID field |

### `views/analytics/AppsPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `analytics.apps.applicationsHaveBeenSent` | 46 | help (InfoTip beside the label) |
| `analytics.apps.anotherAreKnownTo` | 47 | help (InfoTip beside the label) |
| `analytics.apps.eachStepIsA` | 43 | keep inline (one sentence) |
| `analytics.apps.theFirstTwoColumns` | 47 | help (InfoTip beside the label) |
| `analytics.apps.theShareOfApplications2` | 35 | keep inline (one sentence) |
| `analytics.apps.groupsWithFewerThan` | 29 | keep inline (one sentence) |
| `analytics.backlog.sub` | 35 | keep inline (one sentence) |
| `analytics.apps.scoredOrHigherAnd` | 47 | help (InfoTip beside the label) |

### `views/analytics/AutoPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `analytics.auto.durationIsTheMedian` | 47 | help (InfoTip beside the label) |
| `analytics.auto.doneNotFinishedFailed` | 28 | keep inline (one sentence) |
| `analytics.auto.theAgentWorkedApplications` | 61 | help (InfoTip beside the label) |

### `views/analytics/CostPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `analytics.cost.costIsDividedIn` | 31 | keep inline (one sentence) |
| `analytics.cost.aSubscriptionIsA` | 30 | keep inline (one sentence) |
| `analytics.cost.oneCallCanContain` | 41 | keep inline (one sentence) |
| `analytics.cost.everythingAKindOf` | 55 | help (InfoTip beside the label) |
| `analytics.cost.whatFailedRequestsRetries` | 35 | keep inline (one sentence) |
| `analytics.cost.highWellAboveMost` | 63 | help (InfoTip beside the label) |
| `analytics.cost.comparedWithOtherRequests` | 40 | keep inline (one sentence) |
| `analytics.cost.ofTheRequestsIn` | 29 | keep inline (one sentence) |
| `analytics.cost.fromThisVersionOn` | 36 | keep inline (one sentence) |
| `analytics.cost.usDollarsPerMillion` | 143 | popover (Explain / Popover) |
| `analytics.cost.addAModelAnd` | 29 | keep inline (one sentence) |

### `views/analytics/SitesPanel.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `analytics.sites.withEveryApplicationThe` | 107 | help (InfoTip beside the label) |
| `analytics.sites.onceTheAgentHas` | 30 | keep inline (one sentence) |

### `views/ApplicationDetail.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `application.outcomeHow` | 42 | help beside the dialog title |
| `application.fixHow` | 56 | help beside the dialog title |
| `application.noRecord` | 35 | keep inline (one sentence) |
| `application.noMail` | 37 | keep inline (one sentence) |

### `views/ContactsView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `contacts.forExperiencedJobSeekers` | 48 | keep (empty state), one sentence |

### `views/FilesView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `files.page.theDraftThatExists` | 37 | keep inline (one sentence) |
| `files.page.earlierVersionsOfThe` | 60 | popover on the "Overwritten" badge |

### `views/HomeView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `home.newDraftsAndSign` | 32 | keep (empty state) |
| `home.notAppliedSkippedTaken` | 34 | keep inline (one sentence) |
| `home.onceAMailboxIs` | 32 | keep (empty state) |

### `views/JobsView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `postings.addHint` | 31 | keep (one sentence in the dialog) |
| `postings.editHow` | 30 | help beside the dialog title |
| `postings.jdSummary` | 61 | keep (warning: the text is not the whole posting) |
| `postings.jdNone` | 53 | keep (explains why nothing can be scored) |

### `views/LoginView.vue`

All 4 keys: keep (first-run and security text). `login.theFirstSetUp`, `login.ifThatComputerIs`, `login.autoapplyHoldsYourProfile`, `login.atLeastCharactersIf`.

### `views/ProfileView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `profile.usedWhenAnApplication` | 40 | keep inline (one sentence) |
| `profile.onlyFilledInWhen` | 66 | help (InfoTip beside the label) |
| `profile.savingWritesThisTo` | 81 | help (InfoTip beside the label) |
| `profile.onlyWhatYouUploaded` | 33 | keep inline (one sentence) |
| `profile.theProgramOnlyCopies` | 70 | keep (says what the generator will not do) |
| `profile.writtenInMarkdownEditing` | 42 | keep inline (one sentence) |
| `profile.applicationFormsOftenHave` | 138 | popover beside "Experience stories"; keep the first-use instruction |
| `profile.writeInChineseOr` | 70 | help (InfoTip beside the label) |
| `profile.writeInPlainLanguage` | 56 | help (InfoTip beside the label) |
| `profile.everySaveKeepsA` | 35 | keep inline (one sentence) |

### `views/RunsView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `runs.anIntervalCountsFrom` | 67 | popover beside "Scheduled tasks" |
| `runs.besidesEveryMinutesPostings` | 96 | popover beside "Scheduled tasks" |
| `runs.connectTelegramOrDiscord` | 51 | keep (empty state) |

### `views/SettingsView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `settings.page.fromTopToBottom` | 57 | help (InfoTip beside the label) |
| `settings.page.forEachApplicationIts` | 43 | keep inline (one sentence) |
| `settings.page.notSetUpYet` | 49 | help (InfoTip beside the label) |
| `settings.page.yourProfileDecidesWhat` | 47 | help (InfoTip beside the label) |
| `settings.page.thisIsAFilter` | 131 | popover (Explain / Popover) |
| `settings.page.separateWithCommasMatches` | 74 | help (InfoTip beside the label) |
| `settings.page.someSourcesAUniversitys` | 121 | popover (Explain / Popover) |
| `settings.page.oneTitlePerLine` | 48 | help (InfoTip beside the label) |
| `settings.page.careerSitesLikeAmazons` | 53 | help (InfoTip beside the label) |
| `settings.page.whichEmployersAreWatched` | 34 | keep inline (one sentence) |
| `settings.page.whenNewPostingsAre` | 37 | keep inline (one sentence) |
| `settings.page.whenThisManyApplications` | 79 | help (InfoTip beside the label) |
| `settings.page.theAgentWorksEach` | 45 | help (InfoTip beside the label) |
| `settings.page.whateverIsChosenAbove` | 41 | keep inline (one sentence) |
| `settings.page.whenYourProfileAnswers` | 68 | help (InfoTip beside the label) |
| `settings.page.theAgentStopsBefore` | 46 | help (InfoTip beside the label) |
| `settings.page.theAgentIsTold` | 51 | help (InfoTip beside the label) |
| `settings.page.howFormsAreFilled` | 84 | help (InfoTip beside the label) |
| `settings.page.fromThePostingTo` | 83 | help (InfoTip beside the label) |
| `settings.page.eachApplicationHasIts` | 50 | help (InfoTip beside the label) |
| `settings.page.whenARecordIs` | 118 | popover (Explain / Popover) |
| `settings.page.applicationsThatAreSent` | 65 | help (InfoTip beside the label) |
| `settings.page.whenOnTheBrowser` | 82 | help (InfoTip beside the label) |
| `settings.page.switchesItOffIt` | 78 | help (InfoTip beside the label) |
| `settings.page.switchesItOffThe` | 75 | help (InfoTip beside the label) |
| `settings.page.isAtTheBottom` | 86 | help (InfoTip beside the label) |
| `settings.page.theRestWaitsFor` | 49 | help (InfoTip beside the label) |
| `settings.page.forEachPostingThe` | 59 | help (InfoTip beside the label) |
| `settings.page.postingsBelowThisScore` | 29 | keep inline (one sentence) |
| `settings.page.keepsYourRSum` | 61 | help (InfoTip beside the label) |
| `settings.page.whenTickedAnApplication` | 28 | keep inline (one sentence) |
| `settings.page.lettersAreWrittenFrom` | 33 | keep inline (one sentence) |
| `settings.page.whenASiteNeeds` | 105 | help (InfoTip beside the label) |
| `settings.page.toHaveASite` | 89 | help (InfoTip beside the label) |
| `settings.page.afterTheServiceOr` | 115 | popover (Explain / Popover) |
| `settings.page.progressThingsThatNeed` | 49 | help (InfoTip beside the label) |
| `settings.page.theAddressALink` | 42 | keep inline (one sentence) |
| `settings.page.likeTelegramNotificationsArrive` | 81 | help (InfoTip beside the label) |
| `settings.page.thisTokenCannotReach` | 37 | keep inline (one sentence) |
| `settings.page.aBotCanOnly` | 48 | help (InfoTip beside the label) |
| `settings.page.validForMinutesOnce` | 38 | keep inline (one sentence) |
| `settings.page.theButtonsDoWhat` | 138 | popover (Explain / Popover) |
| `settings.page.commandsStatusWhatIs` | 79 | help (InfoTip beside the label) |
| `settings.page.askItHowThings` | 79 | help (InfoTip beside the label) |
| `settings.summary.hint` | 42 | keep inline (one sentence) |
| `settings.page.nothingFromTheseHours` | 117 | popover (Explain / Popover) |
| `settings.page.invitationsToInterviewsAnd` | 36 | keep inline (one sentence) |
| `settings.reminders.intro` | 64 | help (InfoTip beside the label) |
| `settings.reminders.hint` | 28 | keep inline (one sentence) |
| `settings.page.howTheProgramReaches` | 52 | help (InfoTip beside the label) |
| `settings.page.byDefaultThePrograms` | 74 | help (InfoTip beside the label) |
| `settings.page.theseThreeOnlyDecide` | 59 | help (InfoTip beside the label) |
| `settings.page.postingsWithTheSame` | 42 | keep inline (one sentence) |
| `settings.page.toUpdateTheProgram` | 42 | keep inline (one sentence) |

### `views/SourcesView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `sources.theProgramReadsThe` | 80 | help beside the PD Portal card title |
| `sources.latestScanPostingsWere` | 50 | help (InfoTip beside the label) |
| `sources.belowRuledOutNot` | 29 | keep inline (one sentence) |

### `views/TodosView.vue`

| Key | zh length | Decision |
| --- | --- | --- |
| `todos.inThisSignIn` | 54 | help (InfoTip beside the label) |
| `todos.theBrowserWindowIs` | 36 | keep inline (one sentence) |
| `todos.onceYouHaveDone` | 38 | keep inline (one sentence) |
| `todos.sentUsedOld` | 33 | keep inline (one sentence) |
| `todos.requestsToSignIn` | 36 | keep (empty state) |

### `views/WelcomeView.vue`

All 12 keys: keep (onboarding copy; one idea per step). `welcome.aiIsNeededTo`, `welcome.theseDecideWhatPostings`, `welcome.theProgramReadsYour`, `welcome.thisStepNeedsAn`, `welcome.suggestionsByAi`, `welcome.suggestionsGeneric`, `welcome.pickAFewTo`, `welcome.theseCompaniesHavePostings`, `welcome.aSchoolPortalUses`, `welcome.pasteTheUrlOf`, `welcome.yourSettingsAreNow`, `welcome.youCanAlsoSet`.
