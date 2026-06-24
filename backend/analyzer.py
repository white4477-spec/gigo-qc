"""
GIGO QC — 홀 검출 분석 파이프라인 (analyzer.py) — v1.2.0

향상된 Lacey Carbon Grid 홀 자동 검출·측정 모듈.
v1.2.0의 핵심 개선:
  - Sauvola adaptive thresholding (조명 불균일 강건)
  - Distance Transform + Watershed (붙어 있는 홀 분리)
  - Hough Circle 앙상블 (원형 홀 누락 보정)
  - 형태/텍스처 피처 기반 신뢰도 점수
  - Non-Maximum Suppression 후처리
  - 자동 파라미터 추정

각 처리 단계가 독립 함수로 분리되어 있어 SSE 스트리밍 진행에 활용됩니다.
"""

from __future__ import annotations

import base64
import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.filters import threshold_sauvola
from skimage.segmentation import watershed
from skimage.feature import peak_local_max


# ─── 0. 모드 정의 ──────────────────────────────────────────────────────────────

MODE_FAST = "fast"        # 기본 (Otsu 단일, v1.1과 호환)
MODE_BALANCED = "balanced"  # 권장 (Sauvola + Watershed)
MODE_PRECISE = "precise"  # 정밀 (Sauvola + Watershed + Hough 앙상블 + 신뢰도)


# ─── 1. 정규화 ─────────────────────────────────────────────────────────────────

def preprocess_normalize(img: np.ndarray) -> np.ndarray:
    """입력 이미지를 8-bit(0~255) uint8로 정규화합니다."""
    img_f = img.astype(np.float64)
    p1, p99 = np.percentile(img_f, (1, 99))
    if p99 <= p1:
        return np.zeros_like(img, dtype=np.uint8)
    img_clipped = np.clip(img_f, p1, p99)
    img_norm = (img_clipped - p1) / (p99 - p1) * 255.0
    return img_norm.astype(np.uint8)


# ─── 2. CLAHE 대비 향상 ───────────────────────────────────────────────────────

def preprocess_clahe(img_u8: np.ndarray) -> np.ndarray:
    """CLAHE로 국소 대비를 향상합니다."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(img_u8)


# ─── 3. 이진화 (Otsu / Sauvola) ───────────────────────────────────────────────

def preprocess_threshold(
    img_clahe: np.ndarray,
    method: str = "sauvola",
) -> np.ndarray:
    """
    이진화를 수행합니다. method에 따라 알고리즘 선택:
      - "otsu": 전역 Otsu (v1.1 호환, 빠름)
      - "sauvola": 국소 적응형 (조명 불균일에 강건, 권장)
    """
    img_blur = cv2.GaussianBlur(img_clahe, (5, 5), 0)

    if method == "sauvola":
        # 윈도우 크기는 이미지 크기에 비례 (홀 직경의 약 2~3배 권장)
        win_size = max(15, (min(img_clahe.shape) // 30) | 1)  # 홀수
        thresh = threshold_sauvola(img_blur, window_size=win_size, k=0.2)
        img_bin = (img_blur > thresh).astype(np.uint8) * 255
    else:
        _, img_bin = cv2.threshold(
            img_blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

    # 홀 극성 자동 감지: 밝은 영역(255)의 원본 평균 < 128이면 반전
    if np.any(img_bin == 255):
        white_mean = float(img_clahe[img_bin == 255].mean())
        dark_mean = float(img_clahe[img_bin == 0].mean()) if np.any(img_bin == 0) else 255.0
        # 홀은 일반적으로 carbon film보다 밝음 → 밝은 쪽이 홀
        # 단, white_mean이 dark_mean보다 작으면 반전
        if white_mean < dark_mean:
            img_bin = cv2.bitwise_not(img_bin)

    return img_bin


# ─── 4. Morphological 처리 ────────────────────────────────────────────────────

def preprocess_morph(img_bin: np.ndarray, aggressive: bool = False) -> np.ndarray:
    """타원형 커널로 Morphological Opening + Closing을 수행합니다."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    iters = 2 if not aggressive else 3
    img_clean = cv2.morphologyEx(img_bin, cv2.MORPH_OPEN, kernel, iterations=iters)
    img_clean = cv2.morphologyEx(img_clean, cv2.MORPH_CLOSE, kernel, iterations=1)
    return img_clean


