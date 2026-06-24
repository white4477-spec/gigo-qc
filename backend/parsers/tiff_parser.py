"""
GIGO QC — TIFF/TIF 파일 파서
tifffile 라이브러리를 사용해 TIFF를 2D numpy array로 변환합니다.
멀티페이지 TIFF의 경우 첫 번째 페이지를 사용합니다.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

import numpy as np


def parse_tiff(filepath: str) -> Tuple[np.ndarray, Optional[float]]:
    """
    TIFF/TIF 파일을 읽어 2D float32 array를 반환합니다.

    Returns
    -------
    img_2d : np.ndarray
    pixel_scale_nm : float | None
        TIFF 메타데이터(ImageJ, FEI, OME, XResolution)에서 추출 시도.
    """
    try:
        import tifffile
    except ImportError:
        raise ImportError(
            "tifffile 라이브러리가 설치되지 않았습니다.\n"
            "설치 명령: pip install tifffile"
        )

    try:
        data = tifffile.imread(filepath)
    except Exception as exc:
        raise ValueError(
            f"TIFF 파일 파싱 중 오류가 발생했습니다: {exc}\n"
            "파일이 손상되었거나 지원하지 않는 TIFF 형식일 수 있습니다."
        ) from exc

    if data is None or data.size == 0:
        raise ValueError("TIFF 파일에 이미지 데이터가 없습니다.")

    img_2d = _to_2d_grayscale(data)
    pixel_scale_nm = _extract_pixel_scale_tiff(filepath)

    return img_2d.astype(np.float32), pixel_scale_nm


def _to_2d_grayscale(data: np.ndarray) -> np.ndarray:
    """다차원 array를 2D grayscale로 변환합니다."""
    ndim = data.ndim
    shape = data.shape

    if ndim == 2:
        return data
    elif ndim == 3:
        if shape[-1] in (3, 4):
            return _rgb_to_gray(data[..., :3])
        else:
            return data[0]
    elif ndim == 4:
        if shape[-1] in (3, 4):
            return _rgb_to_gray(data[0, ..., :3])
        else:
            return data[0, 0]
    else:
        idx = tuple([0] * (ndim - 2))
        return data[idx]


def _rgb_to_gray(rgb: np.ndarray) -> np.ndarray:
    rgb_f = rgb.astype(np.float32)
    return (0.2989 * rgb_f[..., 0] +
            0.5870 * rgb_f[..., 1] +
            0.1140 * rgb_f[..., 2])


# ─── Pixel scale 추출 ─────────────────────────────────────────────────────────

def _extract_pixel_scale_tiff(filepath: str) -> Optional[float]:
    """
    TIFF 메타에서 pixel scale (nm/px)을 추출합니다.

    우선 순위:
      1) ImageJ ImageDescription (가장 흔한 TEM workflow)
      2) FEI/Helios/Tecnai/Titan metadata
      3) OME-XML PhysicalSizeX
      4) TIFF 표준 XResolution (cm/inch — 신뢰도 낮음, 보수적)
    """
    try:
        import tifffile
        with tifffile.TiffFile(filepath) as tif:
            page = tif.pages[0]
            tags = page.tags

            scale = _try_imagej(tif, tags)
            if scale is not None:
                return scale

            scale = _try_fei(tif, tags)
            if scale is not None:
                return scale

            scale = _try_ome(tif)
            if scale is not None:
                return scale

            scale = _try_standard_resolution(tags)
            if scale is not None:
                return scale
    except Exception:
        pass
    return None


def _sanitize_nm_per_px(value) -> Optional[float]:
    """합리적인 범위(0.001 ~ 10000 nm/px)만 반환."""
    try:
        v = float(value)
        if 0.001 <= v <= 10_000.0:
            return v
    except (TypeError, ValueError):
        pass
    return None


def _try_imagej(tif, tags) -> Optional[float]:
    """ImageJ TIFF: unit + XResolution 기반."""
    unit = ""
    # tifffile 고수준
    try:
        meta = getattr(tif, "imagej_metadata", None)
        if isinstance(meta, dict):
            unit = (meta.get("unit") or "").strip()
    except Exception:
        pass

    # ImageDescription 원문 파싱 fallback
    if not unit:
        try:
            desc_tag = tags.get("ImageDescription")
            if desc_tag is not None:
                text = desc_tag.value
                if isinstance(text, bytes):
                    text = text.decode("utf-8", errors="ignore")
                if isinstance(text, str):
                    m = re.search(r"unit\s*=\s*([^\r\n]+)", text)
                    if m:
                        unit = m.group(1).strip()
        except Exception:
            pass

    if not unit:
        return None

    unit_factor = _unit_factor(unit)
    if unit_factor is None:
        return None

    try:
        x_res = tags.get("XResolution")
        if x_res is not None:
            val = x_res.value
            if isinstance(val, tuple) and len(val) == 2 and val[1] != 0:
                px_per_unit = val[0] / val[1]
                if px_per_unit > 0:
                    return _sanitize_nm_per_px(unit_factor / px_per_unit)
    except Exception:
        pass
    return None


def _try_fei(tif, tags) -> Optional[float]:
    """FEI/Helios/Tecnai metadata → PixelWidth (단위: meter)."""
    # tifffile 고수준 property
    try:
        fei = getattr(tif, "fei_metadata", None)
        if isinstance(fei, dict):
            scan = fei.get("Scan") or {}
            pw = scan.get("PixelWidth")
            if pw:
                s = _sanitize_nm_per_px(float(pw) * 1e9)
                if s is not None:
                    return s
    except Exception:
        pass

    # 원문 텍스트 파싱
    try:
        for tag_name in ("FEI_HELIOS", "FEI_TITAN", "FEI_SFEG", "FEI_BEAM"):
            t = tags.get(tag_name)
            if t is None:
                continue
            text = t.value
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="ignore")
            if not isinstance(text, str):
                continue
            m = re.search(r"PixelWidth\s*=\s*([0-9.eE+\-]+)", text)
            if m:
                try:
                    s = _sanitize_nm_per_px(float(m.group(1)) * 1e9)
                    if s is not None:
                        return s
                except ValueError:
                    pass
    except Exception:
        pass
    return None


def _try_ome(tif) -> Optional[float]:
    """OME-XML PhysicalSizeX (+ unit)."""
    try:
        ome = getattr(tif, "ome_metadata", None)
        if not ome:
            return None
        m_size = re.search(r'PhysicalSizeX\s*=\s*"([0-9.eE+\-]+)"', ome)
        m_unit = re.search(r'PhysicalSizeXUnit\s*=\s*"([^"]+)"', ome)
        if m_size:
            value = float(m_size.group(1))
            unit = (m_unit.group(1) if m_unit else "um").strip()
            unit_factor = _unit_factor(unit)
            if unit_factor is not None:
                return _sanitize_nm_per_px(value * unit_factor)
    except Exception:
        pass
    return None


def _try_standard_resolution(tags) -> Optional[float]:
    """표준 TIFF XResolution + ResolutionUnit (일반 카메라용 — 보수적)."""
    try:
        x_res_tag = tags.get("XResolution")
        res_unit_tag = tags.get("ResolutionUnit")
        if x_res_tag is None:
            return None
        val = x_res_tag.value
        if not (isinstance(val, tuple) and len(val) == 2 and val[0] > 0):
            return None
        px_per_unit = val[0] / val[1] if val[1] != 0 else val[0]
        res_unit = res_unit_tag.value if res_unit_tag else 2
        if res_unit == 2:
            nm_per_px = 25_400_000.0 / px_per_unit  # inch
        elif res_unit == 3:
            nm_per_px = 10_000_000.0 / px_per_unit  # cm
        else:
            return None
        # 100 nm/px 초과면 일반 카메라 DPI일 가능성 — 무시
        if nm_per_px > 100:
            return None
        return _sanitize_nm_per_px(nm_per_px)
    except Exception:
        pass
    return None


def _unit_factor(unit: str) -> Optional[float]:
    """단위 문자열을 nm 단위로 바꾸는 계수 반환."""
    u = unit.lower().strip()
    # μ/µ 정규화
    u = u.replace("\u03bc", "u").replace("\u00b5", "u")
    # 끝의 점/공백 제거
    u = u.rstrip(".").strip()
    table = {
        "nm": 1.0,
        "nanometer": 1.0,
        "nanometers": 1.0,
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
        "\u00c5": 0.1,
    }
    return table.get(u)
