# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the portable, Python-free GUI build.

Build with::

    python tools/build_exe.py            # Windows, produces dist/kemono-dl-gui.exe

The resulting single file contains a complete CPython runtime plus ``requests``
and the whole ``kemono_dl`` downloader, so end users only have to double-click
it — no Python, no pip, no terminal.
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("kemono_dl") + collect_submodules("kemono_dl_gui")

analysis = Analysis(
    ["gui_main.py"],
    pathex=["."],
    binaries=[],
    datas=[("kemono_dl_gui/static", "kemono_dl_gui/static")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pydoc", "doctest", "test"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="kemono-dl-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
