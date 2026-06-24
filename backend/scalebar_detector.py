"""
GIGO QC — 스케일바 자동 인식
이미지 하단/모서리에 그려진 스케일바(흰 막대 + "200 nm" 텍스트)를 검출해
nm/pixel 값을 추정합니다.

전략:
  1) 이미지 하단 ~20% 영역(우/좌 후보)에서 수평 막대 후보 검출
     - 이진화 후 가로 형태 비율(aspect ratio) 큰 컴포넌트 추출
  2) 막대 위/아래/옆 영역에서 Tesseract OCR로 숫자 + 단위 추출
  3) 텍스트가 "200 nm"이고 막대 길이가 100 px이면 → 2.0 nm/px

의존성:
  - pytesseract (Python wrapper)
  - tesseract.exe (시스템 바이너리, Windows에서는 동봉)

Tesseract가 없으면 OCR을 건너뛰고 None을 반환합니다.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


# ─── Tesseract 자동 감지 ──────────────────────────────────────────────────────

_TESSERACT_AVAILABLE: Optional[bool] = None
_TESSERACT_PATH: Optional[str] = None


def _ensure_tesseract() -> bool:
    """Tesseract 바이너리 + pytesseract 모듈 모두 사용 가능한지 확인."""
    global _TESSERACT_AVAILABLE, _TESSERACT_PATH
    if _TESSERACT_AVAILABLE is not None:
        return _TESSERACT_AVAILABLE

    try:
        import pytesseract  # noqa: F401
    except ImportError:
        _TESSERACT_AVAILABLE = False
        return False

    # 1) PATH 검색
    path = shutil.which("tesseract")

    # 2) Windows 표준 위치
    if not path and os.name == "nt":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            # PyInstaller frozen — _MEIPASS 옆 폴더에 동봉되는 경우
        ]
        import sys
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
            candidates.insert(0, os.path.join(base, "tesseract", "tesseract.exe"))
            candidates.insert(0, os.path.join(os.path.dirname(sys.executable), "tesseract", "tesseract.exe"))
        for cand in candidates:
            if os.path.isfile(cand):
                path = cand
                break

    if not path:
        _TESSERACT_AVAILABLE = False
        return False

    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = path
    _TESSERACT_PATH = path
    _TESSERACT_AVAILABLE = True
    return True


def is_ocr_available() -> bool:
    """외부에서 Tesseract 가용 여부 확인용."""
    return _ensure_tesseract()


# ─── 데이터 클래스 ────────────────────────────────────────────────────────────

@dataclass
class ScalebarResult:
    nm_per_px: float
    bar_length_px: int
    text: str
    value: float
    unit: str
    confidence: float  # 0~1


# ─── 메인 진입점 ──────────────────────────────────────────────────────────────

def detect_scalebar(img_array: np.ndarray) -> Optional[ScalebarResult]:
    """
    이미지에서 스케일바를 검출해 nm/px 추정.
    실패 시 None.
    """
    if img_array is None or img_array.size == 0:
        return None
    if not _ensure_tesseract():
        return None

    # uint8 grayscale로 정규화
    img = _to_uint8_gray(img_array)
    h, w = img.shape

    # 후보 ROI: 하단 25% 영역(좌/우 분할도 포함)
    rois = _candidate_rois(img)

    best: Optional[ScalebarResult] = None
    for roi, (x0, y0) in rois:
        result = _scan_roi(roi, x0, y0, full_shape=(h, w))
        if result is None:
            continue
        if best is None or result.confidence > best.confidence:
            best = result

    return best


# ─── 헬퍼 ────────────────────────────────────────────────────────────────────

def _to_uint8_gray(img: np.ndarray) -> np.ndarray:
    if img.dtype == np.uint8 and img.ndim == 2:
        return img
    arr = img.astype(np.float32)
    if arr.ndim == 3:
        arr = arr[..., 0]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-6:
        return np.zeros(arr.shape, dtype=np.uint8)
    norm = (arr - lo) / (hi - lo) * 255.0
    return norm.astype(np.uint8)


def _candidate_rois(img: np.ndarray):
    """스케일바가 존재할 가능성이 큰 ROI 후보 목록."""
    h, w = img.shape
    rois = []
    # 하단 25%
    y_bottom = int(h * 0.75)
    rois.append((img[y_bottom:, :], (0, y_bottom)))
    # 우측 하단 1/3 (별도)
    x_right = int(w * 0.5)
    rois.append((img[y_bottom:, x_right:], (x_right, y_bottom)))
    # 좌측 하단 1/3
    rois.append((img[y_bottom:, :int(w * 0.5)], (0, y_bottom)))
    # 상단 10% (드물지만 일부 SEM 이미지)
    rois.append((img[:int(h * 0.1), :], (0, 0)))
    return rois


def _scan_roi(
    roi: np.ndarray,
    x0: int,
    y0: int,
    full_shape: Tuple[int, int],
) -> Optional[ScalebarResult]:
    """ROI 내에서 막대 후보를 찾고, 인접 텍스트를 OCR로 파싱."""
    h, w = roi.shape
    if h < 10 or w < 30:
        return None

    # 막대는 흰색(밝은 배경) 또는 검정(어두운 배경) 둘 다 가능 — 양쪽 모두 시도
    candidates = []
    for invert in (False, True):
        img_for_bar = cv2.bitwise_not(roi) if invert else roi
        # Otsu + morph
        _, binar = cv2.threshold(img_for_bar, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # 막대는 보통 매우 가로 긴 컴포넌트 → 가로 closing
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
        morphed = cv2.morphologyEx(binar, cv2.MORPH_CLOSE, kernel_h, iterations=1)

        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(morphed, connectivity=8)
        for i in range(1, n_labels):
            x, y, ww, hh, area = stats[i]
            if hh == 0 or ww < 20:
                continue
            ar = ww / max(1, hh)
            # 가로 막대: 종횡비 >= 5, 높이는 작음 (이미지 높이의 5% 미만)
            if ar < 5.0 or hh > full_shape[0] * 0.05:
                continue
            # 너무 거대한 객체 제외 (전체 폭의 80% 초과는 보통 그리드 자체)
            if ww > w * 0.8:
                continue
            # 너무 작은 객체 제외
            if area < 30:
                continue
            candidates.append((x, y, ww, hh, area, invert))

    if not candidates:
        return None

    # 가로 종횡비 큰 순으로 정렬 후 상위 3개만 시도
    candidates.sort(key=lambda c: -(c[2] / max(1, c[3])))

    import pytesseract
    best: Optional[ScalebarResult] = None
    for (x, y, ww, hh, area, invert) in candidates[:3]:
        # 막대 위/아래 텍스트 영역 시도
        text_value = _ocr_around(roi, x, y, ww, hh, pytesseract)
        if text_value is None:
            continue
        value, unit, raw_text = text_value
        unit_to_nm = _unit_to_nm(unit)
        if unit_to_nm is None:
            continue
        nm_per_px = value * unit_to_nm / max(1, ww)
        if not (0.001 <= nm_per_px <= 10_000.0):
            continue

        # 신뢰도: aspect ratio가 클수록, 막대가 짧지 않을수록 높음
        ar = ww / max(1, hh)
        conf = min(1.0, 0.4 + 0.05 * min(ar, 20) + 0.005 * min(ww, 200))

        res = ScalebarResult(
            nm_per_px=nm_per_px,
            bar_length_px=int(ww),
            text=raw_text,
            value=value,
            unit=unit,
            confidence=conf,
        )
        if best is None or res.confidence > best.confidence:
            best = res

    return best


_UNIT_PATTERN = re.compile(
    r"([0-9]+(?:[.,][0-9]+)?)\s*(nm|um|µm|μm|micron[s]?|micrometer[s]?|mm|cm|m|Å|A|angstrom[s]?)\b",
    flags=re.IGNORECASE,
)


def _ocr_around(roi, x, y, ww, hh, pytesseract) -> Optional[Tuple[float, str, str]]:
    """막대 주변 영역(위/아래)을 OCR해 '값 + 단위'를 추출."""
    H, W = roi.shape
    pad_x = max(20, ww // 2)
    pad_y = max(20, hh * 4)

    regions = []
    # 위쪽
    y_top0 = max(0, y - pad_y - 4)
    y_top1 = max(0, y - 2)
    if y_top1 - y_top0 > 8:
        regions.append(roi[y_top0:y_top1, max(0, x - pad_x):min(W, x + ww + pad_x)])
    # 아래쪽
    y_bot0 = min(H, y + hh + 2)
    y_bot1 = min(H, y + hh + pad_y + 4)
    if y_bot1 - y_bot0 > 8:
        regions.append(roi[y_bot0:y_bot1, max(0, x - pad_x):min(W, x + ww + pad_x)])
    # 우측
    regions.append(roi[max(0, y - pad_y):min(H, y + hh + pad_y),
                       min(W, x + ww):min(W, x + ww + pad_x * 3)])

    for region in regions:
        if region.size == 0 or region.shape[0] < 8 or region.shape[1] < 16:
            continue
        # OCR 전 전처리: upscale + 이진화
        scaled = cv2.resize(region, None, fx=3, fy=3,
                            interpolation=cv2.INTER_CUBIC)
        # 텍스트가 어두운 배경에 흰색인 경우가 많음 → 두 가지 모두 시도
        for invert in (False, True):
            img_ocr = cv2.bitwise_not(scaled) if invert else scaled
            try:
                text = pytesseract.image_to_string(
                    img_ocr,
                    config="--psm 7 -c tessedit_char_whitelist=0123456789.,nmuµμÅAcgromicantes ",
                )
            except Exception:
                continue
            if not text:
                continue
            parsed = _parse_text(text)
            if parsed:
                return parsed
    return None


def _parse_text(text: str) -> Optional[Tuple[float, str, str]]:
    """OCR 텍스트에서 '값 + 단위' 추출."""
    text_clean = text.replace(",", ".").strip()
    m = _UNIT_PATTERN.search(text_clean)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2)
    return value, unit, text_clean[:50]


def _unit_to_nm(unit: str) -> Optional[float]:
    u = unit.lower().replace("\u03bc", "u").replace("\u00b5", "u").strip()
    table = {
        "nm": 1.0,
        "um": 1000.0,
        "micron": 1000.0,
        "microns": 1000.0,
        "micrometer": 1000.0,
        "micrometers": 1000.0,
        "mm": 1_000_000.0,
        "cm": 10_000_000.0,
        "m": 1_000_000_000.0,
        "a": 0.1,
        "angstrom": 0.1,
        "angstroms": 0.1,
        "\u00e5": 0.1,
    }
    return table.get(u)
