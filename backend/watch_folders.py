"""Folder watcher for automatic U1 builds."""
from __future__ import annotations

import json
import logging
import base64
import re
import shutil
import struct
import tempfile
import threading
import time
import zipfile
from html import escape
from pathlib import Path
from typing import Any

from reference_catalog import ProfileLoadError, list_profiles, read_source_settings, suggest_profile
from scene_preview import build_preview_scene
from spool_tuning import load_recipe_book
from u1_packager import forge_package, is_painted_model
from workshop_types import BuildRequestSettings

log = logging.getLogger('mkworld2snap.watch')

MODEL_SUFFIXES = {'.3mf', '.stl', '.obj', '.amf'}
CONVERTIBLE_SUFFIXES = {'.3mf', '.stl'}
OUTPUT_FOLDER_NAME = 'OUTPUT_U1'
DEFAULT_SCAN_SECONDS = 6.0
CONVERTER_VERSION = 6


def _json_read(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
    except Exception:
        log.exception('failed to read %s', path)
    return {}


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')


def _signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {'size': int(stat.st_size), 'mtime_ns': int(stat.st_mtime_ns)}


def _is_in_output_folder(path: Path) -> bool:
    return any(part == OUTPUT_FOLDER_NAME for part in path.parts)


def _safe_output_name(source: Path) -> str:
    return f'{source.stem}-U1.3mf'


def _format_float(value: float) -> str:
    return f'{value:.6f}'.rstrip('0').rstrip('.') or '0'


def _normalise_colour(value: Any) -> str:
    text = str(value or '#9aa3a0').strip()
    if re_match := re.match(r'^#[0-9a-fA-F]{6}$', text):
        return re_match.group(0)
    if len(text) == 9 and text.startswith('#'):
        return text[:7]
    return '#9aa3a0'


def _embedded_thumbnail_data_url(path: Path) -> str | None:
    candidates = (
        'Auxiliaries/.thumbnails/thumbnail_3mf.png',
        'Auxiliaries/.thumbnails/thumbnail_middle.png',
        'Auxiliaries/.thumbnails/thumbnail_small.png',
        'Metadata/plate_1.png',
        'Metadata/top_1.png',
        'Metadata/pick_1.png',
    )
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            selected = next((name for name in candidates if name in names), None)
            if selected is None:
                selected = next((name for name in archive.namelist() if name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))), None)
            if selected is None:
                return None
            suffix = Path(selected).suffix.lower()
            mime = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.webp': 'image/webp',
            }.get(suffix)
            if not mime:
                return None
            payload = base64.b64encode(archive.read(selected)).decode('ascii')
            return f'data:{mime};base64,{payload}'
    except Exception:
        log.debug('embedded thumbnail extraction failed for %s', path, exc_info=True)
        return None


