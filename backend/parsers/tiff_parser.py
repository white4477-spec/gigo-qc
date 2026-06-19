"""
GIGO QC — TIFF/TIF 파일 파서
tifffile 라이브러리를 사용해 TIFF를 2D numpy array로 변환합니다.
멀티페이지 TIFF의 경우 첫 번째 페이지를 사용합니다.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


def parse_tiff(filepath: str) -> Tuple[np.ndarray, Optional[float]]:
    """
    TIFF/TIF 파일을 읽어 2D float32 array를 반환합니다.

    Parameters
    ----------
    filepath : str
        TIFF 파일 경로

    Returns
    -------
    img_2d : np.ndarray
        2D float32 grayscale array
    pixel_scale_nm : float | None
        TIFF 메타데이터에서 추출 시도. 일반적으로 None.
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
    """
    다차원 array를 2D grayscale로 변환합니다.

    - 2D: 그대로 사용
    - 3D (Z, Y, X): 첫 번째 Z 슬라이스
    - 3D (Y, X, C): RGB → grayscale (마지막 축이 3 또는 4)
    - 4D (Z, Y, X, C): 첫 슬라이스 후 RGB → grayscale
    """
    ndim = data.ndim
    shape = data.shape

    if ndim == 2:
        return data

    elif ndim == 3:
        # (Y, X, C) — 컬러 이미지
        if shape[-1] in (3, 4):
            return _rgb_to_gray(data[..., :3])
        # (Z, Y, X) — 스택, 첫 슬라이스
        else:
            return data[0]

    elif ndim == 4:
        # (Z, Y, X, C)
        if shape[-1] in (3, 4):
            return _rgb_to_gray(data[0, ..., :3])
        # (Z, C, Y, X) 또는 기타
        else:
            return data[0, 0]

    else:
        # 그 외는 첫 번째 2D 슬라이스 추출 시도
        idx = tuple([0] * (ndim - 2))
        return data[idx]


def _rgb_to_gray(rgb: np.ndarray) -> np.ndarray:
    """표준 luminance 가중치로 RGB → grayscale 변환."""
    rgb_f = rgb.astype(np.float32)
    return (0.2989 * rgb_f[..., 0] +
            0.5870 * rgb_f[..., 1] +
            0.1140 * rgb_f[..., 2])


def _extract_pixel_scale_tiff(filepath: str) -> Optional[float]:
    """
    TIFF XResolution 태그에서 pixel scale 추출을 시도합니다.
    TEM TIFF는 보통 nm/px 정보를 별도 태그에 저장하므로
    일반적으로는 None을 반환합니다.
    """
    try:
        import tifffile
        with tifffile.TiffFile(filepath) as tif:
            page = tif.pages[0]
            tags = page.tags
            # XResolution / YResolution (픽셀/단위, TIFF 표준)
            x_res_tag = tags.get("XResolution")
            res_unit_tag = tags.get("ResolutionUnit")
            if x_res_tag is not None:
                val = x_res_tag.value
                # Rational (분자, 분모) 형식
                if isinstance(val, tuple) and len(val) == 2 and val[0] > 0:
                    px_per_unit = val[0] / val[1] if val[1] != 0 else val[0]
                    res_unit = res_unit_tag.value if res_unit_tag else 2
                    # 2 = inch, 3 = cm
                    if res_unit == 2:  # inch
                        nm_per_px = 25_400_000.0 / px_per_unit
                    elif res_unit == 3:  # cm
                        nm_per_px = 10_000_000.0 / px_per_unit
                    else:
                        return None
                    # 합리적인 범위(0.01~10000 nm/px)만 반환
                    if 0.01 <= nm_per_px <= 10000:
                        return nm_per_px
    except Exception:
        pass
    return None
