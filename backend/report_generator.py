"""
GIGO QC — PDF/CSV 리포트 생성 (report_generator.py)

ReportLab을 사용해 4페이지 PDF 리포트를 생성합니다.
한국어 폰트: Windows malgun.ttf / macOS AppleSDGothicNeo 시도,
실패 시 Helvetica(영문) fallback.

PDF 구조:
  Page 1 — 표지 (Cover)
  Page 2 — 요약 인포그래픽 (Summary Infographic)
  Page 3 — 차트 (직경 히스토그램 + 원형도-직경 산포도)
  Page 4 — 원시 데이터 테이블 (Raw Data)
"""

from __future__ import annotations

import csv
import io
import os
import platform
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

# ─── ReportLab imports ────────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Image as RLImage,
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ─── 색상 정의 (PRD 디자인 시스템) ────────────────────────────────────────────
C_BG         = colors.HexColor("#0D1117")
C_SURFACE    = colors.HexColor("#161B22")
C_TEAL       = colors.HexColor("#2DD4BF")
C_AMBER      = colors.HexColor("#FCD34D")
C_RED        = colors.HexColor("#F87171")
C_TEXT       = colors.HexColor("#E6EDF3")
C_MUTED      = colors.HexColor("#8B949E")
C_WHITE      = colors.white
C_BLACK      = colors.black


# ─── 폰트 설정 ────────────────────────────────────────────────────────────────

def _register_korean_font() -> str:
    """
    시스템 한국어 폰트 등록을 시도합니다.
    성공 시 폰트 이름 반환, 실패 시 "Helvetica" 반환.
    """
    font_candidates = []
    sys = platform.system()

    if sys == "Windows":
        font_candidates = [
            r"C:\Windows\Fonts\malgun.ttf",
            r"C:\Windows\Fonts\NanumGothic.ttf",
        ]
    elif sys == "Darwin":  # macOS
        font_candidates = [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/Library/Fonts/NanumGothic.ttf",
        ]
    else:  # Linux
        font_candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/nanum/NanumGothic.ttf",
            os.path.expanduser("~/.fonts/NanumGothic.ttf"),
        ]

    for path in font_candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("KorFont", path))
                return "KorFont"
            except Exception:
                continue

    return "Helvetica"


_FONT_NAME = _register_korean_font()
_USE_KOREAN = (_FONT_NAME != "Helvetica")


def _t(ko: str, en: str) -> str:
    """한국어 폰트 사용 가능하면 ko, 아니면 en 반환."""
    return ko if _USE_KOREAN else en


# ─── matplotlib 차트 생성 ─────────────────────────────────────────────────────

def _make_histogram_chart(holes: List[Dict[str, Any]]) -> Optional[bytes]:
    """직경 분포 히스토그램 PNG bytes 반환."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from scipy.stats import norm

        diameters = [h["diameter_um"] for h in holes]
        if not diameters:
            return None

        fig, ax = plt.subplots(figsize=(5.5, 3.5))
        fig.patch.set_facecolor("#161B22")
        ax.set_facecolor("#1C2128")

        n, bins, patches = ax.hist(
            diameters, bins=min(20, max(5, len(diameters) // 3)),
            color="#2DD4BF", alpha=0.8, edgecolor="#0D1117", linewidth=0.5
        )

        # 정규분포 피팅 곡선
        if len(diameters) >= 5:
            mu, sigma = np.mean(diameters), np.std(diameters)
            if sigma > 0:
                x = np.linspace(min(diameters), max(diameters), 200)
                dx = (max(diameters) - min(diameters)) / max(len(n), 1)
                scale = len(diameters) * dx
                ax.plot(x, norm.pdf(x, mu, sigma) * scale,
                        color="#FCD34D", linewidth=2, label=f"μ={mu:.2f} σ={sigma:.2f}")
                ax.legend(fontsize=8, facecolor="#1C2128", edgecolor="#484F58",
                          labelcolor="#E6EDF3")

        ax.set_xlabel(_t("직경 (μm)", "Diameter (μm)"), color="#8B949E", fontsize=9)
        ax.set_ylabel(_t("빈도", "Count"), color="#8B949E", fontsize=9)
        ax.set_title(_t("홀 직경 분포", "Hole Diameter Distribution"),
                     color="#E6EDF3", fontsize=11, fontweight="bold")
        ax.tick_params(colors="#8B949E")
        for spine in ax.spines.values():
            spine.set_edgecolor("#484F58")

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


def _make_scatter_chart(holes: List[Dict[str, Any]]) -> Optional[bytes]:
    """원형도 vs 직경 산포도 PNG bytes 반환."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        diameters     = [h["diameter_um"] for h in holes]
        circularities = [h["circularity"] for h in holes]
        if not diameters:
            return None

        fig, ax = plt.subplots(figsize=(5.5, 3.5))
        fig.patch.set_facecolor("#161B22")
        ax.set_facecolor("#1C2128")

        ax.scatter(diameters, circularities,
                   c="#2DD4BF", alpha=0.6, s=25, edgecolors="#0D1117", linewidths=0.5)

        # 원형도 기준선
        ax.axhline(y=0.60, color="#FCD34D", linewidth=1, linestyle="--",
                   alpha=0.6, label="min circ (Type A)")
        ax.axhline(y=0.50, color="#F87171", linewidth=1, linestyle=":",
                   alpha=0.6, label="min circ (Type B)")

        ax.set_xlabel(_t("직경 (μm)", "Diameter (μm)"), color="#8B949E", fontsize=9)
        ax.set_ylabel(_t("원형도", "Circularity"), color="#8B949E", fontsize=9)
        ax.set_title(_t("원형도 vs 직경", "Circularity vs Diameter"),
                     color="#E6EDF3", fontsize=11, fontweight="bold")
        ax.set_ylim(0, 1.05)
        ax.tick_params(colors="#8B949E")
        ax.legend(fontsize=7, facecolor="#1C2128", edgecolor="#484F58",
                  labelcolor="#E6EDF3")
        for spine in ax.spines.values():
            spine.set_edgecolor("#484F58")

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


