@echo off
rem AutoApply: install what is missing, then start. Safe to run every time.
rem Optional: set AUTOAPPLY_PORT=8010 before running to use another port.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if "%AUTOAPPLY_PORT%"=="" set AUTOAPPLY_PORT=8000

where uv >nul 2>nul
if errorlevel 1 if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if not errorlevel 1 goto have_uv
echo [AutoApply] 需要 uv（用来准备 Python 运行环境的小工具，来自 astral.sh）。
set /p ANS="[AutoApply] 现在自动下载安装它吗？(Y/N) "
if /i "%ANS%"=="Y" goto get_uv
echo [AutoApply] 好的。请自己安装后再运行： https://docs.astral.sh/uv/
pause
exit /b 1
:get_uv
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
:have_uv
where uv >nul 2>nul
if errorlevel 1 ( echo [AutoApply] uv 没有装上，请看上面的提示。 & pause & exit /b 1 )

echo [AutoApply] 检查依赖（第一次需要几分钟）...
rem --inexact: keep optional components that were added later (the ChatGPT sign-in component); a plain sync would remove them on every start
uv sync --inexact
if errorlevel 1 ( echo [AutoApply] 安装依赖失败，请看上面的提示。 & pause & exit /b 1 )

rem Asked for every time: it returns at once when the right build is there, and a newer Playwright needs a newer build.
echo [AutoApply] 检查程序用的浏览器（第一次和部分升级后需要下载）...
uv run playwright install chromium
if errorlevel 1 ( echo [AutoApply] 下载浏览器失败，请看上面的提示。 & pause & exit /b 1 )

if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo [AutoApply] 这份代码里没有构建好的界面。请下载发行包（里面已经带了），或安装 Node.js 后重新运行： https://nodejs.org/
    pause
    exit /b 1
  )
  echo [AutoApply] 构建界面（只需一次）...
  pushd frontend
  call npm install
  call npm run build
  popd
)

if not "%AUTOAPPLY_NO_BROWSER%"=="" goto console
if not "%AUTOAPPLY_CONSOLE%"=="" goto console
echo.
echo [AutoApply] 启动中。屏幕右下角的托盘里会出现 AutoApply 图标，网页会自动打开。
echo [AutoApply] 以后从托盘图标打开网页、查看状态、设置开机启动、退出。这个窗口可以关掉。
start "" /b uv run pythonw -m autoapply.launcher --port %AUTOAPPLY_PORT%
timeout /t 4 >nul
exit /b 0

:console
rem 不用托盘：服务直接在这个窗口里运行（关闭窗口即停止）。设 AUTOAPPLY_CONSOLE=1 可以选这种方式。
echo.
echo [AutoApply] 启动中。在浏览器里打开 http://127.0.0.1:%AUTOAPPLY_PORT%  （关闭这个窗口即停止）
echo.
uv run autoapply serve --port %AUTOAPPLY_PORT%
