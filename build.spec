# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec (onedir / windowed).

ExifTool is staged into ./exiftool/ by CI (or manually) before building.
When present, it is bundled into the app's internal folder, where
core._resolve_exiftool looks for exiftool.exe (next to the bundled modules).
When absent, the app falls back to an exiftool found on PATH at runtime.
"""
import os

datas = []
_exe = os.path.join("exiftool", "exiftool.exe")
_files = os.path.join("exiftool", "exiftool_files")
if os.path.exists(_exe):
    datas.append((_exe, "."))
if os.path.isdir(_files):
    datas.append((_files, "exiftool_files"))

a = Analysis(
    ["main_gui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LightroomJpgRawBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LightroomJpgRawBridge",
)
