"""
GIGO QC — End-to-End 파이프라인 검증 스크립트

512×512 이미지에 인공 원형 홀 20개를 그려서 TIFF로 저장하고,
전체 파이프라인을 실행하여 결과가 합리적인지 확인합니다.

실행:
  cd /home/user/workspace/gigo-qc
  python test_pipeline.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time

# 백엔드 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import numpy as np


# ─── 1. 합성 테스트 이미지 생성 ───────────────────────────────────────────────

def create_synthetic_image(
    size: int = 512,
    n_holes: int = 20,
    seed: int = 42,
) -> np.ndarray:
    """
    배경이 어두운 이미지에 밝은 원형 홀 n_holes개를 그린 합성 이미지를 생성합니다.

    Parameters
    ----------
    size : int
        이미지 크기 (size × size)
    n_holes : int
        홀 개수
    seed : int
        난수 시드

    Returns
    -------
    img : np.ndarray
        uint8 2D grayscale 이미지
    """
    rng = np.random.default_rng(seed)

    # 어두운 배경 (탄소막 = 중간 회색)
    img = np.full((size, size), 80, dtype=np.uint8)
    # 약간의 텍스처 노이즈 추가
    noise = rng.integers(-15, 15, size=(size, size), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    holes_drawn = []
    attempts = 0
    max_attempts = n_holes * 30

    while len(holes_drawn) < n_holes and attempts < max_attempts:
        attempts += 1
        # 홀 반경: 10~35 px (pixel_scale=1nm/px → 직경 20~70 nm, 하지만 scale=5nm/px로 테스트)
        r = int(rng.integers(10, 36))
        cx = int(rng.integers(r + 5, size - r - 5))
        cy = int(rng.integers(r + 5, size - r - 5))

        # 기존 홀과 겹치지 않는지 확인
        overlap = False
        for (px, py, pr) in holes_drawn:
            dist = np.sqrt((cx - px) ** 2 + (cy - py) ** 2)
            if dist < r + pr + 8:
                overlap = True
                break

        if overlap:
            continue

        # 원형 홀 그리기 (밝게)
        yy, xx = np.ogrid[:size, :size]
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2
        brightness = int(rng.integers(200, 245))
        img[mask] = brightness

        # 홀 경계에 약간의 그라데이션 효과
        ring_mask = (
            ((xx - cx) ** 2 + (yy - cy) ** 2 <= (r + 2) ** 2) &
            ((xx - cx) ** 2 + (yy - cy) ** 2 > r ** 2)
        )
        img[ring_mask] = np.clip(img[ring_mask].astype(int) + 20, 0, 255).astype(np.uint8)

        holes_drawn.append((cx, cy, r))

    print(f"  합성 이미지 생성: {len(holes_drawn)}개 홀, {size}×{size} px")
    return img


# ─── 2. TIFF 파일로 저장 ──────────────────────────────────────────────────────

def save_as_tiff(img: np.ndarray, path: str) -> None:
    """numpy array를 TIFF로 저장합니다."""
    try:
        import tifffile
        tifffile.imwrite(path, img)
    except ImportError:
        from PIL import Image
        Image.fromarray(img).save(path)


# ─── 3. 파이프라인 실행 ───────────────────────────────────────────────────────

def run_pipeline(tiff_path: str, pixel_scale_nm: float = 5.0) -> dict:
    """
    전체 GIGO QC 파이프라인을 실행하고 결과를 반환합니다.

    Steps:
      1. parse_file    — TIFF 파싱
      2. preprocess_*  — 전처리 단계
      3. detect_contours → measure_holes → compute_stats
      4. classify      — Grid Suitability 분류
      5. evaluate      — QC PASS/FAIL/WARNING 판정
    """
    from parsers import parse_file
    import analyzer as az
    from classifier import classify
    from qc_evaluator import evaluate

    # 1. 파일 파싱
    t0 = time.perf_counter()
    with open(tiff_path, "rb") as f:
        file_bytes = f.read()

    img_array, detected_scale = parse_file(file_bytes, os.path.basename(tiff_path))
    t_parse = time.perf_counter() - t0
    print(f"  [1/7] 파일 파싱:         {t_parse:.3f}s  shape={img_array.shape}  detected_scale={detected_scale}")

    effective_scale = detected_scale if detected_scale else pixel_scale_nm

    # 2. 전처리
    img_norm  = az.preprocess_normalize(img_array)
    t_norm = time.perf_counter() - t0 - t_parse
    print(f"  [2/7] 정규화:            완료  min={img_norm.min()}  max={img_norm.max()}")

    img_clahe = az.preprocess_clahe(img_norm)
    print(f"  [3/7] CLAHE:             완료")

    img_bin   = az.preprocess_threshold(img_clahe)
    white_pct = (img_bin == 255).sum() / img_bin.size * 100
    print(f"  [4/7] Otsu 이진화:       완료  white={white_pct:.1f}%")

    img_clean = az.preprocess_morph(img_bin)
    print(f"  [5/7] Morphological:     완료")

    # 3. 컨투어 검출 → 측정 → 통계
    contours = az.detect_contours(img_clean)
    print(f"  [6/7] 컨투어 검출:       {len(contours)}개 컨투어 (필터링 전)")

    holes = az.measure_holes(contours, effective_scale)
    stats = az.compute_stats(holes, img_array.shape[:2], effective_scale)
    t_measure = time.perf_counter() - t0
    print(f"  [7/7] 측정 완료:         {stats['total_holes']}개 홀  {t_measure:.3f}s 경과")

    # 4. 분류
    classification = classify(stats)

    # 5. QC 판정
    qc_result = evaluate(
        stats,
        grid_type_hint="auto",
        classifier_best_match=classification.get("best_match"),
    )

    return {
        "holes": holes,
        "stats": stats,
        "classification": classification,
        "qc_result": qc_result,
        "pixel_scale_nm": effective_scale,
    }


# ─── 4. 결과 출력 ─────────────────────────────────────────────────────────────

def print_results(result: dict) -> None:
    stats          = result["stats"]
    classification = result["classification"]
    qc_result      = result["qc_result"]
    pixel_scale_nm = result["pixel_scale_nm"]

    print()
    print("=" * 60)
    print("  GIGO QC — 파이프라인 검증 결과")
    print("=" * 60)
    print(f"  픽셀 스케일:      {pixel_scale_nm} nm/px")
    print()

    print("  [통계]")
    print(f"  총 홀 수:         {stats['total_holes']}")
    print(f"  평균 직경:        {stats['avg_diameter']:.3f} μm")
    print(f"  표준편차:         {stats['std_diameter']:.3f} μm")
    print(f"  중앙값:           {stats['median_diameter']:.3f} μm")
    print(f"  최소/최대:        {stats['min_diameter']:.3f} / {stats['max_diameter']:.3f} μm")
    print(f"  평균 원형도:      {stats['avg_circularity']:.3f}")
    print(f"  홀 밀도:          {stats['density_per_um2']:.4f} holes/μm²")
    print(f"  홀 커버리지:      {stats['coverage_pct']:.2f}%")
    print()

    print("  [Grid Suitability 분류]")
    print(f"  Best Match:       {classification['best_match'] or '없음'}")
    print(f"  적합 타입:        {classification['all_suitable'] or ['없음']}")
    if classification["reasons"]:
        print("  부적합 이유:")
        for r in classification["reasons"]:
            print(f"    - {r}")
    print(f"  커버리지 OK:      {classification['coverage_ok']}")
    print()

    print("  [QC 판정]")
    print(f"  판정:             {qc_result['verdict']}")
    print(f"  QC 점수:          {qc_result['qc_score']:.2f} (0~1)")
    print(f"  적용 기준:        {qc_result['grid_type_used']}")
    print("  체크 항목:")
    for key, passed in qc_result["qc_checks"].items():
        mark = "✓" if passed else "✗"
        print(f"    {mark}  {key}")
    if qc_result["fail_messages"]:
        print("  실패 이유:")
        for msg in qc_result["fail_messages"]:
            print(f"    - {msg}")
    print()

    # 검증 기준 확인
    n = stats["total_holes"]
    if 15 <= n <= 25:
        print(f"  ✅ 홀 수 검증 통과: {n}개 (기대 범위 15~25)")
    else:
        print(f"  ⚠  홀 수 {n}개 (기대 범위 15~25 — 검출 알고리즘 확인 필요)")

    print("=" * 60)


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    print()
    print("GIGO QC — End-to-End 파이프라인 테스트 시작")
    print()

    # 합성 이미지 생성
    print("[이미지 생성]")
    img = create_synthetic_image(size=512, n_holes=20, seed=42)

    # TIFF 저장
    with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as tmp:
        tiff_path = tmp.name
    save_as_tiff(img, tiff_path)
    file_size_kb = os.path.getsize(tiff_path) / 1024
    print(f"  TIFF 저장: {tiff_path} ({file_size_kb:.1f} KB)")

    try:
        print()
        print("[파이프라인 실행]  (pixel_scale = 5.0 nm/px)")
        # pixel_scale=5nm/px → 홀 반경 10~35px → 직경 100~350nm → 0.1~0.35μm
        # Type C (0.2~2.0μm) 또는 Type A (0.5~5.0μm) 범위에 해당
        result = run_pipeline(tiff_path, pixel_scale_nm=5.0)
        print_results(result)

        print()
        print("[추가 테스트]  pixel_scale = 50 nm/px (더 큰 홀)")
        result2 = run_pipeline(tiff_path, pixel_scale_nm=50.0)
        stats2 = result2["stats"]
        cls2   = result2["classification"]
        qc2    = result2["qc_result"]
        print(f"  홀 수={stats2['total_holes']}, 평균 직경={stats2['avg_diameter']:.2f} μm, "
              f"best_match={cls2['best_match']}, verdict={qc2['verdict']}")

    finally:
        os.unlink(tiff_path)

    print()
    print("테스트 완료!")


if __name__ == "__main__":
    main()
