# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\WandaoOS_Local\\WandaoLaunchpad\\run.py'],
    pathex=['D:\\WandaoOS_Local\\WandaoLaunchpad'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5.QtWebEngineCore', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtQml', 'PyQt5.QtQuick', 'PyQt5.QtSql', 'PyQt5.QtPdf', 'PyQt5.QtTest', 'tkinter', 'PyQt5.QtDesigner', 'PyQt5.QtBluetooth', 'PyQt5.QtNfc', 'PyQt5.QtLocation'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WandaoLaunchpad',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WandaoLaunchpad',
)
