# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import Tree

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Bundle complete project folders
a.datas += Tree("Steering", prefix="Steering")
a.datas += Tree("Game", prefix="Game")
a.datas += Tree("Assets", prefix="Assets")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Race Ahmed',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.icns'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Race Ahmed',
)

app = BUNDLE(
    coll,
    name='Race Ahmed.app',
    icon='icon.icns',
    bundle_identifier="com.antinfotech.raceahmed",
)