#!/bin/bash
# AutoApply installer for Linux. Installs, upgrades or repairs for the current user: no root, nothing outside $HOME.
#
#   program  -> ~/.local/share/autoapply        (its data/ and knowledge/ are never touched by an upgrade)
#   entry    -> the applications menu (and, if you like, the desktop and "start when I sign in")
#
# With a desktop and zenity installed it asks in windows; otherwise in the terminal. Without questions:
#   install.sh --yes [--dir DIR] [--no-menu] [--desktop] [--autostart] [--no-launch] [--lang zh|en]
#   install.sh --uninstall [--delete-data] [--yes] [--dir DIR]
#
# Ends with 0 when the program is ready, 2 when you stopped it, 7 when AutoApply is running (nothing was changed),
# 1 for anything else. The log is kept with the data: <program folder>/data/logs.
#
# The package brings uv with it (one version, checked when the package was built): nothing is downloaded and run
# as a script. An upgrade is laid out beside the installed version and swapped in; if its dependencies cannot be
# installed, or you stop it, the previous version is put back (scripts/prepare.py, shared with the other systems).
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${XDG_DATA_HOME:-$HOME/.local/share}/autoapply"
VER="$(cat "$HERE/version.txt" 2>/dev/null || echo 0)"
LOG="${TMPDIR:-/tmp}/autoapply-setup.log"       # until the program folder is known; then with the data
YES=0; MENU=1; DESKTOP=0; AUTOSTART=0; LAUNCH=1; UNINSTALL=0; DELETE_DATA=0; LANG_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --dir) TARGET="$2"; shift ;;
    --no-menu) MENU=0 ;;
    --desktop) DESKTOP=1 ;;
    --autostart) AUTOSTART=1 ;;
    --no-launch) LAUNCH=0 ;;
    --uninstall) UNINSTALL=1 ;;
    --delete-data) DELETE_DATA=1 ;;
    --lang) LANG_ARG="$2"; shift ;;
    -h|--help) sed -n 2,13p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# Language follows the system: Chinese (Simplified or Traditional) shows Chinese, everything else English.
ZH=0
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in zh*) ZH=1 ;; esac
case "$LANG_ARG" in zh) ZH=1 ;; en) ZH=0 ;; esac
t() { if [ "$ZH" = 1 ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }

GUI=0
if [ "$YES" = 0 ] && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; } && command -v zenity >/dev/null 2>&1; then GUI=1; fi
say() { echo "[AutoApply] $*"; }
note() { echo "$(date +%H:%M:%S)  $*" >> "$LOG" 2>/dev/null; }
confirm() {  # confirm "<text>" -> 0 = yes
  [ "$YES" = 1 ] && return 0
  if [ "$GUI" = 1 ]; then zenity --question --title "AutoApply" --width 460 --text "$1" 2>/dev/null; return $?; fi
  printf '[AutoApply] %s (y/N) ' "$1"; read -r ans; case "$ans" in y|Y) return 0 ;; *) return 1 ;; esac
}
info() { if [ "$GUI" = 1 ]; then zenity --info --title "AutoApply" --width 420 --text "$1" 2>/dev/null; else say "$1"; fi; }
fail() {  # fail "<text>" [exit code]
  note "ERROR: $1"
  if [ "$GUI" = 1 ]; then zenity --error --title "AutoApply" --width 460 --text "$1\n\n$(t '日志：' 'Log: ')$LOG" 2>/dev/null
  else say "$(t '没有完成：' 'Not finished: ')$(printf '%b' "$1") (log: $LOG)" >&2; fi
  exit "${2:-1}"
}
installed_version() { sed -n 's/^version *= *"\(.*\)"/\1/p' "$1/pyproject.toml" 2>/dev/null | head -1; }

# shellcheck source=../common.sh
. "$HERE/common.sh" || { echo "the installer is incomplete (common.sh is missing)" >&2; exit 1; }

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
DESKTOP_DIR="$(command -v xdg-user-dir >/dev/null 2>&1 && xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