# ─── PDF 페이지 헬퍼 ──────────────────────────────────────────────────────────

def _verdict_color(verdict: str) -> Any:
    if verdict == "PASS":
        return C_TEAL
    elif verdict == "WARNING":
        return C_AMBER
    else:
        return C_RED


def _make_styles() -> Dict[str, ParagraphStyle]:
    """공통 ParagraphStyle 딕셔너리 반환."""
    base = getSampleStyleSheet()
    styles = {}

    styles["title"] = ParagraphStyle(
        "gigo_title", fontName=_FONT_NAME, fontSize=28, textColor=C_TEXT,
        spaceAfter=6, leading=34, alignment=1,  # center
    )
    styles["subtitle"] = ParagraphStyle(
        "gigo_subtitle", fontName=_FONT_NAME, fontSize=14, textColor=C_MUTED,
        spaceAfter=4, leading=18, alignment=1,
    )
    styles["h2"] = ParagraphStyle(
        "gigo_h2", fontName=_FONT_NAME, fontSize=14, textColor=C_TEXT,
        spaceBefore=10, spaceAfter=4, leading=18, fontWeight="bold",
    )
    styles["body"] = ParagraphStyle(
        "gigo_body", fontName=_FONT_NAME, fontSize=10, textColor=C_TEXT,
        spaceAfter=4, leading=15,
    )
    styles["muted"] = ParagraphStyle(
        "gigo_muted", fontName=_FONT_NAME, fontSize=9, textColor=C_MUTED,
        spaceAfter=3, leading=13,
    )
    styles["mono"] = ParagraphStyle(
        "gigo_mono", fontName="Courier", fontSize=9, textColor=C_TEXT,
        spaceAfter=2, leading=13,
    )
    styles["kpi_big"] = ParagraphStyle(
        "gigo_kpi_big", fontName="Courier-Bold", fontSize=30, textColor=C_TEAL,
        alignment=1, leading=36,
    )
    styles["kpi_label"] = ParagraphStyle(
        "gigo_kpi_label", fontName=_FONT_NAME, fontSize=9, textColor=C_MUTED,
        alignment=1, leading=12,
    )
    styles["verdict_big"] = ParagraphStyle(
        "gigo_verdict_big", fontName="Helvetica-Bold", fontSize=36,
        alignment=1, leading=44,
    )

    return styles


# ─── Page 1: 표지 ─────────────────────────────────────────────────────────────

