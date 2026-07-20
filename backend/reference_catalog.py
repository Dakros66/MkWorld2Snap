"""Load U1 reference profiles from disk.

User profiles in /app/user_profiles take precedence over bundled profiles in
/app/profiles (same id => user wins). Each profile is a full Snapmaker Orca
.3mf export containing Metadata/project_settings.config.
"""
from __future__ import annotations
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from workshop_types import ProfileCard
PROJECT_SETTINGS = 'Metadata/project_settings.config'
MODEL_SETTINGS = 'Metadata/model_settings.config'
MODEL_3D = '3D/3dmodel.model'
_PLATE_GCODE_RE = re.compile('^Metadata/plate_\\d+\\.gcode$')

class ProfileNotFoundError(Exception):
    pass

class ProfileLoadError(Exception):
    pass

def _profile_id_from_name(path: Path) -> str:
    local_00 = path.stem.strip().lower()
    return re.sub('[^a-z0-9.]+', '-', local_00).strip('-')

def read_project_settings(profile_path: Path) -> dict:
    """Return parsed project_settings.config from a reference 3mf."""
    if not profile_path.exists():
        raise ProfileNotFoundError(str(profile_path))
    try:
        with zipfile.ZipFile(profile_path, 'r') as local_00:
            if PROJECT_SETTINGS not in local_00.namelist():
                raise ProfileLoadError(f'{profile_path.name} is missing {PROJECT_SETTINGS}')
            local_01 = local_00.read(PROJECT_SETTINGS).decode('utf-8')
            return json.loads(local_01)
    except zipfile.BadZipFile as err:
        raise ProfileLoadError(f'{profile_path.name} is not a valid zip') from err
    except json.JSONDecodeError as err:
        raise ProfileLoadError(f'{profile_path.name} has malformed project_settings.config') from err

def read_source_settings(source_path: Path) -> tuple[dict, str | None]:
    """Read settings from any supported 3mf format.

    Returns (settings_dict, detected_slicer) where detected_slicer is:
      None         — Orca/Bambu format (caller checks printer_model for Bambu vs other)
      "PrusaSlicer" — Metadata/Slic3r_PE.config present
      "Cura"        — Cura/ directory present
      "Unknown"     — valid 3mf but no recognised slicer config
    Raises ProfileLoadError if the file is not a valid zip.
    """
    try:
        with zipfile.ZipFile(source_path, 'r') as local_00:
            local_01 = local_00.namelist()
            _reject_sliced_gcode_without_geometry(source_path.name, local_00, local_01)
            if PROJECT_SETTINGS in local_01:
                local_02 = local_00.read(PROJECT_SETTINGS).decode('utf-8')
                try:
                    return (json.loads(local_02), None)
                except json.JSONDecodeError as err:
                    raise ProfileLoadError(f'{source_path.name} has malformed project_settings.config') from err
            if 'Metadata/Slic3r_PE.config' in local_01:
                local_02 = local_00.read('Metadata/Slic3r_PE.config').decode('utf-8')
                local_03 = _read_prusa_settings(local_02)
                return (local_03, 'PrusaSlicer')
            local_04 = [local_05 for local_05 in local_01 if local_05.startswith('Cura/') and (local_05.endswith('.cfg') or local_05.endswith('.fdm_material') or local_05.endswith('.xml'))]
            if local_04:
                local_03 = _read_cura_settings([(local_06, local_00.read(local_06).decode('utf-8', errors='replace')) for local_06 in sorted(local_04)])
                return (local_03, 'Cura')
            if '3D/3dmodel.model' in local_01:
                return ({'layer_height': '0.20', 'print_settings_id': 'Geometry fallback 0.20 Standard', 'filament_settings_id': ['Generic PLA'], 'filament_type': ['PLA'], 'filament_colour': ['#808080'], 'filament_diameter': ['1.75'], 'nozzle_temperature': ['220'], 'nozzle_temperature_initial_layer': ['220'], 'hot_plate_temp': ['60'], 'hot_plate_temp_initial_layer': ['60']}, 'Geometry')
    except zipfile.BadZipFile as err:
        raise ProfileLoadError(f'{source_path.name} is not a valid zip') from err
    raise ProfileLoadError(f'{source_path.name}: unrecognised 3mf format')

def _setting(raw: str, key: str) -> str | None:
    local_00 = f'^\\s*;?\\s*{re.escape(key)}\\s*=\\s*(.*?)\\s*$'
    local_01 = re.search(local_00, raw, re.MULTILINE)
    return local_01.group(1).strip().strip('"') if local_01 else None

