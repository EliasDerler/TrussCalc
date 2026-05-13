# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

datas = [
    ('trusscalc/resources/default_truss_types.json', 'trusscalc/resources'),
    ('trusscalc/resources/logo_noisegate.pdf',       'trusscalc/resources'),
    ('trusscalc/resources/TrussCalcLogo.png',        'trusscalc/resources'),
    ('trusscalc/resources/TrussCalcLogo.ico',        'trusscalc/resources'),
    ('trusscalc/database/schema.sql',                'trusscalc/database'),
]

hiddenimports = [
    'PyQt6.QtPrintSupport',
    'anastruct',
    'scipy.spatial.transform._rotation_groups',
    'cv2',
] + collect_submodules('cv2')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='TrussCalc',
    icon='trusscalc/resources/TrussCalcLogo.ico',
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TrussCalc',
)
