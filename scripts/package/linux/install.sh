#!/bin/bash
# AutoApply installer for Linux. Installs, upgrades or repairs for the current user: no root, nothing outside $HOME.
#
#   program  -> ~/.local/share/autoapply        (its data/ and knowledge/ are never touched by an upgrade)
#   entry    -> the applications menu (and, if you like, the desktop and "start when I sign in")
#
# With a desktop and zenity installed it asks in windows; otherwise in the terminal. Without questions:
#   install.sh --yes [--dir DIR] [--no-menu] [--desktop] [--autostart] [--no-launch] [--lang zh|en]
#   install.sh --uninstall [--delete-data] [--yes] [--dir DIR]
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${XDG_DATA_HOME:-$HOME/.local/share}/autoapply"
VER="$(cat "$HERE/version.txt" 2>/dev/null || echo 0)"
LOG="${TMPDIR:-/tmp}/autoapply-setup.log"
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
    -h|--help) sed -n 2,11p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
note() { echo "$(date +%H:%M:%S)  $*" >> "$LOG"; }
confirm() {  # confirm "<text>" -> 0 = yes
  [ "$YES" = 1 ] && return 0
  if [ "$GUI" = 1 ]; then zenity --question --title "AutoApply" --width 460 --text "$1" 2>/dev/null; return $?; fi
  printf '[AutoApply] %s (y/N) ' "$1"; read -r ans; case "$ans" in y|Y) return 0 ;; *) return 1 ;; esac
}
info() { if [ "$GUI" = 1 ]; then zenity --info --title "AutoApply" --width 420 --text "$1" 2>/dev/null; else say "$1"; fi; }
fail() {
  note "ERROR: $1"
  if [ "$GUI" = 1 ]; then zenity --error --title "AutoApply" --width 460 --text "$1\n\n$(t '已经完成的部分不会丢，再运行一次会从停下的地方继续。日志：' 'What was done is kept; running it again continues from where it stopped. Log: ')$LOG" 2>/dev/null
  else say "$(t '失败：' 'FAILED: ')$1 (log: $LOG)" >&2; fi
  exit 1
}
installed_version() { sed -n 's/^version *= *"\(.*\)"/\1/p' "$1/pyproject.toml" 2>/dev/null | head -1; }

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

stop_running() {
  pkill -f "$TARGET/.venv/bin/python" 2>/dev/null || true
  sleep 1
}

# ---------------------------------------------------------------- uninstall
if [ "$UNINSTALL" = 1 ]; then
  [ -f "$TARGET/pyproject.toml" ] || { say "$(t '没有找到已安装的 AutoApply：' 'No installed AutoApply was found in: ')$TARGET"; exit 1; }
  if [ "$YES" = 0 ]; then
    confirm "$(t '卸载 AutoApply？位置：' 'Uninstall AutoApply? Location: ')$TARGET" || exit 0
    if confirm "$(t '保留你的数据（岗位、草案、个人资料、上传的文件）吗？保留的话以后重新安装还能接着用。选“否”会全部删除，无法恢复。' 'Keep your data (jobs, drafts, profile, uploaded files)? If kept, a later install picks it up again. "No" deletes everything; it cannot be brought back.')"; then DELETE_DATA=0; else DELETE_DATA=1; fi
  fi
  : > "$LOG"; note "uninstall $TARGET delete_data=$DELETE_DATA"
  stop_running
  rm -f "$APPS/autoapply.desktop" "$AUTOSTART_DIR/autoapply.desktop" "$DESKTOP_DIR/AutoApply.desktop"
  if [ "$DELETE_DATA" = 1 ]; then rm -rf "$TARGET"
  else find "$TARGET" -mindepth 1 -maxdepth 1 ! -name data ! -name knowledge -exec rm -rf {} +; fi
  if [ "$DELETE_DATA" = 1 ]; then info "$(t '已卸载，数据也已删除。' 'Uninstalled; the data was deleted too.')"
  else info "$(t '已卸载。你的数据还在：' 'Uninstalled. Your data is still in: ')$TARGET"; fi
  exit 0
fi

# ---------------------------------------------------------------- install / upgrade / repair
[ -f "$HERE/app.zip" ] || fail "$(t '安装包不完整（缺少 app.zip）。' 'The installer is incomplete (app.zip is missing).')"
OLD="$(installed_version "$TARGET")"