def _split_setting(value: str | None) -> list[str]:
    if value is None:
        return []
    local_00 = [local_01.strip().strip('"') for local_01 in value.split(';')]
    return [local_01 for local_01 in local_00 if local_01 != '']

def _repeat_scalar(value: str | None, count: int) -> list[str]:
    if value is None or count <= 0:
        return []
    return [value] * count

def _read_prusa_settings(raw: str) -> dict:
    local_00: dict = {}
    if (local_01 := _setting(raw, 'layer_height')):
        local_00['layer_height'] = local_01
    local_02 = _split_setting(_setting(raw, 'filament_type'))
    local_03 = _split_setting(_setting(raw, 'filament_settings_id'))
    if not local_03 and local_02:
        local_03 = [f'Prusa {local_04}' if local_04 else 'Prusa filament' for local_04 in local_02]
    if local_03:
        local_00['filament_settings_id'] = local_03
    if local_02:
        local_00['filament_type'] = local_02
    local_05 = {'#FF8000', '#FF8000FF', ''}
    for local_06 in ('extruder_colour', 'filament_colour'):
        local_07 = _split_setting(_setting(raw, local_06))
        if local_07 and any((local_08 not in local_05 for local_08 in local_07)):
            local_00['filament_colour'] = local_07
            break
    local_09 = len(local_00.get('filament_settings_id') or local_00.get('filament_type') or [])
    for local_10, local_11 in (('single_extruder_multi_material', 'single_extruder_multi_material'), ('wipe_tower', 'enable_prime_tower'), ('printer_model', 'printer_model')):
        if (local_12 := _setting(raw, local_10)):
            local_00[local_11] = local_12
    for local_10, local_11 in (('nozzle_diameter', 'nozzle_diameter'), ('filament_diameter', 'filament_diameter'), ('temperature', 'nozzle_temperature'), ('first_layer_temperature', 'nozzle_temperature_initial_layer'), ('bed_temperature', 'hot_plate_temp'), ('first_layer_bed_temperature', 'hot_plate_temp_initial_layer')):
        local_13 = _split_setting(_setting(raw, local_10))
        if local_13:
            local_00[local_11] = local_13 if len(local_13) > 1 else local_13[0]
        elif local_09 and (local_14 := _setting(raw, local_10)):
            local_00[local_11] = _repeat_scalar(local_14, local_09)
    return local_00

def _read_cura_settings(raw_files: list[tuple[str, str]]) -> dict:
    local_00: dict = {}
    local_01 = [(local_02, local_03) for local_02, local_03 in raw_files if local_02.endswith('.cfg')]
    local_04 = [_read_cura_material_xml(local_03) for local_02, local_03 in raw_files if local_02.endswith('.fdm_material') or local_02.endswith('.xml')]
    local_04 = [local_05 for local_05 in local_04 if local_05]
    local_06 = '\n'.join((local_03 for local_07, local_03 in local_01))
    if (local_08 := _setting(local_06, 'layer_height')):
        local_00['layer_height'] = local_08
    elif (local_09 := _setting(local_06, 'layer_height_0')):
        local_00['layer_height'] = local_09
    if (local_10 := _setting(local_06, 'machine_name')):
        local_00['printer_model'] = local_10
    local_11 = [(local_02, local_03) for local_02, local_03 in local_01 if _cura_extruder_index(local_02) is not None]
    if local_11:
        local_11.sort(key=lambda item: _cura_extruder_index(item[0]) or 0)
        local_12 = []
        for local_13, (local_07, local_03) in enumerate(local_11):
            local_14 = _read_cura_material_cfg(local_03)
            if local_13 < len(local_04):
                local_14 = {**local_04[local_13], **local_14}
            local_12.append(local_14)
    else:
        local_15 = _read_cura_material_cfg(local_06)
        if local_04:
            local_15 = {**local_04[0], **local_15}
        local_12 = [local_15]
    _apply_cura_material_arrays(local_00, local_12)
    local_16 = len(local_00.get('filament_settings_id') or []) or 1
    local_17 = _setting(local_06, 'material_bed_temperature')
    local_18 = _setting(local_06, 'material_bed_temperature_layer_0')
    if local_17:
        local_00['hot_plate_temp'] = _repeat_scalar(local_17, local_16)
    if local_18:
        local_00['hot_plate_temp_initial_layer'] = _repeat_scalar(local_18, local_16)
    if (local_19 := _setting(local_06, 'machine_nozzle_size')):
        local_00['nozzle_diameter'] = _repeat_scalar(local_19, local_16)
    if 'filament_settings_id' not in local_00:
        local_00['filament_settings_id'] = ['Cura material']
    if 'filament_type' not in local_00:
        local_00['filament_type'] = ['PLA']
    return local_00