desktop_entry() {  # desktop_entry <file>
  cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Name=AutoApply
Comment=$(t '在你自己电脑上运行的求职助手' 'A job-search assistant that runs on your own computer')
Exec="$TARGET/.venv/bin/python" -m autoapply.launcher
Path=$TARGET
Icon=$TARGET/autoapply.png
Terminal=false
Categories=Office;
EOF
  chmod +x "$1"
}

# Nothing is stopped for you: a running AutoApply may be in the middle of an application. Asks until it is quit;
# without questions (--yes) it ends with 7 and changes nothing.
wait_until_quit() {
  while running_from "$TARGET"; do
    if [ "$YES" = 1 ]; then fail "$(running_message)" 7; fi
    if [ "$GUI" = 1 ]; then
      zenity --question --title "AutoApply" --width 480 --ok-label "$(t 重试 Retry)" --cancel-label "$(t 取消 Cancel)" --text "$(running_message)" 2>/dev/null || exit 7
    else
      say "$(running_message)"
      printf '[AutoApply] %s ' "$(t '退出后按回车重试，输入 q 放弃：' 'Press Enter to try again once it is quit, or q to give up:')"; read -r ans
      case "$ans" in q|Q) exit 7 ;; esac
    fi
  done
}

# ---------------------------------------------------------------- uninstall
if [ "$UNINSTALL" = 1 ]; then
  [ -f "$TARGET/pyproject.toml" ] || { say "$(t '没有找到已安装的 AutoApply：' 'No installed AutoApply was found in: ')$TARGET"; exit 1; }
  if [ "$YES" = 0 ]; then
    confirm "$(t '卸载 AutoApply？位置：' 'Uninstall AutoApply? Location: ')$TARGET" || exit 0
    if confirm "$(t '保留你的数据（岗位、草案、个人资料、上传的文件）吗？保留的话以后重新安装还能接着用。选“否”会全部删除，无法恢复。' 'Keep your data (jobs, drafts, profile, uploaded files)? If kept, a later install picks it up again. Choosing No deletes everything and cannot be undone.')"; then DELETE_DATA=0; else DELETE_DATA=1; fi
  fi
  : > "$LOG"; note "uninstall $TARGET delete_data=$DELETE_DATA"
  wait_until_quit
  rm -f "$APPS/autoapply.desktop" "$AUTOSTART_DIR/autoapply.desktop" "$DESKTOP_DIR/AutoApply.desktop"
  if [ "$DELETE_DATA" = 1 ]; then rm -rf "$TARGET"
  else find "$TARGET" -mindepth 1 -maxdepth 1 ! -name data ! -name knowledge -exec rm -rf {} +; fi
  if [ "$DELETE_DATA" = 1 ]; then info "$(t '已卸载，数据也已删除。' 'Uninstalled; the data was deleted too.')"
  else info "$(t '已卸载。你的数据还在：' 'Uninstalled. Your data is still in: ')$TARGET"; fi
  exit 0
fi

# ---------------------------------------------------------------- install / upgrade / repair
[ -f "$HERE/app/pyproject.toml" ] || fail "$(t '安装包不完整（缺少程序文件）。' 'The installer is incomplete (the program files are missing).')"
UV="$(uv_for_this_machine "$HERE")" || fail "$(t '这个安装包不支持这台电脑的处理器：' 'This package has nothing for this computer'"'"'s processor: ')$(uname -m)"
OLD="$(installed_version "$TARGET")"

