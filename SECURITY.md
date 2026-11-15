# Security

AutoApply runs on your own computer, holds your sign-ins to job sites and fills in forms in your name. A flaw in it can
matter, so reports are taken seriously.

## Supported versions

| Version | Supported |
|---|---|
| 1.x (latest release) | yes |
| `legacy-v0` and anything before 1.0 | no |

Fixes are released as a new version; there are no patches for older releases.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub: [**Report a vulnerability**](https://github.com/Liam-Frost/AutoApply/security/advisories/new)
(the *Security* tab of the repository → *Report a vulnerability*). Only the maintainer sees it.

A useful report says:

- which version and operating system;
- what an attacker needs (a web page you visit, a job posting you open in the program, access to your computer, …);
- what they get (read your profile, make the program act, obtain a saved sign-in, …);
- how to reproduce it, as exactly as you can.

What to expect: this is a one-person project, so replies are best effort, usually within a week. You will be told
whether the report is accepted and, when it is, what the fix is and in which release it ships. There is no bug bounty;
you will be credited in the release notes unless you prefer not to be.

## What counts

Anything that breaks one of the program's own promises:

- **It acts without you.** An application submitted, a draft approved, a setting changed or an account created without the
  user's decision, including by text on a web page or in a job posting that the AI reads (prompt injection).
- **Secrets leave their place.** Passwords, API keys, verification codes or saved sign-ins reaching the AI's context,
  the logs, a notification or anything outside the system keyring and the encrypted session files.
- **Someone else reaches the local server.** The server has no login and relies on answering only this computer's own
  pages: it listens on `127.0.0.1`, refuses requests whose `Host` is not this computer's, and refuses cross-site
  requests. A web page, another device on the network or a DNS-rebinding trick getting past that is a vulnerability.
- **Data goes somewhere it should not.** Your profile, documents or mail sent anywhere other than the AI service you
  chose and the job sites you apply to.
- **The installer or the release process** can be made to run or publish something it should not.

## What does not

- Vulnerabilities in a job site or an applicant-tracking system: report those to their owners.
- The packages not being code-signed. This is known and stated in the README.
- Another user account on the same computer reading your files: the program relies on the operating system's own
  separation between accounts.
- A job site refusing or detecting the program's browser. The program does not disguise itself, by design.

## How the program protects you, briefly

- Passwords and API keys are in the operating system's keyring; saved sign-ins are encrypted on disk.
- The tools given to the AI cannot submit an application, type a password or read a verification code.
- Text from web pages is treated as data, never as instructions; the rules that matter are enforced in code, not in prompts.
- Mailboxes are opened read-only.
- Nothing is sent to the project or to anyone else: there is no telemetry and no account.