def filter_components_by_size(
    img_clean: np.ndarray,
    min_area_frac: float = 0.15,
    max_area_frac: float = 5.0,
) -> np.ndarray:
    """
    Connected components 기반으로 너무 작거나 큰 조각들을 제거합니다.

    전략: 면적 분포의 상위 25 percentile 근처를 "진짜 홀" 대표 크기로 설정.
    이유: Sauvola 이진화 후 핀 더 속하면 노이즈(작은 텔스처)가
    다수이고 실제 홀은 소수이므로, median을 쓰면 노이즈 크기가 기준이 됨.
    상위 percentile을 기준으로 쓰면 진짜 홀 크기에 수렴함.

    - 기준_면적 = percentile_75(컴포넌트 면적, image의 30% 초과 제외)
    - 기준_면적 × min_area_frac 미만: 노이즈 → 제거
    - 기준_면적 × max_area_frac 초과: 외곽/배경 구조 → 제거
    """
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(img_clean, connectivity=8)
    if n_labels <= 2:
        return img_clean

    total_pixels = img_clean.shape[0] * img_clean.shape[1]
    areas = stats[1:, cv2.CC_STAT_AREA].astype(np.int64)
    if len(areas) == 0:
        return img_clean

    # 거대 컴포넌트(전체 30% 이상) 제외
    sane = areas[areas < total_pixels * 0.3]
    if len(sane) == 0:
        sane = areas

    # 상위 25 percentile (= 75th)을 "진짜 홀" 대표 크기로 사용
    # 이면 소수의 큰 홀과 다수의 작은 노이즈 상황에서도 안정→진짜 홀을 잡아냄
    ref_area = float(np.percentile(sane, 75))

    min_thresh = max(50, ref_area * min_area_frac)
    max_thresh = ref_area * max_area_frac

    output = np.zeros_like(img_clean)
    for i in range(1, n_labels):
        a = stats[i, cv2.CC_STAT_AREA]
        if min_thresh <= a <= max_thresh:
            output[labels == i] = 255
    return output


# ─── 5a. Watershed 기반 분리 ──────────────────────────────────────────────────

