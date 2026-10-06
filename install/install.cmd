@echo off
rem install.cmd: starts the Weekly Planning installer on Windows. It only finds Git Bash (which comes with Git for
rem Windows) and runs install.sh with it, so Windows, Mac and Linux all use the same installer. Needs Docker Desktop.
setlocal
set "BASH=%ProgramFiles%\Git\bin\bash.exe"
if not exist "%BASH%" set "BASH=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not exist "%BASH%" set "BASH=%LocalAppData%\Programs\Git\bin\bash.exe"
if not exist "%BASH%" (
  echo Git for Windows is needed. It also gives this installer its shell.
  echo Install it from https://git-scm.com/download/win and run install.cmd again.
  exit /b 1
)
"%BASH%" "%~dp0install.sh" %*
exit /b %ERRORLEVEL%
