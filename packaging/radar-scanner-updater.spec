import os
from pathlib import Path


project_root = Path(SPECPATH).parent
version_file = os.environ.get("RADAR_UPDATER_VERSION_FILE")

analysis = Analysis(
    [str(project_root / "src" / "radar_agent" / "updater_main.py")],
    pathex=[str(project_root / "src")],
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
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="radar-scanner-updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    uac_admin=True,
    version=version_file,
)
