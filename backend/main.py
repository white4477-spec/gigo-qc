"""
GIGO QC — FastAPI 앱 진입점 (main.py)

엔드포인트:
  POST /api/analyze/stream   — SSE 실시간 분석 스트리밍
  POST /api/report/pdf       — PDF 리포트 다운로드
  POST /api/report/csv       — CSV 데이터 다운로드
  GET  /api/health           — 서버 상태 확인

실행 방법 (프로젝트 루트에서):
  uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

Windows 실행:
  python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

# 백엔드 디렉토리를 Python 경로에 추가 (직접 실행 시 대비)
_BACKEND_DIR = Path(__file__).parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# 내부 모듈 import
from parsers import parse_file
import analyzer as _analyzer
from classifier import classify
from qc_evaluator import evaluate
import report_generator as _report_gen


# ─── FastAPI 앱 초기화 ─────────────────────────────────────────────────────────

app = FastAPI(
    title="GIGO QC API",
    description=(
        "Lacey Carbon Grid 홀 자동 검출·측정 및 QC 판정 API.\n\n"
        "TEM 이미지(MRC/TIFF/PNG/JPG)를 업로드하면 "
        "Server-Sent Events(SSE)로 실시간 분석 결과를 스트리밍합니다."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS 설정 (로컬 개발 및 다중 클라이언트 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── SSE 유틸리티 ─────────────────────────────────────────────────────────────

def _sse_event(data: Dict[str, Any]) -> str:
    """dict를 SSE 이벤트 문자열로 변환합니다."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# SSE 단계 정의 (label은 한국어)
_SSE_STEPS = [
    ("parse",     "파일 파싱",               10),
    ("normalize", "이미지 정규화",            20),
    ("clahe",     "CLAHE 대비 향상",          35),
    ("threshold", "Otsu 이진화",              50),
    ("morph",     "Morphological 처리",       65),
    ("contours",  "홀 컨투어 검출",           80),
    ("measure",   "파라미터 계산",            90),
    ("classify",  "Grid Suitability 분류",   95),
    ("done",      "완료",                    100),
]


# ─── API 라우트 (mount보다 먼저 등록) ─────────────────────────────────────────

@app.get("/api/health", summary="서버 상태 확인")
async def health_check():
    """서버가 정상 동작 중인지 확인합니다."""
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.post("/api/analyze/stream", summary="이미지 분석 (SSE 스트리밍)")
async def analyze_stream(
    file: UploadFile = File(..., description="MRC/MRCS/TIFF/PNG/JPG 이미지 파일"),
    pixel_scale_nm: float = Form(
        1.0,
        description="nm/pixel 스케일 값. MRC는 자동 추출 시도.",
        gt=0,
    ),
    grid_type_hint: str = Form(
        "auto",
        description=(
            "'auto': 자동 분류 | 'A': 막단백질 | "
            "'B': 단백질 복합체 | 'C': 나노소재 | 'D': 대형 시편"
        ),
    ),
):
    """
    이미지를 업로드하고 홀 검출·분석을 실행합니다.

    결과는 Server-Sent Events(SSE) 스트림으로 실시간 전달됩니다.
    각 이벤트는 JSON 형식이며 step, label, progress 필드를 포함합니다.
    마지막 이벤트(step=done)에는 result 필드에 전체 분석 결과가 포함됩니다.

    ### SSE 이벤트 구조
    ```json
    {"step": "parse", "label": "파일 파싱", "progress": 10}
    ...
    {"step": "done", "label": "완료", "progress": 100, "result": {...}}
    ```

    ### 에러 이벤트
    ```json
    {"step": "error", "message": "에러 메시지"}
    ```
    """
    # 파일 내용 미리 읽기 (스트리밍 전에 UploadFile 소비)
    file_bytes = await file.read()
    filename   = file.filename or "unknown"

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # ── Step 1: 파일 파싱 ────────────────────────────────────────────
            yield _sse_event({"step": "parse", "label": "파일 파싱", "progress": 10})
            await asyncio.sleep(0.05)

            try:
                img_array, detected_scale = await asyncio.get_event_loop().run_in_executor(
                    None, parse_file, file_bytes, filename
                )
            except ValueError as e:
                yield _sse_event({
                    "step": "error",
                    "message": f"파일을 읽을 수 없습니다: {e}"
                })
                return

            # MRC에서 자동 감지된 스케일이 있으면 우선 사용
            effective_scale = detected_scale if detected_scale and detected_scale > 0 \
                              else pixel_scale_nm

            # ── Step 2: 정규화 ────────────────────────────────────────────────
            yield _sse_event({"step": "normalize", "label": "이미지 정규화", "progress": 20})
            await asyncio.sleep(0.05)

            img_norm = await asyncio.get_event_loop().run_in_executor(
                None, _analyzer.preprocess_normalize, img_array
            )

            # ── Step 3: CLAHE ──────────────────────────────────────────────────
            yield _sse_event({"step": "clahe", "label": "CLAHE 대비 향상", "progress": 35})
            await asyncio.sleep(0.05)

            img_clahe = await asyncio.get_event_loop().run_in_executor(
                None, _analyzer.preprocess_clahe, img_norm
            )

            # ── Step 4: 이진화 ────────────────────────────────────────────────
            yield _sse_event({"step": "threshold", "label": "Otsu 이진화", "progress": 50})
            await asyncio.sleep(0.05)

            img_bin = await asyncio.get_event_loop().run_in_executor(
                None, _analyzer.preprocess_threshold, img_clahe
            )

            # ── Step 5: Morphological 처리 ────────────────────────────────────
            yield _sse_event({"step": "morph", "label": "Morphological 처리", "progress": 65})
            await asyncio.sleep(0.05)

            img_clean = await asyncio.get_event_loop().run_in_executor(
                None, _analyzer.preprocess_morph, img_bin
            )

            # ── Step 6: 컨투어 검출 ───────────────────────────────────────────
            yield _sse_event({"step": "contours", "label": "홀 컨투어 검출", "progress": 80})
            await asyncio.sleep(0.05)

            contours = await asyncio.get_event_loop().run_in_executor(
                None, _analyzer.detect_contours, img_clean
            )

            # ── Step 7: 파라미터 계산 ─────────────────────────────────────────
            yield _sse_event({"step": "measure", "label": "파라미터 계산", "progress": 90})
            await asyncio.sleep(0.05)

            holes = await asyncio.get_event_loop().run_in_executor(
                None, _analyzer.measure_holes, contours, effective_scale
            )
            stats = await asyncio.get_event_loop().run_in_executor(
                None, _analyzer.compute_stats, holes, img_array.shape[:2], effective_scale
            )

            if stats["total_holes"] == 0:
                yield _sse_event({
                    "step": "error",
                    "message": (
                        "홀이 검출되지 않았습니다. "
                        "픽셀 스케일 값을 확인하거나, 이미지 품질을 점검해 주세요."
                    )
                })
                return

            # ── Step 8: 분류 & QC 판정 ────────────────────────────────────────
            yield _sse_event({
                "step": "classify",
                "label": "Grid Suitability 분류",
                "progress": 95
            })
            await asyncio.sleep(0.05)

            classification = await asyncio.get_event_loop().run_in_executor(
                None, classify, stats
            )
            qc_result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: evaluate(
                    stats,
                    grid_type_hint=grid_type_hint,
                    classifier_best_match=classification.get("best_match"),
                )
            )

            # 오버레이 프리뷰 생성
            preview_b64 = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _analyzer.generate_overlay_preview(
                    img_norm, holes, contours,
                    qc_result.get("qc_checks")
                )
            )

            # ── Step 9: 완료 ──────────────────────────────────────────────────
            result: Dict[str, Any] = {
                "filename":            filename,
                "analysis_time":       datetime.now().isoformat(),
                "pixel_scale_nm":      effective_scale,
                "scale_source":        "auto" if detected_scale else "manual",
                "holes":               holes,
                "stats":               stats,
                "classification":      classification,
                # 프론트엔드 호환 키 (qc, overlay_png_base64) + 기존 키도 유지
                "qc":                  qc_result,
                "qc_result":           qc_result,
                "overlay_png_base64":  preview_b64,
                "preview_b64":         preview_b64,
            }

            yield _sse_event({
                "step":     "done",
                "label":    "완료",
                "progress": 100,
                "result":   result,
            })

        except Exception as exc:
            # 예기치 못한 에러 — 스택 트레이스와 함께 에러 이벤트 전송
            err_msg = (
                f"분석 중 예기치 못한 오류가 발생했습니다: {exc}\n"
                "관리자에게 문의하거나 다른 이미지로 다시 시도해 주세요."
            )
            # 서버 로그에는 상세 에러 출력
            traceback.print_exc()
            yield _sse_event({"step": "error", "message": err_msg})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
        },
    )


