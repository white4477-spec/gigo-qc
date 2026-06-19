"""
GIGO QC — 일반 이미지 파서 (PNG/JPG/JPEG)
Pillow를 사용해 일반 이미지 포맷을 2D grayscale numpy array로 변환합니다.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


def parse_image(filepath: str) -> Tuple[np.ndarray, Optional[float]]:
    """
    PNG/JPG/JPEG 파일을 읽어 2D float32 grayscale array를 반환합니다.

    Parameters
    ----------
    filepath : str
        이미지 파일 경로

    Returns
    -------
    img_2d : np.ndarray
        2D float32 grayscale array
    pixel_scale_nm : float | None
        일반 이미지는 스케일 정보가 없으므로 항상 None.
    """
    try:
        from PIL import Image
    except ImportError:
        raise ImportError(
            "Pillow 라이브러리가 설치되지 않았습니다.\n"
            "설치 명령: pip install Pillow"
        )

    try:
        with Image.open(filepath) as img:
            # RGBA, 팔레트 등도 포함하여 grayscale('L')로 변환
            if img.mode != "L":
                img = img.convert("L")
            img_array = np.array(img, dtype=np.float32)
    except Exception as exc:
        raise ValueError(
            f"이미지 파일 파싱 중 오류가 발생했습니다: {exc}\n"
            "파일이 손상되었거나 지원하지 않는 이미지 형식일 수 있습니다."
        ) from exc

    if img_array.ndim != 2:
        raise ValueError(
            f"예상치 못한 이미지 형태: shape={img_array.shape}\n"
            "2D grayscale 이미지만 지원합니다."
        )

    return img_array, None  # 일반 이미지는 pixel scale 정보 없음