if [ "$YES" = 0 ]; then
  if [ -n "$OLD" ]; then
    if [ "$OLD" = "$VER" ]; then head="$(t "已经安装了同一个版本（$VER）。要修复它吗？（重新复制程序文件、补齐环境）" "The same version ($VER) is already installed. Repair it? (copy the program files again, complete the environment)")"
    else head="$(t "已安装的版本是 $OLD，要升级到 $VER 吗？" "Version $OLD is installed. Upgrade to $VER?")"; fi
    confirm "$head\n\n$(t '位置：' 'Location: ')$TARGET\n$(t '你的数据（data 和 knowledge 文件夹）不会被改动。要卸载的话，运行：' 'Your data (the data and knowledge folders) is not touched. To uninstall instead, run: ')install.sh --uninstall" || exit 0
  else
    if [ "$GUI" = 1 ]; then
      zenity --question --title "AutoApply $VER" --width 480 --ok-label "$(t 继续 Continue)" --cancel-label "$(t 取消 Cancel)" \
        --text "$(t '安装 AutoApply：在你自己电脑上运行的求职助手。\n\n安装过程会联网下载 uv、Python 和依赖（来自 astral.sh 和 pypi.org），以及程序自己用的浏览器（Chromium）。约 600 MB，需要几分钟。只装在你的用户目录里，不需要 root。' 'Install AutoApply: a job-search assistant that runs on your own computer.\n\nSetup downloads uv, Python and the dependencies (from astral.sh and pypi.org) and the browser the program uses (Chromium): about 600 MB, a few minutes. Everything goes into your home folder; root is not needed.')" 2>/dev/null || exit 0
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
      confirm "$(t '安装过程会联网下载 uv、Python 和依赖，以及程序自己用的浏览器，约 600 MB。继续吗？' 'Setup downloads uv, Python and the dependencies and the browser the program uses, about 600 MB. Continue?')" || exit 0
      confirm "$(t '添加桌面快捷方式？' 'Add a desktop shortcut?')" && DESKTOP=1
      confirm "$(t '登录时自动启动？' 'Start when you sign in?')" && AUTOSTART=1
    fi
  fi
fi

: > "$LOG"; note "install $VER -> $TARGET (was: ${OLD:-none})"
work() {
  step() { note "$2"; echo "# $2"; echo "$1"; }
  step 5 "$(t '复制程序文件' 'Copying the program files')"
  [ -n "$OLD" ] && stop_running
  mkdir -p "$TARGET" || return 1
  tmp="$(mktemp -d)"
  if command -v unzip >/dev/null 2>&1; then unzip -q "$HERE/app.zip" -d "$tmp" >> "$LOG" 2>&1 || return 1
  else python3 -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$HERE/app.zip" "$tmp" >> "$LOG" 2>&1 || return 1; fi
  src="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
  [ -f "$src/pyproject.toml" ] || return 1
  rm -rf "$TARGET/backend" "$TARGET/frontend" "$TARGET/scripts"        # replaced whole: no leftovers of an older version
  cp -R "$src"/. "$TARGET"/ || return 1
  rm -rf "$tmp"
  cp "$HERE/autoapply.png" "$TARGET/autoapply.png" 2>/dev/null || true
  cp "$HERE/install.sh" "$TARGET/scripts/install-linux.sh" 2>/dev/null || true   # kept for a later uninstall
  printf '%s' "$VER" > "$TARGET/scripts/version.txt" 2>/dev/null || true

  step 20 "$(t '准备 uv（管理 Python 环境的小工具）' 'Getting uv (the tool that prepares Python)')"
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    if command -v curl >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh | sh >> "$LOG" 2>&1
    else wget -qO- https://astral.sh/uv/install.sh | sh >> "$LOG" 2>&1; fi
    command -v uv >/dev/null 2>&1 || return 2
  fi

  step 35 "$(t '安装 Python 和依赖（要几分钟）' 'Installing Python and the dependencies (a few minutes)')"
  (cd "$TARGET" && uv sync --inexact >> "$LOG" 2>&1) || return 3

  step 75 "$(t '准备程序用的浏览器' 'Getting the browser the program uses')"
  # every time: it returns at once when the right build is there, and a newer Playwright needs a newer build
  (cd "$TARGET" && uv run playwright install chromium >> "$LOG" 2>&1) || return 4

  step 92 "$(t '创建快捷方式' 'Creating the shortcuts')"
  if [ ! -f "$TARGET/data/app.db" ]; then   # a first install: the program starts in this language
    mkdir -p "$TARGET/data"
    if [ "$ZH" = 1 ]; then echo zh > "$TARGET/data/ui-lang.txt"; else echo en > "$TARGET/data/ui-lang.txt"; fi
  fi
  if [ "$MENU" = 1 ]; then mkdir -p "$APPS"; desktop_entry "$APPS/autoapply.desktop"; else rm -f "$APPS/autoapply.desktop"; fi
  if [ "$DESKTOP" = 1 ]; then mkdir -p "$DESKTOP_DIR"; desktop_entry "$DESKTOP_DIR/AutoApply.desktop"; fi
  if [ "$AUTOSTART" = 1 ]; then mkdir -p "$AUTOSTART_DIR"; desktop_entry "$AUTOSTART_DIR/autoapply.desktop"; fi
  step 100 "$(t '完成' 'Done')"
  return 0
}

if [ "$GUI" = 1 ]; then
  work > >(zenity --progress --title "AutoApply" --width 460 --auto-close --no-cancel --text "$(t '正在安装…' 'Installing…')" 2>/dev/null)
  rc=$?
else
  work | while read -r line; do case "$line" in "# "*) say "${line#\# }" ;; esac; done
  rc=${PIPESTATUS[0]}
fi
case "$rc" in
  0) ;;
  2) fail "$(t 'uv 没有装上（多数是网络问题）。' 'uv could not be installed (usually the network).')" ;;
  3) fail "$(t '安装 Python 和依赖失败（多数是网络问题）。' 'Installing Python and the dependencies failed (usually the network).')" ;;
  4) fail "$(t '下载浏览器失败。' 'Downloading the browser failed.')" ;;
  *) fail "$(t '复制程序文件失败。' 'Copying the program files failed.')" ;;
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
