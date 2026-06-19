@echo off
chcp 65001 > nul
title GIGO QC - 실행 중

echo.
echo ============================================================
echo   GIGO QC 서버를 시작합니다.
echo ============================================================
echo.

REM 가상환경 확인
if not exist ".venv\Scripts\activate.bat" (
  echo [X] 가상환경이 없습니다.
  echo     먼저 install.bat 을 더블클릭해서 설치하세요.
  echo.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat

echo [실행 중] 브라우저가 곧 자동으로 열립니다...
echo.
echo   ▶ 종료하려면 이 창에서 Ctrl + C 를 누르세요.
echo   ▶ 또는 이 창을 닫으면 서버가 종료됩니다.
echo.

REM 브라우저 자동 오픈 (1.5초 후)
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"

REM 서버 시작
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000

pause
