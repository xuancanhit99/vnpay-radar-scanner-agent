import os
from pathlib import Path


project_root = Path(SPECPATH).parent
version_file = os.environ.get("RADAR_AGENT_VERSION_FILE")
icon_file = project_root / "logo" / "icon.ico"

analysis = Analysis(
    [str(project_root / "src" / "radar_agent" / "__main__.py")],
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
    [],
    exclude_binaries=True,
    name="radar-scanner-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    version=version_file,
    icon=str(icon_file),
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="radar-scanner-agent",
)
