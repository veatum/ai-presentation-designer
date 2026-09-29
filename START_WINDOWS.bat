@echo off
setlocal
cd /d "%~dp0"
set "BASE_PORT=8090"
set "PORT=%BASE_PORT%"
if not exist "%~dp0static\index.html" (
  echo Error: static\index.html was not found in this project.
  pause
  exit /b 1
)
if not exist "outputs" mkdir "outputs"
if not exist ".env" copy /Y ".env.example" ".env" >nul

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
  echo First launch: creating virtual environment...
  %PY% -m venv --system-site-packages .venv
  if errorlevel 1 %PY% -m venv .venv
)
set "VENV_PY=.venv\Scripts\python.exe"

%VENV_PY% -c "import fastapi,uvicorn,multipart,dotenv,openai,pptx,PIL,fitz,pypdf,docx,requests" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies...
  %VENV_PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Failed to install dependencies. See outputs\server.log
    pause
    exit /b 1
  )
)

powershell -NoProfile -Command "$r=$null; try{$r=Invoke-RestMethod -UseBasicParsing http://127.0.0.1:%PORT%/api/version -TimeoutSec 2}catch{}; if($r -and $r.build -eq '7.4.2-final'){exit 0}else{exit 1}" >nul 2>&1
if not errorlevel 1 (
  start "" "http://127.0.0.1:%PORT%"
  exit /b 0
)

powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if($p){exit 0}else{exit 1}" >nul 2>&1
if not errorlevel 1 (
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do taskkill /PID %%P /F >nul 2>&1
)

start "" "http://127.0.0.1:%PORT%"
echo Server runs in this window. Press Ctrl+C to stop.
%VENV_PY% -m uvicorn app:app --host 127.0.0.1 --port %PORT%
pause
endlocal
