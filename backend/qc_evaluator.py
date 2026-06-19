"""
GIGO QC — QC 판정 모듈 (qc_evaluator.py)

PRD F-04 기준에 따라 PASS / WARNING / FAIL 판정을 수행합니다.

Grid 타입별 QC 기준 (PRD 3.md):
  Type A: 직경 0.5~5.0 μm, 원형도 ≥ 0.6, 밀도 ≥ 2.0/μm², 커버리지 20~60%
  Type B: 직경 1.0~10.0 μm, 원형도 ≥ 0.5, 밀도 1.0~5.0/μm², 커버리지 25~55%
  Type C: 직경 0.2~2.0 μm, 원형도 ≥ 0.55, 밀도 ≥ 3.0/μm², 커버리지 15~50%
  Type D: 직경 5.0~30.0 μm, 원형도 ≥ 0.4, 밀도 ≥ 0.5/μm², 커버리지 10~50%

판정 로직:
  4/4 통과 → PASS
  2~3/4 통과 → WARNING
  0~1/4 통과 → FAIL
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ─── QC 기준 테이블 ────────────────────────────────────────────────────────────
# short 키(A/B/C/D)를 사용해 빠른 룩업 지원

QC_STANDARDS: Dict[str, Dict[str, Any]] = {
    "A": {
        "name": "Type A — Membrane Protein",
        "diam_min": 0.5,
        "diam_max": 5.0,
        "min_circ": 0.60,
        "density_min": 2.0,
        "density_max": None,   # 상한 없음
        "cov_min": 20.0,
        "cov_max": 60.0,
        "desc_fail": {
            "diameter_range": "홀 직경이 막단백질 실험 기준(0.5~5.0 μm)을 벗어났습니다.",
            "circularity":    "원형도가 기준(≥ 0.60) 미만입니다.",
            "density":        "홀 밀도가 기준(≥ 2.0 holes/μm²) 미만입니다.",
            "coverage":       "홀 커버리지가 기준(20~60%) 범위를 벗어났습니다.",
        },
    },
    "B": {
        "name": "Type B — Protein Complex",
        "diam_min": 1.0,
        "diam_max": 10.0,
        "min_circ": 0.50,
        "density_min": 1.0,
        "density_max": 5.0,
        "cov_min": 25.0,
        "cov_max": 55.0,
        "desc_fail": {
            "diameter_range": "홀 직경이 단백질 복합체 실험 기준(1.0~10.0 μm)을 벗어났습니다.",
            "circularity":    "원형도가 기준(≥ 0.50) 미만입니다.",
            "density":        "홀 밀도가 기준(1.0~5.0 holes/μm²) 범위를 벗어났습니다.",
            "coverage":       "홀 커버리지가 기준(25~55%) 범위를 벗어났습니다.",
        },
    },
    "C": {
        "name": "Type C — Nanomaterial / Virus",
        "diam_min": 0.2,
        "diam_max": 2.0,
        "min_circ": 0.55,
        "density_min": 3.0,
        "density_max": None,
        "cov_min": 15.0,
        "cov_max": 50.0,
        "desc_fail": {
            "diameter_range": "홀 직경이 나노소재 실험 기준(0.2~2.0 μm)을 벗어났습니다.",
            "circularity":    "원형도가 기준(≥ 0.55) 미만입니다.",
            "density":        "홀 밀도가 기준(≥ 3.0 holes/μm²) 미만입니다.",
            "coverage":       "홀 커버리지가 기준(15~50%) 범위를 벗어났습니다.",
        },
    },
    "D": {
        "name": "Type D — Large Specimen",
        "diam_min": 5.0,
        "diam_max": 30.0,
        "min_circ": 0.40,
        "density_min": 0.5,
        "density_max": None,
        "cov_min": 10.0,
        "cov_max": 50.0,
        "desc_fail": {
            "diameter_range": "홀 직경이 대형 시편 기준(5.0~30.0 μm)을 벗어났습니다.",
            "circularity":    "원형도가 기준(≥ 0.40) 미만입니다.",
            "density":        "홀 밀도가 기준(≥ 0.5 holes/μm²) 미만입니다.",
            "coverage":       "홀 커버리지가 기준(10~50%) 범위를 벗어났습니다.",
        },
    },
}

# 이름(full)에서 short 키로의 매핑
_FULL_NAME_TO_SHORT = {
    "Type A — Membrane Protein":    "A",
    "Type B — Protein Complex":     "B",
    "Type C — Nanomaterial / Virus": "C",
    "Type D — Large Specimen":      "D",
}


def evaluate(
    stats: Dict[str, Any],
    grid_type_hint: str = "auto",
    classifier_best_match: Optional[str] = None,
) -> Dict[str, Any]:
    """
    QC 판정을 수행합니다.

    Parameters
    ----------
    stats : dict
        compute_stats()의 반환값.
        필수 키: avg_diameter, avg_circularity, density_per_um2, coverage_pct
    grid_type_hint : str
        "auto" | "A" | "B" | "C" | "D"
        "auto"이면 classifier_best_match를 사용합니다.
    classifier_best_match : str | None
        classify()["best_match"]의 값 (grid_type_hint="auto"일 때 사용)

    Returns
    -------
    result : dict
        verdict : "PASS" | "WARNING" | "FAIL"
        qc_score : float (0.0 ~ 1.0)
        qc_checks : dict[str, bool]  4개 체크 항목
        grid_type_used : str
        fail_messages : list[str]  (한국어 실패 이유)
        details : dict  체크 항목별 세부 정보
    """
    # 1. 사용할 그리드 타입 결정
    short = _resolve_grid_type(grid_type_hint, classifier_best_match)

    if short is None:
        # 분류기도 best match를 못 찾은 경우
        return {
            "verdict": "FAIL",
            "qc_score": 0.0,
            "qc_checks": {
                "diameter_range": False,
                "circularity": False,
                "density": False,
                "coverage": False,
            },
            "grid_type_used": "N/A",
            "fail_messages": [
                "어떤 그리드 타입의 기준에도 부합하지 않습니다. "
                "스케일 값을 확인하거나 새 그리드를 사용해 주세요."
            ],
            "details": {},
        }

    std = QC_STANDARDS[short]

    avg_diam = stats.get("avg_diameter", 0.0)
    avg_circ = stats.get("avg_circularity", 0.0)
    density  = stats.get("density_per_um2", 0.0)
    coverage = stats.get("coverage_pct", 0.0)

    # 2. 4개 체크
    diam_ok    = std["diam_min"] <= avg_diam <= std["diam_max"]
    circ_ok    = avg_circ >= std["min_circ"]
    dens_ok    = _check_density(density, std["density_min"], std["density_max"])
    cov_ok     = std["cov_min"] <= coverage <= std["cov_max"]

    qc_checks = {
        "diameter_range": diam_ok,
        "circularity":    circ_ok,
        "density":        dens_ok,
        "coverage":       cov_ok,
    }

    pass_count = sum(qc_checks.values())

    # 3. 판정
    if pass_count == 4:
        verdict = "PASS"
    elif pass_count >= 2:
        verdict = "WARNING"
    else:
        verdict = "FAIL"

    qc_score = pass_count / 4.0

    # 4. 실패 항목 메시지 수집
    fail_messages: list[str] = []
    for key, passed in qc_checks.items():
        if not passed:
            fail_messages.append(std["desc_fail"][key])

    # 5. 세부 정보
    details = {
        "diameter_range": {
            "value": avg_diam,
            "unit": "μm",
            "range": f"{std['diam_min']}~{std['diam_max']} μm",
            "passed": diam_ok,
        },
        "circularity": {
            "value": avg_circ,
            "threshold": f"≥ {std['min_circ']}",
            "passed": circ_ok,
        },
        "density": {
            "value": density,
            "unit": "holes/μm²",
            "threshold": _density_threshold_str(std),
            "passed": dens_ok,
        },
        "coverage": {
            "value": coverage,
            "unit": "%",
            "range": f"{std['cov_min']}~{std['cov_max']}%",
            "passed": cov_ok,
        },
    }

    return {
        "verdict": verdict,
        "qc_score": round(qc_score, 2),
        "qc_checks": qc_checks,
        "grid_type_used": std["name"],
        "fail_messages": fail_messages,
        "details": details,
    }


def _resolve_grid_type(
    hint: str,
    classifier_best_match: Optional[str],
) -> Optional[str]:
    """
    grid_type_hint를 short 키(A/B/C/D)로 변환합니다.
    """
    hint = (hint or "auto").strip().upper()

    if hint in QC_STANDARDS:
        return hint

    if hint == "AUTO":
        if classifier_best_match is None:
            return None
        # full name → short key
        short = _FULL_NAME_TO_SHORT.get(classifier_best_match)
        return short  # None이면 분류 실패

    # 알 수 없는 hint → auto 처리
    return None


def _check_density(
    density: float,
    density_min: Optional[float],
    density_max: Optional[float],
) -> bool:
    """밀도 범위 체크 (density_max=None이면 상한 없음)."""
    if density_min is not None and density < density_min:
        return False
    if density_max is not None and density > density_max:
        return False
    return True


def _density_threshold_str(std: Dict[str, Any]) -> str:
    dmin = std.get("density_min")
    dmax = std.get("density_max")
    if dmin is not None and dmax is not None:
        return f"{dmin}~{dmax} holes/μm²"
    elif dmin is not None:
        return f"≥ {dmin} holes/μm²"
    elif dmax is not None:
        return f"≤ {dmax} holes/μm²"
    return "N/A"
