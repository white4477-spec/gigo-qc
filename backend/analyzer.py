"""
GIGO QC — 홀 검출 분석 파이프라인 (analyzer.py)

OpenCV 기반 Lacey Carbon Grid 홀 자동 검출·측정 모듈.
각 처리 단계가 독립 함수로 분리되어 있어 SSE 스트리밍 진행에 활용됩니다.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


# ─── 1. 정규화 ─────────────────────────────────────────────────────────────────

def preprocess_normalize(img: np.ndarray) -> np.ndarray:
    """
    입력 이미지를 8-bit(0~255) uint8로 정규화합니다.

    16-bit, float 등 다양한 입력을 지원하며
    percentile(1%, 99%) 클리핑으로 극단값에 강건합니다.

    Parameters
    ----------
    img : np.ndarray
        2D float/int array (임의 dtype)

    Returns
    -------
    img_u8 : np.ndarray
        2D uint8 array (0~255)
    """
    img_f = img.astype(np.float64)

    # 극단값 클리핑 (outlier 픽셀 제거)
    p1, p99 = np.percentile(img_f, (1, 99))
    if p99 <= p1:
        # 균일한 이미지 처리
        return np.zeros_like(img, dtype=np.uint8)

    img_clipped = np.clip(img_f, p1, p99)
    img_norm = (img_clipped - p1) / (p99 - p1) * 255.0
    return img_norm.astype(np.uint8)


# ─── 2. CLAHE 대비 향상 ───────────────────────────────────────────────────────

def preprocess_clahe(img_u8: np.ndarray) -> np.ndarray:
    """
    CLAHE(Contrast Limited Adaptive Histogram Equalization)로 국소 대비를 향상합니다.

    TEM 이미지의 불균일한 조명을 보정하는 데 효과적입니다.

    Parameters
    ----------
    img_u8 : np.ndarray
        2D uint8 array

    Returns
    -------
    img_clahe : np.ndarray
        2D uint8 array (대비 향상됨)
    """
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(img_u8)


# ─── 3. Otsu 이진화 ───────────────────────────────────────────────────────────

def preprocess_threshold(img_clahe: np.ndarray) -> np.ndarray:
    """
    Gaussian blur 후 Otsu's 방법으로 이진화합니다.
    홀이 밝은지 어두운지 자동으로 판단하여 적절히 반전합니다.

    Lacey carbon grid에서 홀(hole)은 배경(carbon film)보다
    전자 밀도가 낮아 TEM 이미지에서 밝게 보이는 경향이 있습니다.
    하지만 이미지 설정에 따라 반전될 수 있으므로 자동 감지합니다.

    Parameters
    ----------
    img_clahe : np.ndarray
        2D uint8 array (CLAHE 처리됨)

    Returns
    -------
    img_bin : np.ndarray
        2D uint8 이진 array (홀=255, 배경=0)
    """
    # Gaussian blur로 노이즈 제거
    img_blur = cv2.GaussianBlur(img_clahe, (5, 5), 0)

    # Otsu's thresholding
    _, img_bin = cv2.threshold(
        img_blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    # 홀이 밝은 영역(255)의 평균 원본 밝기가 128 미만이면
    # 실제로는 어두운 영역이 홀 → 반전
    white_region_mean = img_clahe[img_bin == 255].mean() if np.any(img_bin == 255) else 0
    if white_region_mean < 128:
        img_bin = cv2.bitwise_not(img_bin)

    return img_bin


# ─── 4. Morphological 처리 ────────────────────────────────────────────────────

def preprocess_morph(img_bin: np.ndarray) -> np.ndarray:
    """
    타원형 커널로 Morphological Opening을 수행합니다.

    Opening = Erosion → Dilation:
    - 작은 노이즈 제거
    - 홀 경계 매끄럽게 보정
    - 인접한 홀 분리

    Parameters
    ----------
    img_bin : np.ndarray
        2D uint8 이진 array

    Returns
    -------
    img_clean : np.ndarray
        2D uint8 이진 array (모폴로지 처리됨)
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    img_clean = cv2.morphologyEx(
        img_bin, cv2.MORPH_OPEN, kernel, iterations=2
    )
    return img_clean


# ─── 5. 컨투어 검출 ───────────────────────────────────────────────────────────

