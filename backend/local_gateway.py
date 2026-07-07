"""FastAPI entrypoint for the local MkWorld2Snap engine.

Endpoints:

  POST   /engine/jobs/u1              build a U1-ready package and return a job id
  POST   /engine/jobs/target-profile        beta cross-profile rebuild
  GET    /engine/jobs/{job_id}/artifact    fetch the built .3mf
  GET    /engine/reference-shelf             list U1 reference profiles
  GET    /engine/target-shelf       list Target Shelf shelf entries
  GET    /engine/spool-tuning                list YAML recipes
  POST   /engine/spool-tuning                create a new recipe
  GET    /engine/spool-tuning/{name}         fetch one recipe as raw YAML
  PUT    /engine/spool-tuning/{name}         update recipe YAML
  DELETE /engine/spool-tuning/{name}         delete recipe
  POST   /engine/spool-tuning/probe     inspect a 3MF and return matching recipes

Static file serving for the built frontend lives at /.
"""
from __future__ import annotations
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from u1_packager import forge_package, is_painted_model, _MULTIPLATE_SPAN_MM
from activity_report import compose_report_sections
from workshop_types import BuildRequestSettings, ProfileCard, RecipeDefinition
from reference_catalog import ProfileLoadError, ProfileNotFoundError, list_profiles, read_project_settings, read_source_settings, resolve_profile, suggest_profile
from scene_preview import build_preview_scene
from spool_tuning import SpoolMatchContext, RecipeLoadError, serialise_recipe, find_recipe_hits, load_recipe_file, load_recipe_book
from static_security import SECURITY_HEADERS, render_privacy_html
from watch_folders import FolderWatchService, _thumbnail_data_url
logger = logging.getLogger('mkworld2snap')

class _DropHealthcheckAccessLogs(logging.Filter):

    def filter(self, record: logging.LogRecord) -> bool:
        return '"GET /engine/ping ' not in record.getMessage()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
logging.getLogger('uvicorn.access').addFilter(_DropHealthcheckAccessLogs())

def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)
APP_ROOT = Path(_env('MKWORLD2SNAP_APP_ROOT', '/app'))
_MAX_TOOLHEADS = 4
PROFILES_DIR = Path(_env('MKWORLD2SNAP_PROFILES', str(APP_ROOT / 'profiles')))
USER_PROFILES_DIR = Path(_env('MKWORLD2SNAP_USER_PROFILES', str(APP_ROOT / 'user_profiles')))
TARGET_PROFILES_DEFAULT_DIR = Path(_env('MKWORLD2SNAP_TARGET_PROFILES', str(APP_ROOT / 'target_profiles')))
RULES_DIR = Path(_env('MKWORLD2SNAP_RULES', str(APP_ROOT / 'rules')))
TMP_DIR = Path(_env('MKWORLD2SNAP_TMP', str(APP_ROOT / 'tmp')))
FAILED_TMP_DIR = Path(_env('MKWORLD2SNAP_FAILED_TMP', str(APP_ROOT / 'tmp_failed')))
FRONTEND_DIST = Path(_env('MKWORLD2SNAP_FRONTEND_DIST', str(APP_ROOT / 'frontend' / 'dist')))
MAX_UPLOAD_MB = int(os.environ.get('MAX_UPLOAD_MB', '500'))
CLEANUP_AFTER_SECONDS = int(os.environ.get('CLEANUP_TEMP_AFTER_SECONDS', '300'))
SITE_URL = 'https://' + os.environ.get('DOMAINHOST', 'localhost').rstrip('/')
FAILED_CLEANUP_AFTER_SECONDS = int(os.environ.get('CLEANUP_FAILED_TEMP_AFTER_SECONDS', str(7 * 24 * 60 * 60)))
RETAIN_FAILED_FILES = os.environ.get('RETAIN_FAILED_FILES', 'false').lower() in ('1', 'true', 'yes')
CONFIG_FILE = Path(os.environ.get('MKWORLD2SNAP_CONFIG', TMP_DIR.parent / 'settings.json'))
HISTORY_FILE = CONFIG_FILE.parent / 'conversion_history.json'
for d in (PROFILES_DIR, USER_PROFILES_DIR, TARGET_PROFILES_DEFAULT_DIR, RULES_DIR, TMP_DIR, FAILED_TMP_DIR):
    d.mkdir(parents=True, exist_ok=True)
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()

def _read_history() -> list[dict[str, Any]]:
    try:
        if HISTORY_FILE.exists():
            data = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
            records = data.get('records', [])
            if isinstance(records, list):
                return [record for record in records if isinstance(record, dict)]
    except Exception:
        logger.exception('failed to read history file %s', HISTORY_FILE)
    return []

def _write_history(records: list[dict[str, Any]]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps({'records': records[:250]}, indent=2, sort_keys=True), encoding='utf-8')

def _history_add(record: dict[str, Any]) -> None:
    records = _read_history()
    records = [existing for existing in records if existing.get('job_id') != record.get('job_id')]
    records.insert(0, record)
    _write_history(records)

def _folder_stats(path: Path) -> dict[str, int]:
    files = 0
    total = 0
    if not path.exists():
        return {'files': 0, 'bytes': 0}
    for item in path.rglob('*'):
        if item.is_file():
            files += 1
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return {'files': files, 'bytes': total}

