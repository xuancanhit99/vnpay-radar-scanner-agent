import os
from pathlib import Path


project_root = Path(SPECPATH).parent
version_file = os.environ.get("RADAR_MANAGER_VERSION_FILE")
icon_file = project_root / "logo" / "icon.ico"
brand_data = [
    (str(project_root / "logo" / "icon.ico"), "logo"),
    (str(project_root / "logo" / "icon.svg"), "logo"),
    (str(project_root / "logo" / "logo.svg"), "logo"),
]

analysis = Analysis(
    [str(project_root / "src" / "radar_agent" / "manager_main.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=brand_data,
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
    name="radar-scanner-manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    uac_admin=True,
    version=version_file,
    icon=str(icon_file),
)
