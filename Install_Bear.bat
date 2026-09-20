@echo off
title 🐾 Bear Audio Limiter - Setup
color 0b
echo ===========================================
echo    🐾 BEAR AUDIO LIMITER INSTALLER
echo ===========================================
echo.

:startup_ask
set /p choice="Do you want Bear to start automatically with Windows? (y/n): "

if /I "%choice%"=="y" goto set_startup
if /I "%choice%"=="n" goto finish
echo Invalid choice, please type y or n.
goto startup_ask

:set_startup
echo.
echo Setting up Startup Shortcut...

set EXE_PATH=%~dp0Bear.exe
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set LNK_NAME=BearAudioLimiter.lnk

(
echo Set oWS = CreateObject("WScript.Shell"^)
echo sLinkFile = "%STARTUP_DIR%\%LNK_NAME%"
echo Set oLink = oWS.CreateShortcut(sLinkFile^)
echo oLink.TargetPath = "%EXE_PATH%"
echo oLink.WorkingDirectory = "%~dp0"
echo oLink.IconLocation = "%EXE_PATH%"
echo oLink.Save
) > "%temp%\MakeShortcut.vbs"

cscript //nologo "%temp%\MakeShortcut.vbs"
del "%temp%\MakeShortcut.vbs"

echo ✅ Startup shortcut created!
echo.

:finish
echo ===========================================
echo    🐾 BEAR IS READY TO PROTECT!
echo ===========================================
echo.
echo You can now close this window and run Bear.exe
pause