def _build_cover(
    story: list,
    styles: Dict[str, ParagraphStyle],
    data: Dict[str, Any],
    verdict: str,
    verdict_color: Any,
) -> None:
    filename = data.get("filename", "Unknown File")
    analysis_time = data.get(
        "analysis_time",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    notes = data.get("notes", "")

    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph("GIGO QC", styles["title"]))
    story.append(Paragraph(
        _t("Lacey Carbon Grid 자동 품질검증 시스템", "Lacey Carbon Grid Auto QC System"),
        styles["subtitle"]
    ))
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=C_TEAL, spaceAfter=8 * mm))

    # QC 판정 대형 배지
    verdict_text = {
        "PASS": "✓  PASS",
        "WARNING": "⚠  WARNING",
        "FAIL": "✗  FAIL",
    }.get(verdict, verdict)

    verdict_style = ParagraphStyle(
        "cover_verdict", fontName="Helvetica-Bold", fontSize=40,
        textColor=verdict_color, alignment=1, leading=50,
        borderPad=10,
    )
    story.append(Paragraph(verdict_text, verdict_style))
    story.append(Spacer(1, 10 * mm))

    # 파일 정보
    info_data = [
        [_t("분석 파일", "File"), filename],
        [_t("분석 일시", "Analyzed"), analysis_time],
    ]
    if notes:
        info_data.append([_t("메모", "Notes"), notes])

    info_table = Table(info_data, colWidths=[45 * mm, 110 * mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE",  (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), C_MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), C_TEXT),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_SURFACE, C_BG]),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, C_MUTED),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_MUTED))
    story.append(Spacer(1, 5 * mm))

    # 푸터 메모
    story.append(Paragraph(
        _t(
            "본 리포트는 GIGO QC 시스템에 의해 자동 생성되었습니다.",
            "This report was automatically generated by GIGO QC."
        ),
        styles["muted"]
    ))
    story.append(PageBreak())


# ─── Page 2: 요약 인포그래픽 ──────────────────────────────────────────────────

def _build_summary(
    story: list,
    styles: Dict[str, ParagraphStyle],
    stats: Dict[str, Any],
    classification: Dict[str, Any],
    qc_result: Dict[str, Any],
) -> None:
    verdict       = qc_result.get("verdict", "N/A")
    verdict_color = _verdict_color(verdict)
    best_match    = classification.get("best_match", _t("없음", "None"))

    story.append(Paragraph(
        _t("분석 요약", "Analysis Summary"),
        styles["h2"]
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=C_TEAL, spaceAfter=5 * mm))

    # KPI 카드 4개
    kpi_vals = [
        (str(stats.get("total_holes", 0)),  _t("총 홀 수", "Total Holes")),
        (f"{stats.get('avg_diameter', 0):.2f} μm", _t("평균 직경", "Avg Diameter")),
        (f"{stats.get('avg_circularity', 0):.3f}", _t("평균 원형도", "Avg Circularity")),
        (f"{stats.get('coverage_pct', 0):.1f}%",  _t("홀 커버리지", "Coverage")),
    ]

    kpi_table_data = [[
        Paragraph(v, styles["kpi_big"]) for v, _ in kpi_vals
    ], [
        Paragraph(lbl, styles["kpi_label"]) for _, lbl in kpi_vals
    ]]

    kpi_table = Table(kpi_table_data, colWidths=[40 * mm] * 4)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_SURFACE),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1), [C_SURFACE]),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("BOX",           (0, 0), (-1, -1), 1, C_TEAL),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, C_MUTED),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 6 * mm))

    # Grid Suitability 섹션
    story.append(Paragraph(
        _t("Grid Suitability 분류 결과", "Grid Suitability Classification"),
        styles["h2"]
    ))

    suitability_data = [
        [_t("그리드 타입", "Grid Type"), _t("적합성", "Suitability"), _t("이유", "Reason")]
    ]

    from classifier import GRID_PROFILES  # 순환 import 방지를 위해 로컬 import
    suitable_set = set(classification.get("all_suitable", []))
    unsuitable_reasons = classification.get("unsuitable_reasons", {})

    for type_name, spec in GRID_PROFILES.items():
        is_suitable = type_name in suitable_set
        marker = "✓  SUITABLE" if is_suitable else "✗  NO"
        color_mark = colors.green if is_suitable else colors.red
        if type_name == classification.get("best_match"):
            marker = "★  BEST FIT"

        reasons_str = ", ".join(unsuitable_reasons.get(type_name, []))
        suitability_data.append([
            type_name,
            marker,
            reasons_str if reasons_str else ("—" if is_suitable else _t("범위 초과", "Out of range")),
        ])

    suit_table = Table(
        suitability_data,
        colWidths=[70 * mm, 35 * mm, 55 * mm]
    )
    suit_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C_SURFACE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_TEAL),
        ("FONTNAME",      (0, 0), (-1, 0), _FONT_NAME),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("FONTNAME",      (0, 1), (-1, -1), _FONT_NAME),
        ("TEXTCOLOR",     (0, 1), (-1, -1), C_TEXT),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_SURFACE, C_BG]),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("GRID",          (0, 0), (-1, -1), 0.3, C_MUTED),
    ]))
    story.append(suit_table)
    story.append(Spacer(1, 5 * mm))

    # QC 판정 결과
    story.append(Paragraph(_t("QC 판정 세부사항", "QC Check Details"), styles["h2"]))
    qc_checks = qc_result.get("qc_checks", {})
    details   = qc_result.get("details", {})

    check_labels = {
        "diameter_range": _t("홀 직경 범위", "Diameter Range"),
        "circularity":    _t("원형도", "Circularity"),
        "density":        _t("홀 밀도", "Hole Density"),
        "coverage":       _t("홀 커버리지", "Coverage"),
    }
    qc_data = [[
        _t("항목", "Check"),
        _t("측정값", "Value"),
        _t("기준", "Threshold"),
        _t("결과", "Result"),
    ]]
    for key, label in check_labels.items():
        passed = qc_checks.get(key, False)
        det = details.get(key, {})
        val = det.get("value", "—")
        unit = det.get("unit", "")
        threshold = det.get("range", det.get("threshold", "—"))
        val_str = f"{val:.3f} {unit}".strip() if isinstance(val, float) else str(val)
        result_str = "PASS" if passed else "FAIL"
        qc_data.append([label, val_str, threshold, result_str])

    qc_table = Table(qc_data, colWidths=[45 * mm, 35 * mm, 55 * mm, 25 * mm])
    qc_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C_SURFACE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_TEAL),
        ("FONTNAME",      (0, 0), (-1, 0), _FONT_NAME),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("FONTNAME",      (0, 1), (-1, -1), _FONT_NAME),
        ("TEXTCOLOR",     (0, 1), (-1, -1), C_TEXT),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_SURFACE, C_BG]),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("GRID",          (0, 0), (-1, -1), 0.3, C_MUTED),
    ]))
    story.append(qc_table)

    # 추천 문구
    recommendation = classification.get("recommendation", "")
    if recommendation:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph(
            _t("추천 사항", "Recommendation"), styles["h2"]
        ))
        story.append(Paragraph(recommendation, styles["body"]))

    story.append(PageBreak())