def _cura_extruder_index(name: str) -> int | None:
    local_00 = re.search('extruder[_-]?(\\d+)', Path(name).stem, re.IGNORECASE)
    return int(local_00.group(1)) if local_00 else None

def _read_cura_material_cfg(raw: str) -> dict:
    local_00 = _setting(raw, 'material_type') or _setting(raw, 'material_generic')
    local_01 = _setting(raw, 'material_name') or local_00
    return {'name': local_01, 'type': local_00, 'brand': _setting(raw, 'material_brand'), 'colour': _setting(raw, 'material_colour'), 'diameter': _setting(raw, 'material_diameter'), 'temperature': _setting(raw, 'material_print_temperature'), 'initial_temperature': _setting(raw, 'material_print_temperature_layer_0')}

def _read_cura_material_xml(raw: str) -> dict:
    try:
        local_00 = ET.fromstring(raw)
    except ET.ParseError:
        return {}

    def first_text(*names: str) -> str | None:
        local_00 = {local_01.lower() for local_01 in names}
        for local_02 in local_00.iter():
            local_03 = local_02.tag.rsplit('}', 1)[-1].lower()
            if local_03 in local_00 and local_02.text and local_02.text.strip():
                return local_02.text.strip()
        return None
    return {'name': first_text('name', 'display_name'), 'type': first_text('material', 'material_type', 'generic_material'), 'brand': first_text('brand', 'manufacturer'), 'colour': first_text('color_code', 'colour', 'color'), 'diameter': first_text('diameter'), 'temperature': first_text('print_temperature'), 'initial_temperature': first_text('standby_temperature')}

def _apply_cura_material_arrays(cfg: dict, materials: list[dict]) -> None:
    local_00 = materials or [{}]
    local_01: list[str] = []
    local_02: list[str] = []
    local_03: list[str] = []
    local_04: list[str] = []
    local_05: list[str] = []
    local_06: list[str] = []
    local_07: list[str] = []
    for local_08 in local_00:
        local_09 = local_08.get('type') or 'PLA'
        local_10 = local_08.get('name') or f'Cura {local_09}'
        local_01.append(local_10)
        local_02.append(local_09)
        local_03.append(local_08.get('brand') or '')
        local_04.append(local_08.get('colour') or '#808080')
        local_05.append(local_08.get('diameter') or '1.75')
        local_06.append(local_08.get('temperature') or '220')
        local_07.append(local_08.get('initial_temperature') or local_08.get('temperature') or '220')
    cfg['filament_settings_id'] = local_01
    cfg['filament_type'] = local_02
    cfg['filament_vendor'] = local_03
    cfg['filament_colour'] = local_04
    cfg['filament_diameter'] = local_05
    cfg['nozzle_temperature'] = local_06
    cfg['nozzle_temperature_initial_layer'] = local_07

def _reject_sliced_gcode_without_geometry(filename: str, zf: zipfile.ZipFile, names: list[str]) -> None:
    """Reject sliced G-code 3MF packages that no longer contain editable geometry."""
    if not any((_PLATE_GCODE_RE.match(local_00) for local_00 in names)):
        return
    local_01 = any((local_00.startswith('3D/Objects/') and local_00.endswith('.model') for local_00 in names))
    if local_01:
        return
    local_02 = zf.read(MODEL_3D).decode('utf-8', errors='replace') if MODEL_3D in names else ''
    local_03 = bool(re.search('<(?:\\w+:)?object\\b', local_02) or re.search('<(?:\\w+:)?mesh\\b', local_02) or re.search('<(?:\\w+:)?item\\b', local_02))
    if local_03:
        return
    raise ProfileLoadError(f'{filename} appears to be a sliced G-code 3MF with no model geometry. Use the original project .3mf instead; if you only have STL/model files, open them in a slicer and export a project .3mf first.')

def read_model_settings(profile_path: Path) -> str | None:
    """Return raw model_settings.config text, or None if absent."""
    if not profile_path.exists():
        raise ProfileNotFoundError(str(profile_path))
    with zipfile.ZipFile(profile_path, 'r') as local_00:
        if MODEL_SETTINGS not in local_00.namelist():
            return None
        return local_00.read(MODEL_SETTINGS).decode('utf-8')

