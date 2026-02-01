# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

project_root = Path.cwd()
assets_dir = project_root / "assets"

# -------------------------------------------------
# Platform flags
# -------------------------------------------------
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# -------------------------------------------------
# Icons
# -------------------------------------------------
WIN_ICON = str(assets_dir / "Namecards.ico")
MAC_ICON = str(assets_dir / "Namecards.icns")

# -------------------------------------------------
# Hidden imports (Qt / OpenGL)
# -------------------------------------------------
hiddenimports = (
    collect_submodules("pyqtgraph.opengl")
    + collect_submodules("OpenGL")
    + [
        "PySide6.QtSvg",
        "PySide6.QtOpenGL",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ]
)

# -------------------------------------------------
# Analysis
# -------------------------------------------------
a = Analysis(
    ["gui.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # ETC resources (OpenSCAD / STL base)
        ("etc", "etc"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# -------------------------------------------------
# PYZ
# -------------------------------------------------
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

# -------------------------------------------------
# Executable
# -------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Namecards",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,  # GUI app
    icon=WIN_ICON if IS_WIN else None,
)

# -------------------------------------------------
# macOS bundle (.app)
# -------------------------------------------------
if IS_MAC:
    app = BUNDLE(
        exe,
        name="Namecards.app",
        icon=MAC_ICON,
        bundle_identifier="com.open.namecards",
        info_plist={
            "CFBundleName": "Namecards",
            "CFBundleDisplayName": "Namecards",
            "CFBundleIdentifier": "com.open.namecards",
            "NSHighResolutionCapable": True,
        },
    )