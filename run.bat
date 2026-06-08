@echo off
REM Lanny launcher for Windows.
REM   * Creates .venv on first run, installs deps.
REM   * Starts the tray app (Flask runs in-process).
setlocal
cd /d "%~dp0"

if not defined PYTHON set PYTHON=python

if not exist .venv (
    echo ==^> creating virtualenv ^(.venv^)
    %PYTHON% -m venv .venv || goto :err
)

call .venv\Scripts\activate.bat

REM Install deps if requirements.txt hash changed.
set "STAMP=.venv\.deps.sha"
for /f "delims=" %%H in ('certutil -hashfile requirements.txt SHA1 ^| findstr /v ":" ^| findstr /v "CertUtil"') do set "CUR=%%H"
set "CUR=%CUR: =%"

set "PREV="
if exist "%STAMP%" set /p PREV=<"%STAMP%"

if not "%CUR%"=="%PREV%" (
    echo ==^> installing dependencies
    python -m pip install --upgrade pip --quiet || goto :err
    pip install -r requirements.txt --quiet || goto :err
    > "%STAMP%" echo %CUR%
)

echo ==^> launching Lanny ^(open http://127.0.0.1:5050 or use the tray icon^)
python tray.py
goto :eof

:err
echo Failed. See messages above.
exit /b 1
