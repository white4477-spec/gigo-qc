# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for GIGO QC.
Build:  pyinstaller gigo-qc.spec --clean --noconfirm
Output: dist/GIGO-QC/GIGO-QC.exe  (--onedir 모드, 시작 빠름)
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("starlette")
hiddenimports += collect_submodules("anyio")
hiddenimports += collect_submodules("h11")
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("pydantic_core")
hiddenimports += [
    "mrcfile",
    "tifffile",
    "PIL",
    "PIL.Image",
    "cv2",
    "numpy",
    "scipy",
    "scipy.ndimage",
    "skimage",
    "skimage.measure",
    "skimage.morphology",
    # v1.2.0: AI 기반 홀 인식 의존성
    "skimage.feature",        # peak_local_max
    "skimage.segmentation",   # watershed
    "skimage.filters",        # threshold_sauvola, threshold_otsu
    "skimage._shared",
    "skimage._shared.utils",
    "reportlab",
    "reportlab.pdfgen",
    "reportlab.lib",
    "reportlab.platypus",
    "matplotlib",
    "matplotlib.backends.backend_agg",
]

datas = [
    ("frontend", "frontend"),
    ("backend", "backend"),
]
datas += collect_data_files("reportlab")
datas += collect_data_files("matplotlib")

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GIGO-QC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 로그 확인용 콘솔 창 유지
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="installer/icon.ico" if __import__("os").path.exists("installer/icon.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GIGO-QC",
)