def _descriptor(path: Path, source: str) -> ProfileCard:
    try:
        local_00 = read_project_settings(path)
    except (ProfileLoadError, ProfileNotFoundError):
        local_00 = {}
    return ProfileCard(id=_profile_id_from_name(path), display_name=_clean_display_name(path.stem), path=str(path), source=source, layer_height=_as_str(local_00.get('layer_height')), printer_variant=_as_str(local_00.get('printer_variant')))
_MODEL_SUFFIX_RE = re.compile('\\s+-\\s+[A-Za-z][A-Za-z\\s]*$')

def _clean_display_name(stem: str) -> str:
    """Strip a trailing model label while keeping profile quality tokens."""
    return _MODEL_SUFFIX_RE.sub('', stem).strip()

def _as_str(v: object) -> str | None:
    if v is None:
        return None
    if isinstance(v, list):
        return ','.join((str(local_00) for local_00 in v))
    return str(v)

def list_profiles(bundled_dir: Path, user_dir: Path | None=None) -> list[ProfileCard]:
    """Discover all .3mf reference profiles, user-dir shadowing bundled."""
    local_00: dict[str, ProfileCard] = {}
    for local_01 in sorted(bundled_dir.glob('*.3mf')):
        local_02 = _descriptor(local_01, source='bundled')
        local_00[local_02.id] = local_02
    if user_dir is not None and user_dir.exists():
        for local_01 in sorted(user_dir.glob('*.3mf')):
            local_02 = _descriptor(local_01, source='user')
            local_00[local_02.id] = local_02
    return sorted(local_00.values(), key=lambda d: d.display_name)
_QUALITY_KEYWORDS = ('extra draft', 'fast draft', 'draft', 'fine detail', 'fine', 'high quality', 'balanced', 'optimal', 'strength', 'standard')

def suggest_profile(profiles: list[ProfileCard], source_settings: dict) -> ProfileCard | None:
    """Return the best-matching U1 profile for the given source project_settings.

    Matching priority:
      1. Same layer_height AND quality keyword present in print_settings_id
      2. Same layer_height, any quality
      3. Closest layer_height (fallback)
    """
    if not profiles:
        return None
    local_00 = source_settings.get('layer_height')
    try:
        local_01 = round(float(local_00), 4) if local_00 is not None else None
    except (TypeError, ValueError):
        local_01 = None
    local_02 = str(source_settings.get('print_settings_id') or '').lower()
    local_03 = next((local_04 for local_04 in _QUALITY_KEYWORDS if local_04 in local_02), None)
    local_05 = []
    for local_06 in profiles:
        try:
            local_07 = round(float(local_06.layer_height), 4) if local_06.layer_height else None
        except (TypeError, ValueError):
            local_07 = None
        if local_01 is not None and local_07 == local_01:
            local_05.append(local_06)
    if local_05:
        if local_03:
            local_08 = [local_06 for local_06 in local_05 if local_03 in local_06.display_name.lower()]
            if local_03 == 'standard':
                local_09 = next((local_06 for local_06 in local_08 if 'palette' not in local_06.display_name.lower()), local_08[0] if local_08 else None)
            else:
                local_09 = local_08[0] if local_08 else None
            if local_09:
                return local_09
        return local_05[0]
    if local_01 is not None:

        def _dist(p: ProfileCard) -> float:
            try:
                return abs(float(p.layer_height or 0) - local_01)
            except (TypeError, ValueError):
                return 999.0
        return min(profiles, key=_dist)
    local_10 = next((local_06 for local_06 in profiles if (local_06.layer_height or '').startswith('0.2') and 'standard' in local_06.display_name.lower() and ('palette' not in local_06.display_name.lower())), profiles[0])
    return local_10

def resolve_profile(profile_id: str, bundled_dir: Path, user_dir: Path | None=None) -> ProfileCard:
    """Look up a single profile by id, user-dir first."""
    local_00 = list_profiles(bundled_dir, user_dir)
    for local_01 in local_00:
        if local_01.id == profile_id:
            return local_01
    local_02 = profile_id.strip().lower()
    for local_01 in local_00:
        if local_01.display_name.strip().lower() == local_02:
            return local_01
    raise ProfileNotFoundError(f'no reference profile with id {profile_id!r} (have: {[local_01.id for local_01 in local_00]})')
