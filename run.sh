#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "============================================================"
echo "  GIGO QC 서버를 시작합니다."
echo "============================================================"
echo ""

if [ ! -f ".venv/bin/activate" ]; then
  echo -e "${RED}[X] 가상환경이 없습니다.${NC}"
  echo "    먼저 ./install.sh 를 실행하세요."
  exit 1
fi

source .venv/bin/activate

echo -e "${GREEN}[실행 중]${NC} 브라우저가 곧 자동으로 열립니다..."
echo ""
echo -e "  ▶ 종료하려면 ${YELLOW}Ctrl + C${NC} 를 누르세요."
echo ""

# 브라우저 자동 오픈 (2초 후, 백그라운드)
(
  sleep 2
  if [[ "$OSTYPE" == "darwin"* ]]; then
    open http://localhost:8000
  elif command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:8000 2>/dev/null || true
  fi
) &

cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