@app.post("/api/report/pdf", summary="PDF 리포트 생성")
async def generate_pdf(request: Request):
    """
    분석 결과 JSON을 받아 PDF 리포트를 생성하여 반환합니다.

    Request body: analyze/stream의 done 이벤트에서 받은 result dict.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON 파싱 오류: 올바른 JSON을 전송해 주세요.")

    try:
        pdf_bytes = await asyncio.get_event_loop().run_in_executor(
            None, _report_gen.create_pdf, data
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"PDF 생성 중 오류가 발생했습니다: {exc}"
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=GIGO-QC-Report.pdf"
        },
    )


@app.post("/api/report/csv", summary="CSV 데이터 내보내기")
async def generate_csv(request: Request):
    """
    분석 결과 JSON을 받아 CSV 파일을 생성하여 반환합니다.

    CSV는 UTF-8 BOM 인코딩으로 Windows Excel에서 한글 깨짐 없이 열립니다.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON 파싱 오류: 올바른 JSON을 전송해 주세요.")

    try:
        csv_bytes = await asyncio.get_event_loop().run_in_executor(
            None, _report_gen.create_csv, data
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"CSV 생성 중 오류가 발생했습니다: {exc}"
        )

    filename = data.get("filename", "analysis")
    stem = Path(filename).stem
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"GIGO-QC-{stem}-{ts}.csv"

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8-sig",
        headers={
            "Content-Disposition": f"attachment; filename={csv_filename}"
        },
    )


# ─── 정적 파일 마운트 (API 라우트들 이후에 등록) ─────────────────────────────

# PyInstaller로 패키징되었을 때를 위해 환경변수 우선
import os as _os
_env_frontend = _os.environ.get("GIGO_FRONTEND_DIR")
if _env_frontend:
    _FRONTEND_DIR = Path(_env_frontend)
else:
    _FRONTEND_DIR = _BACKEND_DIR.parent / "frontend"

if _FRONTEND_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIR), html=True),
        name="frontend",
    )
else:
    # 프론트엔드 디렉토리가 없으면 루트에 안내 메시지
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "message": "GIGO QC API 서버가 실행 중입니다.",
            "docs": "/api/docs",
            "health": "/api/health",
        }