if [ "$YES" = 0 ]; then
  if [ -n "$OLD" ]; then
    if [ "$OLD" = "$VER" ]; then head="$(t "已经安装了同一个版本（$VER）。要修复它吗？（重新复制程序文件、补齐环境）" "The same version ($VER) is already installed. Repair it? (copy the program files again, complete the environment)")"
    else head="$(t "已安装的版本是 $OLD，要升级到 $VER 吗？" "Version $OLD is installed. Upgrade to $VER?")"; fi
    confirm "$head\n\n$(t '位置：' 'Location: ')$TARGET\n$(t '你的数据（data 和 knowledge 文件夹）不会被改动；新版本没能准备好时，会恢复成现在的版本。要卸载的话，运行：' 'Your data (the data and knowledge folders) is not touched, and if the new version cannot be made ready the one you have now is put back. To uninstall instead, run: ')install.sh --uninstall" || exit 0
  else
    if [ "$GUI" = 1 ]; then
      zenity --question --title "AutoApply $VER" --width 480 --ok-label "$(t 继续 Continue)" --cancel-label "$(t 取消 Cancel)" \
        --text "$(t '安装 AutoApply：在你自己电脑上运行的求职助手。\n\n安装过程会联网下载 Python 和依赖（来自 GitHub 和 pypi.org），以及程序自己用的浏览器（Chromium）。约 600 MB，需要几分钟。只装在你的用户目录里，不需要管理员权限。' 'Install AutoApply: a job-search assistant that runs on your own computer.\n\nSetup downloads Python and the dependencies (from GitHub and pypi.org) and the browser the program uses (Chromium): about 600 MB and a few minutes. Everything goes into your user folder; no administrator rights are needed.')" 2>/dev/null || exit 0
      if ! zenity --question --title "AutoApply" --width 460 --ok-label "$(t 就装在这里 'Install here')" --cancel-label "$(t 选别的位置… 'Choose another…')" --text "$(t '安装位置：' 'Install location: ')$TARGET" 2>/dev/null; then
        picked="$(zenity --file-selection --directory --title "$(t '选一个文件夹，AutoApply 会装到它里面的 autoapply 子文件夹' 'Choose a folder; AutoApply goes into an autoapply subfolder of it')" 2>/dev/null)" || exit 0
        case "$picked" in */autoapply) TARGET="$picked" ;; *) TARGET="$picked/autoapply" ;; esac
      fi
      opts="$(zenity --list --checklist --title "AutoApply" --width 460 --height 260 --text "$(t '快捷方式' 'Shortcuts')" --column "" --column "id" --column "$(t 选项 Option)" --hide-column 2 --print-column 2 \
        TRUE menu "$(t '添加到应用程序菜单' 'Add to the applications menu')" TRUE desktop "$(t '添加桌面快捷方式' 'Add a desktop shortcut')" FALSE autostart "$(t '登录时自动启动' 'Start when I sign in')" 2>/dev/null)" || exit 0
      MENU=0; DESKTOP=0; AUTOSTART=0
      case "$opts" in *menu*) MENU=1 ;; esac
      case "$opts" in *desktop*) DESKTOP=1 ;; esac
      case "$opts" in *autostart*) AUTOSTART=1 ;; esac
    else
      say "$(t "安装 AutoApply $VER 到：" "Installing AutoApply $VER to: ")$TARGET"
      confirm "$(t '安装过程会联网下载 Python 和依赖，以及程序自己用的浏览器，约 600 MB。继续吗？' 'Setup downloads Python and the dependencies and the browser the program uses, about 600 MB. Continue?')" || exit 0
      confirm "$(t '添加桌面快捷方式？' 'Add a desktop shortcut?')" && DESKTOP=1
      confirm "$(t '登录时自动启动？' 'Start when you sign in?')" && AUTOSTART=1
    fi
  fi
fi

wait_until_quit
mkdir -p "$TARGET/data/logs" || fail "$(t '不能创建程序文件夹：' 'The program folder cannot be created: ')$TARGET"
LOG="$TARGET/data/logs/setup-$(date +%Y%m%d-%H%M%S)-installer.log"
note "install $VER -> $TARGET (was: ${OLD:-none})"
RESULT="$(mktemp)"       # the outcome of work(), which runs on the far side of a pipe

# One number for the bar: the steps one after another, the browser's own percentage inside its share.
overall() {  # overall <step> <percent>
  case "$1" in
    0) echo 8 ;;
    1) echo 14 ;;
    2) echo 20 ;;
    *) if [ "$2" -ge 0 ] 2>/dev/null; then echo $((60 + $2 * 35 / 100)); else echo 60; fi ;;
  esac
}
LAST=""
progress() {  # progress <step> <percent> <part>: a line for the window or the terminal when something changed
  line="$(prepare_step "$1")"
  if [ "${2:--1}" -ge 0 ] 2>/dev/null; then line="$line  $2%"; fi
  [ "$line" = "$LAST" ] && return 0
  LAST="$line"
  # the reader is gone when the window's Cancel was pressed: that is the request to stop
  { echo "# $line" && overall "$1" "${2:--1}"; } 2>/dev/null || : > "$PREPARE_CANCEL"
}