def segment_watershed(img_clean: np.ndarray) -> np.ndarray:
    """
    Distance Transform + Watershed로 붙어 있는 홀을 분리합니다.

    1) 거리 변환으로 각 홀의 중심 후보(local maxima) 찾기
    2) Marker 라벨링 후 Watershed로 영역 분할

    Returns
    -------
    labels : np.ndarray
        각 픽셀이 속한 홀의 라벨(int32). 0=배경, 1..N=각 홀
    """
    mask = (img_clean > 0).astype(np.uint8)
    if mask.sum() == 0:
        return np.zeros_like(img_clean, dtype=np.int32)

    # Distance Transform (각 픽셀에서 가장 가까운 배경까지의 거리)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)

    # 거리 맵의 local maxima → 각 홀의 중심 후보
    # min_distance는 일반적 홀 반지름에 비례 (과분할 방지)
    # 거리 맵의 75 percentile을 활용하면 이미지 특성에 더 잘 적응
    nonzero_dist = dist[dist > 0]
    if len(nonzero_dist) > 0:
        typical_radius = float(np.percentile(nonzero_dist, 75))
        # 2.0배: 인접한 홀이 거의 붙어 있을 때만 분리, 단일 홀의 과분할 방지
        min_dist = max(10, int(typical_radius * 2.0))
    else:
        min_dist = max(10, min(img_clean.shape) // 30)

    coords = peak_local_max(
        dist,
        min_distance=min_dist,
        threshold_abs=dist.max() * 0.6,  # 더 보수적: 중심 근처만
        labels=mask,
    )

    if len(coords) == 0:
        # local maxima 없으면 단순 connected components
        n_labels, labels = cv2.connectedComponents(mask, connectivity=8)
        return labels.astype(np.int32)

    # Marker 이미지 생성
    markers = np.zeros(dist.shape, dtype=np.int32)
    for i, (y, x) in enumerate(coords, start=1):
        markers[y, x] = i

    # Watershed: -distance 사용 (거리가 클수록 낮은 위치 = 영역 내부)
    labels = watershed(-dist, markers, mask=mask)
    return labels.astype(np.int32)


# ─── 5b. 라벨 → 컨투어 변환 ───────────────────────────────────────────────────

def labels_to_contours(labels: np.ndarray) -> List[np.ndarray]:
    """라벨 이미지를 cv2 컨투어 목록으로 변환합니다."""
    contours: List[np.ndarray] = []
    n_labels = int(labels.max())
    for label_id in range(1, n_labels + 1):
        region = (labels == label_id).astype(np.uint8) * 255
        cnts, _ = cv2.findContours(
            region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        # 가장 큰 컨투어 1개만 (라벨당 1개 영역 보장)
        if cnts:
            largest = max(cnts, key=cv2.contourArea)
            contours.append(largest)
    return contours


# ─── 5c. 기존 컨투어 검출 (FAST 모드) ─────────────────────────────────────────

def detect_contours(img_clean: np.ndarray) -> List[np.ndarray]:
    """RETR_EXTERNAL로 외부 컨투어만 검출합니다 (FAST 모드용)."""
    contours, _ = cv2.findContours(
        img_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    return list(contours)


# ─── 5d. Hough Circle 앙상블 ──────────────────────────────────────────────────

def detect_hough_circles(
    img_u8: np.ndarray,
    pixel_scale_nm: float,
    expected_d_um_range: Tuple[float, float] = (0.2, 5.0),
) -> List[Tuple[int, int, int]]:
    """
    Hough Circle Transform으로 원형 홀을 보조 검출합니다.

    Returns
    -------
    circles : list[(cx, cy, r)]
        원의 중심 픽셀 좌표와 반지름.
    """
    scale_nm_per_px = pixel_scale_nm
    if scale_nm_per_px <= 0:
        return []

    # µm → px 반지름 범위
    min_r_px = max(5, int(expected_d_um_range[0] * 1000.0 / scale_nm_per_px / 2))
    max_r_px = max(min_r_px + 5, int(expected_d_um_range[1] * 1000.0 / scale_nm_per_px / 2))

    img_blur = cv2.medianBlur(img_u8, 5)
    try:
        circles = cv2.HoughCircles(
            img_blur,
            cv2.HOUGH_GRADIENT,
            dp=1.5,
            minDist=max(min_r_px * 3, 20),  # 홀 간 임은 채택 방지
            param1=100,                       # Canny 임계값 상향
            param2=45,                        # 투표 임계값 상향 (허위 감소)
            minRadius=min_r_px,
            maxRadius=max_r_px,
        )
    except cv2.error:
        return []

    if circles is None:
        return []
    circles = np.round(circles[0]).astype(int)
    return [(int(c[0]), int(c[1]), int(c[2])) for c in circles]


# ─── 6. 홀 측정 + 신뢰도 점수 ─────────────────────────────────────────────────

def _compute_confidence(
    area_um2: float,
    circularity: float,
    aspect_ratio: float,
    solidity: float,
    extent: float,
) -> float:
    """
    형태 피처를 결합하여 0~1 신뢰도 점수를 산출합니다.
    Lacey 카본 홀은 원형/볼록/적당한 크기인 경향을 활용한 휴리스틱 분류기.
    (RandomForest 학습 데이터가 모이면 학습 모델로 교체 가능한 슬롯)
    """
    # 각 피처별 점수 (0~1)
    # 1) 원형도: 0.55 미만은 가파르게 감점
    s_circ = max(0.0, min(1.0, (circularity - 0.45) / 0.45))
    # 2) 종횡비: 1.0이 이상, 2.0 초과 시 감점
    s_ar = max(0.0, min(1.0, 1.0 - (aspect_ratio - 1.0) / 1.5))
    # 3) Solidity (convex hull 대비 면적 비): 0.85 이상이면 좋음
    s_sol = max(0.0, min(1.0, (solidity - 0.6) / 0.35))
    # 4) Extent (bounding box 대비 면적 비): 0.6~0.85가 원형의 자연 범위
    s_ext = 1.0 - min(1.0, abs(extent - 0.78) / 0.3)
    s_ext = max(0.0, s_ext)
    # 5) 면적 자체는 사후 필터링에서 처리

    # 가중 평균 (원형도와 solidity가 핵심)
    score = 0.35 * s_circ + 0.20 * s_ar + 0.30 * s_sol + 0.15 * s_ext
    return float(round(score, 4))


def measure_holes(
    contours: List[np.ndarray],
    pixel_scale_nm: float,
    min_area_px: int = 50,
    compute_confidence: bool = False,
    adaptive_min_area: bool = True,
) -> List[Dict[str, Any]]:
    """
    각 컨투어에서 홀의 물리적 파라미터와 (옵션) 신뢰도 점수를 계산합니다.

    adaptive_min_area=True면 전체 검출 면적 분포의 25 percentile을
    하한으로 반영해 작은 노이즈를 자동으로 제거합니다.
    """
    scale_um = pixel_scale_nm / 1000.0

    # 적응형 최소 면적 계산 (median 기반, 아주 작은 검출 제거)
    effective_min_area = min_area_px
    if adaptive_min_area and len(contours) >= 4:
        areas = np.array([cv2.contourArea(c) for c in contours])
        areas = areas[areas >= min_area_px]
        if len(areas) >= 4:
            # median의 1/5 또는 기본 min_area_px 중 큰 값
            med = float(np.median(areas))
            effective_min_area = max(min_area_px, int(med * 0.2))

    holes: List[Dict[str, Any]] = []
    hole_id = 1

    for cnt in contours:
        area_px = cv2.contourArea(cnt)
        if area_px < effective_min_area:
            continue

        perim_px = cv2.arcLength(cnt, closed=True)
        area_um2 = area_px * (scale_um ** 2)
        perim_um = perim_px * scale_um

        ecd_um = 2.0 * math.sqrt(area_um2 / math.pi) if area_um2 > 0 else 0.0

        if perim_um > 0:
            circ = min((4.0 * math.pi * area_um2) / (perim_um ** 2), 1.0)
        else:
            circ = 0.0

        if len(cnt) >= 5:
            try:
                ellipse = cv2.fitEllipse(cnt)
                axes = sorted(ellipse[1])
                ar = axes[1] / axes[0] if axes[0] > 0 else 1.0
            except cv2.error:
                ar = 1.0
        else:
            ar = 1.0

        # 중심
        M = cv2.moments(cnt)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            x, y, w, h = cv2.boundingRect(cnt)
            cx, cy = x + w // 2, y + h // 2

        # 추가 피처 (신뢰도용)
        hull = cv2.convexHull(cnt)
        hull_area = cv2.contourArea(hull)
        solidity = area_px / hull_area if hull_area > 0 else 0.0

        x, y, w, h = cv2.boundingRect(cnt)
        bbox_area = w * h
        extent = area_px / bbox_area if bbox_area > 0 else 0.0

        hole = {
            "id": hole_id,
            "area_um2": round(area_um2, 4),
            "diameter_um": round(ecd_um, 4),
            "circularity": round(circ, 4),
            "aspect_ratio": round(ar, 4),
            "solidity": round(float(solidity), 4),
            "extent": round(float(extent), 4),
            "cx_px": cx,
            "cy_px": cy,
        }
        if compute_confidence:
            hole["confidence"] = _compute_confidence(
                area_um2, circ, ar, solidity, extent
            )
        holes.append(hole)
        hole_id += 1

    return holes


# ─── 6b. NMS (Non-Maximum Suppression) ────────────────────────────────────────

def _nms_holes(
    holes: List[Dict[str, Any]],
    iou_threshold: float = 0.3,
) -> List[Dict[str, Any]]:
    """
    중심 거리 + 직경 기반 NMS로 중복된 홀 검출을 제거합니다.
    Hough 앙상블 후 사용.
    """
    if not holes:
        return holes
    # 신뢰도(없으면 원형도) 내림차순 정렬
    def score(h: Dict[str, Any]) -> float:
        return h.get("confidence", h.get("circularity", 0.0))

    sorted_holes = sorted(holes, key=score, reverse=True)
    kept: List[Dict[str, Any]] = []

    for h in sorted_holes:
        cx1, cy1 = h["cx_px"], h["cy_px"]
        # 직경 px 추정 (cv2 측정 기반)
        r1 = math.sqrt(h["area_um2"]) if h["area_um2"] > 0 else 0
        overlap = False
        for k in kept:
            cx2, cy2 = k["cx_px"], k["cy_px"]
            r2 = math.sqrt(k["area_um2"]) if k["area_um2"] > 0 else 0
            dist = math.hypot(cx1 - cx2, cy1 - cy2)
            # 중심간 거리 < (r1+r2)*0.5 픽셀 환산 ≈ 겹침
            # 실제 픽셀 좌표 기준이므로 직경 px로 다시 환산 필요 → 단순 임계값 사용
            min_dist_px = max(r1, r2) * 30  # 보수적
            if dist < min_dist_px * iou_threshold:
                overlap = True
                break
        if not overlap:
            kept.append(h)

    # id 재부여
    for i, h in enumerate(kept, 1):
        h["id"] = i
    return kept


# ─── 7. 통계 계산 ─────────────────────────────────────────────────────────────

def compute_stats(
    holes: List[Dict[str, Any]],
    img_shape: Tuple[int, int],
    pixel_scale_nm: float,
) -> Dict[str, Any]:
    """홀 목록으로부터 집계 통계를 계산합니다."""
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
            "avg_confidence": 0.0,
            "density_per_um2": 0.0,
            "coverage_pct": 0.0,
        }

    diameters = np.array([h["diameter_um"] for h in holes], dtype=np.float64)
    circularities = np.array([h["circularity"] for h in holes], dtype=np.float64)
    confidences = np.array(
        [h.get("confidence", 1.0) for h in holes], dtype=np.float64
    )
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
        "avg_confidence": round(float(np.mean(confidences)), 4),
        "density_per_um2": round(len(holes) / total_area_um2, 6) if total_area_um2 > 0 else 0.0,
        "coverage_pct": round(hole_area_sum / total_area_um2 * 100.0, 3) if total_area_um2 > 0 else 0.0,
    }


# ─── 8. 오버레이 프리뷰 생성 ──────────────────────────────────────────────────

def generate_overlay_preview(
    img_u8: np.ndarray,
    holes: List[Dict[str, Any]],
    contours: List[np.ndarray],
    qc_checks: Optional[Dict[str, bool]] = None,
    use_confidence_color: bool = False,
) -> str:
    """
    원본 이미지에 검출된 홀 윤곽과 번호를 오버레이하여 base64 PNG로 반환합니다.

    use_confidence_color=True이면 홀별 신뢰도에 따라 색상 그라데이션 적용:
      - 신뢰도 ≥ 0.7: 청록 (높음)
      - 0.4 ≤ 신뢰도 < 0.7: 노랑 (보통)
      - 신뢰도 < 0.4: 주황 (낮음)
    """
    overlay = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2BGR)

    passed = True
    if qc_checks:
        passed = all(qc_checks.values())

    teal_bgr   = (191, 212, 45)   # BGR: #2DD4BF
    red_bgr    = (113, 113, 248)  # BGR: #F87171
    yellow_bgr = (47, 188, 250)   # BGR: #FABC2F
    orange_bgr = (47, 130, 250)   # BGR: #FA822F
    default_color = teal_bgr if passed else red_bgr

    # contours와 holes 매핑: holes의 cx_px, cy_px가 contour의 중심
    # contours가 watershed에서 온 경우 holes와 1:1 (필터 후 제외분 차이 있음)
    valid_cnts: List[Tuple[np.ndarray, Dict[str, Any]]] = []
    for cnt in contours:
        if cv2.contourArea(cnt) < 50:
            continue
        # 가장 가까운 hole 찾기
        M = cv2.moments(cnt)
        if M["m00"] > 0:
            ccx = int(M["m10"] / M["m00"])
            ccy = int(M["m01"] / M["m00"])
        else:
            x, y, w, h = cv2.boundingRect(cnt)
            ccx, ccy = x + w // 2, y + h // 2
        # 최근접 hole
        best = None
        best_d = 1e9
        for h in holes:
            d = (h["cx_px"] - ccx) ** 2 + (h["cy_px"] - ccy) ** 2
            if d < best_d:
                best_d = d
                best = h
        if best is not None:
            valid_cnts.append((cnt, best))

    # 컨투어 그리기
    for cnt, hole in valid_cnts:
        if use_confidence_color and "confidence" in hole:
            conf = hole["confidence"]
            if conf >= 0.7:
                c = teal_bgr
            elif conf >= 0.4:
                c = yellow_bgr
            else:
                c = orange_bgr
        else:
            c = default_color
        cv2.drawContours(overlay, [cnt], -1, c, 2)

    # 홀 번호 텍스트
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.35, min(0.6, overlay.shape[0] / 1200.0))
    for hole in holes:
        cx, cy = hole["cx_px"], hole["cy_px"]
        label = str(hole["id"])
        cv2.putText(
            overlay, label, (cx - 4, cy + 4),
            font, font_scale, default_color, 1, cv2.LINE_AA
        )

    _, buf = cv2.imencode(".png", overlay)
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ─── 9. 전체 파이프라인 ───────────────────────────────────────────────────────

