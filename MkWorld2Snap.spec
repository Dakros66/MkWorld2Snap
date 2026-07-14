# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(SPECPATH)
IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
MAC_ICON = PROJECT_ROOT / "assets" / "app-icon.icns"
WINDOWS_ICON = PROJECT_ROOT / "assets" / "app-icon.ico"
TARGET_ARCH = os.environ.get("PYINSTALLER_TARGET_ARCH") if IS_MACOS else None
if IS_MACOS and not TARGET_ARCH:
    TARGET_ARCH = "universal2"


def collect_tree(source: str, target: str):
    base = PROJECT_ROOT / source
    if not base.exists():
        return []
    collected = []
    for path in sorted(base.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            collected.append((str(path), str(Path(target) / path.relative_to(base).parent)))
    return collected


datas = [
    *collect_tree("frontend/dist", "frontend/dist"),
    *collect_tree("profiles", "profiles"),
    *collect_tree("rules", "rules"),
]

runtime_modules = [
    "local_gateway",
    "scene_metadata",
    "activity_report",
    "workshop_types",
    "static_security",
    "u1_packager",
    "reference_catalog",
    "spool_tuning",
    "parameter_guardrails",
    "pause_planner",
    "machine_script_library",
]

uvicorn_modules = [
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
]

a = Analysis(
    ["desktop_app.py"],
    pathex=[str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")],
    binaries=[],
    datas=datas,
    hiddenimports=[*runtime_modules, *uvicorn_modules],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if IS_WINDOWS or IS_MACOS or IS_LINUX:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        exclude_binaries=False,
        name="MkWorld2Snap",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=TARGET_ARCH,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(WINDOWS_ICON) if IS_WINDOWS and WINDOWS_ICON.exists() else None,
    )
if IS_MACOS:
    app = BUNDLE(
        exe,
        name="MkWorld2Snap.app",
        icon=str(MAC_ICON) if MAC_ICON.exists() else None,
        bundle_identifier="local.mkworld2snap.app",
        info_plist={
            "NSHighResolutionCapable": "True",
            "NSRequiresAquaSystemAppearance": "False",
        },
    )
