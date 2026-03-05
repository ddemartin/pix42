# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Luma Viewer.

Run via build_windows.bat, which passes --distpath and --workpath.
SPECPATH is the scripts/ directory; project root is one level up.
"""

from pathlib import Path

project_dir = Path(SPECPATH).parent   # scripts/ -> project root

a = Analysis(
    [str(project_dir / "main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[
        (str(project_dir / "assets"), "assets"),
    ],
    hiddenimports=[
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtXml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Luma",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(project_dir / "assets" / "app" / "icon.ico"),
    # NOTE: icon.ico must be created from assets/app/icon.svg before building.
    # Quick conversion: use Inkscape, ImageMagick, or any online SVG-to-ICO tool.
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Luma",
)
