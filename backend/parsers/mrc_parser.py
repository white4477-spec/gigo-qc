"""
GIGO QC — MRC/MRCS 파일 파서
mrcfile 라이브러리를 사용해 MRC/MRCS를 2D numpy array로 변환합니다.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


def parse_mrc(filepath: str) -> Tuple[np.ndarray, Optional[float]]:
    """
    MRC/MRCS 파일을 읽어 2D float32 array와 pixel scale(nm/px)을 반환합니다.

    Parameters
    ----------
    filepath : str
        MRC/MRCS 파일 경로

    Returns
    -------
    img_2d : np.ndarray
        2D float32 grayscale array
    pixel_scale_nm : float | None
        voxel_size(Å) → nm/px 변환 값. 추출 실패 시 None.
    """
    try:
        import mrcfile
    except ImportError:
        raise ImportError(
            "mrcfile 라이브러리가 설치되지 않았습니다.\n"
            "설치 명령: pip install mrcfile"
        )

    try:
        with mrcfile.open(filepath, mode="r", permissive=True) as mrc:
            data = mrc.data

            if data is None:
                raise ValueError("MRC 파일에 데이터가 없습니다.")

            # 3D(스택) 또는 2D 처리
            if data.ndim == 3:
                # 첫 번째 슬라이스 사용
                img_2d = data[0].copy().astype(np.float32)
            elif data.ndim == 2:
                img_2d = data.copy().astype(np.float32)
            else:
                raise ValueError(
                    f"지원하지 않는 MRC 데이터 차원: {data.ndim}D\n"
                    "2D 또는 3D(스택) 형식만 지원합니다."
                )

            # Voxel size에서 pixel scale 추출 (Å → nm: 1 Å = 0.1 nm)
            pixel_scale_nm = _extract_pixel_scale(mrc)

    except Exception as exc:
        # mrcfile 관련 에러를 사용자 친화적 메시지로 변환
        if "mrcfile" in type(exc).__module__:
            raise ValueError(
                f"MRC 파일 파싱 중 오류가 발생했습니다: {exc}\n"
                "파일이 손상되었거나 지원하지 않는 MRC 버전일 수 있습니다."
            ) from exc
        raise

    return img_2d, pixel_scale_nm


def _extract_pixel_scale(mrc) -> Optional[float]:
    """
    MRC 헤더에서 pixel scale (nm/px)을 추출합니다.
    voxel_size는 Å 단위이므로 0.1을 곱해 nm로 변환합니다.
    """
    try:
        vs = mrc.voxel_size
        # voxel_size는 structured array: vs.x, vs.y, vs.z (단위: Å)
        x_angstrom = float(vs.x)
        if x_angstrom > 0:
            return x_angstrom * 0.1  # Å → nm
    except Exception:
        pass
    return None
