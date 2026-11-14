# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- The local server now refuses requests that do not come from its own pages. It has no login and relies on being reachable
  only from this computer; before this change a web page open in the user's browser could send it requests (approve a
  pending draft, change a setting), and a domain name pointed at `127.0.0.1` could read from it. Requests with a foreign
  `Host` header, and API requests from another site, are answered with 403.

### Repository

- Security policy, code of conduct, issue and pull-request templates, weekly dependency updates.
- The shell scripts are executable after a clone (`./start.sh` works without `chmod`).
- CI uses current versions of the GitHub actions and rehearses the publish step on every run.

## [1.0.0] - 2026-11-14

The first release of the rewrite. The previous code base is kept on the `legacy-v0` branch; nothing of it is carried over.
Why it was rewritten, and what is done differently, is in the README under *What the previous version got wrong, and what changed*.

### The application chain

- Postings from the careers pages you choose: Greenhouse, Lever, Ashby, SmartRecruiters and Workday boards, eight large tech companies, job boards that publish a feed, or any careers page read by the AI. 46 employers and 16 job boards are checked and ready to pick from.
- Scoring against rules written in plain language; hard exclusions are applied before any AI is used.
- Drafts: the real form is read, every question is answered from your profile only, each answer shows its source and confidence, and unanswered questions are left for you.
- Review in the page, with changes asked for in plain words.
- Execution: a driver fills the form; the program reads what the form itself reports (invalid fields, error messages, required fields still empty); an AI finishes what is left, from your profile only; what remains is listed for you in a visible window. Nothing is called filled in while the form says otherwise.
- Tracking through your mailbox, read-only (Gmail, Outlook, any IMAP mailbox).
- Notifications on Telegram, in the interface language.

### You and your data

- A first-run guide sets the program up for your career stage, field and target roles; not only for software roles.
- The profile is a Markdown document you and the AI both edit; salary, notice period and referees have a form of their own.
- Region packs describe how forms ask in Canada, the United States, the United Kingdom, the European Union, Australia and Singapore.
- Everything stays on your computer. Export and restore in one file.

### AI services

- Claude subscription, ChatGPT subscription, the Claude and OpenAI APIs, Gemini, DeepSeek, Qwen, OpenRouter and any OpenAI-compatible endpoint.
- Backups: when the service in use runs out or cannot be reached, the same step is repeated on the next one, for the main and the small model alike.
- Allowance: shown where a service reports it (Claude and ChatGPT subscriptions, DeepSeek, OpenRouter), with a warning before it runs out.

### Packages

- Windows: an installer with a window of its own (choose the location and the shortcuts; upgrade, repair and uninstall with the same program; Chinese and English).
- macOS: a disk image with the app.
- Linux: a self-extracting installer.
- A portable zip for all three.
- A tray / menu-bar launcher: status, what needs you, pause, start at sign-in.
- Every package is built by the release workflow and installed and started on its own system before it is published.

### Known limits

- The packages are not code-signed.
- Workday and the UBC portal driver have not been run for real past the sign-in step.
- The macOS and Linux packages are exercised by CI only.
- The English interface is machine-translated.

[Unreleased]: https://github.com/Liam-Frost/AutoApply/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Liam-Frost/AutoApply/releases/tag/v1.0.0
