@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem  kemono-dl GUI launcher (source mode, needs Python 3.11+)
rem  For a Python-free experience use dist\kemono-dl-gui.exe instead.
rem ---------------------------------------------------------------

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo.
    echo   [x] 未检测到 Python。
    echo.
    echo   如果你不想安装 Python，直接双击：dist\kemono-dl-gui.exe
    echo   便携版已经内置运行环境，无需任何安装。
    echo.
    pause
    exit /b 1
)

echo   正在启动 kemono-dl GUI ...
%PY% -m kemono_dl_gui %*
if errorlevel 1 (
    echo.
    echo   [x] 启动失败。若提示缺少 requests，请先运行：%PY% -m pip install -r requirements.txt
    pause
)
endlocal