work() {
  trap '' PIPE
  step() { note "$2"; echo "# $2"; echo "$1"; }
  step 3 "$(t '复制程序文件' 'Copying the program files')"
  rm -rf "$TARGET/.staged"
  mkdir -p "$TARGET/.staged" && cp -R "$HERE/app/." "$TARGET/.staged/" || { echo files > "$RESULT"; return 1; }
  cp "$HERE/autoapply.png" "$TARGET/.staged/autoapply.png"
  cp "$HERE/install.sh" "$TARGET/.staged/scripts/install-linux.sh"      # kept for a later uninstall, with what it needs
  cp "$HERE/common.sh" "$TARGET/.staged/scripts/common.sh"
  printf '%s' "$VER" > "$TARGET/.staged/scripts/version.txt"
  put_uv "$UV" "$TARGET" || { echo files > "$RESULT"; return 1; }

  if ! run_prepare "$TARGET" progress; then echo "$PREPARE_RESULT" > "$RESULT"; return 1; fi

  step 96 "$(t '创建快捷方式' 'Creating the shortcuts')"
  if [ ! -f "$TARGET/data/app.db" ]; then   # a first install: the program starts in this language
    if [ "$ZH" = 1 ]; then echo zh > "$TARGET/data/ui-lang.txt"; else echo en > "$TARGET/data/ui-lang.txt"; fi
  fi
  if [ "$MENU" = 1 ]; then mkdir -p "$APPS"; desktop_entry "$APPS/autoapply.desktop"; else rm -f "$APPS/autoapply.desktop"; fi
  if [ "$DESKTOP" = 1 ]; then mkdir -p "$DESKTOP_DIR"; desktop_entry "$DESKTOP_DIR/AutoApply.desktop"; fi
  if [ "$AUTOSTART" = 1 ]; then mkdir -p "$AUTOSTART_DIR"; desktop_entry "$AUTOSTART_DIR/autoapply.desktop"; fi
  echo ok > "$RESULT"
  step 100 "$(t '完成' 'Done')"
  return 0
}

if [ "$GUI" = 1 ]; then
  work | zenity --progress --title "AutoApply" --width 480 --auto-close --text "$(t '正在安装…' 'Installing…')" 2>/dev/null
else
  # Ctrl+C asks for an orderly stop: prepare.py takes the signal itself and puts the previous version back
  trap 'say "$(t "正在停止，并恢复原样…" "Stopping, and putting things back...")"' INT
  work | while read -r line; do case "$line" in "# "*) say "${line#\# }" ;; esac; done
  trap - INT
fi
outcome="$(cat "$RESULT" 2>/dev/null)"; rm -f "$RESULT"
case "$outcome" in
  ok) ;;
  cancelled) fail "$(prepare_message cancelled)" 2 ;;
  "") fail "$(prepare_message interrupted)" 1 ;;
  *) fail "$(prepare_message "$outcome" "$TARGET")" 1 ;;
esac

note "done"
done_text="$(t '安装完成。以后从应用程序菜单里的 AutoApply 启动；卸载运行：' 'Installed. Start it from the applications menu; to uninstall run: ')bash \"$TARGET/scripts/install-linux.sh\" --uninstall"
if [ "$LAUNCH" = 1 ] && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
  info "$done_text"
  (cd "$TARGET" && nohup "$TARGET/.venv/bin/python" -m autoapply.launcher >/dev/null 2>&1 &)
else
  say "$done_text"
  [ "$LAUNCH" = 1 ] && say "$(t '没有图形桌面：在终端里运行' 'No desktop session: start it in a terminal with') \"$TARGET/start.sh\""
fi
exit 0
