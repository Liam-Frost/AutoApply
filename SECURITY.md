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
- **Someone else reaches the server.** The page asks for a login (one administrator account; only a salted hash of
  the password is kept, and five wrong passwords close it for fifteen minutes), and the server answers only its own
  pages: by default it listens on `127.0.0.1`, refuses requests whose `Host` is not one of its own, and refuses
  cross-site requests. Getting past the login, the lock-out, the local token the tray icon uses or those checks - from
  a web page, another device on the network, a proxy's forwarded headers or a DNS-rebinding trick - is a vulnerability.
- **The remote window is reached by someone else.** A page that needs you is shown in the program's page on a
  computer without a screen, and passwords are typed into it. Reaching it without the login, from another site's page,
  or over plain HTTP from another device; what is typed or shown ending up in a log, on disk or in the AI's context;
  or another account on the server watching the virtual screen - each is a vulnerability.
- **Data goes somewhere it should not.** Your profile, documents or mail sent anywhere other than the AI service you
  chose and the job sites you apply to.
- **The installer or the release process** can be made to run or publish something it should not.

## What does not

- Vulnerabilities in a job site or an applicant-tracking system: report those to their owners.
- The packages not being code-signed. This is known and stated in the README.
- Another user account on the same computer reading your files: the program relies on the operating system's own
  separation between accounts.
- A job site refusing or detecting the program's browser, with either browser backend.

## How the program protects you, briefly

- Passwords and API keys are in the operating system's keyring; saved sign-ins are encrypted on disk. On a server,
  which has no keyring, they are in one encrypted file whose master key you can keep outside the data folder; with
  the key beside the data, whoever can read that folder as you can read them, and the program says so.
- The tools given to the AI cannot submit an application, type a password or read a verification code.
- Text from web pages is treated as data, never as instructions; the rules that matter are enforced in code, not in prompts.
- The page needs a login, on the computer it runs on as well; the server does not do HTTPS itself and says so when it
  is made to listen beyond this computer.
- Mailboxes are opened read-only.
- Nothing is sent to the project or to anyone else: there is no telemetry and no account.