# ─── Page 3: 차트 ─────────────────────────────────────────────────────────────

def _build_charts(
    story: list,
    styles: Dict[str, ParagraphStyle],
    holes: List[Dict[str, Any]],
) -> None:
    story.append(Paragraph(
        _t("분포 차트", "Distribution Charts"),
        styles["h2"]
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=C_TEAL, spaceAfter=5 * mm))

    if not holes:
        story.append(Paragraph(
            _t("검출된 홀이 없어 차트를 생성할 수 없습니다.",
               "No holes detected. Charts unavailable."),
            styles["muted"]
        ))
        story.append(PageBreak())
        return

    hist_bytes = _make_histogram_chart(holes)
    scat_bytes = _make_scatter_chart(holes)

    chart_data = [[]]
    if hist_bytes:
        hist_buf = io.BytesIO(hist_bytes)
        chart_data[0].append(RLImage(hist_buf, width=82 * mm, height=55 * mm))
    else:
        chart_data[0].append(Paragraph(
            _t("[히스토그램 생성 실패]", "[Histogram unavailable]"), styles["muted"]
        ))

    if scat_bytes:
        scat_buf = io.BytesIO(scat_bytes)
        chart_data[0].append(RLImage(scat_buf, width=82 * mm, height=55 * mm))
    else:
        chart_data[0].append(Paragraph(
            _t("[산포도 생성 실패]", "[Scatter unavailable]"), styles["muted"]
        ))

    chart_table = Table(chart_data, colWidths=[90 * mm, 90 * mm])
    chart_table.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(chart_table)

    # 기술 통계 요약
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(_t("기술 통계", "Descriptive Statistics"), styles["h2"]))

    diameters = [h["diameter_um"] for h in holes]
    circularities = [h["circularity"] for h in holes]

    stat_data = [
        [_t("통계량", "Statistic"),
         _t("직경 (μm)", "Diameter (μm)"),
         _t("원형도", "Circularity")],
        [_t("평균", "Mean"),
         f"{np.mean(diameters):.4f}",
         f"{np.mean(circularities):.4f}"],
        [_t("중앙값", "Median"),
         f"{np.median(diameters):.4f}",
         f"{np.median(circularities):.4f}"],
        [_t("표준편차", "Std Dev"),
         f"{np.std(diameters):.4f}",
         f"{np.std(circularities):.4f}"],
        [_t("최소", "Min"),
         f"{np.min(diameters):.4f}",
         f"{np.min(circularities):.4f}"],
        [_t("최대", "Max"),
         f"{np.max(diameters):.4f}",
         f"{np.max(circularities):.4f}"],
    ]

    stat_table = Table(stat_data, colWidths=[50 * mm, 60 * mm, 50 * mm])
    stat_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C_SURFACE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_TEAL),
        ("FONTNAME",      (0, 0), (-1, 0), _FONT_NAME),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("FONTNAME",      (0, 1), (-1, -1), "Courier"),
        ("TEXTCOLOR",     (0, 1), (-1, -1), C_TEXT),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_SURFACE, C_BG]),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("GRID",          (0, 0), (-1, -1), 0.3, C_MUTED),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(stat_table)
    story.append(PageBreak())