def _failed_diagnostics() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not FAILED_TMP_DIR.exists():
        return rows
    for folder in sorted((item for item in FAILED_TMP_DIR.iterdir() if item.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
        payload = {'folder': str(folder), 'retained_at': int(folder.stat().st_mtime)}
        error_file = folder / 'error.json'
        if error_file.exists():
            try:
                loaded = json.loads(error_file.read_text(encoding='utf-8'))
                if isinstance(loaded, dict):
                    payload.update(loaded)
            except Exception:
                logger.exception('failed to read diagnostic %s', error_file)
        rows.append(payload)
    return rows[:50]

def _register_job(job_id: str, output_path: Path, diff_payload: dict, *, source_path: Path | None=None, reference_path: Path | None=None, settings: BuildRequestSettings | None=None) -> None:
    with _JOBS_LOCK:
        _JOBS[job_id] = {'output_path': output_path, 'diff': diff_payload, 'created_at': time.time(), 'source_path': source_path, 'reference_path': reference_path, 'settings': settings}
    try:
        report = diff_payload.get('report', {}) if isinstance(diff_payload, dict) else {}
        counts = diff_payload.get('counts', {}) if isinstance(diff_payload, dict) else {}
        thumbnail = _thumbnail_data_url(output_path) if output_path.exists() else None
        profile = getattr(settings, 'reference_profile', None)
        _history_add({
            'job_id': job_id,
            'mode': 'manual',
            'status': 'converted',
            'source_filename': report.get('source_filename') or (source_path.name if source_path else ''),
            'output_filename': report.get('output_filename') or output_path.name,
            'output_path': str(output_path),
            'source_path': str(source_path) if source_path else None,
            'reference_profile': profile,
            'created_at': time.time(),
            'counts': counts,
            'thumbnail': thumbnail,
        })
    except Exception:
        logger.exception('failed to update conversion history for %s', job_id)

def _get_job(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)

def _ensure_3mf_suffix(path: Path) -> Path:
    return path if path.name.lower().endswith('.3mf') else path.with_name(f'{path.name}.3mf')

def _applescript_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

def _choose_save_path(suggested_name: str) -> Path | None:
    if os.environ.get('MKWORLD2SNAP_SAVE_DIALOG', '1') == '0':
        return None
    local_00 = Path(suggested_name or 'converted.3mf').name
    if sys.platform == 'darwin':
        local_01 = '\n'.join([f'set defaultName to {_applescript_string(local_00)}', 'set defaultFolder to (path to downloads folder)', 'set chosenFile to choose file name with prompt "Save converted 3MF as:" default name defaultName default location defaultFolder', 'POSIX path of chosenFile'])
        local_02 = subprocess.run(['osascript', '-e', local_01], capture_output=True, text=True, check=False)
        if local_02.returncode != 0:
            return None
        local_03 = local_02.stdout.strip()
        return _ensure_3mf_suffix(Path(local_03)) if local_03 else None
    return None

def _reveal_saved_file(path: Path) -> bool:
    if os.environ.get('MKWORLD2SNAP_REVEAL_SAVED', '1') == '0':
        return False
    try:
        if sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', str(path)])
        elif os.name == 'nt':
            subprocess.Popen(['explorer', f'/select,{path}'])
        else:
            subprocess.Popen(['xdg-open', str(path.parent)])
        return True
    except Exception:
        logger.exception('failed to reveal saved file %s', path)
        return False

def _retain_failed_workdir(*, job_id: str, workdir: Path, endpoint: str, filename: str, reference_profile: str, detail: str, error_type: str, request_meta: dict[str, Any]) -> None:
    if not workdir.exists():
        return
    if not RETAIN_FAILED_FILES:
        shutil.rmtree(workdir, ignore_errors=True)
        return
    local_00 = FAILED_TMP_DIR / f'{int(time.time())}-{job_id}'
    try:
        shutil.move(str(workdir), str(local_00))
        local_01 = {'job_id': job_id, 'endpoint': endpoint, 'filename': filename, 'reference_profile': reference_profile, 'error_type': error_type, 'detail': detail, 'request_meta': request_meta, 'retained_at': int(time.time())}
        (local_00 / 'error.json').write_text(json.dumps(local_01, indent=2, sort_keys=True), encoding='utf-8')
        logger.warning('retained failed upload  file=%s  reason=%s', local_01.get('filename', '?'), local_01.get('detail', '?'))
    except Exception:
        logger.exception('failed to retain workdir %s', workdir)
        shutil.rmtree(workdir, ignore_errors=True)

def _cleanup_tmp_dir(now: float) -> None:
    """Remove TMP_DIR subdirectories older than CLEANUP_AFTER_SECONDS.

    Covers both in-registry jobs and orphaned dirs from previous container
    sessions (which never appear in _JOBS after a restart).
    """
    with _JOBS_LOCK:
        local_00 = set(_JOBS.keys())
    for local_01 in TMP_DIR.iterdir():
        if not local_01.is_dir():
            continue
        if local_01.name in local_00:
            continue
        try:
            local_02 = now - local_01.stat().st_mtime
        except FileNotFoundError:
            continue
        if local_02 > CLEANUP_AFTER_SECONDS:
            shutil.rmtree(local_01, ignore_errors=True)
            logger.info('cleanup: removed orphaned workdir %s', local_01.name)

def _cleanup_loop() -> None:
    while True:
        time.sleep(30)
        local_00 = time.time()
        local_01: list[str] = []
        with _JOBS_LOCK:
            for local_02, local_03 in _JOBS.items():
                if local_00 - local_03['created_at'] > CLEANUP_AFTER_SECONDS:
                    local_01.append(local_02)
            for local_02 in local_01:
                local_03 = _JOBS.pop(local_02)
                local_04 = local_03['output_path']
                if isinstance(local_04, Path) and local_04.exists():
                    local_05 = local_04.parent
                    shutil.rmtree(local_05, ignore_errors=True)
        _cleanup_tmp_dir(local_00)
        for local_05 in FAILED_TMP_DIR.iterdir():
            if not local_05.is_dir():
                continue
            try:
                local_06 = local_00 - local_05.stat().st_mtime
            except FileNotFoundError:
                continue
            if local_06 > FAILED_CLEANUP_AFTER_SECONDS:
                shutil.rmtree(local_05, ignore_errors=True)
threading.Thread(target=_cleanup_loop, daemon=True).start()
app = FastAPI(title='MkWorld2Snap Local Engine', version='0.1.0')

@app.middleware('http')
async def _security_headers(request: Request, call_next):
    local_00 = await call_next(request)
    for local_01, local_02 in SECURITY_HEADERS.items():
        local_00.headers[local_01] = local_02
    return local_00
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
_RULE_NAME_RE = re.compile('^[A-Za-z0-9 _.\\-]+$')

def _load_settings() -> dict[str, Any]:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    except Exception:
        logger.exception('failed to read settings file %s', CONFIG_FILE)
    return {}

def _save_settings(settings: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding='utf-8')

def _target_profiles_dir() -> Path:
    local_00 = _load_settings().get('target_profiles_dir')
    if isinstance(local_00, str) and local_00.strip():
        return Path(local_00).expanduser()
    return TARGET_PROFILES_DEFAULT_DIR

def _set_target_profiles_dir(path: Path) -> Path:
    local_00 = path.expanduser().resolve()
    if not local_00.exists() or not local_00.is_dir():
        raise HTTPException(400, detail='selected path is not a folder')
    local_01 = _load_settings()
    local_01['target_profiles_dir'] = str(local_00)
    _save_settings(local_01)
    return local_00

def _choose_folder_macos(prompt: str) -> Path | None:
    if sys.platform != 'darwin':
        return None
    local_00 = '\n'.join([f'set chosenFolder to choose folder with prompt {_applescript_string(prompt)}', 'POSIX path of chosenFolder'])
    local_01 = subprocess.run(['osascript', '-e', local_00], capture_output=True, text=True, check=False)
    if local_01.returncode != 0:
        return None
    local_02 = local_01.stdout.strip()
    return Path(local_02) if local_02 else None

def _choose_folders_macos(prompt: str) -> list[Path]:
    if sys.platform != 'darwin':
        return []
    local_00 = '\n'.join([
        f'set chosenFolders to choose folder with prompt {_applescript_string(prompt)} with multiple selections allowed',
        'set outputText to ""',
        'repeat with chosenFolder in chosenFolders',
        '  set outputText to outputText & POSIX path of chosenFolder & linefeed',
        'end repeat',
        'outputText',
    ])
    local_01 = subprocess.run(['osascript', '-e', local_00], capture_output=True, text=True, check=False)
    if local_01.returncode != 0:
        return []
    return [Path(local_02.strip()) for local_02 in local_01.stdout.splitlines() if local_02.strip()]

def _rule_filename(name: str) -> Path:
    if not _RULE_NAME_RE.fullmatch(name):
        raise HTTPException(400, detail='invalid rule name')
    local_00 = name.strip().replace(' ', '_')
    return RULES_DIR / f'{local_00}.yaml'

_FOLDER_WATCH = FolderWatchService(config_file=CONFIG_FILE, profiles_dir=PROFILES_DIR, user_profiles_dir=USER_PROFILES_DIR, rules_dir=RULES_DIR, tmp_dir=TMP_DIR, max_file_mb=MAX_UPLOAD_MB)
_FOLDER_WATCH.start()

class WatchTogglePayload(BaseModel):
    enabled: bool

class WatchPathPayload(BaseModel):
    path: str

class PathActionPayload(BaseModel):
    path: str

class RebuildPayload(BaseModel):
    custom_overrides: dict[str, Any] = {}
    default_keys: list[str] = []
    exclude_object: bool | None = None

def _parameter_group(key: str) -> str:
    local_00 = key.lower()
    if any(local_01 in local_00 for local_01 in ('layer', 'line_width', 'wall', 'seam', 'ironing', 'quality', 'resolution')):
        return 'Quality'
    if any(local_01 in local_00 for local_01 in ('infill', 'solid', 'sparse', 'shell', 'top_', 'bottom_', 'strength')):
        return 'Strength'
    if any(local_01 in local_00 for local_01 in ('speed', 'accel', 'jerk', 'travel', 'slow', 'fan', 'cooling', 'flow')):
        return 'Speed'
    if any(local_01 in local_00 for local_01 in ('support', 'raft', 'brim', 'skirt')):
        return 'Supports'
    if any(local_01 in local_00 for local_01 in ('filament', 'nozzle_temperature', 'hot_plate', 'bed_', 'temperature', 'extruder', 'wipe', 'prime_tower', 'flush', 'ams')):
        return 'Multimaterial'
    return 'Others'

def _iter_setting_values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]

def _lint_source_settings(settings: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    filament_count = len(settings.get('filament_settings_id') or [])
    for key, value in settings.items():
        key_lower = key.lower()
        if key_lower.endswith('_filament') or key_lower in {'wall_filament', 'sparse_infill_filament', 'solid_infill_filament'}:
            for item in _iter_setting_values(value):
                try:
                    index = int(str(item).strip())
                except (TypeError, ValueError):
                    continue
                if filament_count and (index < 1 or index > filament_count):
                    issues.append({
                        'key': key,
                        'value': item,
                        'severity': 'error',
                        'message': f'filament index must be between 1 and {filament_count}',
                    })
        if key_lower == 'raft_first_layer_expansion':
            for item in _iter_setting_values(value):
                try:
                    numeric = float(str(item).strip())
                except (TypeError, ValueError):
                    continue
                if numeric < 0:
                    issues.append({'key': key, 'value': item, 'severity': 'error', 'message': 'must be 0 or higher'})
        if key_lower == 'tree_support_wall_count':
            for item in _iter_setting_values(value):
                try:
                    numeric = int(str(item).strip())
                except (TypeError, ValueError):
                    continue
                if numeric < 0 or numeric > 2:
                    issues.append({'key': key, 'value': item, 'severity': 'error', 'message': 'must be between 0 and 2'})
    return issues[:80]

def _read_project_settings_from_job(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    local_00 = job.get('output_path')
    if not isinstance(local_00, Path) or not local_00.exists():
        raise HTTPException(410, detail='output file was cleaned up')
    try:
        local_01 = read_project_settings(local_00)
    except ProfileLoadError as err:
        raise HTTPException(400, detail=str(err)) from err
    local_02: dict[str, Any] = {}
    local_03 = job.get('reference_path')
    if isinstance(local_03, Path) and local_03.exists():
        try:
            local_02 = read_project_settings(local_03)
        except ProfileLoadError:
            logger.warning('could not read reference settings from %s', local_03)
    return local_01, local_02

@app.get('/engine/reference-shelf', response_model=list[ProfileCard])
def list_reference_shelf() -> list[ProfileCard]:
    return list_profiles(PROFILES_DIR, USER_PROFILES_DIR)

@app.post('/engine/reference-shelf/import')
async def import_reference_profiles(files: list[UploadFile]=File(...)) -> JSONResponse:
    imported: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for upload in files:
        if not upload.filename or not upload.filename.lower().endswith('.3mf'):
            errors.append({'name': upload.filename or 'unknown', 'error': 'expected a .3mf file'})
            continue
        safe_name = re.sub(r'[^A-Za-z0-9_. ()\\-]+', '_', Path(upload.filename).name).strip('._ ') or 'U1 Profile.3mf'
        target = USER_PROFILES_DIR / safe_name
        if target.exists():
            target = USER_PROFILES_DIR / f'{Path(safe_name).stem}-{uuid.uuid4().hex[:6]}.3mf'
        with tempfile.TemporaryDirectory(dir=TMP_DIR) as workdir_raw:
            candidate = Path(workdir_raw) / safe_name
            try:
                _save_upload(upload, candidate, size_limit_bytes=MAX_UPLOAD_MB * 1024 * 1024)
                settings = read_project_settings(candidate)
                printer_model = str(settings.get('printer_model') or '')
                layer_height = str(settings.get('layer_height') or '')
                if 'snapmaker' not in printer_model.lower() and 'u1' not in printer_model.lower():
                    logger.warning('importing reference profile without obvious Snapmaker/U1 marker: %s printer=%r', safe_name, printer_model)
                shutil.copy2(candidate, target)
                imported.append({'name': target.name, 'printer_model': printer_model, 'layer_height': layer_height})
            except Exception as err:
                errors.append({'name': safe_name, 'error': str(err)})
    return JSONResponse({'imported': imported, 'errors': errors, 'profiles': [profile.model_dump() for profile in list_profiles(PROFILES_DIR, USER_PROFILES_DIR)]})

@app.delete('/engine/reference-shelf/{profile_id}')
def delete_reference_profile(profile_id: str) -> JSONResponse:
    profiles = list_profiles(PROFILES_DIR, USER_PROFILES_DIR)
    profile = next((entry for entry in profiles if entry.id == profile_id), None)
    if profile is None:
        raise HTTPException(404, detail='profile not found')
    if profile.source != 'user':
        raise HTTPException(400, detail='bundled profiles cannot be deleted')
    path = Path(profile.path)
    if not path.exists() or path.parent.resolve() != USER_PROFILES_DIR.resolve():
        raise HTTPException(400, detail='profile path is outside the user profile shelf')
    path.unlink()
    return JSONResponse({'ok': True, 'profiles': [entry.model_dump() for entry in list_profiles(PROFILES_DIR, USER_PROFILES_DIR)]})

@app.get('/engine/folder-watch')
def folder_watch_status() -> JSONResponse:
    return JSONResponse(_FOLDER_WATCH.status())

@app.get('/engine/history')
def conversion_history() -> JSONResponse:
    records = _read_history()
    watch_records = []
    for item in _FOLDER_WATCH.status().get('recent', []):
        if not isinstance(item, dict):
            continue
        watch_records.append({
            'job_id': None,
            'mode': 'auto',
            'status': item.get('status'),
            'source_filename': item.get('name'),
            'output_filename': Path(str(item.get('output_path') or '')).name if item.get('output_path') else '',
            'output_path': item.get('output_path'),
            'source_path': item.get('path'),
            'reference_profile': item.get('profile'),
            'created_at': item.get('converted_at') or item.get('updated_at'),
            'message': item.get('message'),
            'thumbnail': item.get('thumbnail'),
        })
    combined = sorted(records + watch_records, key=lambda r: float(r.get('created_at') or 0), reverse=True)
    return JSONResponse({'records': combined[:250]})

@app.post('/engine/history/reveal')
def reveal_history_path(payload: PathActionPayload) -> JSONResponse:
    path = Path(payload.path).expanduser()
    if not path.exists():
        raise HTTPException(404, detail='file or folder not found')
    revealed = _reveal_saved_file(path)
    return JSONResponse({'ok': revealed})

@app.get('/engine/diagnostics')
def diagnostics_summary() -> JSONResponse:
    history = _read_history()
    return JSONResponse({
        'app_root': str(APP_ROOT),
        'data_root': str(CONFIG_FILE.parent),
        'config_file': str(CONFIG_FILE),
        'profiles_dir': str(PROFILES_DIR),
        'user_profiles_dir': str(USER_PROFILES_DIR),
        'rules_dir': str(RULES_DIR),
        'tmp_dir': str(TMP_DIR),
        'failed_tmp_dir': str(FAILED_TMP_DIR),
        'history_count': len(history),
        'tmp': _folder_stats(TMP_DIR),
        'failed_tmp': _folder_stats(FAILED_TMP_DIR),
        'failed_cases': _failed_diagnostics(),
    })

@app.post('/engine/diagnostics/reveal-data')
def reveal_data_folder() -> JSONResponse:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    return JSONResponse({'ok': _reveal_saved_file(CONFIG_FILE.parent)})

@app.post('/engine/diagnostics/clear-history')
def clear_conversion_history() -> JSONResponse:
    _write_history([])
    return diagnostics_summary()

@app.post('/engine/diagnostics/clear-temp')
def clear_temporary_files() -> JSONResponse:
    active_dirs: set[Path] = set()
    with _JOBS_LOCK:
        for job in _JOBS.values():
            output = job.get('output_path')
            if isinstance(output, Path):
                active_dirs.add(output.parent)
    candidates = TMP_DIR.iterdir() if TMP_DIR.exists() else []
    for folder in candidates:
        if folder.is_dir() and folder not in active_dirs:
            shutil.rmtree(folder, ignore_errors=True)
    return diagnostics_summary()

@app.get('/engine/diagnostics/support-pack')
def support_pack() -> FileResponse:
    out_dir = TMP_DIR / f'support-{uuid.uuid4().hex}'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'mkworld2snap-support-{int(time.time())}.zip'
    payload = {
        'generated_at': int(time.time()),
        'app_root': str(APP_ROOT),
        'data_root': str(CONFIG_FILE.parent),
        'history_count': len(_read_history()),
        'tmp': _folder_stats(TMP_DIR),
        'failed_tmp': _folder_stats(FAILED_TMP_DIR),
        'profiles': [profile.model_dump(exclude={'path'}) for profile in list_profiles(PROFILES_DIR, USER_PROFILES_DIR)],
        'failed_cases': _failed_diagnostics(),
    }
    with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('diagnostics.json', json.dumps(payload, indent=2, sort_keys=True))
        archive.writestr('history-redacted.json', json.dumps({'records': [
            {key: value for key, value in record.items() if key not in {'source_path', 'output_path', 'thumbnail'}}
            for record in _read_history()
        ]}, indent=2, sort_keys=True))
        for idx, failure in enumerate(_failed_diagnostics()):
            archive.writestr(f'failed/{idx + 1:02d}.json', json.dumps(failure, indent=2, sort_keys=True))
    return FileResponse(out_path, filename=out_path.name, media_type='application/zip')

@app.post('/engine/folder-watch/select')
def folder_watch_select() -> JSONResponse:
    local_00 = _choose_folders_macos('Choose one or more folders to watch for new 3MF/STL files:')
    if not local_00:
        return JSONResponse({'ok': False, 'cancelled': True, **_FOLDER_WATCH.status()})
    local_01 = _FOLDER_WATCH.add_paths(local_00)
    return JSONResponse({'ok': True, **local_01})

@app.post('/engine/folder-watch/enabled')
def folder_watch_enabled(payload: WatchTogglePayload) -> JSONResponse:
    return JSONResponse(_FOLDER_WATCH.set_enabled(payload.enabled))

@app.post('/engine/folder-watch/exclude-object')
def folder_watch_exclude_object(payload: WatchTogglePayload) -> JSONResponse:
    return JSONResponse(_FOLDER_WATCH.set_exclude_object(payload.enabled))

@app.post('/engine/folder-watch/scan')
def folder_watch_scan() -> JSONResponse:
    return JSONResponse(_FOLDER_WATCH.scan_now())

@app.post('/engine/folder-watch/remove')
def folder_watch_remove(payload: WatchPathPayload) -> JSONResponse:
    return JSONResponse(_FOLDER_WATCH.remove_path(Path(payload.path)))

@app.post('/engine/folder-watch/retry')
def folder_watch_retry(payload: WatchPathPayload) -> JSONResponse:
    return JSONResponse(_FOLDER_WATCH.retry(Path(payload.path)))

@app.post('/engine/folder-watch/ignore')
def folder_watch_ignore(payload: WatchPathPayload) -> JSONResponse:
    return JSONResponse(_FOLDER_WATCH.ignore(Path(payload.path)))

@app.post('/engine/folder-watch/reveal')
def folder_watch_reveal(payload: PathActionPayload) -> JSONResponse:
    path = Path(payload.path).expanduser()
    if not path.exists():
        raise HTTPException(404, detail='file or folder not found')
    return JSONResponse({'ok': _reveal_saved_file(path)})

@app.get('/engine/target-shelf')
def list_target_shelf() -> list[dict[str, str]]:
    """Return target-printer choices derived from readable shelf files."""
    local_00 = _target_profiles_dir()
    local_00.mkdir(parents=True, exist_ok=True)
    local_01 = list_profiles(local_00, local_00)
    local_02 = []
    for local_03 in local_01:
        try:
            local_04 = read_project_settings(Path(local_03.path))
            local_05 = local_04.get('printer_model') or local_03.display_name
        except Exception:
            logger.warning('could not read printer_model from %s', local_03.path)
            local_05 = local_03.display_name
        local_02.append({'id': local_03.id, 'name': local_05})
    return local_02

@app.get('/engine/target-shelf/location')
def target_shelf_location() -> JSONResponse:
    local_00 = _target_profiles_dir()
    local_01 = len(list(local_00.glob('*.3mf'))) if local_00.exists() else 0
    return JSONResponse({'path': str(local_00), 'exists': local_00.exists(), 'count': local_01, 'default_path': str(TARGET_PROFILES_DEFAULT_DIR)})

@app.post('/engine/target-shelf/location/select')
def choose_target_shelf_location() -> JSONResponse:
    local_00 = _choose_folder_macos('Choose the folder that contains Bambu/Orca reference .3mf profiles:')
    if local_00 is None:
        return JSONResponse({'ok': False, 'cancelled': True})
    local_01 = _set_target_profiles_dir(local_00)
    local_02 = len(list(local_01.glob('*.3mf')))
    return JSONResponse({'ok': True, 'path': str(local_01), 'count': local_02})

class RulePayload(BaseModel):
    yaml_text: str

@app.get('/engine/spool-tuning')
def list_spool_tuning() -> list[dict[str, Any]]:
    try:
        local_00 = load_recipe_book(RULES_DIR)
    except RecipeLoadError as err:
        raise HTTPException(500, detail=str(err)) from err
    return [{'name': local_01.name, 'file_key': Path(local_01.source_path).stem if local_01.source_path else local_01.name.strip().replace(' ', '_'), 'description': local_01.description, 'enabled': local_01.enabled, 'priority': local_01.priority, 'match': local_01.match.model_dump(exclude_none=True), 'overrides': local_01.overrides, 'source_path': local_01.source_path} for local_01 in local_00]

@app.get('/engine/spool-tuning/{name}')
def get_spool_tuning_rule(name: str) -> dict[str, str]:
    local_00 = _rule_filename(name)
    if not local_00.exists():
        raise HTTPException(404, detail='rule not found')
    return {'name': name, 'yaml_text': local_00.read_text(encoding='utf-8')}

@app.put('/engine/spool-tuning/{name}')
def put_spool_tuning_rule(name: str, payload: RulePayload) -> dict[str, str]:
    try:
        local_00 = _parse_rule_yaml(payload.yaml_text)
    except RecipeLoadError as err:
        raise HTTPException(400, detail=str(err)) from err
    if local_00.name.strip() != name.strip():
        raise HTTPException(400, detail=f"yaml name {local_00.name!r} doesn't match URL {name!r}")
    local_01 = _rule_filename(name)
    local_01.write_text(payload.yaml_text, encoding='utf-8')
    return {'status': 'ok', 'path': str(local_01)}

@app.post('/engine/spool-tuning')
def create_spool_tuning_rule(payload: RulePayload) -> dict[str, str]:
    try:
        local_00 = _parse_rule_yaml(payload.yaml_text)
    except RecipeLoadError as err:
        raise HTTPException(400, detail=str(err)) from err
    local_01 = _rule_filename(local_00.name)
    if local_01.exists():
        raise HTTPException(409, detail='rule with that name already exists')
    local_01.write_text(payload.yaml_text, encoding='utf-8')
    return {'status': 'ok', 'name': local_00.name, 'path': str(local_01)}

@app.delete('/engine/spool-tuning/{name}')
def delete_spool_tuning_rule(name: str) -> dict[str, str]:
    local_00 = _rule_filename(name)
    if not local_00.exists():
        raise HTTPException(404, detail='rule not found')
    local_00.unlink()
    return {'status': 'deleted'}

@app.post('/engine/spool-tuning/probe')
async def probe_spool_tuning(file: UploadFile=File(...)) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith('.3mf'):
        raise HTTPException(400, detail='expected a .3mf upload')
    with tempfile.TemporaryDirectory(dir=TMP_DIR) as local_00:
        local_01 = Path(local_00) / file.filename
        _save_upload(file, local_01)
        from reference_catalog import read_project_settings as _rps
        try:
            local_02 = _rps(local_01)
        except ProfileLoadError as err:
            raise HTTPException(400, detail=str(err)) from err
        local_03 = SpoolMatchContext.from_settings(local_02)
    local_04 = load_recipe_book(RULES_DIR)
    local_05 = find_recipe_hits(local_04, local_03)
    return {'context': {'settings_ids': list(local_03.settings_ids), 'vendors': list(local_03.vendors), 'types': list(local_03.types), 'base_profile': local_03.base_profile}, 'matches': [{'rule_name': local_06.name, 'priority': local_06.priority, 'evidence': local_07, 'overrides': local_06.overrides} for local_06, local_07 in local_05]}

def _parse_rule_yaml(yaml_text: str) -> RecipeDefinition:
    try:
        local_00 = yaml.safe_load(yaml_text)
    except yaml.YAMLError as err:
        raise RecipeLoadError(f'invalid YAML: {err}') from err
    if not isinstance(local_00, dict):
        raise RecipeLoadError('top-level must be a mapping')
    try:
        return RecipeDefinition(**local_00)
    except Exception as err:
        raise RecipeLoadError(str(err)) from err

@app.post('/engine/intake/inspect')
async def inspect_intake_file(file: UploadFile=File(...)) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith('.3mf'):
        raise HTTPException(400, detail='expected a .3mf upload')
    local_00 = uuid.uuid4().hex
    local_01 = TMP_DIR / local_00
    local_01.mkdir(parents=True)
    local_02 = local_01 / file.filename
    _save_upload(file, local_02)
    try:
        try:
            local_03, local_04 = read_source_settings(local_02)
        except ProfileLoadError as err:
            _retain_failed_workdir(job_id=local_00, workdir=local_01, endpoint='/engine/intake/inspect', filename=file.filename, reference_profile='', detail=str(err), error_type=type(err).__name__, request_meta={})
            raise HTTPException(400, detail=str(err)) from err
        with zipfile.ZipFile(local_02) as local_05:
            local_06 = local_05.namelist()
            local_07 = local_05.read('3D/3dmodel.model').decode('utf-8', errors='replace') if '3D/3dmodel.model' in local_06 else ''
        local_08 = list_profiles(PROFILES_DIR, USER_PROFILES_DIR)
        local_09 = suggest_profile(local_08, local_03)
        if local_09 is None:
            raise HTTPException(404, detail='no profiles available')
        local_10 = local_03.get('printer_model', '')
        local_11 = 'snapmaker' in local_10.lower()
        local_12 = local_03.get('filament_settings_id') or []
        local_13 = local_03.get('filament_type') or []
        local_14 = local_03.get('filament_vendor') or []
        local_15 = local_03.get('filament_colour') or []
        local_16 = [{'index': local_17, 'settings_id': local_12[local_17] if local_17 < len(local_12) else None, 'filament_type': local_13[local_17] if local_17 < len(local_13) else None, 'vendor': local_14[local_17] if local_17 < len(local_14) else None, 'colour': local_15[local_17] if local_17 < len(local_15) else None} for local_17 in range(len(local_12))]
        local_18 = len(local_12)
        local_19 = is_painted_model(local_06, local_18)
        import re as _re
        local_20 = _re.findall('transform="([^"]+)"', local_07)
        local_21, local_22 = ([], [])
        for local_23 in local_20:
            local_24 = local_23.split()
            if len(local_24) == 12:
                local_21.append(float(local_24[9]))
                local_22.append(float(local_24[10]))
        local_25 = bool(local_21) and (max(local_21) - min(local_21) > _MULTIPLATE_SPAN_MM or max(local_22) - min(local_22) > _MULTIPLATE_SPAN_MM)
        local_26 = local_03.get('printable_area') or ['0x0']
        local_27 = [float(local_28.split('x')[0]) for local_28 in local_26]
        local_29 = [float(local_28.split('x')[1]) for local_28 in local_26]
        local_30 = max(local_27) - min(local_27) > 270.0 or max(local_29) - min(local_29) > 270.0
        local_31 = any((local_32 == '1' for local_32 in local_03.get('filament_is_mixed') or []))
        local_34 = _lint_source_settings(local_03)
        if local_11:
            local_33 = None
        elif local_04 is not None:
            local_33 = local_04
        elif local_10.lower().startswith('bambu lab'):
            local_33 = None
        else:
            local_33 = local_10 or 'Unknown slicer'
        logger.info('SUGGEST %s  lh=%s  pid=%r  printer=%r  already_converted=%s  filaments=%d  painted=%s  target=%s', file.filename, local_03.get('layer_height'), local_03.get('print_settings_id'), local_10, local_11, local_18, local_19, local_09.display_name)
        return {'profile_id': local_09.id, 'display_name': local_09.display_name, 'source_printer': local_10, 'already_converted': local_11, 'filaments': local_16, 'is_painted_model': local_19, 'is_multiplate': local_25, 'is_oversized': local_30, 'is_colour_mixed': local_31, 'source_slicer': local_33, 'lint_issues': local_34, 'matched_on': {'layer_height': local_03.get('layer_height'), 'print_settings_id': local_03.get('print_settings_id')}}
    finally:
        shutil.rmtree(local_01, ignore_errors=True)

@app.post('/engine/intake/scene')
async def intake_scene(file: UploadFile=File(...)) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith('.3mf'):
        raise HTTPException(400, detail='expected a .3mf upload')
    with tempfile.TemporaryDirectory(dir=TMP_DIR) as local_00:
        local_01 = Path(local_00) / file.filename
        _save_upload(file, local_01, size_limit_bytes=MAX_UPLOAD_MB * 1024 * 1024)
        try:
            return JSONResponse(build_preview_scene(local_01))
        except ProfileLoadError as err:
            raise HTTPException(400, detail=str(err)) from err
        except Exception as err:
            logger.exception('intake scene extraction failed')
            raise HTTPException(500, detail=f'scene extraction failed: {err}') from err

@app.post('/engine/jobs/u1')
async def build_u1_job(file: UploadFile=File(...), reference_profile: str=Form(...), apply_recipe_book: bool=Form(True), clamp_speeds: bool=Form(True), preserve_color_painting: bool=Form(True), advanced_overrides: str=Form('{}'), slot_map: str=Form('{}'), insert_swap_pauses: str=Form('false'), exclude_object: str=Form('true')) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith('.3mf'):
        raise HTTPException(400, detail='expected a .3mf upload')
    try:
        local_00 = yaml.safe_load(advanced_overrides) or {}
        if not isinstance(local_00, dict):
            raise ValueError('must be a mapping')
    except (ValueError, yaml.YAMLError) as err:
        raise HTTPException(400, detail=f'bad advanced_overrides: {err}') from err
    try:
        import json as _json
        local_01 = (slot_map or '').strip()
        local_02 = _json.loads(local_01) if local_01 and local_01 != '{}' else {}
        local_03: dict[int, int] = {int(local_04): int(local_05) for local_04, local_05 in local_02.items()}
    except (ValueError, TypeError) as err:
        raise HTTPException(400, detail=f'bad slot_map: {err}') from err
    if any((local_05 < 0 or local_05 >= _MAX_TOOLHEADS for local_05 in local_03.values())):
        raise HTTPException(400, detail='slot_map values must be 0–3')
    try:
        local_06 = resolve_profile(reference_profile, PROFILES_DIR, USER_PROFILES_DIR)
    except ProfileNotFoundError as err:
        raise HTTPException(404, detail=str(err)) from err
    local_07 = uuid.uuid4().hex
    local_08 = TMP_DIR / local_07
    local_08.mkdir(parents=True)
    local_09 = local_08 / file.filename
    _save_upload(file, local_09, size_limit_bytes=MAX_UPLOAD_MB * 1024 * 1024)
    local_10 = f'{Path(file.filename).stem}-U1.3mf'
    local_11 = local_08 / local_10
    local_12 = BuildRequestSettings(reference_profile=local_06.id, apply_recipe_book=apply_recipe_book, clamp_speeds=clamp_speeds, preserve_color_painting=preserve_color_painting, advanced_overrides=local_00, slot_map=local_03, insert_swap_pauses=insert_swap_pauses.lower() == 'true', exclude_object=exclude_object.lower() == 'true')
    local_13 = load_recipe_book(RULES_DIR)
    try:
        local_14 = forge_package(source_path=local_09, reference_path=Path(local_06.path), output_path=local_11, settings=local_12, rules=local_13)
    except ProfileLoadError as err:
        _retain_failed_workdir(job_id=local_07, workdir=local_08, endpoint='/engine/jobs/u1', filename=file.filename, reference_profile=local_06.id, detail=str(err), error_type=type(err).__name__, request_meta={'apply_recipe_book': apply_recipe_book, 'clamp_speeds': clamp_speeds, 'preserve_color_painting': preserve_color_painting, 'slot_map': local_03, 'insert_swap_pauses': insert_swap_pauses.lower() == 'true'})
        raise HTTPException(400, detail=str(err)) from err
    except Exception as err:
        _retain_failed_workdir(job_id=local_07, workdir=local_08, endpoint='/engine/jobs/u1', filename=file.filename, reference_profile=local_06.id, detail=str(err), error_type=type(err).__name__, request_meta={'apply_recipe_book': apply_recipe_book, 'clamp_speeds': clamp_speeds, 'preserve_color_painting': preserve_color_painting, 'slot_map': local_03, 'insert_swap_pauses': insert_swap_pauses.lower() == 'true'})
        logger.exception('conversion failed')
        raise HTTPException(500, detail=f'conversion failed: {err}') from err
    local_15 = local_14.diff.counts()
    local_16 = {'report': local_14.diff.model_dump(), 'sections': compose_report_sections(local_14.diff), 'counts': local_15}
    _register_job(local_07, local_11, local_16, source_path=local_09, reference_path=Path(local_06.path), settings=local_12)
    return JSONResponse({'job_id': local_07, 'download_name': local_10, 'diff': local_16})

def _coerce_override_value(key: str, raw_value: Any, reference_value: Any) -> Any:
    if isinstance(reference_value, list):
        if isinstance(raw_value, list):
            return raw_value
        if isinstance(raw_value, str):
            local_00 = raw_value.strip()
            if not local_00:
                return []
            try:
                local_01 = yaml.safe_load(local_00)
                if isinstance(local_01, list):
                    return local_01
            except yaml.YAMLError:
                pass
            return [local_02.strip() for local_02 in local_00.split(',')]
        raise HTTPException(400, detail=f'{key}: expected a list or comma-separated values')
    if isinstance(reference_value, bool):
        if isinstance(raw_value, bool):
            return raw_value
        local_03 = str(raw_value).strip().lower()
        if local_03 in {'1', 'true', 'yes', 'on'}:
            return True
        if local_03 in {'0', 'false', 'no', 'off'}:
            return False
        raise HTTPException(400, detail=f'{key}: expected true/false')
    if isinstance(reference_value, int) and not isinstance(reference_value, bool):
        try:
            return int(str(raw_value).strip())
        except (TypeError, ValueError) as err:
            raise HTTPException(400, detail=f'{key}: expected an integer') from err
    if isinstance(reference_value, float):
        try:
            return float(str(raw_value).strip())
        except (TypeError, ValueError) as err:
            raise HTTPException(400, detail=f'{key}: expected a number') from err
    if isinstance(raw_value, (dict, tuple, set)):
        raise HTTPException(400, detail=f'{key}: custom object values are not supported')
    return str(raw_value).strip()

@app.post('/engine/jobs/{job_id}/rebuild')
def rebuild_u1_job(job_id: str, payload: RebuildPayload) -> JSONResponse:
    local_00 = _get_job(job_id)
    if local_00 is None:
        raise HTTPException(404, detail='job expired or not found')
    local_01 = local_00.get('source_path')
    local_02 = local_00.get('reference_path')
    local_03 = local_00.get('settings')
    local_04 = local_00.get('output_path')
    if not isinstance(local_01, Path) or not isinstance(local_02, Path) or not isinstance(local_03, BuildRequestSettings) or not isinstance(local_04, Path):
        raise HTTPException(400, detail='this job cannot be rebuilt')
    if not local_01.exists():
        raise HTTPException(410, detail='source upload was cleaned up; load the file again')
    if not local_02.exists():
        raise HTTPException(410, detail='reference profile is no longer available')
    local_05 = read_project_settings(local_02)
    local_06 = dict(local_03.advanced_overrides)
    for local_07 in payload.default_keys:
        if local_07 not in local_05:
            raise HTTPException(400, detail=f'{local_07}: no U1 default is available')
        local_06[local_07] = local_05[local_07]
    for local_07, local_08 in payload.custom_overrides.items():
        if local_07 not in local_05:
            raise HTTPException(400, detail=f'{local_07}: custom editing is not supported')
        local_06[local_07] = _coerce_override_value(local_07, local_08, local_05[local_07])
    local_09 = local_03.model_copy(update={
        'advanced_overrides': local_06,
        'exclude_object': local_03.exclude_object if payload.exclude_object is None else bool(payload.exclude_object),
    })
    local_10 = uuid.uuid4().hex
    local_11 = TMP_DIR / local_10
    local_11.mkdir(parents=True)
    local_12 = local_11 / local_01.name
    shutil.copy2(local_01, local_12)
    local_13 = local_11 / local_04.name
    try:
        local_14 = forge_package(source_path=local_12, reference_path=local_02, output_path=local_13, settings=local_09, rules=load_recipe_book(RULES_DIR))
    except ProfileLoadError as err:
        _retain_failed_workdir(job_id=local_10, workdir=local_11, endpoint=f'/engine/jobs/{job_id}/rebuild', filename=local_01.name, reference_profile=local_09.reference_profile, detail=str(err), error_type=type(err).__name__, request_meta={'default_keys': payload.default_keys, 'custom_overrides': payload.custom_overrides, 'exclude_object': payload.exclude_object})
        raise HTTPException(400, detail=str(err)) from err
    except Exception as err:
        _retain_failed_workdir(job_id=local_10, workdir=local_11, endpoint=f'/engine/jobs/{job_id}/rebuild', filename=local_01.name, reference_profile=local_09.reference_profile, detail=str(err), error_type=type(err).__name__, request_meta={'default_keys': payload.default_keys, 'custom_overrides': payload.custom_overrides, 'exclude_object': payload.exclude_object})
        logger.exception('rebuild failed')
        raise HTTPException(500, detail=f'rebuild failed: {err}') from err
    local_15 = {'report': local_14.diff.model_dump(), 'sections': compose_report_sections(local_14.diff), 'counts': local_14.diff.counts()}
    _register_job(local_10, local_13, local_15, source_path=local_12, reference_path=local_02, settings=local_09)
    return JSONResponse({'job_id': local_10, 'download_name': local_13.name, 'diff': local_15})

@app.post('/engine/jobs/target-profile')
async def build_target_profile_job(file: UploadFile=File(...), reference_profile: str=Form(...), apply_recipe_book: bool=Form(True), clamp_speeds: bool=Form(True), preserve_color_painting: bool=Form(True), advanced_overrides: str=Form('{}'), insert_swap_pauses: str=Form('false')) -> JSONResponse:
    """Convert a Bambu 3mf to a different Bambu printer target.

    The reference_profile must point at a compatible target-printer project.
    Bambu/Orca metadata sidecars are kept for this mode; use /engine/jobs/u1
    when the desired output is Snapmaker U1.
    """
    if not file.filename or not file.filename.lower().endswith('.3mf'):
        raise HTTPException(400, detail='expected a .3mf upload')
    try:
        local_00 = yaml.safe_load(advanced_overrides) or {}
        if not isinstance(local_00, dict):
            raise ValueError('must be a mapping')
    except (ValueError, yaml.YAMLError) as err:
        raise HTTPException(400, detail=f'bad advanced_overrides: {err}') from err
    try:
        local_01 = resolve_profile(reference_profile, _target_profiles_dir(), _target_profiles_dir())
    except ProfileNotFoundError as err:
        raise HTTPException(404, detail=str(err)) from err
    local_02 = read_project_settings(Path(local_01.path))
    local_03 = local_02.get('printer_model', local_01.id)
    local_04 = local_03.split()[-1] if local_03 else local_01.id
    local_05 = uuid.uuid4().hex
    local_06 = TMP_DIR / local_05
    local_06.mkdir(parents=True)
    local_07 = local_06 / file.filename
    _save_upload(file, local_07, size_limit_bytes=MAX_UPLOAD_MB * 1024 * 1024)
    local_08 = f'{Path(file.filename).stem}-{local_04}.3mf'
    local_09 = local_06 / local_08
    local_10 = BuildRequestSettings(reference_profile=local_01.id, apply_recipe_book=apply_recipe_book, clamp_speeds=clamp_speeds, preserve_color_painting=preserve_color_painting, advanced_overrides=local_00, slot_map={}, insert_swap_pauses=insert_swap_pauses.lower() == 'true')
    local_11 = load_recipe_book(RULES_DIR)
    try:
        local_12 = forge_package(source_path=local_07, reference_path=Path(local_01.path), output_path=local_09, settings=local_10, rules=local_11, preserve_source_metadata=True)
    except ProfileLoadError as err:
        _retain_failed_workdir(job_id=local_05, workdir=local_06, endpoint='/engine/jobs/target-profile', filename=file.filename, reference_profile=local_01.id, detail=str(err), error_type=type(err).__name__, request_meta={'apply_recipe_book': apply_recipe_book, 'clamp_speeds': clamp_speeds, 'preserve_color_painting': preserve_color_painting, 'insert_swap_pauses': insert_swap_pauses.lower() == 'true'})
        raise HTTPException(400, detail=str(err)) from err
    except Exception as err:
        _retain_failed_workdir(job_id=local_05, workdir=local_06, endpoint='/engine/jobs/target-profile', filename=file.filename, reference_profile=local_01.id, detail=str(err), error_type=type(err).__name__, request_meta={'apply_recipe_book': apply_recipe_book, 'clamp_speeds': clamp_speeds, 'preserve_color_painting': preserve_color_painting, 'insert_swap_pauses': insert_swap_pauses.lower() == 'true'})
        logger.exception('conversion failed')
        raise HTTPException(500, detail=f'conversion failed: {err}') from err
    local_13 = {'report': local_12.diff.model_dump(), 'sections': compose_report_sections(local_12.diff), 'counts': local_12.diff.counts()}
    _register_job(local_05, local_09, local_13)
    return JSONResponse({'job_id': local_05, 'download_name': local_08, 'diff': local_13})

@app.get('/engine/jobs/{job_id}/artifact')
def job_artifact(job_id: str) -> FileResponse:
    local_00 = _get_job(job_id)
    if local_00 is None:
        raise HTTPException(404, detail='job expired or not found')
    local_01: Path = local_00['output_path']
    if not local_01.exists():
        raise HTTPException(410, detail='output file was cleaned up')
    return FileResponse(local_01, filename=local_01.name, media_type='application/octet-stream')

@app.get('/engine/jobs/{job_id}')
def job_summary(job_id: str) -> JSONResponse:
    local_00 = _get_job(job_id)
    if local_00 is None:
        raise HTTPException(404, detail='job expired or not found')
    local_01: Path = local_00['output_path']
    if not local_01.exists():
        raise HTTPException(410, detail='output file was cleaned up')
    return JSONResponse({'job_id': job_id, 'download_name': local_01.name, 'diff': local_00['diff']})

@app.get('/engine/jobs/{job_id}/scene')
def job_scene(job_id: str) -> JSONResponse:
    local_00 = _get_job(job_id)
    if local_00 is None:
        raise HTTPException(404, detail='job expired or not found')
    local_01: Path = local_00['output_path']
    if not local_01.exists():
        raise HTTPException(410, detail='output file was cleaned up')
    try:
        return JSONResponse(build_preview_scene(local_01))
    except Exception as err:
        logger.exception('scene extraction failed')
        raise HTTPException(500, detail=f'scene extraction failed: {err}') from err

@app.get('/engine/jobs/{job_id}/source-scene')
def job_source_scene(job_id: str) -> JSONResponse:
    local_00 = _get_job(job_id)
    if local_00 is None:
        raise HTTPException(404, detail='job expired or not found')
    local_01 = local_00.get('source_path')
    if not isinstance(local_01, Path) or not local_01.exists():
        raise HTTPException(410, detail='source upload was cleaned up')
    try:
        return JSONResponse(build_preview_scene(local_01))
    except Exception as err:
        logger.exception('source scene extraction failed')
        raise HTTPException(500, detail=f'source scene extraction failed: {err}') from err

@app.get('/engine/jobs/{job_id}/parameters')
def job_parameters(job_id: str) -> JSONResponse:
    local_00 = _get_job(job_id)
    if local_00 is None:
        raise HTTPException(404, detail='job expired or not found')
    local_01, local_02 = _read_project_settings_from_job(local_00)
    local_03: dict[str, list[dict[str, Any]]] = {}
    for local_04 in sorted(local_01.keys()):
        if local_04.startswith('compatible_') or local_04 in {'inherits', 'inherits_group'}:
            continue
        local_05 = _parameter_group(local_04)
        local_06 = local_01.get(local_04)
        local_07 = local_02.get(local_04)
        local_03.setdefault(local_05, []).append({
            'key': local_04,
            'value': local_06,
            'default_value': local_07,
            'has_u1_default': local_04 in local_02,
            'changed_from_default': local_04 in local_02 and local_06 != local_07,
            'value_type': 'list' if isinstance(local_06, list) else type(local_06).__name__,
        })
    local_08 = ['Quality', 'Strength', 'Speed', 'Supports', 'Multimaterial', 'Others']
    local_09 = [{'name': local_10, 'items': local_03.get(local_10, [])} for local_10 in local_08 if local_03.get(local_10)]
    return JSONResponse({
        'job_id': job_id,
        'can_rebuild': isinstance(local_00.get('source_path'), Path) and isinstance(local_00.get('settings'), BuildRequestSettings),
        'groups': local_09,
    })

@app.post('/engine/jobs/{job_id}/save-dialog')
def save_job_with_dialog(job_id: str) -> JSONResponse:
    local_00 = _get_job(job_id)
    if local_00 is None:
        raise HTTPException(404, detail='job expired or not found')
    local_01: Path = local_00['output_path']
    if not local_01.exists():
        raise HTTPException(410, detail='output file was cleaned up')
    local_02 = _choose_save_path(local_01.name)
    if local_02 is None:
        return JSONResponse({'ok': False, 'cancelled': True})
    local_02.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_01, local_02)
    local_03 = _reveal_saved_file(local_02)
    return JSONResponse({'ok': True, 'path': str(local_02), 'revealed': local_03})

def _save_upload(file: UploadFile, dst: Path, *, size_limit_bytes: int | None=None) -> None:
    local_00 = 0
    with dst.open('wb') as local_01:
        while True:
            local_02 = file.file.read(1024 * 1024)
            if not local_02:
                break
            local_00 += len(local_02)
            if size_limit_bytes is not None and local_00 > size_limit_bytes:
                local_01.close()
                dst.unlink(missing_ok=True)
                raise HTTPException(413, detail='file too large')
            local_01.write(local_02)

@app.get('/engine/ping')
def engine_ping() -> dict[str, str]:
    return {'status': 'ok'}

@app.get('/robots.txt', include_in_schema=False)
def robots_txt():
    from fastapi.responses import PlainTextResponse
    local_00 = f'User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n'
    return PlainTextResponse(local_00, media_type='text/plain')

@app.get('/sitemap.xml', include_in_schema=False)
def sitemap_xml():
    from fastapi.responses import Response
    from datetime import date
    local_00 = date.today().isoformat()
    local_01 = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n  <url>\n    <loc>{SITE_URL}/</loc>\n    <lastmod>{local_00}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>1.0</priority>\n  </url>\n  <url>\n    <loc>{SITE_URL}/privacy.html</loc>\n    <lastmod>{local_00}</lastmod>\n    <changefreq>monthly</changefreq>\n    <priority>0.3</priority>\n  </url>\n</urlset>'
    return Response(content=local_01, media_type='application/xml')

@app.middleware('http')
async def _log_requests(request: Request, call_next):
    local_00 = time.monotonic()
    local_01 = await call_next(request)
    if request.url.path == '/engine/ping':
        return local_01
    logger.info('%s %s -> %d (%.1f ms)', request.method, request.url.path, local_01.status_code, (time.monotonic() - local_00) * 1000)
    return local_01

@app.get('/privacy.html', response_class=HTMLResponse, include_in_schema=False)
def privacy_page() -> HTMLResponse:
    local_00 = FRONTEND_DIST / 'privacy.html'
    if not local_00.exists():
        raise HTTPException(404, detail='not found')
    return HTMLResponse(render_privacy_html(local_00.read_text(encoding='utf-8')))
if FRONTEND_DIST.exists():
    app.mount('/', StaticFiles(directory=FRONTEND_DIST, html=True), name='frontend')