def detect_contours(img_clean: np.ndarray) -> List[np.ndarray]:
    """
    이진 이미지에서 홀의 외부 컨투어를 검출합니다.

    RETR_EXTERNAL: 가장 바깥쪽 컨투어만 검출 (중첩 홀 제외)
    CHAIN_APPROX_SIMPLE: 직선 구간 압축으로 메모리 효율화

    Parameters
    ----------
    img_clean : np.ndarray
        2D uint8 이진 array (모폴로지 처리됨)

    Returns
    -------
    contours : list[np.ndarray]
        검출된 컨투어 목록
    """
    contours, _ = cv2.findContours(
        img_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    return list(contours)


# ─── 6. 홀 측정 ───────────────────────────────────────────────────────────────

def measure_holes(
    contours: List[np.ndarray],
    pixel_scale_nm: float,
) -> List[Dict[str, Any]]:
    """
    각 컨투어에서 홀의 물리적 파라미터를 계산합니다.

    Parameters
    ----------
    contours : list[np.ndarray]
        detect_contours()에서 반환된 컨투어 목록
    pixel_scale_nm : float
        nm/pixel 스케일 값

    Returns
    -------
    holes : list[dict]
        각 홀의 측정값 dict 목록.
        필드: id, area_um2, diameter_um, circularity, aspect_ratio, cx_px, cy_px
    """
    scale_um = pixel_scale_nm / 1000.0  # nm → µm
    holes: List[Dict[str, Any]] = []
    hole_id = 1

    for cnt in contours:
        area_px = cv2.contourArea(cnt)

        # 노이즈 필터: 너무 작은 영역 제외 (50 px²)
        if area_px < 50:
            continue

        perim_px = cv2.arcLength(cnt, closed=True)
        area_um2 = area_px * (scale_um ** 2)
        perim_um = perim_px * scale_um

        # 등가원 직경 (Equivalent Circle Diameter)
        ecd_um = 2.0 * math.sqrt(area_um2 / math.pi) if area_um2 > 0 else 0.0

        # 원형도 (4π·A / P²), 최대값 1.0으로 클리핑
        if perim_um > 0:
            circ = min((4.0 * math.pi * area_um2) / (perim_um ** 2), 1.0)
        else:
            circ = 0.0

        # 종횡비 (fitEllipse는 5점 이상 필요)
        if len(cnt) >= 5:
            try:
                ellipse = cv2.fitEllipse(cnt)
                axes = sorted(ellipse[1])  # (minor, major)
                ar = axes[1] / axes[0] if axes[0] > 0 else 1.0
            except cv2.error:
                ar = 1.0
        else:
            ar = 1.0

        # 중심 좌표 (moments 기반)
        M = cv2.moments(cnt)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            x, y, w, h = cv2.boundingRect(cnt)
            cx, cy = x + w // 2, y + h // 2

        holes.append({
            "id": hole_id,
            "area_um2": round(area_um2, 4),
            "diameter_um": round(ecd_um, 4),
            "circularity": round(circ, 4),
            "aspect_ratio": round(ar, 4),
            "cx_px": cx,
            "cy_px": cy,
        })
        hole_id += 1

    return holes


# ─── 7. 통계 계산 ─────────────────────────────────────────────────────────────

def compute_stats(
    holes: List[Dict[str, Any]],
    img_shape: Tuple[int, int],
    pixel_scale_nm: float,
) -> Dict[str, Any]:
    """
    홀 목록으로부터 집계 통계를 계산합니다.

    Parameters
    ----------
    holes : list[dict]
        measure_holes()의 반환값
    img_shape : tuple[int, int]
        이미지 크기 (height, width) in pixels
    pixel_scale_nm : float
        nm/pixel 스케일 값

    Returns
    -------
    stats : dict
        total_holes, avg_diameter, std_diameter, median_diameter,
        min_diameter, max_diameter, avg_circularity, std_circularity,
        density_per_um2, coverage_pct
    """
    scale_um = pixel_scale_nm / 1000.0
    total_area_um2 = img_shape[0] * img_shape[1] * (scale_um ** 2)

    if not holes:
        return {
            "total_holes": 0,
            "avg_diameter": 0.0,
            "std_diameter": 0.0,
            "median_diameter": 0.0,
            "min_diameter": 0.0,
            "max_diameter": 0.0,
            "avg_circularity": 0.0,
            "std_circularity": 0.0,
            "density_per_um2": 0.0,
            "coverage_pct": 0.0,
        }

    diameters = np.array([h["diameter_um"] for h in holes], dtype=np.float64)
    circularities = np.array([h["circularity"] for h in holes], dtype=np.float64)
    hole_area_sum = sum(h["area_um2"] for h in holes)

    return {
        "total_holes": len(holes),
        "avg_diameter": round(float(np.mean(diameters)), 4),
        "std_diameter": round(float(np.std(diameters)), 4),
        "median_diameter": round(float(np.median(diameters)), 4),
        "min_diameter": round(float(np.min(diameters)), 4),
        "max_diameter": round(float(np.max(diameters)), 4),
        "avg_circularity": round(float(np.mean(circularities)), 4),
        "std_circularity": round(float(np.std(circularities)), 4),
        "density_per_um2": round(len(holes) / total_area_um2, 6) if total_area_um2 > 0 else 0.0,
        "coverage_pct": round(hole_area_sum / total_area_um2 * 100.0, 3) if total_area_um2 > 0 else 0.0,
    }


# ─── 8. 오버레이 프리뷰 생성 ──────────────────────────────────────────────────

def generate_overlay_preview(
    img_u8: np.ndarray,
    holes: List[Dict[str, Any]],
    contours: List[np.ndarray],
    qc_checks: Optional[Dict[str, bool]] = None,
) -> str:
    """
    원본 8-bit 이미지에 검출된 홀의 윤곽선과 번호를 오버레이하여
    base64 PNG 문자열로 반환합니다.

    색상 코드:
    - 청록색 (#2DD4BF): QC 통과 또는 판정 없음
    - 빨간색 (#F87171): QC 실패 (해당 없음 — 홀 단위 판정은 미지원)

    Parameters
    ----------
    img_u8 : np.ndarray
        2D uint8 grayscale 이미지
    holes : list[dict]
        measure_holes()의 반환값
    contours : list[np.ndarray]
        detect_contours()의 반환값 (holes와 인덱스 일치)
    qc_checks : dict | None
        QC 판정 결과 (있으면 pass=teal, fail=red)

    Returns
    -------
    base64_png : str
        PNG 이미지의 base64 인코딩 문자열 (data URI prefix 없음)
    """
    # grayscale → BGR for OpenCV drawing
    overlay = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2BGR)

    # 전체 QC 통과 여부로 색상 결정
    passed = True
    if qc_checks:
        passed = all(qc_checks.values())

    teal_bgr = (191, 212, 45)   # BGR: #2DD4BF
    red_bgr  = (113, 113, 248)  # BGR: #F87171
    color = teal_bgr if passed else red_bgr

    # holes와 contours 인덱스 매핑
    # measure_holes에서 area<50 필터로 일부 컨투어가 제외되므로
    # 실제 holes 수 ≤ contours 수
    # holes[i]의 cx_px, cy_px를 사용해 텍스트 위치 지정

    # 전체 컨투어 중 홀에 해당하는 것만 추출
    valid_cnts = [c for c in contours if cv2.contourArea(c) >= 50]

    # 컨투어 그리기
    cv2.drawContours(overlay, valid_cnts, -1, color, 2)

    # 홀 번호 텍스트
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.35, min(0.6, overlay.shape[0] / 1200.0))
    for hole in holes:
        cx, cy = hole["cx_px"], hole["cy_px"]
        label = str(hole["id"])
        cv2.putText(
            overlay, label, (cx - 4, cy + 4),
            font, font_scale, color, 1, cv2.LINE_AA
        )

    # PNG 인코딩 → base64
    _, buf = cv2.imencode(".png", overlay)
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ─── 9. 전체 파이프라인 (동기) ────────────────────────────────────────────────