# ─── Page 4: 원시 데이터 테이블 ───────────────────────────────────────────────

def _build_raw_data(
    story: list,
    styles: Dict[str, ParagraphStyle],
    holes: List[Dict[str, Any]],
    stats: Dict[str, Any],
    pixel_scale_nm: float,
) -> None:
    story.append(Paragraph(
        _t("원시 데이터 테이블", "Raw Data Table"),
        styles["h2"]
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=C_TEAL, spaceAfter=5 * mm))

    if not holes:
        story.append(Paragraph(
            _t("검출된 홀 데이터가 없습니다.", "No hole data available."),
            styles["muted"]
        ))
        return

    # 분석 파라미터 메타데이터
    meta_data = [
        [_t("픽셀 스케일", "Pixel Scale"), f"{pixel_scale_nm:.4f} nm/px"],
        [_t("총 홀 수", "Total Holes"), str(stats.get("total_holes", 0))],
        [_t("홀 밀도", "Hole Density"),
         f"{stats.get('density_per_um2', 0):.6f} holes/μm²"],
        [_t("홀 커버리지", "Coverage"), f"{stats.get('coverage_pct', 0):.3f}%"],
    ]
    meta_table = Table(meta_data, colWidths=[50 * mm, 110 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE",  (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), C_MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), C_TEXT),
        ("FONTNAME",  (1, 0), (1, -1), "Courier"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_SURFACE, C_BG]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.3, C_MUTED),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 5 * mm))

    # 홀 데이터 테이블 (최대 500개 표시)
    MAX_ROWS = 500
    display_holes = holes[:MAX_ROWS]

    header = [
        _t("ID", "ID"),
        _t("직경(μm)", "Diam(μm)"),
        _t("면적(μm²)", "Area(μm²)"),
        _t("원형도", "Circ."),
        _t("종횡비", "AR"),
        _t("X(px)", "X(px)"),
        _t("Y(px)", "Y(px)"),
    ]
    rows = [header]
    for h in display_holes:
        rows.append([
            str(h["id"]),
            f"{h['diameter_um']:.3f}",
            f"{h['area_um2']:.4f}",
            f"{h['circularity']:.3f}",
            f"{h['aspect_ratio']:.3f}",
            str(h["cx_px"]),
            str(h["cy_px"]),
        ])

    hole_table = Table(
        rows,
        colWidths=[14 * mm, 24 * mm, 24 * mm, 20 * mm, 18 * mm, 18 * mm, 18 * mm],
        repeatRows=1,
    )
    hole_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C_SURFACE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_TEAL),
        ("FONTNAME",      (0, 0), (-1, 0), _FONT_NAME),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 1), (-1, -1), "Courier"),
        ("TEXTCOLOR",     (0, 1), (-1, -1), C_TEXT),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_SURFACE, C_BG]),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("GRID",          (0, 0), (-1, -1), 0.2, C_MUTED),
        ("ALIGN",         (0, 0), (-1, -1), "RIGHT"),
        ("ALIGN",         (0, 0), (0, -1), "CENTER"),
    ]))
    story.append(hole_table)

    if len(holes) > MAX_ROWS:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(
            _t(
                f"* 전체 {len(holes)}개 홀 중 {MAX_ROWS}개만 표시됩니다. "
                "CSV 내보내기로 전체 데이터를 확인하세요.",
                f"* Showing {MAX_ROWS} of {len(holes)} holes. "
                "Export CSV for full data."
            ),
            styles["muted"]
        ))


