"""
GIGO QC - 통합 런처
PyInstaller로 단일 .exe로 패키징되는 진입점.
실행 시:
  1) 내장된 FastAPI 서버를 백그라운드 스레드로 시작
  2) 기본 브라우저에서 http://127.0.0.1:8765 자동 오픈
  3) 콘솔 창에 종료 안내 출력 (X 누르거나 Ctrl+C로 종료)
"""
import os
import sys
import time
import threading
import webbrowser
import socket
from pathlib import Path

# PyInstaller --onefile 환경에서는 임시 디렉터리(_MEIPASS)에 데이터가 풀림
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent

# backend 패키지를 import 경로에 추가
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "backend"))

# 프론트엔드 정적 파일 경로를 환경변수로 전달
os.environ["GIGO_FRONTEND_DIR"] = str(BASE_DIR / "frontend")

HOST = "127.0.0.1"
PORT = 8765  # 일반 개발 포트 8000 대신 충돌 적은 포트 사용


def find_free_port(preferred: int) -> int:
    """선호 포트가 사용 중이면 다음 가용 포트 탐색."""
    for p in [preferred, 8766, 8767, 8768, 8769, 0]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((HOST, p))
                return s.getsockname()[1]
        except OSError:
            continue
    return preferred


def open_browser_when_ready(url: str, timeout: float = 30.0) -> None:
    """서버가 응답하기 시작하면 브라우저 오픈."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1).read()
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.3)
    # 못 띄워도 브라우저는 그냥 시도
    webbrowser.open(url)


def banner(url: str) -> None:
    print()
    print("=" * 60)
    print("  GIGO QC - Lacey Carbon Grid QC")
    print("=" * 60)
    print(f"  서버 주소: {url}")
    print(f"  브라우저가 자동으로 열립니다.")
    print()
    print("  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.")
    print("=" * 60)
    print()


def main() -> None:
    port = find_free_port(PORT)
    url = f"http://{HOST}:{port}"
    banner(url)

    threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()

    # uvicorn 서버 (메인 스레드에서 실행 → Ctrl+C 처리)
    import uvicorn
    from backend.main import app  # noqa: E402

    config = uvicorn.Config(
        app,
        host=HOST,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n종료합니다...")


if __name__ == "__main__":
    main()
