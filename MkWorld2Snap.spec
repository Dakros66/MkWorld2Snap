# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


PROJECT_ROOT = Path(SPECPATH)


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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MkWorld2Snap",
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
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MkWorld2Snap",
)
app = BUNDLE(
    coll,
    name="MkWorld2Snap.app",
    icon=None,
    bundle_identifier="local.mkworld2snap.app",
    info_plist={
        "NSHighResolutionCapable": "True",
        "NSRequiresAquaSystemAppearance": "False",
    },
)
