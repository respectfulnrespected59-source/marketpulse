@echo off
REM MarketPulse daily runner — the one thing Task Scheduler calls.
REM
REM Exists because the previous task pointed straight at python.exe with an
REM empty WorkingDirectory and no log. When it died on 2026-08-14 (exit
REM 0xC000013A, process terminated) it left no trace anywhere: reports\ simply
REM had no file for that day, which is indistinguishable from a quiet market.
REM
REM So this wrapper does three things the bare command could not:
REM   1. pins the working directory, so relative paths resolve
REM   2. captures BOTH stdout and stderr to a dated log
REM   3. runs the journal even if the plays report fails, and reports a
REM      non-zero code if either did — a partial failure must not read as success
REM
REM The vault journal writes its own _heartbeat.md every run, pass or fail.
REM That file is the alarm; this log is the evidence.

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM %LOCALAPPDATA% rather than a full path: this repo is public and an absolute
REM path would publish the author's username for no benefit.
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "logs" mkdir "logs"
for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TODAY=%%a"
set "LOG=logs\daily_%TODAY%.log"

echo ============================================ >> "%LOG%" 2>&1
echo [%DATE% %TIME%] daily run starting >> "%LOG%" 2>&1

set "RC=0"

echo --- daily_plays.py --- >> "%LOG%" 2>&1
"%PY%" daily_plays.py >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [warn] daily_plays.py failed >> "%LOG%" 2>&1
  set "RC=1"
)

REM Runs regardless of the above: a failed plays report must not cost the
REM journal its entry for the day.
echo --- vault_journal.py --- >> "%LOG%" 2>&1
"%PY%" vault_journal.py >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [warn] vault_journal.py failed >> "%LOG%" 2>&1
  set "RC=1"
)

echo [%DATE% %TIME%] daily run finished rc=!RC! >> "%LOG%" 2>&1
endlocal & exit /b %RC%