def analyze(
    img_array: np.ndarray,
    pixel_scale_nm: float,
) -> Dict[str, Any]:
    """
    전체 홀 검출 파이프라인을 실행합니다.

    이 함수는 동기 함수입니다. FastAPI SSE 엔드포인트에서는
    각 단계 함수를 직접 호출하여 단계별 이벤트를 yield하십시오.

    Parameters
    ----------
    img_array : np.ndarray
        2D float32 grayscale array
    pixel_scale_nm : float
        nm/pixel 스케일 값

    Returns
    -------
    result : dict
        holes, stats, preview_b64 (base64 PNG) 포함
    """
    if pixel_scale_nm <= 0:
        raise ValueError(
            f"픽셀 스케일 값이 유효하지 않습니다: {pixel_scale_nm} nm/px\n"
            "양수 값을 입력해 주세요."
        )

    # 파이프라인 실행
    img_norm   = preprocess_normalize(img_array)
    img_clahe  = preprocess_clahe(img_norm)
    img_bin    = preprocess_threshold(img_clahe)
    img_clean  = preprocess_morph(img_bin)
    contours   = detect_contours(img_clean)
    holes      = measure_holes(contours, pixel_scale_nm)
    stats      = compute_stats(holes, img_array.shape[:2], pixel_scale_nm)
    preview_b64 = generate_overlay_preview(img_norm, holes, contours)

    return {
        "holes": holes,
        "stats": stats,
        "preview_b64": preview_b64,
    }
