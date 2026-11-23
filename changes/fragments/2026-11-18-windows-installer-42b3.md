---
id: 2026-11-18-windows-installer-42b3
type: changed
scope: packages
summary:
  en: "A rebuilt Windows installer; the macOS app and the Linux installer work the same way"
  zh: "重做的 Windows 安装程序；macOS 应用和 Linux 安装程序采用同样的方式"
  fr: "Un installateur Windows refait ; l’app macOS et l’installateur Linux fonctionnent de la même façon"
highlight: true
---

- **The Windows installer is rebuilt.** It was a self-extracting archive around a PowerShell script that drew its
  own window, which is why the taskbar showed PowerShell, the file had no icon or version details, and the progress
  line showed unreadable characters. The window looks the same - the program's own design, English or Chinese, light
  or dark - but is now a program of its own with the program's icon, name and version, and the installing behind it is
  done by Inno Setup, so the program is registered and removed the way Windows expects.
  - **An upgrade can be taken back.** The new version is copied beside the installed one and swapped in; if its
    dependencies cannot be installed, or you cancel, the previous version's files return. Before, the old folders
    were deleted first and a failure left a broken installation.
  - **It does not stop the program for you.** While AutoApply is running the installer says so and waits; it used to
    end every Python process whose command line mentioned the folder, whatever it was doing.
  - **uv comes in the package**, one fixed version checked by its SHA-256 when the installer is built. The installer
    no longer downloads a script and runs it.
  - **The browser is asked for on every install and upgrade** (and by the start scripts and the macOS and Linux
    packages): "its folder exists" was taken to mean it was there, so an upgrade that needed a newer build did not
    get one.
  - **Progress you can read, and a Cancel button**: a percentage where the download reports one, a moving bar where
    it does not. The log is kept with your data (`data/logs`, the last twelve), not in the temporary folder.
- **The macOS app and the Linux installer work the same way** as the Windows installer, through the same code
  (`scripts/prepare.py`): an upgrade is laid out beside the installed version and swapped in, and put back when its
  dependencies cannot be installed or you stop it; uv comes in the package (for Intel and ARM alike) instead of being
  downloaded as a script; a running AutoApply is not killed - you are asked to quit it; logs stay with the data.
  The Linux installer no longer needs `unzip` or `curl`, and ends with a result a script can rely on (0 ready, 2
  stopped, 7 running, 1 failed).
- **A browser that was downloaded but cannot start is found at install time**, on every system: it is started once.
  On Linux, where that usually means missing system libraries, the installer says so and names the command that
  installs them, instead of the program failing later on its first application.
- The tray icon and its notifications are AutoApply to Windows, not `pythonw.exe`, and shortcuts are written directly
  instead of through PowerShell.
