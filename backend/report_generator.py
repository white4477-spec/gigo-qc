"""
GIGO QC — PDF / CSV 리포트 생성기 (v1.1.0 redesign)

PRD 1.2 디자인 시스템(다크 베이스, teal 액센트, 시스템 grayscale)을
인쇄용 라이트 톤으로 매핑해 적용한다.

create_pdf(data) -> bytes
create_csv(data) -> bytes
"""
from __future__ import annotations

import base64
import io
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image as PILImage

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)


# ─── 디자인 토큰 (PRD 1.2 → 인쇄용 매핑) ───────────────────────────────────────
INK_PRIMARY   = HexColor("#0F172A")   # slate-900 (텍스트 본문)
INK_SECONDARY = HexColor("#475569")   # slate-600 (보조 텍스트)
INK_MUTED     = HexColor("#94A3B8")   # slate-400 (캡션)
PAPER         = HexColor("#FFFFFF")
SURFACE       = HexColor("#F8FAFC")   # slate-50 (카드 배경)
BORDER        = HexColor("#E2E8F0")   # slate-200
ACCENT        = HexColor("#0D9488")   # teal-600 (PRD teal 인쇄 톤)
ACCENT_SOFT   = HexColor("#CCFBF1")   # teal-100

PASS_BG     = HexColor("#DCFCE7")
PASS_FG     = HexColor("#15803D")
WARN_BG     = HexColor("#FEF3C7")
WARN_FG     = HexColor("#B45309")
FAIL_BG     = HexColor("#FEE2E2")
FAIL_FG     = HexColor("#B91C1C")