def _thumbnail_data_url(path: Path) -> str | None:
    embedded = _embedded_thumbnail_data_url(path)
    if embedded:
        return embedded
    try:
        scene = build_preview_scene(path)
    except Exception:
        log.debug('thumbnail extraction failed for %s', path, exc_info=True)
        return None
    meshes = scene.get('meshes') or []
    if not meshes:
        return None
    stats = scene.get('stats') or {}
    bounds = scene.get('bounds') or {}
    low = bounds.get('min') or [0, 0, 0]
    high = bounds.get('max') or [1, 1, 1]
    min_x, min_y = float(low[0]), float(low[1])
    max_x, max_y = float(high[0]), float(high[1])
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    size = 96.0
    pad = 8.0
    scale = min((size - pad * 2) / span_x, (size - pad * 2) / span_y)
    offset_x = (size - span_x * scale) / 2
    offset_y = (size - span_y * scale) / 2

    def project(x: float, y: float) -> tuple[float, float]:
        return (offset_x + (x - min_x) * scale, size - (offset_y + (y - min_y) * scale))

    polygons: list[str] = []
    total_tris = sum(max(0, len(mesh.get('indices') or []) // 3) for mesh in meshes)
    stride = max(1, total_tris // 260)
    seen = 0
    for mesh in meshes:
        vertices = mesh.get('vertices') or []
        indices = mesh.get('indices') or []
        colours = mesh.get('triangle_colors') or []
        fallback = _normalise_colour(mesh.get('color'))
        for tri in range(0, len(indices) - 2, 3):
            if seen % stride != 0:
                seen += 1
                continue
            seen += 1
            pts: list[str] = []
            for pos in (indices[tri], indices[tri + 1], indices[tri + 2]):
                base = int(pos) * 3
                if base + 1 >= len(vertices):
                    continue
                x, y = project(float(vertices[base]), float(vertices[base + 1]))
                pts.append(f'{x:.1f},{y:.1f}')
            if len(pts) == 3:
                colour = _normalise_colour(colours[tri // 3] if tri // 3 < len(colours) else fallback)
                polygons.append(f'<polygon points="{" ".join(pts)}" fill="{colour}" opacity="0.86"/>')
            if len(polygons) >= 280:
                break
        if len(polygons) >= 280:
            break
    if not polygons:
        return None
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">'
        '<rect width="96" height="96" rx="14" fill="#f7faf6"/>'
        '<path d="M8 80H88M16 72H80M24 64H72" stroke="#d8e1dd" stroke-width="1"/>'
        f'<g stroke="#233631" stroke-width=".35">{"".join(polygons)}</g>'
        '</svg>'
    )
    payload = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    return f'data:image/svg+xml;base64,{payload}'


def _read_stl_triangles(path: Path) -> list[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]]:
    data = path.read_bytes()
    if len(data) >= 84:
        tri_count = struct.unpack_from('<I', data, 80)[0]
        expected = 84 + tri_count * 50
        if expected == len(data):
            triangles = []
            offset = 84
            for _ in range(tri_count):
                offset += 12
                vertices = []
                for _vertex in range(3):
                    vertices.append(struct.unpack_from('<fff', data, offset))
                    offset += 12
                offset += 2
                triangles.append((vertices[0], vertices[1], vertices[2]))
            return triangles
    text = data.decode('utf-8', errors='ignore')
    vertices: list[tuple[float, float, float]] = []
    for raw_line in text.splitlines():
        parts = raw_line.strip().split()
        if len(parts) == 4 and parts[0].lower() == 'vertex':
            try:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            except ValueError:
                continue
    return [(vertices[i], vertices[i + 1], vertices[i + 2]) for i in range(0, len(vertices) - 2, 3)]


def _write_geometry_3mf_from_stl(stl_path: Path, target_3mf: Path) -> None:
    triangles = _read_stl_triangles(stl_path)
    if not triangles:
        raise ProfileLoadError(f'{stl_path.name}: STL geometry could not be read')
    points = [point for triangle in triangles for point in triangle]
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    min_z = min(point[2] for point in points)
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    width = max_x - min_x
    depth = max_y - min_y
    shift_x = 135.0 - width / 2 - min_x
    shift_y = 135.0 - depth / 2 - min_y
    shift_z = -min_z

    vertices_xml: list[str] = []
    triangles_xml: list[str] = []
    vertex_index = 0
    for triangle in triangles:
        indices = []
        for x, y, z in triangle:
            vertices_xml.append(
                '<vertex x="%s" y="%s" z="%s" />'
                % (_format_float(x + shift_x), _format_float(y + shift_y), _format_float(z + shift_z))
            )
            indices.append(vertex_index)
            vertex_index += 1
        triangles_xml.append('<triangle v1="%d" v2="%d" v3="%d" />' % tuple(indices))

    project_settings = {
        'layer_height': '0.20',
        'print_settings_id': 'Geometry fallback 0.20 Standard',
        'filament_settings_id': ['Generic PLA'],
        'filament_type': ['PLA'],
        'filament_colour': ['#808080'],
        'filament_diameter': ['1.75'],
        'nozzle_temperature': ['220'],
        'nozzle_temperature_initial_layer': ['220'],
        'hot_plate_temp': ['60'],
        'hot_plate_temp_initial_layer': ['60'],
        'printable_area': ['270x270'],
    }
    model_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
        '  <resources>\n'
        '    <object id="1" type="model" name="%s">\n'
        '      <mesh>\n'
        '        <vertices>\n          %s\n        </vertices>\n'
        '        <triangles>\n          %s\n        </triangles>\n'
        '      </mesh>\n'
        '    </object>\n'
        '  </resources>\n'
        '  <build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0" /></build>\n'
        '</model>\n'
    ) % (escape(stl_path.stem), '\n          '.join(vertices_xml), '\n          '.join(triangles_xml))
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        '  <Default Extension="config" ContentType="application/json"/>\n'
        '</Types>\n'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        '</Relationships>\n'
    )
    target_3mf.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target_3mf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('3D/3dmodel.model', model_xml)
        zf.writestr('Metadata/project_settings.config', json.dumps(project_settings, indent=4))


class FolderWatchService:
    def __init__(
        self,
        *,
        config_file: Path,
        profiles_dir: Path,
        user_profiles_dir: Path,
        rules_dir: Path,
        tmp_dir: Path,
        max_file_mb: int,
    ) -> None:
        self.config_file = config_file
        self.manifest_file = config_file.parent / 'watched_files.json'
        self.profiles_dir = profiles_dir
        self.user_profiles_dir = user_profiles_dir
        self.rules_dir = rules_dir
        self.tmp_dir = tmp_dir
        self.max_file_bytes = max_file_mb * 1024 * 1024
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._scanning = False
        self._records: dict[str, dict[str, Any]] = {}
        self._load_manifest()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._loop, name='mkworld2snap-folder-watch', daemon=True)
        self._worker.start()

    def _config(self) -> dict[str, Any]:
        return _json_read(self.config_file)

    def _save_config(self, data: dict[str, Any]) -> None:
        _json_write(self.config_file, data)

    def _load_manifest(self) -> None:
        data = _json_read(self.manifest_file)
        records = data.get('records', {})
        if isinstance(records, dict):
            self._records = {str(k): v for k, v in records.items() if isinstance(v, dict)}

    def _save_manifest(self) -> None:
        _json_write(self.manifest_file, {'records': self._records})

    def _paths(self) -> list[Path]:
        raw = self._config().get('watch_paths', [])
        if not isinstance(raw, list):
            return []
        paths: list[Path] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                continue
            path = Path(item).expanduser()
            key = str(path)
            if key not in seen:
                seen.add(key)
                paths.append(path)
        return paths

    def add_paths(self, paths: list[Path]) -> dict[str, Any]:
        config = self._config()
        current = [str(Path(p).expanduser()) for p in self._paths()]
        for path in paths:
            resolved = path.expanduser().resolve()
            if resolved.is_dir() and str(resolved) not in current:
                current.append(str(resolved))
        config['watch_paths'] = current
        config['watch_enabled'] = bool(current)
        self._save_config(config)
        self.start()
        return self.status()

    def remove_path(self, path: Path) -> dict[str, Any]:
        target = str(path.expanduser())
        config = self._config()
        config['watch_paths'] = [p for p in [str(item) for item in config.get('watch_paths', [])] if p != target]
        if not config['watch_paths']:
            config['watch_enabled'] = False
        self._save_config(config)
        return self.status()

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        config = self._config()
        config['watch_enabled'] = enabled and bool(self._paths())
        self._save_config(config)
        self.start()
        return self.status()

    def enabled(self) -> bool:
        return bool(self._config().get('watch_enabled') and self._paths())

    def exclude_object_enabled(self) -> bool:
        return bool(self._config().get('watch_exclude_object', True))

    def set_exclude_object(self, enabled: bool) -> dict[str, Any]:
        config = self._config()
        config['watch_exclude_object'] = bool(enabled)
        self._save_config(config)
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            records = sorted(self._records.values(), key=lambda r: float(r.get('updated_at') or 0), reverse=True)
            counts: dict[str, int] = {}
            for record in records:
                status = str(record.get('status') or 'unknown')
                counts[status] = counts.get(status, 0) + 1
            paths = [str(path) for path in self._paths()]
            return {
                'enabled': self.enabled(),
                'exclude_object': self.exclude_object_enabled(),
                'paths': paths,
                'scanning': self._scanning,
                'known_count': len(records),
                'converted_count': counts.get('converted', 0),
                'failed_count': counts.get('failed', 0),
                'unsupported_count': counts.get('unsupported', 0),
                'ignored_count': counts.get('ignored', 0),
                'pending_count': counts.get('queued', 0) + counts.get('running', 0),
                'recent': records[:120],
            }

    def scan_now(self) -> dict[str, Any]:
        self.scan_once()
        return self.status()

    def retry(self, source: Path) -> dict[str, Any]:
        source = source.expanduser()
        if not source.exists() or not source.is_file():
            self._record(source, status='failed', message='Source file is no longer available.')
            return self.status()
        with self._lock:
            self._records.pop(str(source), None)
        self._handle_source(source)
        with self._lock:
            self._save_manifest()
        return self.status()

    def ignore(self, source: Path) -> dict[str, Any]:
        source = source.expanduser()
        try:
            sig = _signature(source) if source.exists() and source.is_file() else {}
        except OSError:
            sig = {}
        self._record(source, status='ignored', message='Ignored until retry is selected.', **sig)
        with self._lock:
            self._save_manifest()
        return self.status()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            if self.enabled():
                try:
                    self.scan_once()
                except Exception:
                    log.exception('folder watch scan failed')
            self._stop_event.wait(DEFAULT_SCAN_SECONDS)

    def scan_once(self) -> None:
        paths = [path for path in self._paths() if path.is_dir()]
        if not paths:
            return
        with self._lock:
            if self._scanning:
                return
            self._scanning = True
        try:
            for root in paths:
                for source in self._iter_sources(root):
                    self._handle_source(source)
        finally:
            with self._lock:
                self._scanning = False
                self._save_manifest()

    def _iter_sources(self, root: Path):
        for source in root.rglob('*'):
            if not source.is_file():
                continue
            if _is_in_output_folder(source):
                continue
            if source.suffix.lower() in MODEL_SUFFIXES:
                yield source

    def _record(self, source: Path, **updates: Any) -> None:
        key = str(source)
        current = self._records.get(key, {'path': key, 'name': source.name, 'suffix': source.suffix.lower()})
        current.update(updates)
        current['updated_at'] = time.time()
        self._records[key] = current

    def _handle_source(self, source: Path) -> None:
        suffix = source.suffix.lower()
        try:
            sig = _signature(source)
        except OSError as err:
            self._record(source, status='failed', message=str(err))
            return
        if sig['size'] > self.max_file_bytes:
            self._record(source, status='failed', message=f'File exceeds {self.max_file_bytes // (1024 * 1024)} MB', **sig)
            return
        if suffix not in CONVERTIBLE_SUFFIXES:
            self._record(source, status='unsupported', message='Detected, but automatic conversion currently supports .3mf and .stl only.', **sig)
            return
        output_dir = source.parent / OUTPUT_FOLDER_NAME
        output_path = output_dir / _safe_output_name(source)
        previous = self._records.get(str(source), {})
        if previous.get('status') == 'ignored' and previous.get('size') == sig['size'] and previous.get('mtime_ns') == sig['mtime_ns']:
            return
        same_input = previous.get('size') == sig['size'] and previous.get('mtime_ns') == sig['mtime_ns']
        current_converter = previous.get('converter_version') == CONVERTER_VERSION
        if same_input and current_converter and previous.get('status') == 'converted' and output_path.exists():
            enrichment: dict[str, Any] = {}
            if not previous.get('converted_at'):
                enrichment['converted_at'] = output_path.stat().st_mtime
            if not previous.get('thumbnail'):
                thumbnail = _thumbnail_data_url(output_path)
                if thumbnail:
                    enrichment['thumbnail'] = thumbnail
            if enrichment:
                self._record(source, **enrichment, **sig)
            return
        if output_path.exists() and output_path.stat().st_mtime_ns >= sig['mtime_ns'] and current_converter and previous.get('status') != 'failed':
            enrichment = {'status': 'converted', 'message': 'Already present in OUTPUT_U1.', 'output_path': str(output_path), 'converted_at': output_path.stat().st_mtime}
            thumbnail = _thumbnail_data_url(output_path)
            if thumbnail:
                enrichment['thumbnail'] = thumbnail
            self._record(source, **enrichment, **sig)
            return
        if same_input and previous.get('status') == 'failed':
            return
        self._record(source, status='running', message='Building U1 package...', output_path=str(output_path), **sig)
        try:
            self._convert_source(source, output_path)
        except Exception as err:
            log.exception('automatic conversion failed for %s', source)
            self._record(source, status='failed', message=str(err), output_path=str(output_path), **sig)
        else:
            previous_message = str(self._records.get(str(source), {}).get('message') or 'Saved in OUTPUT_U1.')
            enrichment = {'status': 'converted', 'message': previous_message, 'output_path': str(output_path), 'converted_at': time.time(), 'converter_version': CONVERTER_VERSION}
            thumbnail = _thumbnail_data_url(output_path)
            if thumbnail:
                enrichment['thumbnail'] = thumbnail
            self._record(source, **enrichment, **sig)

    def _convert_source(self, source: Path, output_path: Path) -> None:
        profiles = list_profiles(self.profiles_dir, self.user_profiles_dir)
        if not profiles:
            raise ProfileLoadError('No U1 reference profiles are available')
        with tempfile.TemporaryDirectory(dir=self.tmp_dir) as workdir_raw:
            workdir = Path(workdir_raw)
            source_for_engine = source
            source_settings = None
            detected_note = None
            if source.suffix.lower() == '.stl':
                source_for_engine = workdir / f'{source.stem}.3mf'
                _write_geometry_3mf_from_stl(source, source_for_engine)
                detected_note = 'STL geometry, defaulted to 0.20 Standard.'
            source_settings, _slicer = read_source_settings(source_for_engine)
            profile = suggest_profile(profiles, source_settings)
            if profile is None:
                raise ProfileLoadError('No matching U1 reference profile was found')
            with zipfile.ZipFile(source_for_engine) as zf:
                names = zf.namelist()
            filaments = source_settings.get('filament_settings_id') or []
            slot_map: dict[int, int] = {}
            if is_painted_model(names, len(filaments)) and len(filaments) > 4:
                slot_map = {idx: idx % 4 for idx in range(len(filaments))}
            output_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_output = workdir / output_path.name
            result = forge_package(
                source_path=source_for_engine,
                reference_path=Path(profile.path),
                output_path=tmp_output,
                settings=BuildRequestSettings(
                    reference_profile=profile.id,
                    apply_recipe_book=True,
                    clamp_speeds=True,
                    preserve_color_painting=True,
                    advanced_overrides={},
                    slot_map=slot_map,
                    insert_swap_pauses=False,
                    exclude_object=self.exclude_object_enabled(),
                ),
                rules=load_recipe_book(self.rules_dir),
            )
            shutil.copy2(result.output_path, output_path)
            message = f'Profile: {profile.display_name}.'
            if detected_note:
                message = f'{message} {detected_note}'
            with self._lock:
                record = self._records.get(str(source), {})
                record['profile'] = profile.display_name
                record['message'] = message
                self._records[str(source)] = record
