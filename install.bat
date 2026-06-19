@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
title GIGO QC - 설치

echo.
echo ============================================================
echo   GIGO QC - Lacey Carbon Grid 자동 품질검증
echo   설치를 시작합니다.
echo ============================================================
echo.

REM ─────────────────────────────────────────────────────────────
REM  1) Python 설치 확인
REM ─────────────────────────────────────────────────────────────
echo [1/4] Python 설치 확인 중...
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [X] Python이 설치되어 있지 않습니다.
  echo.
  echo     아래 사이트에서 Python 3.10 이상을 설치해주세요:
  echo     https://www.python.org/downloads/
  echo.
  echo     설치할 때 반드시 "Add Python to PATH" 체크박스를
  echo     선택하셔야 합니다.
  echo.
  pause
  exit /b 1
)

REM Python 3.9+ 버전 확인
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python !PYVER! 감지됨
python -c "import sys; exit(0) if sys.version_info >= (3,9) else exit(1)" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [X] Python 3.9 이상이 필요합니다. 현재 버전: !PYVER!
  echo     https://www.python.org/downloads/ 에서 최신 버전을 받아주세요.
  pause
  exit /b 1
)

REM ─────────────────────────────────────────────────────────────
REM  2) 가상환경 생성
REM ─────────────────────────────────────────────────────────────
echo.
echo [2/4] 가상환경 생성 중... (잠시만요)
if exist ".venv" (
  echo [OK] 가상환경이 이미 존재합니다. 건너뜁니다.
) else (
  python -m venv .venv
  if errorlevel 1 (
    echo [X] 가상환경 생성에 실패했습니다.
    pause
    exit /b 1
  )
  echo [OK] 가상환경 생성 완료
)

REM ─────────────────────────────────────────────────────────────
REM  3) pip 업그레이드
REM ─────────────────────────────────────────────────────────────
echo.
echo [3/4] pip 업그레이드 중...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet --disable-pip-version-check
if errorlevel 1 (
  echo [경고] pip 업그레이드 실패. 계속 진행합니다.
)

REM ─────────────────────────────────────────────────────────────
REM  4) 의존 패키지 설치
REM ─────────────────────────────────────────────────────────────
echo.
echo [4/4] 필요한 라이브러리 설치 중... (5~10분 소요)
echo       (numpy, opencv, mrcfile, fastapi 등을 설치합니다)
echo.
pip install -r backend\requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo [X] 패키지 설치에 실패했습니다.
  echo     인터넷 연결을 확인하고 다시 시도해주세요.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   설치 완료!
echo.
echo   이제 run.bat 파일을 더블클릭하면 프로그램이 실행됩니다.
echo ============================================================
echo.
pause