# ─── 한글 폰트 등록 ────────────────────────────────────────────────────────────
def _resource_path(rel: str) -> str:
    """PyInstaller --onedir/--onefile 모두 지원하는 리소스 경로 해석."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        # PyInstaller datas=("backend","backend") → backend/fonts/...
        return os.path.join(base, rel)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


def _register_korean_font() -> str:
    """한글 폰트(Regular+Bold)를 찾아 등록. 우선순위: 번들된 NanumGothic → 시스템."""
    # 1) 앱과 함께 번들된 폰트 (모든 OS에서 동일하게 작동)
    bundled_reg = _resource_path("fonts/NanumGothic-Regular.ttf")
    bundled_bold = _resource_path("fonts/NanumGothic-Bold.ttf")
    if os.path.exists(bundled_reg):
        try:
            pdfmetrics.registerFont(TTFont("KFont", bundled_reg))
            bold_path = bundled_bold if os.path.exists(bundled_bold) else bundled_reg
            pdfmetrics.registerFont(TTFont("KFont-Bold", bold_path))
            return "KFont"
        except Exception:
            pass

    # 2) 시스템 폰트 폴백
    candidates = [
        # Windows
        (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
        # macOS
        ("/System/Library/Fonts/AppleSDGothicNeo.ttc", "/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        ("/Library/Fonts/AppleSDGothicNeo.ttc", "/Library/Fonts/AppleSDGothicNeo.ttc"),
        # Linux
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
         "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
         "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    ]
    for reg, bold in candidates:
        if os.path.exists(reg):
            try:
                pdfmetrics.registerFont(TTFont("KFont", reg))
                bold_path = bold if os.path.exists(bold) else reg
                pdfmetrics.registerFont(TTFont("KFont-Bold", bold_path))
                return "KFont"
            except Exception:
                continue
    return "Helvetica"


KFONT = _register_korean_font()
KFONT_BOLD = "KFont-Bold" if KFONT == "KFont" else "Helvetica-Bold"


# ─── 스타일 정의 ───────────────────────────────────────────────────────────────
def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"],
            fontName=KFONT, fontSize=26, leading=32,
            textColor=INK_PRIMARY, alignment=TA_LEFT, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"],
            fontName=KFONT, fontSize=11, leading=14,
            textColor=INK_SECONDARY, alignment=TA_LEFT, spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"],
            fontName=KFONT, fontSize=15, leading=19,
            textColor=INK_PRIMARY, spaceBefore=14, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"],
            fontName=KFONT, fontSize=12, leading=16,
            textColor=INK_PRIMARY, spaceBefore=10, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontName=KFONT, fontSize=10, leading=14,
            textColor=INK_PRIMARY, alignment=TA_LEFT,
        ),
        "caption": ParagraphStyle(
            "caption", parent=base["Normal"],
            fontName=KFONT, fontSize=8.5, leading=11,
            textColor=INK_MUTED, alignment=TA_LEFT,
        ),
        "verdict_label": ParagraphStyle(
            "verdict_label", parent=base["Normal"],
            fontName=KFONT, fontSize=10, leading=12,
            textColor=INK_SECONDARY, alignment=TA_LEFT,
        ),
        "kpi_val": ParagraphStyle(
            "kpi_val", parent=base["Normal"],
            fontName=KFONT, fontSize=20, leading=24,
            textColor=INK_PRIMARY, alignment=TA_CENTER, spaceAfter=2,
        ),
        "kpi_lbl": ParagraphStyle(
            "kpi_lbl", parent=base["Normal"],
            fontName=KFONT, fontSize=8.5, leading=11,
            textColor=INK_SECONDARY, alignment=TA_CENTER,
        ),
    }


# ─── 헬퍼: verdict 색상 ────────────────────────────────────────────────────────
def _verdict_palette(verdict: str):
    v = (verdict or "").upper()
    if v == "PASS":
        return PASS_BG, PASS_FG, "PASS"
    if v == "WARNING":
        return WARN_BG, WARN_FG, "WARNING"
    return FAIL_BG, FAIL_FG, "FAIL"


# ─── 차트 생성 ─────────────────────────────────────────────────────────────────
def _chart_histogram(holes: List[Dict[str, Any]]) -> Optional[bytes]:
    if not holes:
        return None
    diams = [h["diameter_um"] for h in holes]
    fig, ax = plt.subplots(figsize=(5.2, 2.4), dpi=150)
    ax.hist(diams, bins=min(20, max(5, len(diams) // 2)), color="#0D9488",
            edgecolor="white", linewidth=0.8)
    ax.set_xlabel("Diameter (µm)", fontsize=9, color="#475569")
    ax.set_ylabel("Count", fontsize=9, color="#475569")
    ax.tick_params(labelsize=8, colors="#475569")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#CBD5E1")
    ax.grid(axis="y", linestyle="--", linewidth=0.5, color="#E2E8F0", alpha=0.8)
    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _chart_scatter(holes: List[Dict[str, Any]]) -> Optional[bytes]:
    if not holes:
        return None
    diams = [h["diameter_um"] for h in holes]
    circs = [h["circularity"] for h in holes]
    fig, ax = plt.subplots(figsize=(5.2, 2.4), dpi=150)
    ax.scatter(diams, circs, s=22, c="#0D9488", alpha=0.7,
               edgecolor="white", linewidth=0.6)
    ax.set_xlabel("Diameter (µm)", fontsize=9, color="#475569")
    ax.set_ylabel("Circularity", fontsize=9, color="#475569")
    ax.set_ylim(0, 1.05)
    ax.tick_params(labelsize=8, colors="#475569")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#CBD5E1")
    ax.grid(linestyle="--", linewidth=0.5, color="#E2E8F0", alpha=0.8)
    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ─── 페이지 헤더/푸터 ─────────────────────────────────────────────────────────
def _on_page(canvas, doc):
    canvas.saveState()
    w, h = A4
    # 상단 강조선
    canvas.setFillColor(ACCENT)
    canvas.rect(0, h - 4 * mm, w, 4 * mm, fill=1, stroke=0)
    # 푸터
    canvas.setFont(KFONT, 8)
    canvas.setFillColor(INK_MUTED)
    canvas.drawString(20 * mm, 10 * mm, "GIGO QC · Lacey Carbon Grid QC Report")
    canvas.drawRightString(w - 20 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


# ─── 섹션: 표지 / 요약 헤더 ───────────────────────────────────────────────────
def _build_cover(data: Dict[str, Any], S: Dict[str, ParagraphStyle]) -> list:
    qc = data.get("qc") or data.get("qc_result") or {}
    cls = data.get("classification") or {}
    stats = data.get("stats") or {}

    verdict = qc.get("verdict", "—")
    bg, fg, label = _verdict_palette(verdict)

    story: list = []
    story.append(Paragraph("GIGO QC Report", S["title"]))
    story.append(Paragraph(
        f"Lacey Carbon Grid 품질 검증 결과 · {data.get('filename', '—')}",
        S["subtitle"],
    ))

    # Verdict 배지
    verdict_style = ParagraphStyle(
        "vbadge", fontName=KFONT, fontSize=18, leading=22,
        textColor=fg, alignment=TA_CENTER,
    )
    verdict_cell = Paragraph(f"<b>{label}</b>", verdict_style)
    score_cell = Paragraph(
        f"<font size=9 color='#475569'>QC SCORE</font><br/>"
        f"<font size=22 color='#0F172A'><b>{int((qc.get('qc_score', 0) or 0) * 100)}</b></font>"
        f"<font size=12 color='#94A3B8'> / 100</font>",
        ParagraphStyle("score", fontName=KFONT, alignment=TA_CENTER, leading=24),
    )
    grid_cell = Paragraph(
        f"<font size=9 color='#475569'>BEST MATCH</font><br/>"
        f"<font size=11 color='#0F172A'><b>{cls.get('best_match', '—')}</b></font>",
        ParagraphStyle("gm", fontName=KFONT, alignment=TA_CENTER, leading=14),
    )

    header_tbl = Table(
        [[verdict_cell, score_cell, grid_cell]],
        colWidths=[55 * mm, 55 * mm, 60 * mm],
        rowHeights=[28 * mm],
    )
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), bg),
        ("BACKGROUND", (1, 0), (2, 0), SURFACE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEAFTER", (0, 0), (0, 0), 0.6, BORDER),
        ("LINEAFTER", (1, 0), (1, 0), 0.6, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 6 * mm))

    # 메타데이터 줄
    when = data.get("analysis_time") or ""
    try:
        when_disp = datetime.fromisoformat(when).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        when_disp = when or "—"
    meta = [
        ["분석 시각", when_disp],
        ["픽셀 스케일", f"{data.get('pixel_scale_nm', '—')} nm/px ({data.get('scale_source','—')})"],
        ["검출 홀 수", f"{stats.get('total_holes', 0)} 개"],
    ]
    meta_tbl = Table(meta, colWidths=[35 * mm, 135 * mm])
    meta_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), KFONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), INK_SECONDARY),
        ("TEXTCOLOR", (1, 0), (1, -1), INK_PRIMARY),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, BORDER),
    ]))
    story.append(meta_tbl)
    return story


# ─── 섹션: 프리뷰 이미지 ─────────────────────────────────────────────────────
def _build_preview(data: Dict[str, Any], S: Dict[str, ParagraphStyle]) -> list:
    b64 = data.get("overlay_png_base64") or data.get("preview_b64")
    if not b64:
        return []
    try:
        png = base64.b64decode(b64)
        img = PILImage.open(io.BytesIO(png))
        # 큰 이미지 다운샘플 (출력 가로 ~165mm 최대)
        max_w = 1600
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        rl_img = Image(buf)
        # 본문 폭 170mm에 맞춰 비율 유지
        target_w = 170 * mm
        ratio = target_w / rl_img.imageWidth
        rl_img.drawWidth = target_w
        rl_img.drawHeight = rl_img.imageHeight * ratio
    except Exception:
        return []

    story = [
        Paragraph("분석 프리뷰", S["h1"]),
        Paragraph(
            "검출된 홀의 윤곽선과 번호가 원본 이미지에 오버레이되어 있습니다.",
            S["caption"],
        ),
        Spacer(1, 3 * mm),
        rl_img,
        Spacer(1, 2 * mm),
        Paragraph(
            f"총 {(data.get('stats') or {}).get('total_holes', 0)}개의 홀이 검출되었습니다.",
            S["caption"],
        ),
    ]
    return story


# ─── 섹션: KPI 4종 ─────────────────────────────────────────────────────────────
def _kpi_card(label: str, value: str, S: Dict[str, ParagraphStyle]) -> Table:
    t = Table(
        [[Paragraph(value, S["kpi_val"])], [Paragraph(label, S["kpi_lbl"])]],
        colWidths=[40 * mm],
        rowHeights=[12 * mm, 6 * mm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


_MODE_KOR = {"fast": "빠름", "balanced": "균형", "precise": "정밀"}


def _build_kpis(stats: Dict[str, Any], S: Dict[str, ParagraphStyle], data: Dict[str, Any] | None = None) -> list:
    cards = [
        _kpi_card("평균 직경 (µm)", f"{stats.get('avg_diameter', 0):.2f}", S),
        _kpi_card("평균 원형도", f"{stats.get('avg_circularity', 0):.3f}", S),
        _kpi_card("밀도 (holes/µm²)", f"{stats.get('density_per_um2', 0):.3f}", S),
        _kpi_card("커버리지 (%)", f"{stats.get('coverage_pct', 0):.1f}", S),
    ]
    grid = Table([cards], colWidths=[42.5 * mm] * 4, rowHeights=[20 * mm])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
    ]))

    result = [Paragraph("주요 측정값", S["h1"]), Spacer(1, 1 * mm), grid]

    # v1.2.0: AI 기반 분석 메타 칩 (mode + avg_confidence)
    mode = (data or {}).get("mode")
    avg_conf = stats.get("avg_confidence")
    if mode or avg_conf is not None:
        parts = []
        if mode:
            parts.append(f"분석 모드: <b>{_MODE_KOR.get(mode, mode)}</b>")
        if avg_conf is not None:
            parts.append(f"AI 신뢰도: <b>{avg_conf:.2f}</b>")
        if stats.get("hough_added"):
            parts.append(f"Hough 보완: <b>+{stats['hough_added']}</b>")
        meta = "  ·  ".join(parts)
        result.extend([
            Spacer(1, 2 * mm),
            Paragraph(meta, S["body"]),
        ])

    return result


# ─── 섹션: QC 체크리스트 ──────────────────────────────────────────────────────
def _build_qc_checks(qc: Dict[str, Any], S: Dict[str, ParagraphStyle]) -> list:
    details = qc.get("details") or {}
    rows = [["검사 항목", "측정값", "기준", "결과"]]

    def _row(name_ko: str, key: str):
        d = details.get(key, {})
        val = d.get("value", "—")
        if isinstance(val, (int, float)):
            unit = d.get("unit", "")
            val = f"{val:.3f}{(' ' + unit) if unit else ''}"
        threshold = d.get("threshold") or d.get("range") or "—"
        passed = d.get("passed")
        mark = "✓ 통과" if passed else ("✗ 미달" if passed is not None else "—")
        return [name_ko, str(val), str(threshold), mark]

    rows.append(_row("홀 직경", "diameter_range"))
    rows.append(_row("원형도", "circularity"))
    rows.append(_row("홀 밀도", "density"))
    rows.append(_row("커버리지", "coverage"))

    tbl = Table(rows, colWidths=[45 * mm, 40 * mm, 50 * mm, 35 * mm])
    style = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), KFONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, SURFACE]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
    ])
    # 결과 컬럼 색 강조
    for i, row in enumerate(rows[1:], start=1):
        result = row[3]
        if result.startswith("✓"):
            style.add("TEXTCOLOR", (3, i), (3, i), PASS_FG)
        elif result.startswith("✗"):
            style.add("TEXTCOLOR", (3, i), (3, i), FAIL_FG)
    tbl.setStyle(style)

    return [Paragraph("QC 검사 결과", S["h1"]), tbl]


# ─── 섹션: 분류 및 추천 ───────────────────────────────────────────────────────
def _build_recommendation(cls: Dict[str, Any], qc: Dict[str, Any], S: Dict[str, ParagraphStyle]) -> list:
    parts: list = [Paragraph("그리드 적합성 분석", S["h1"])]

    parts.append(Paragraph(
        f"<b>최적 매칭:</b> {cls.get('best_match', '—')}", S["body"],
    ))
    if cls.get("all_suitable"):
        parts.append(Paragraph(
            "<b>적합 그리드 유형:</b> " + ", ".join(cls.get("all_suitable", [])),
            S["body"],
        ))
    if cls.get("unsuitable_for"):
        parts.append(Paragraph(
            "<b>부적합 그리드 유형:</b> " + ", ".join(cls.get("unsuitable_for", [])),
            S["body"],
        ))

    parts.append(Spacer(1, 3 * mm))
    rec = cls.get("recommendation") or "—"
    rec_tbl = Table([[Paragraph(rec, S["body"])]], colWidths=[170 * mm])
    rec_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    parts.append(rec_tbl)

    fail_msgs = qc.get("fail_messages") or []
    if fail_msgs:
        parts.append(Spacer(1, 4 * mm))
        parts.append(Paragraph("주의 사항", S["h2"]))
        for m in fail_msgs:
            parts.append(Paragraph(f"• {m}", S["body"]))
    return parts


# ─── 섹션: 차트 ────────────────────────────────────────────────────────────────
def _img_from_bytes(b: Optional[bytes], width_mm: float) -> Optional[Image]:
    if not b:
        return None
    bio = io.BytesIO(b)
    im = Image(bio)
    ratio = (width_mm * mm) / im.imageWidth
    im.drawWidth = width_mm * mm
    im.drawHeight = im.imageHeight * ratio
    return im


def _build_charts(holes: List[Dict[str, Any]], S: Dict[str, ParagraphStyle]) -> list:
    hist = _img_from_bytes(_chart_histogram(holes), 82)
    scat = _img_from_bytes(_chart_scatter(holes), 82)
    if not hist and not scat:
        return []
    rows: list = [Paragraph("분포 차트", S["h1"])]
    cap_h = Paragraph("홀 직경 히스토그램", S["caption"])
    cap_s = Paragraph("직경 vs 원형도", S["caption"])
    tbl = Table(
        [[cap_h, cap_s], [hist or "—", scat or "—"]],
        colWidths=[85 * mm, 85 * mm],
    )
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    rows.append(tbl)
    return rows


# ─── 섹션: Raw 데이터 (상위 30개) ─────────────────────────────────────────────
def _build_raw(holes: List[Dict[str, Any]], S: Dict[str, ParagraphStyle]) -> list:
    if not holes:
        return []
    head = ["#", "직경 (µm)", "원형도", "면적 (µm²)", "X (px)", "Y (px)"]
    rows = [head]
    for i, h in enumerate(holes[:30], start=1):
        rows.append([
            str(i),
            f"{h.get('diameter_um', 0):.3f}",
            f"{h.get('circularity', 0):.3f}",
            f"{h.get('area_um2', 0):.3f}",
            f"{int(h.get('center_x_px', 0))}",
            f"{int(h.get('center_y_px', 0))}",
        ])
    tbl = Table(rows, colWidths=[15*mm, 30*mm, 28*mm, 32*mm, 30*mm, 30*mm])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), KFONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, SURFACE]),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
    ]))
    extra = []
    if len(holes) > 30:
        extra.append(Paragraph(
            f"...상위 30개만 표시. 전체 {len(holes)}개 데이터는 CSV로 내보내기 하세요.",
            S["caption"],
        ))
    return [Paragraph("개별 홀 측정 데이터", S["h1"]), tbl] + extra


# ─── 메인: create_pdf ─────────────────────────────────────────────────────────
def create_pdf(data: Dict[str, Any]) -> bytes:
    """
    분석 결과 dict를 받아 PDF bytes를 반환한다.

    필수 키: filename, stats, classification, qc(또는 qc_result), holes
    선택: overlay_png_base64(또는 preview_b64), pixel_scale_nm, analysis_time
    """
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="GIGO QC Report",
        author="GIGO QC",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="main",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_on_page)])

    S = _styles()
    qc = data.get("qc") or data.get("qc_result") or {}
    cls = data.get("classification") or {}
    stats = data.get("stats") or {}
    holes = data.get("holes") or []

    story: list = []
    story.extend(_build_cover(data, S))
    story.append(Spacer(1, 6 * mm))
    story.extend(_build_kpis(stats, S, data))
    story.append(Spacer(1, 6 * mm))
    story.extend(_build_qc_checks(qc, S))
    story.append(Spacer(1, 4 * mm))
    story.extend(_build_recommendation(cls, qc, S))

    # 프리뷰 + 차트는 별도 페이지로
    preview = _build_preview(data, S)
    charts = _build_charts(holes, S)
    raw = _build_raw(holes, S)
    if preview or charts or raw:
        story.append(PageBreak())
    if preview:
        story.extend(preview)
        story.append(Spacer(1, 6 * mm))
    if charts:
        story.extend(charts)
        story.append(Spacer(1, 6 * mm))
    if raw:
        story.extend(raw)

    doc.build(story)
    return buf.getvalue()


# ─── CSV ──────────────────────────────────────────────────────────────────────
def create_csv(data: Dict[str, Any]) -> bytes:
    """
    Excel/한글 정상 표시를 위해 UTF-8 BOM 포함 CSV bytes 반환.
    """
    import csv

    holes = data.get("holes") or []
    stats = data.get("stats") or {}
    qc = data.get("qc") or data.get("qc_result") or {}
    cls = data.get("classification") or {}

    out = io.StringIO()
    out.write("\ufeff")  # BOM
    w = csv.writer(out)

    # 요약 헤더
    w.writerow(["# GIGO QC Report"])
    w.writerow(["Filename", data.get("filename", "")])
    w.writerow(["Analysis Time", data.get("analysis_time", "")])
    w.writerow(["Pixel Scale (nm/px)", data.get("pixel_scale_nm", "")])
    w.writerow(["Verdict", qc.get("verdict", "")])
    w.writerow(["QC Score", qc.get("qc_score", "")])
    w.writerow(["Best Match", cls.get("best_match", "")])
    w.writerow([])
    w.writerow(["# Statistics"])
    for k, v in stats.items():
        w.writerow([k, v])
    w.writerow([])

    # 홀 데이터
    w.writerow(["# Individual Holes"])
    w.writerow(["index", "diameter_um", "circularity", "area_um2",
                "center_x_px", "center_y_px"])
    for i, h in enumerate(holes, start=1):
        w.writerow([
            i,
            f"{h.get('diameter_um', 0):.4f}",
            f"{h.get('circularity', 0):.4f}",
            f"{h.get('area_um2', 0):.4f}",
            int(h.get("center_x_px", 0)),
            int(h.get("center_y_px", 0)),
        ])

    return out.getvalue().encode("utf-8")
