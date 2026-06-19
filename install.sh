#!/bin/bash
set -e

# 색상
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "============================================================"
echo "  GIGO QC — Lacey Carbon Grid 자동 품질검증"
echo "  설치를 시작합니다."
echo "============================================================"
echo ""

# ─────────────────────────────────────────────────────────────
# 1) Python 확인
# ─────────────────────────────────────────────────────────────
echo "[1/4] Python 설치 확인 중..."
if ! command -v python3 &> /dev/null; then
  echo -e "${RED}[X] Python3가 설치되어 있지 않습니다.${NC}"
  echo ""
  echo "  macOS: brew install python3"
  echo "  Ubuntu: sudo apt install python3 python3-venv python3-pip"
  echo ""
  exit 1
fi

PY=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
MAJOR=$(echo "$PY" | cut -d. -f1)
MINOR=$(echo "$PY" | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 9 ]; }; then
  echo -e "${RED}[X] Python 3.9 이상이 필요합니다. 현재: $PY${NC}"
  exit 1
fi
echo -e "${GREEN}[OK] Python $PY 감지됨${NC}"

# ─────────────────────────────────────────────────────────────
# 2) 가상환경 생성
# ─────────────────────────────────────────────────────────────
echo ""
echo "[2/4] 가상환경 생성 중..."
if [ -d ".venv" ]; then
  echo -e "${GREEN}[OK] 가상환경이 이미 존재합니다. 건너뜁니다.${NC}"
else
  python3 -m venv .venv
  echo -e "${GREEN}[OK] 가상환경 생성 완료${NC}"
fi

# ─────────────────────────────────────────────────────────────
# 3) pip 업그레이드
# ─────────────────────────────────────────────────────────────
echo ""
echo "[3/4] pip 업그레이드 중..."
source .venv/bin/activate
python -m pip install --upgrade pip --quiet --disable-pip-version-check

# ─────────────────────────────────────────────────────────────
# 4) 의존 패키지 설치
# ─────────────────────────────────────────────────────────────
echo ""
echo "[4/4] 필요한 라이브러리 설치 중... (5~10분 소요)"
echo "      (numpy, opencv, mrcfile, fastapi 등)"
echo ""
pip install -r backend/requirements.txt --quiet --disable-pip-version-check

echo ""
echo "============================================================"
echo -e "${GREEN}  설치 완료!${NC}"
echo ""
echo "  이제 다음 명령으로 실행하세요:"
echo -e "  ${YELLOW}  ./run.sh${NC}"
echo "============================================================"
echo ""
