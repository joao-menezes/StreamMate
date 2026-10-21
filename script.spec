# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('images', 'images'), ('fonts', 'fonts')]
datas += collect_data_files('customtkinter')
datas += collect_data_files('imageio_ffmpeg')   # binário do ffmpeg usado na conversão
datas += collect_data_files('pytubefix')

a = Analysis(
    ['script.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['darkdetect'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['moviepy', 'numpy', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='StreamMate',
    icon='images/streammate.ico',
    version='version_info.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
