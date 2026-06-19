"""
GIGO QC — 이미지 파서 패키지
지원 포맷: .mrc, .mrcs, .tif, .tiff, .png, .jpg, .jpeg
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .mrc_parser import parse_mrc
from .tiff_parser import parse_tiff
from .image_parser import parse_image


def parse_file(
    file_bytes: bytes,
    filename: str,
) -> Tuple[np.ndarray, Optional[float]]:
    """
    업로드된 파일 bytes를 받아 2D grayscale numpy array로 변환합니다.

    Parameters
    ----------
    file_bytes : bytes
        업로드된 파일의 raw bytes
    filename : str
        원본 파일명 (확장자 감지에 사용)

    Returns
    -------
    img_array : np.ndarray
        2D float32 array (grayscale)
    pixel_scale_nm : float | None
        MRC voxel_size에서 추출한 nm/pixel 값. 추출 실패 시 None.

    Raises
    ------
    ValueError
        지원하지 않는 파일 형식이거나 파싱에 실패한 경우
    """
    ext = Path(filename).suffix.lower()

    # 임시 파일에 저장 후 각 파서에 전달
    suffix = ext if ext else ".tmp"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        if ext in (".mrc", ".mrcs"):
            img, pixel_scale_nm = parse_mrc(tmp_path)
        elif ext in (".tif", ".tiff"):
            img, pixel_scale_nm = parse_tiff(tmp_path)
        elif ext in (".png", ".jpg", ".jpeg"):
            img, pixel_scale_nm = parse_image(tmp_path)
        else:
            raise ValueError(
                f"지원하지 않는 파일 형식입니다: '{ext}'\n"
                f"지원 형식: .mrc, .mrcs, .tif, .tiff, .png, .jpg, .jpeg"
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # 항상 2D float32로 정규화
    if img.ndim != 2:
        raise ValueError(
            f"이미지가 2D가 아닙니다 (shape={img.shape}). "
            "파싱 단계에서 문제가 발생했습니다."
        )

    img = img.astype(np.float32)
    return img, pixel_scale_nm


__all__ = ["parse_file", "parse_mrc", "parse_tiff", "parse_image"]
