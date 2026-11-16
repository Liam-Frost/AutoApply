# Shared by the Linux installer (linux/install.sh) and the macOS app (macos/AutoApply): the part of an installation
# that is the same on both. Sourced, not run. Written for the bash 3.2 that macOS has.
#
# The caller provides:  t "<Chinese>" "<English>"   the text in the chosen language
#                       note "<line>"               a line for the caller's log
#
# What happens here is what the Windows installer does too:
#   - a new version is laid out in <root>/.staged; the installed one is not touched
#   - scripts/prepare.py, run with the uv that came in the package, swaps it in, installs the dependencies and the
#     browser, and puts the previous version back if that fails or is cancelled
#   - nothing is stopped: while the program runs from <root>, the caller is told so

# Is AutoApply running out of <root>? The program leaves a mark per running process in data/run (runstate.py): a
# file holding the process id. A mark whose process is gone (a crash) is cleared here. Copies from before the marks
# existed, and anything else started with the folder's Python by its full path, are found by their command line.
running_from() {
  [ -d "$1/.venv" ] || return 1
  for _mark in "$1"/data/run/*.pid; do
    [ -f "$_mark" ] || continue
    _pid="$(cat "$_mark" 2>/dev/null)"
    case "$_pid" in ''|*[!0-9]*) rm -f "$_mark"; continue ;; esac
    if kill -0 "$_pid" 2>/dev/null && ps -p "$_pid" -o command= 2>/dev/null | grep -qi python; then return 0; fi
    rm -f "$_mark"
  done
  pgrep -f "$1/.venv/bin/python" >/dev/null 2>&1
}

# The uv for this machine among the ones in <dir> (uv-x86_64, uv-aarch64). Prints its path; fails when there is none.
uv_for_this_machine() {
  case "$(uname -m)" in
    x86_64|amd64) arch=x86_64 ;;
    arm64|aarch64) arch=aarch64 ;;
    *) return 1 ;;
  esac
  [ -f "$1/uv-$arch" ] || return 1
  printf '%s' "$1/uv-$arch"
}

# put_uv <packaged uv> <root>: the package's uv becomes <root>/tools/uv
put_uv() {
  mkdir -p "$2/tools" || return 1
  cp "$1" "$2/tools/uv.new" && chmod 755 "$2/tools/uv.new" && mv -f "$2/tools/uv.new" "$2/tools/uv"
}

# run_prepare <root> <on_progress>
#   Runs the second half and waits for it. While it runs, <on_progress> is called about twice a second with
#   "<step> <percent> <part>" (step 0 Python, 1 files, 2 dependencies, 3 browser; percent -1 when unknown).
#   To ask for a stop, create the file named in $PREPARE_CANCEL (set here before the first call).
#   Afterwards $PREPARE_RESULT is "ok", "cancelled" or an error code (see prepare_message), and $PREPARE_LOG is
#   the log that was kept with the data.
run_prepare() {
  _root="$1"; _progress="$2"
  _dir="$(mktemp -d)" || return 1
  _status="$_dir/status"; _done="$_dir/done"
  PREPARE_CANCEL="$_dir/cancel"
  mkdir -p "$_root/data/logs"
  PREPARE_LOG="$_root/data/logs/setup-$(date +%Y%m%d-%H%M%S).log"
  printf '0 -1 0' > "$_status"
  note "starting the second half; its log: $PREPARE_LOG"
  ( cd "$_root" && "$_root/tools/uv" run --no-project --python 3.12 "$_root/.staged/scripts/prepare.py" \
      --root "$_root" --staged "$_root/.staged" --uv "$_root/tools/uv" \
      --status "$_status" --done "$_done" --cancel "$PREPARE_CANCEL" --log "$PREPARE_LOG" ) >> "${PREPARE_LOG%.log}-start.log" 2>&1 &
  _pid=$!
  while kill -0 "$_pid" 2>/dev/null; do
    _line="$(cat "$_status" 2>/dev/null)"
    [ -n "$_line" ] && "$_progress" $_line
    sleep 0.5
  done
  wait "$_pid"
  if [ -f "$_done" ]; then PREPARE_RESULT="$(cat "$_done")"; else PREPARE_RESULT="error bootstrap"; fi
  PREPARE_RESULT="${PREPARE_RESULT#error }"
  note "the second half ended: $PREPARE_RESULT"
  rm -rf "$_dir"
  [ "$PREPARE_RESULT" = ok ]
}

# What a step is called, for a progress line.
prepare_step() {
  case "$1" in
    0) t '准备 Python' 'Getting Python' ;;
    1) t '放置新版本的文件' 'Putting the new files in place' ;;
    2) t '安装依赖（第一次约 300 MB）' 'Installing the dependencies (about 300 MB the first time)' ;;
    *) t '准备程序用的浏览器' 'Getting the browser the program uses' ;;
  esac
}

# prepare_message <code> <root>: what went wrong, in words. The codes are the ones scripts/prepare.py ends with.
prepare_message() {
  case "$1" in
    cancelled) t '你停止了安装。如果之前装有旧版本，它已经恢复原样。再运行一次会接着来，已经下载的内容不会重新下载。' 'You stopped the installation. If a version was installed before, it is back in place. Running it again continues; what was already downloaded is kept.' ;;
    bootstrap) t 'Python 下载失败（多数是网络问题）。之前安装的内容没有被改动。' 'Python could not be downloaded (usually the network). Nothing that was installed before was changed.' ;;
    files) t '新版本的文件放置失败（可能有文件被别的程序占用）。之前的版本没有被改动。' 'The new files could not be put in place (a file may be open in another program). The previous version is untouched.' ;;
    deps) t '依赖安装失败（多数是网络问题）。再运行一次会接着来，已经下载的内容不会重新下载。' 'The dependencies could not be installed (usually the network). Running it again continues; what was already downloaded is kept.' ;;
    deps_restored) t '新版本的依赖安装失败（多数是网络问题）。之前的版本已经恢复，可以照常使用。' 'The dependencies of the new version could not be installed (usually the network). The previous version was put back and works.' ;;
    deps_broken) t '依赖安装失败，旧版本的依赖也没能恢复。你的数据没有被改动。请在网络正常时再运行一次。' 'The dependencies could not be installed, and the previous version'"'"'s could not be restored. Your data is untouched. Run it again when the network works.' ;;
    browser) t '程序用的浏览器下载失败（多数是网络问题）。其余部分已经装好，再运行一次即可完成。' 'The browser the program uses could not be downloaded (usually the network). Everything else is installed; running it again finishes it.' ;;
    browser_libs) t "程序用的浏览器已经下载，但启动不了：这台电脑缺少它需要的系统库。在 Debian 或 Ubuntu 上运行下面这条命令安装（需要管理员权限），然后再运行一次安装程序：\n    sudo apt-get install -y libatomic1 && sudo \"$2/.venv/bin/playwright\" install-deps chromium" "The browser the program uses was downloaded but cannot start: this computer lacks system libraries it needs. On Debian or Ubuntu install them with the command below (it needs administrator rights), then run setup again:\n    sudo apt-get install -y libatomic1 && sudo \"$2/.venv/bin/playwright\" install-deps chromium" ;;
    *) t "安装没有完成（$1）。" "Setup did not finish ($1)." ;;
  esac
}

running_message() {
  t '这个文件夹里的 AutoApply 正在运行。请先退出它：点托盘（菜单栏）里的图标，选“退出”；如果正在填写某份申请，等它填完。' 'AutoApply is running from this folder. Quit it first: its icon in the tray (menu bar), then Quit; if an application is being filled in, let it finish.'
}
