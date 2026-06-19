"""
GIGO QC — Grid Suitability 자동 분류 (classifier.py)

측정 결과로부터 어떤 실험 목적에 이 그리드가 적합한지
역방향으로 자동 분류합니다. 사전에 타입을 지정하는 게 아니라
분석 후 리포트에서 표기합니다.

Grid Profile 4종 (PRD 섹션 3-4 기준):
  Type A — Membrane Protein:   직경 0.5~5.0 µm, 원형도 ≥ 0.60
  Type B — Protein Complex:    직경 1.0~10.0 µm, 원형도 ≥ 0.50
  Type C — Nanomaterial/Virus: 직경 0.2~2.0 µm, 원형도 ≥ 0.55
  Type D — Large Specimen:     직경 5.0~30.0 µm, 원형도 ≥ 0.40
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# PRD 3-4에서 제공된 GRID_PROFILES (그대로 사용)
GRID_PROFILES: Dict[str, Dict[str, Any]] = {
    "Type A — Membrane Protein": {
        "diam_range": (0.5, 5.0),
        "min_circ": 0.60,
        "desc": "단백질 막 복합체, 소형 단백질 (<300 kDa)",
        "short": "A",
    },
    "Type B — Protein Complex": {
        "diam_range": (1.0, 10.0),
        "min_circ": 0.50,
        "desc": "대형 단백질 복합체 (>300 kDa), 리보솜, 바이러스 캡시드",
        "short": "B",
    },
    "Type C — Nanomaterial / Virus": {
        "diam_range": (0.2, 2.0),
        "min_circ": 0.55,
        "desc": "나노입자, 소형 바이러스, 무기 나노소재",
        "short": "C",
    },
    "Type D — Large Specimen": {
        "diam_range": (5.0, 30.0),
        "min_circ": 0.40,
        "desc": "세포 소기관, 대형 어셈블리, 박테리아",
        "short": "D",
    },
}


def classify(stats: Dict[str, Any]) -> Dict[str, Any]:
    """
    홀 측정 통계를 입력받아 Grid Suitability를 역방향 분류합니다.

    Parameters
    ----------
    stats : dict
        compute_stats()의 반환값.
        필수 키: avg_diameter, avg_circularity, coverage_pct, density_per_um2

    Returns
    -------
    result : dict
        best_match : str | None
            가장 적합한 그리드 타입 이름
        all_suitable : list[str]
            적합한 그리드 타입 목록 (점수 내림차순)
        unsuitable_for : list[str]
            부적합한 그리드 타입 목록
        scores : dict[str, float]
            각 타입별 점수
        reasons : list[str]
            부적합 이유 (한국어)
        coverage_ok : bool
            커버리지가 허용 범위(5~60%)인지 여부
        recommendation : str
            최종 추천 텍스트 (한국어)
    """
    avg_diam = stats.get("avg_diameter", 0.0)
    avg_circ = stats.get("avg_circularity", 0.0)
    coverage = stats.get("coverage_pct", 0.0)
    density  = stats.get("density_per_um2", 0.0)

    suitable: List[str] = []
    scores: Dict[str, float] = {}

    for name, spec in GRID_PROFILES.items():
        dmin, dmax = spec["diam_range"]
        in_range = dmin <= avg_diam <= dmax
        circ_ok  = avg_circ >= spec["min_circ"]

        if in_range and circ_ok:
            # 점수: 직경이 범위 중앙에 가까울수록 + 원형도가 기준보다 높을수록
            mid = (dmin + dmax) / 2.0
            diam_range_span = dmax - dmin
            score = 100.0 - abs(avg_diam - mid) / diam_range_span * 50.0
            score += (avg_circ - spec["min_circ"]) * 30.0
            scores[name] = round(score, 2)
            suitable.append(name)

    # 점수 내림차순 정렬
    suitable.sort(key=lambda x: scores.get(x, 0.0), reverse=True)
    best = suitable[0] if suitable else None

    # 부적합 이유 생성 (한국어)
    reasons: List[str] = []
    if avg_diam < 0.2:
        reasons.append(
            f"평균 직경 {avg_diam:.2f} µm — 모든 표준 타입보다 작습니다 "
            "(홀이 너무 작거나 노이즈가 검출되었을 수 있습니다)"
        )
    elif avg_diam > 30.0:
        reasons.append(
            f"평균 직경 {avg_diam:.2f} µm — 표준 범위를 초과합니다 "
            "(그리드 노화 또는 손상 의심)"
        )
    if avg_circ < 0.40:
        reasons.append(
            f"원형도 {avg_circ:.2f} — 모든 타입의 기준에 미달합니다 "
            "(홀 형태가 심하게 불균일)"
        )
    if coverage < 5.0:
        reasons.append(
            f"커버리지 {coverage:.1f}% — 너무 낮습니다 "
            "(홀 밀도 부족, 스케일 재확인 권장)"
        )
    if coverage > 60.0:
        reasons.append(
            f"커버리지 {coverage:.1f}% — 너무 높습니다 "
            "(필름 강도 취약 가능성, 새 그리드 권장)"
        )

    # 각 타입별 부적합 이유
    unsuitable_reasons: Dict[str, List[str]] = {}
    for name, spec in GRID_PROFILES.items():
        if name not in suitable:
            dmin, dmax = spec["diam_range"]
            sub_reasons: List[str] = []
            if avg_diam < dmin:
                sub_reasons.append(f"직경 {avg_diam:.2f} µm < 최소 {dmin} µm")
            elif avg_diam > dmax:
                sub_reasons.append(f"직경 {avg_diam:.2f} µm > 최대 {dmax} µm")
            if avg_circ < spec["min_circ"]:
                sub_reasons.append(
                    f"원형도 {avg_circ:.2f} < 기준 {spec['min_circ']}"
                )
            unsuitable_reasons[name] = sub_reasons

    return {
        "best_match": best,
        "all_suitable": suitable,
        "unsuitable_for": [k for k in GRID_PROFILES if k not in suitable],
        "unsuitable_reasons": unsuitable_reasons,
        "scores": scores,
        "reasons": reasons,
        "coverage_ok": 5.0 <= coverage <= 60.0,
        "recommendation": _generate_recommendation(
            best, avg_diam, avg_circ, coverage, density
        ),
    }


def _generate_recommendation(
    best: Optional[str],
    diam: float,
    circ: float,
    coverage: float,
    density: float,
) -> str:
    """
    분류 결과를 바탕으로 한국어 추천 문구를 생성합니다.

    Parameters
    ----------
    best : str | None
        가장 적합한 타입 이름
    diam : float
        평균 직경 (µm)
    circ : float
        평균 원형도
    coverage : float
        홀 커버리지 (%)
    density : float
        홀 밀도 (holes/µm²)

    Returns
    -------
    recommendation : str
        한국어 추천 문구
    """
    if not best:
        return (
            "측정된 홀 특성이 표준 그리드 타입 기준에 부합하지 않습니다. "
            "스케일 값을 재확인하거나 새 그리드 사용을 권장합니다."
        )

    spec = GRID_PROFILES[best]
    dmin, dmax = spec["diam_range"]
    coverage_desc = _coverage_description(coverage)

    lines = [
        f"이 그리드는 {best}에 가장 적합합니다.",
        f"평균 홀 직경 {diam:.2f} µm, 원형도 {circ:.2f}로 해당 실험 조건에 적합합니다.",
        f"직경 허용 범위 {dmin}~{dmax} µm 내에 있습니다.",
        f"홀 커버리지 {coverage:.1f}%는 {coverage_desc}입니다.",
    ]
    if density > 0:
        lines.append(f"홀 밀도 {density:.3f} holes/µm².")

    return " ".join(lines)


def _coverage_description(coverage: float) -> str:
    if coverage < 5:
        return "매우 낮음 — 홀 밀도 확인 필요"
    elif coverage < 15:
        return "낮은 범위"
    elif coverage <= 40:
        return "적정 범위"
    elif coverage <= 60:
        return "높은 편이나 허용 범위"
    else:
        return "매우 높음 — 필름 강도 주의"
