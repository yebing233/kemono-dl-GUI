@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem  Build dist\kemono-dl-gui.exe (portable, no Python needed)
rem  Requires a local Python 3.11+ to run the build itself.
rem ---------------------------------------------------------------

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo   [x] 未检测到 Python，无法构建。构建只需要本机 Python，成品不需要。
    pause
    exit /b 1
)

%PY% tools\build_exe.py %*
if errorlevel 1 (
    echo.
    echo   [x] 构建失败，请查看上面的错误信息。
) else (
    echo.
    echo   [ok] 便携版已生成：dist\kemono-dl-gui.exe
)
pause
endlocal