def analyze(
    img_array: np.ndarray,
    pixel_scale_nm: float,
    mode: str = MODE_BALANCED,
    min_confidence: float = 0.0,
) -> Dict[str, Any]:
    """
    전체 홀 검출 파이프라인을 실행합니다.

    Parameters
    ----------
    img_array : np.ndarray
        2D grayscale array (임의 dtype)
    pixel_scale_nm : float
        nm/pixel 스케일 값
    mode : str
        "fast" | "balanced" | "precise"
    min_confidence : float
        precise 모드에서 신뢰도 임계값 (0.0 = 비활성)

    Returns
    -------
    result : dict
        holes, stats, preview_b64, mode 포함
    """
    if pixel_scale_nm <= 0:
        raise ValueError(
            f"픽셀 스케일 값이 유효하지 않습니다: {pixel_scale_nm} nm/px\n"
            "양수 값을 입력해 주세요."
        )

    # 1~2: 정규화 + CLAHE
    img_norm = preprocess_normalize(img_array)
    img_clahe = preprocess_clahe(img_norm)

    # 3: 이진화 (모드에 따라 알고리즘 선택)
    thresh_method = "otsu" if mode == MODE_FAST else "sauvola"
    img_bin = preprocess_threshold(img_clahe, method=thresh_method)

    # 4: 모폴로지
    img_clean = preprocess_morph(img_bin, aggressive=(thresh_method == "sauvola"))

    # 4b: Sauvola 이진화 사용 시 작은 컴포넌트 제거 (carbon film 텔스처)
    if thresh_method == "sauvola":
        img_clean = filter_components_by_size(img_clean, min_area_frac=0.15)

    # 5: 분할 (모드에 따라)
    if mode == MODE_FAST:
        contours = detect_contours(img_clean)
    else:
        labels = segment_watershed(img_clean)
        contours = labels_to_contours(labels)

    # 6: 측정 + (precise면) 신뢰도 점수
    compute_conf = (mode == MODE_PRECISE)
    holes = measure_holes(
        contours,
        pixel_scale_nm,
        compute_confidence=compute_conf,
    )

    # 7: Precise 모드 — Hough 앙상블 + NMS + 신뢰도 필터
    if mode == MODE_PRECISE:
        # 직경 통계로 Hough 검색 범위 추정
        if holes:
            diameters = np.array([h["diameter_um"] for h in holes])
            d_range = (
                max(0.1, float(np.percentile(diameters, 10)) * 0.5),
                float(np.percentile(diameters, 90)) * 1.5,
            )
        else:
            d_range = (0.2, 5.0)

        hough_circles = detect_hough_circles(img_norm, pixel_scale_nm, d_range)
        # Hough에서 검출된 원 중 기존 holes에 없는 것만 추가
        scale_um = pixel_scale_nm / 1000.0
        existing_centers = [(h["cx_px"], h["cy_px"]) for h in holes]
        next_id = (max([h["id"] for h in holes]) + 1) if holes else 1
        for cx, cy, r in hough_circles:
            # 중심 거리 체크 (보다 보수적)
            too_close = any(
                math.hypot(cx - ex, cy - ey) < r * 1.5
                for ex, ey in existing_centers
            )
            if too_close:
                continue
            # 가상 측정값 (정확도 떨어지므로 신뢰도 낮음)
            area_um2 = math.pi * (r * scale_um) ** 2
            new_hole = {
                "id": next_id,
                "area_um2": round(area_um2, 4),
                "diameter_um": round(2 * r * scale_um, 4),
                "circularity": 0.95,  # Hough는 원형 가정
                "aspect_ratio": 1.0,
                "solidity": 0.95,
                "extent": 0.78,
                "cx_px": cx,
                "cy_px": cy,
                "confidence": 0.6,  # Hough 단독 검출은 보통 수준 신뢰도
                "source": "hough",
            }
            holes.append(new_hole)
            existing_centers.append((cx, cy))
            next_id += 1

        # NMS로 중복 제거
        holes = _nms_holes(holes)

        # 신뢰도 필터
        if min_confidence > 0:
            holes = [h for h in holes if h.get("confidence", 1.0) >= min_confidence]
            # id 재부여
            for i, h in enumerate(holes, 1):
                h["id"] = i

    # 8: 통계
    stats = compute_stats(holes, img_array.shape[:2], pixel_scale_nm)

    # 9: 프리뷰
    use_conf_color = (mode == MODE_PRECISE)
    preview_b64 = generate_overlay_preview(
        img_norm, holes, contours, use_confidence_color=use_conf_color
    )

    return {
        "holes": holes,
        "stats": stats,
        "preview_b64": preview_b64,
        "mode": mode,
    }