# ─── 공개 API ─────────────────────────────────────────────────────────────────

def create_pdf(data: Dict[str, Any]) -> bytes:
    """
    분석 결과 dict를 받아 PDF bytes를 생성합니다.

    Parameters
    ----------
    data : dict
        키:
          - holes: list[dict]            (measure_holes 결과)
          - stats: dict                  (compute_stats 결과)
          - classification: dict         (classify 결과)
          - qc_result: dict              (evaluate 결과)
          - pixel_scale_nm: float
          - filename: str                (원본 파일명)
          - analysis_time: str           (분석 시각, ISO 형식)
          - notes: str                   (선택 메모)

    Returns
    -------
    pdf_bytes : bytes
        PDF 파일 bytes
    """
    holes         = data.get("holes", [])
    stats         = data.get("stats", {})
    classification = data.get("classification", {})
    qc_result     = data.get("qc_result", {})
    pixel_scale_nm = data.get("pixel_scale_nm", 1.0)

    verdict       = qc_result.get("verdict", "N/A")
    verdict_color = _verdict_color(verdict)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = _make_styles()
    story: list = []

    _build_cover(story, styles, data, verdict, verdict_color)
    _build_summary(story, styles, stats, classification, qc_result)
    _build_charts(story, styles, holes)
    _build_raw_data(story, styles, holes, stats, pixel_scale_nm)

    doc.build(story)
    buf.seek(0)
    return buf.read()


def create_csv(data: Dict[str, Any]) -> bytes:
    """
    분석 결과 dict를 받아 CSV bytes를 생성합니다.

    Parameters
    ----------
    data : dict
        create_pdf()와 동일한 키 구조

    Returns
    -------
    csv_bytes : bytes
        UTF-8 BOM CSV (Windows Excel 호환)
    """
    holes = data.get("holes", [])
    stats = data.get("stats", {})
    qc_result = data.get("qc_result", {})
    classification = data.get("classification", {})

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")

    # 메타 섹션
    writer.writerow(["# GIGO QC Analysis Report"])
    writer.writerow(["# File", data.get("filename", "")])
    writer.writerow(["# Analyzed", data.get("analysis_time", datetime.now().isoformat())])
    writer.writerow(["# Pixel Scale (nm/px)", data.get("pixel_scale_nm", "N/A")])
    writer.writerow([])

    # 통계 요약
    writer.writerow(["## Summary Statistics"])
    writer.writerow(["Metric", "Value", "Unit"])
    stat_rows = [
        ("Total Holes",      stats.get("total_holes", 0),        "count"),
        ("Avg Diameter",     stats.get("avg_diameter", 0),       "μm"),
        ("Std Diameter",     stats.get("std_diameter", 0),       "μm"),
        ("Median Diameter",  stats.get("median_diameter", 0),    "μm"),
        ("Min Diameter",     stats.get("min_diameter", 0),       "μm"),
        ("Max Diameter",     stats.get("max_diameter", 0),       "μm"),
        ("Avg Circularity",  stats.get("avg_circularity", 0),    "0~1"),
        ("Std Circularity",  stats.get("std_circularity", 0),    "0~1"),
        ("Density",          stats.get("density_per_um2", 0),    "holes/μm²"),
        ("Coverage",         stats.get("coverage_pct", 0),       "%"),
    ]
    for row in stat_rows:
        writer.writerow(row)
    writer.writerow([])

    # QC 판정
    writer.writerow(["## QC Result"])
    writer.writerow(["Verdict",     qc_result.get("verdict", "N/A")])
    writer.writerow(["QC Score",    qc_result.get("qc_score", 0)])
    writer.writerow(["Grid Used",   qc_result.get("grid_type_used", "N/A")])
    writer.writerow(["Best Match",  classification.get("best_match", "None")])
    writer.writerow([])

    # 개별 홀 데이터
    writer.writerow(["## Individual Hole Data"])
    writer.writerow([
        "ID", "Diameter (μm)", "Area (μm²)", "Circularity",
        "Aspect Ratio", "Center X (px)", "Center Y (px)"
    ])
    for h in holes:
        writer.writerow([
            h["id"],
            h["diameter_um"],
            h["area_um2"],
            h["circularity"],
            h["aspect_ratio"],
            h["cx_px"],
            h["cy_px"],
        ])

    # UTF-8 BOM (Windows Excel 호환)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
