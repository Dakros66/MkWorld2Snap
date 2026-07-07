"""3MF package rebuild pipeline.

Run order:

  1. Load source project_settings + model_settings from the uploaded 3mf
  2. Load the U1 reference profile
  3. Identity rebuild (printer_* keys, build volume, nozzle list)
  4. Custom script replacement
  5. Key filter (drop source-specific keys)
  6. Value clamp (speed / accel ceilings from the reference)
  7. Material recipe engine
  8. Advanced user overrides (from the UI, applied last so they win)
  9. Normalise filament_* arrays to 4 slots (U1 has 4 toolheads)
 10. Filament slot remap on model_settings.config
 11. Key-filter model_settings.config (no-op in v1 — we don't drop XML attrs)
 12. Strip Metadata/plate_*.gcode / plate_*.json slice caches
 13. Repack as ``{original}-U1.3mf`` alongside a BuildReport JSON

The pipeline is pure over file contents — it reads a source path, reads a
reference path, and writes to an output path. Runtime and HTTP concerns live in
``local_gateway.py``.
"""
from __future__ import annotations
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
log = logging.getLogger('mkworld2snap.u1_packager')
from activity_report import ChangeLedger
from machine_script_library import GCODE_KEYS, swap_gcode
from parameter_guardrails import clamp_numeric_ceilings, filter_to_schema
from scene_metadata import minimal_model_settings, minimal_slice_info, rewrite_custom_gcode_per_layer, rewrite_slice_info, translate_prusa_mmu_paint
from workshop_types import BuildRequestSettings, BuildReport, RecipeDefinition, SlotRemapEvent
from reference_catalog import read_project_settings, read_source_settings
from spool_tuning import SpoolMatchContext, apply_recipe_book
from pause_planner import insert_swap_pauses
IDENTITY_COPY_KEYS: tuple[str, ...] = ('printer_settings_id', 'printer_model', 'printer_variant', 'printable_area', 'printable_height', 'nozzle_diameter', 'nozzle_type', 'nozzle_volume', 'compatible_printers', 'compatible_printers_condition', 'print_compatible_printers', 'print_compatible_printers_condition', 'upward_compatible_machine', 'default_print_profile', 'default_filament_profile', 'bed_exclude_area', 'version')
_FILAMENT_SLOT_SENTINEL_KEYS: frozenset[str] = frozenset({'wall_filament', 'sparse_infill_filament', 'solid_infill_filament', 'support_filament', 'support_interface_filament', 'wipe_tower_filament'})
_NEGATIVE_SENTINEL_KEYS: frozenset[str] = frozenset({'raft_first_layer_expansion', 'tree_support_wall_count', 'prime_tower_lift_height'})
_VALUE_REMAP: dict[str, dict[str, str]] = {'ensure_vertical_shell_thickness': {'disabled': 'none', 'enabled': 'ensure_all', 'partial': 'ensure_all'}, 'support_style': {'tree_organic': 'default'}}
_U1_TOOLHEADS_DEFAULT = 4
_DIFFERENCE_MARKER_SKIP_KEYS: frozenset[str] = frozenset({
    'different_settings_to_system',
    'print_settings_id',
    'printer_settings_id',
    'printer_model',
    'printer_variant',
    'printable_area',
    'printable_height',
    'compatible_printers',
    'compatible_printers_condition',
    'print_compatible_printers',
    'print_compatible_printers_condition',
    'upward_compatible_machine',
    'default_print_profile',
    'default_filament_profile',
    'inherits',
    'inherits_group',
    'version',
})
PROJECT_SETTINGS = 'Metadata/project_settings.config'
MODEL_SETTINGS = 'Metadata/model_settings.config'
SLICE_INFO = 'Metadata/slice_info.config'
CUSTOM_GCODE_XML = 'Metadata/custom_gcode_per_layer.xml'
MODEL_3D = '3D/3dmodel.model'
_MULTIPLATE_SPAN_MM = 400.0
_BED_MARGIN_MM = 3.0

def is_painted_model(archive_names: list[str], filament_count: int) -> bool:
    """True when the file likely uses painted geometry rather than per-layer colour G-code."""
    return CUSTOM_GCODE_XML not in archive_names and filament_count > 1
_SLICE_ARTIFACT_PATTERNS = (re.compile('^Metadata/plate_\\d+\\.gcode(\\.md5)?$'), re.compile('^Metadata/plate_\\d+\\.json$'), re.compile('^Metadata/_rels/'), re.compile('^Metadata/process_settings_\\d+\\.config$'), re.compile('^Metadata/filament_settings_\\d+\\.config$'))
_SOURCE_ONLY_FILES: frozenset[str] = frozenset({'Metadata/filament_sequence.json', 'Metadata/cut_information.xml', 'Metadata/auxiliary.xml'})
_PRUSA_ONLY_FILES: frozenset[str] = frozenset({'Metadata/Slic3r_PE.config', 'Metadata/Slic3r_PE_model.config', 'Metadata/Prusa_Slicer_wipe_tower_information.xml'})

@dataclass
class ForgeResult:
    output_path: Path
    diff: BuildReport

def forge_package(*, source_path: Path, reference_path: Path, output_path: Path, settings: BuildRequestSettings, rules: list[RecipeDefinition], preserve_source_metadata: bool=False) -> ForgeResult:
    """Run the full pipeline. Returns the output path + BuildReport.

    ``preserve_source_metadata`` — when True, source-specific metadata files
    (filament_sequence.json, cut_information.xml, auxiliary.xml) are kept in
    the output and model_settings.config is not rewritten.  Use this for
    advanced same-family profile retargeting where those files remain valid.
    """
    local_00 = time.monotonic()
    local_01 = source_path.stat().st_size
    log.info('START  %s  (%.1f KB)  profile=%s  rules=%s  clamp=%s  painting=%s', source_path.name, local_01 / 1024, reference_path.stem, settings.apply_recipe_book, settings.clamp_speeds, settings.preserve_color_painting)
    local_02, local_03 = read_source_settings(source_path)
    local_04 = read_project_settings(reference_path)
    with zipfile.ZipFile(source_path) as local_05:
        local_06 = local_05.namelist()
    local_07 = is_painted_model(local_06, len(local_02.get('filament_settings_id') or []))
    local_08 = local_02.get('printer_model', '?')
    local_09 = local_02.get('layer_height', '?')
    local_10 = local_02.get('filament_settings_id') or []
    log.info('SOURCE printer=%s  layer_height=%s  filaments=%s', local_08, local_09, local_10)
    local_11 = ChangeLedger(source_filename=source_path.name, output_filename=output_path.name, reference_profile=reference_path.stem)
    local_12 = _apply_identity_swap(local_02, local_04, local_11)
    local_12['print_settings_id'] = _output_process_label(local_04, reference_path)
    local_13 = len(local_11.build().identity_swaps)
    log.info('STAGE  identity-swap: %d keys updated', local_13)
    local_12, local_14 = swap_gcode(local_12, local_04)
    local_11.extend_gcode_swaps(local_14)
    log.info('STAGE  gcode-swap: %d blocks replaced', len(local_14))
    local_15 = set(local_04.keys())
    local_12, local_16 = filter_to_schema(local_12, local_15, keep_keys=['custom_gcode_per_layer', 'internal_bridge_support_thickness'])
    local_11.extend_keys_dropped(local_16)
    log.info('STAGE  key-filter: %d keys dropped', len(local_16))
    for local_17, local_18 in local_04.items():
        local_12.setdefault(local_17, local_18)
    if not preserve_source_metadata:
        local_12['wipe_tower_wall_type'] = 'rectangle'
    if preserve_source_metadata and 'print_compatible_printers' in local_04:
        local_12['print_compatible_printers'] = local_04['print_compatible_printers']
    if 'inherits_group' in local_12:
        local_19 = len(local_12['inherits_group']) if isinstance(local_12['inherits_group'], list) else 0
        local_12['inherits_group'] = [''] * local_19
    local_12 = _collapse_extruder_lists(local_12, local_04)
    log.info('STAGE  collapse-lists: done')
    local_20 = 0
    for local_21 in _FILAMENT_SLOT_SENTINEL_KEYS:
        if local_12.get(local_21) in ('0', 0):
            local_12[local_21] = '1'
            local_20 += 1
    local_22 = 0
    for local_21, local_23 in list(local_12.items()):
        if not (local_21 == 'line_width' or local_21.endswith('_line_width')):
            continue
        if local_21 == 'brim_width':
            continue
        try:
            if float(str(local_23)) == 0.0 and local_21 in local_04:
                local_24 = local_04[local_21]
                if float(str(local_24)) > 0:
                    local_12[local_21] = local_24
                    local_22 += 1
        except (TypeError, ValueError):
            pass
    if local_22:
        log.info('STAGE  sentinels: lw_zero=%d', local_22)
    local_25 = 0
    for local_21 in _NEGATIVE_SENTINEL_KEYS:
        try:
            if float(str(local_12.get(local_21))) == -1.0 and local_21 in local_04:
                local_12[local_21] = local_04[local_21]
                local_25 += 1
        except (TypeError, ValueError):
            pass
    local_26 = 0
    for local_21, local_27 in _VALUE_REMAP.items():
        local_23 = local_12.get(local_21)
        if isinstance(local_23, str) and local_23 in local_27:
            local_12[local_21] = local_27[local_23]
            local_26 += 1
    if local_20 or local_25 or local_26:
        log.info('STAGE  sentinels: slot=%d neg=%d enum=%d lw=%d', local_20, local_25, local_26, local_22)
    if settings.clamp_speeds:
        local_12, local_28 = clamp_numeric_ceilings(local_12, local_04)
        local_11.extend_values_clamped(local_28)
        log.info('STAGE  clamp: %d values clamped', len(local_28))
    else:
        log.info('STAGE  clamp: skipped')
    local_29 = 'Metadata/layer_config_ranges.xml'
    local_30 = 'Metadata/layer_heights_profile.txt'
    local_31 = local_29 in local_06 or local_30 in local_06
    log.info('STAGE  vlh: %s', local_31)
    if local_12.get('enable_prime_tower') in ('1', 1) and local_31:
        local_12['enable_prime_tower'] = '0'
        log.info('STAGE  prime-tower: disabled — VLH present (layer_config_ranges or layer_heights_profile)')
    local_32 = local_12.get('support_type', '')
    if 'tree' in str(local_32) and local_30 in local_06:
        local_12['support_type'] = 'normal(auto)'
        log.info('STAGE  supports: tree to normal(auto); layer_heights_profile.txt present (VLH conflict)')
    if settings.apply_recipe_book and rules:
        local_33 = SpoolMatchContext.from_settings(local_02)
        local_12, local_34 = apply_recipe_book(local_12, rules, local_33, valid_keys=local_12.keys())
        local_11.extend_rules_matched(local_34)
        for local_35 in local_34:
            log.info('RULE   %r (priority %d) matched — %d overrides applied, %d skipped', local_35.rule_name, local_35.priority, len(local_35.overrides_applied), len(local_35.overrides_skipped))
        if not local_34:
            log.info('STAGE  rules: no rules matched')
        elif settings.clamp_speeds:
            local_12, local_36 = clamp_numeric_ceilings(local_12, local_04)
            local_11.extend_values_clamped(local_36)
            if local_36:
                log.info('STAGE  post-rules-clamp: %d recipe values clamped', len(local_36))
    else:
        log.info('STAGE  rules: skipped (apply_recipe_book=%s, n_rules=%d)', settings.apply_recipe_book, len(rules))
    for local_17, local_18 in settings.advanced_overrides.items():
        local_12[local_17] = local_18
        local_11.record_advanced_override(local_17, local_18)
    if settings.advanced_overrides and settings.clamp_speeds:
        local_12, local_36 = clamp_numeric_ceilings(local_12, local_04)
        local_11.extend_values_clamped(local_36)
        if local_36:
            log.info('STAGE  post-override-clamp: %d manual values clamped', len(local_36))
    local_12['exclude_object'] = '1' if settings.exclude_object else '0'
    local_11.record_advanced_override('exclude_object', local_12['exclude_object'])
    if settings.advanced_overrides:
        log.info('STAGE  advanced-overrides: %d keys', len(settings.advanced_overrides))
    local_37 = len(local_02.get('filament_settings_id') or [])
    local_38 = len(local_04.get('filament_settings_id') or []) or _U1_TOOLHEADS_DEFAULT
    if preserve_source_metadata and local_37 > 0:
        local_39 = local_37
    elif settings.slot_map:
        local_39 = _U1_TOOLHEADS_DEFAULT
    elif local_07:
        local_39 = local_37
    else:
        local_40 = 'printer_model' not in local_02
        if local_37 > 0:
            local_39 = local_37 if local_40 else min(local_37, local_38)
        elif 'filament_settings_id' in local_02:
            local_39 = local_38
        else:
            local_39 = 1
    local_41 = _normalise_filament_arrays(local_12, local_02, local_11, slot_map=settings.slot_map or {}, n_target=local_39)
    for local_42 in ('nozzle_diameter', 'nozzle_type', 'nozzle_volume'):
        local_43 = local_12.get(local_42)
        if isinstance(local_43, list) and local_43:
            if len(local_43) > local_39:
                local_12[local_42] = local_43[:local_39]
            elif len(local_43) < local_39:
                local_12[local_42] = local_43 + [local_43[-1]] * (local_39 - len(local_43))
    log.info('STAGE  filament-normalise: remap=%s', local_41)
    if preserve_source_metadata:
        _map_filaments_to_reference(local_12, local_02, local_04, local_39)
        log.info('STAGE  filament-profile-remap: done')
    else:
        _map_filaments_to_reference(local_12, local_12, local_04, local_39, prefer_u1=True)
        log.info('STAGE  filament-profile-remap-u1: done')
    if preserve_source_metadata:
        local_44 = len(local_04.get('filament_settings_id') or [])
        if local_44 > 0:
            for local_45, local_46 in local_04.items():
                if not local_45.startswith('filament_') or not isinstance(local_46, list):
                    continue
                if local_02.get(local_45):
                    continue
                if len(local_46) % local_44 != 0:
                    continue
                local_47 = len(local_46) // local_44
                if local_47 <= 1:
                    continue
                if local_45 == 'filament_self_index':
                    local_12[local_45] = [str(local_48 + 1) for local_48 in range(local_39) for local_03 in range(local_47)]
                else:
                    local_49 = local_46[:local_47]
                    local_12[local_45] = local_49 * local_39
        log.info('STAGE  filament-stride-fix: done (n_ref_slots=%d)', local_44)
    if not preserve_source_metadata:
        _refresh_difference_markers(local_12, local_04)
        log.info('STAGE  difference-markers: refreshed')
    local_50: str | None = None
    if settings.insert_swap_pauses:
        with zipfile.ZipFile(source_path) as local_51:
            if CUSTOM_GCODE_XML in local_51.namelist():
                local_52 = local_51.read(CUSTOM_GCODE_XML).decode('utf-8')
                local_53 = local_12.get('filament_colour') or []
                local_54 = local_12.get('machine_pause_gcode', 'M600')
                local_55, local_56 = insert_swap_pauses(local_52, local_41, local_53, local_54)
                if local_56:
                    local_50 = rewrite_custom_gcode_per_layer(local_55, local_54)
                    local_11._report.swap_instructions = local_56
                    log.info('STAGE  swap-pauses: %d pauses inserted', len(local_56))
            else:
                local_11._report.swap_pauses_skipped_painted = True
                log.info('STAGE  swap-pauses: skipped — no custom_gcode_per_layer.xml (painted model)')
    local_57 = local_04.get('printer_model', '')
    _write_output_archive(source_path=source_path, reference_path=reference_path, output_path=output_path, new_project_settings=local_12, remap=local_41, diff=local_11, settings=settings, custom_gcode_xml_override=local_50, preserve_source_metadata=preserve_source_metadata, target_printer_model=local_57)
    local_58 = local_11.build()
    local_59 = output_path.stat().st_size
    local_60 = (time.monotonic() - local_00) * 1000
    local_61 = local_58.counts()
    log.info('DONE   %s  (%.1f KB)  elapsed=%.0f ms  identity=%d  gcode=%d  dropped=%d  clamped=%d  rules=%d  slots=%d', output_path.name, local_59 / 1024, local_60, local_61.get('identity_swaps', 0), local_61.get('gcode_swaps', 0), local_61.get('keys_dropped', 0), local_61.get('values_clamped', 0), local_61.get('rules_matched', 0), local_61.get('slot_remaps', 0))
    return ForgeResult(output_path=output_path, diff=local_58)

def _apply_identity_swap(source_cfg: dict[str, Any], reference_cfg: dict[str, Any], diff: ChangeLedger) -> dict[str, Any]:
    local_00 = dict(source_cfg)
    for local_01 in IDENTITY_COPY_KEYS:
        if local_01 not in reference_cfg:
            continue
        local_02 = local_00.get(local_01)
        local_03 = reference_cfg[local_01]
        if local_02 != local_03:
            diff.record_identity_swap(local_01, local_02, local_03)
        local_00[local_01] = local_03
    return local_00

def _output_process_label(reference_cfg: dict[str, Any], reference_path: Path) -> str:
    local_00 = str(reference_cfg.get('print_settings_id') or reference_path.stem).strip()
    if not local_00:
        local_00 = 'Snapmaker U1 process'
    return local_00

def _collapse_extruder_lists(settings: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """Collapse per-extruder list values to scalars where reference expects a scalar.

    Bambu stores many print settings as [val_ext0, val_ext1, ...].  For keys
    where the U1 reference profile uses a single scalar, take the first element
    so downstream clamping operates on a comparable type.  filament_* arrays are
    intentionally excluded — they are handled by ``_normalise_filament_arrays``.
    """
    local_00 = dict(settings)
    for local_01, local_02 in reference.items():
        if local_01.startswith('filament_') or local_01 not in local_00:
            continue
        local_03 = local_00[local_01]
        if isinstance(local_03, list) and (not isinstance(local_02, list)):
            local_00[local_01] = local_03[0] if local_03 else local_02
    return local_00

def _map_filaments_to_reference(merged: dict[str, Any], source_cfg: dict[str, Any], reference_cfg: dict[str, Any], n_target: int, *, prefer_u1: bool=False) -> None:
    """Replace source filament profiles with target-printer-certified equivalents.

    Source filament_type is matched against reference filament_type to find
    the closest certified profile, for example PLA to Bambu PLA Basic @BBL H2S.
    filament_settings_id, filament_ids, and filament_nozzle_map are updated;
    filament_colour and all embedded temp/speed settings are kept from source.
    """
    local_00 = source_cfg.get('filament_type') or []
    local_01 = source_cfg.get('filament_settings_id') or []
    local_02 = reference_cfg.get('filament_type') or []
    local_03 = reference_cfg.get('filament_settings_id') or []
    local_04 = reference_cfg.get('filament_ids') or []
    local_05 = reference_cfg.get('filament_nozzle_map') or []
    local_10 = ['support', 'matte', 'silk', 'basic', 'high flow', ' hf']

    def local_21(local_22: int, local_23: str, local_24: str) -> int:
        local_25 = str(local_02[local_22] if local_22 < len(local_02) else '').upper()
        local_26 = str(local_03[local_22] if local_22 < len(local_03) else '')
        local_27 = local_26.lower()
        local_28 = 100 if local_25 == str(local_24 or '').upper() else 0
        for local_29 in local_10:
            if local_29 in local_23 and local_29 in local_27:
                local_28 += 140 if local_29 == 'support' else 60
        if prefer_u1:
            if '@u1' in local_27:
                local_28 += 80
            if 'snapmaker' in local_27:
                local_28 += 80
            if 'generic' in local_27:
                local_28 += 25
            if '@bbl' in local_27:
                local_28 -= 200
            if ' x1' in local_27 or ' p1' in local_27 or ' a1' in local_27:
                local_28 -= 120
        else:
            if 'basic' in local_27:
                local_28 += 20
        return local_28

    def local_30(local_23: str, local_24: str) -> int | None:
        local_31 = [local_32 for local_32 in range(len(local_03)) if local_32 < len(local_02) and str(local_02[local_32]).upper() == str(local_24 or '').upper()]
        if not local_31:
            local_31 = list(range(len(local_03)))
        if not local_31:
            return None
        return max(local_31, key=lambda local_32: local_21(local_32, local_23, local_24))

    local_14, local_15, local_16 = ([], [], [])
    for local_07 in range(n_target):
        local_17 = local_00[local_07] if local_07 < len(local_00) else 'PLA'
        local_18 = (local_01[local_07] if local_07 < len(local_01) else '').lower()
        local_19 = local_30(local_18, local_17)
        if local_19 is not None:
            local_14.append(local_03[local_19] if local_19 < len(local_03) else f'Generic {local_17}')
            local_15.append(local_04[local_19] if local_19 < len(local_04) else '')
            local_16.append('1')
        else:
            local_14.append(f'Generic {local_17}' if local_17 else 'Generic PLA')
            local_20 = merged.get('filament_ids') or []
            local_15.append(local_20[local_07] if local_07 < len(local_20) else '')
            local_16.append('0')
    merged['filament_settings_id'] = local_14
    merged['filament_ids'] = local_15
    merged['filament_nozzle_map'] = local_16

def _normalise_filament_arrays(merged: dict[str, Any], source_cfg: dict[str, Any], diff: ChangeLedger, slot_map: dict[int, int] | None=None, n_target: int=_U1_TOOLHEADS_DEFAULT) -> dict[int, int]:
    """Reorder, pad, and truncate every ``filament_*`` array to n_target slots.

    ``slot_map`` maps 0-indexed source slots to 0-indexed target toolheads.
    If empty/None the identity map is used (slot N to toolhead N).
    Source slots that map beyond n_target are dropped; unpopulated target
    slots are filled by repeating the last mapped entry.
    """
    local_00 = source_cfg.get('filament_settings_id') or []
    local_01 = len(local_00)
    local_02: dict[int, int] = {}
    for local_03 in range(local_01):
        if slot_map and local_03 in slot_map:
            local_04 = slot_map[local_03]
        else:
            local_04 = local_03
        if local_04 >= n_target:
            local_04 = -1
        local_02[local_03] = local_04
    for local_03, local_04 in local_02.items():
        diff.extend_slot_remaps([SlotRemapEvent(from_index=local_03, to_index=local_04, filament_id=local_00[local_03] if local_03 < len(local_00) else None)])
    for local_05, local_06 in list(merged.items()):
        if not (local_05.startswith('filament_') and isinstance(local_06, list)):
            continue
        if not local_06:
            continue
        local_07: list[Any] = [None] * n_target
        local_08 = local_06[-1] if local_06 else None
        for local_09, local_10 in local_02.items():
            if local_10 >= 0 and local_09 < len(local_06) and (local_07[local_10] is None):
                local_07[local_10] = local_06[local_09]
        for local_11 in range(n_target):
            if local_07[local_11] is None:
                local_07[local_11] = local_08
        merged[local_05] = local_07
    return local_02

def _marker_key_list(value: Any) -> list[str]:
    if isinstance(value, list) and value:
        value = value[0]
    if not isinstance(value, str):
        return []
    return [local_00.strip() for local_00 in value.split(';') if local_00.strip()]

def _marker_values_differ(value: Any, reference_value: Any) -> bool:
    if value == reference_value:
        return False
    if isinstance(value, list) or isinstance(reference_value, list):
        return value != reference_value
    return str(value) != str(reference_value)

def _refresh_difference_markers(settings: dict[str, Any], reference: dict[str, Any]) -> None:
    """Populate Orca's "changed from system profile" marker list.

    Orca/Bambu uses ``different_settings_to_system`` to decide which process
    fields should be highlighted as changed.  Recompute the process entry
    against the selected U1 reference while preserving existing filament-slot
    marker entries.
    """
    local_00 = settings.get('different_settings_to_system')
    local_01: list[Any] = list(local_00) if isinstance(local_00, list) else ([local_00] if isinstance(local_00, str) else [])
    local_02 = set(_marker_key_list(local_01[0] if local_01 else ''))
    for local_03, local_04 in settings.items():
        if local_03 in _DIFFERENCE_MARKER_SKIP_KEYS:
            continue
        if local_03.startswith('filament_') or local_03.startswith('printer_'):
            continue
        if local_03.startswith('machine_') or local_03.startswith('nozzle_'):
            continue
        if local_03 not in reference:
            continue
        if _marker_values_differ(local_04, reference.get(local_03)):
            local_02.add(local_03)
    local_05 = ';'.join(sorted(local_02))
    local_06 = max(len(local_01), 1 + len(settings.get('filament_settings_id') or []), 1)
    local_07 = [''] * local_06
    local_07[0] = local_05
    for local_08 in range(1, min(len(local_01), local_06)):
        local_07[local_08] = str(local_01[local_08] or '')
    settings['different_settings_to_system'] = local_07

def _bed_shift(model_xml: str, src_printable_area: list[str], ref_printable_area: list[str]) -> tuple[str, bool]:
    """Shift build item translations so objects clear the U1 bed origin.

    Bambu beds start at (0, 0); the U1 bed starts at (0.5, 1).  Models that
    fill the source bed to its front/left edge land 1mm off the U1 plate.

    For multi-plate files (build items spread > _MULTIPLATE_SPAN_MM), skip
    the shift — each plate has its own world-space offset and a uniform
    translation would misalign all but the first plate.

    Returns (possibly-modified xml, shifted: bool).
    """
    local_00 = re.findall('transform="([^"]+)"', model_xml)
    if not local_00:
        return (model_xml, False)
    local_01 = []
    local_02 = []
    for local_03 in local_00:
        local_04 = local_03.split()
        if len(local_04) == 12:
            local_01.append(float(local_04[9]))
            local_02.append(float(local_04[10]))
    if not local_01:
        return (model_xml, False)
    if max(local_01) - min(local_01) > _MULTIPLATE_SPAN_MM or max(local_02) - min(local_02) > _MULTIPLATE_SPAN_MM:
        return (model_xml, False)

    def _parse_min(area: list[str]) -> tuple[float, float]:
        local_00, local_01 = ([], [])
        for local_02 in area:
            local_03, local_04 = local_02.split('x')
            local_00.append(float(local_03))
            local_01.append(float(local_04))
        return (min(local_00), min(local_01))
    local_10, local_11 = _parse_min(src_printable_area)
    local_12, local_13 = _parse_min(ref_printable_area)
    local_14 = local_12 - local_10 + _BED_MARGIN_MM
    local_15 = local_13 - local_11 + _BED_MARGIN_MM
    if abs(local_14) < 1e-06 and abs(local_15) < 1e-06:
        return (model_xml, False)

    def _replace(m: re.Match) -> str:
        local_00 = m.group(0)
        local_01 = re.search('transform="([^"]+)"', local_00)
        if not local_01:
            return m.group(0)
        local_02 = local_01.group(1).split()
        if len(local_02) != 12:
            return m.group(0)
        local_02[9] = f'{float(local_02[9]) + local_14:.6g}'
        local_02[10] = f'{float(local_02[10]) + local_15:.6g}'
        return local_00[:local_01.start(1)] + ' '.join(local_02) + local_00[local_01.end(1):]
    return (re.sub('<item\\b[^>]*>', _replace, model_xml), True)

def _xml_name(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]

def _identity_transform() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]

def _parse_transform(value: str | None) -> list[float]:
    if not value:
        return _identity_transform()
    try:
        local_00 = [float(local_01) for local_01 in value.split()]
    except ValueError:
        return _identity_transform()
    return local_00 if len(local_00) == 12 else _identity_transform()

def _apply_transform(point: tuple[float, float, float], matrix: list[float]) -> tuple[float, float, float]:
    local_00, local_01, local_02 = point
    return (matrix[0] * local_00 + matrix[3] * local_01 + matrix[6] * local_02 + matrix[9], matrix[1] * local_00 + matrix[4] * local_01 + matrix[7] * local_02 + matrix[10], matrix[2] * local_00 + matrix[5] * local_01 + matrix[8] * local_02 + matrix[11])

def _compose_transform(first: list[float], second: list[float]) -> list[float]:
    local_00: list[float] = []
    for local_01 in range(3):
        local_02 = (second[local_01 * 3], second[local_01 * 3 + 1], second[local_01 * 3 + 2])
        local_00.extend([first[0] * local_02[0] + first[3] * local_02[1] + first[6] * local_02[2], first[1] * local_02[0] + first[4] * local_02[1] + first[7] * local_02[2], first[2] * local_02[0] + first[5] * local_02[1] + first[8] * local_02[2]])
    local_03 = _apply_transform((second[9], second[10], second[11]), first)
    local_00.extend([local_03[0], local_03[1], local_03[2]])
    return local_00

def _read_printable_bounds(area: list[str]) -> tuple[float, float, float, float]:
    local_00: list[float] = []
    local_01: list[float] = []
    for local_02 in area:
        try:
            local_03, local_04 = local_02.split('x', 1)
            local_00.append(float(local_03))
            local_01.append(float(local_04))
        except (ValueError, AttributeError):
            continue
    if not local_00 or not local_01:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(local_00), min(local_01), max(local_00), max(local_01))

def _plate_object_groups(model_settings_xml: str | None) -> list[tuple[int, list[str]]]:
    if not model_settings_xml:
        return []
    try:
        local_00 = ET.fromstring(model_settings_xml)
    except ET.ParseError:
        return []
    local_01: list[tuple[int, list[str]]] = []
    for local_02, local_03 in enumerate(local_00.findall('.//plate'), start=1):
        local_04 = local_02
        local_05: list[str] = []
        for local_06 in local_03.findall('./metadata'):
            if local_06.get('key') == 'plater_id':
                try:
                    local_04 = int(local_06.get('value') or local_02)
                except ValueError:
                    local_04 = local_02
        for local_07 in local_03.findall('./model_instance'):
            for local_06 in local_07.findall('./metadata'):
                if local_06.get('key') == 'object_id' and local_06.get('value'):
                    local_05.append(local_06.get('value', ''))
        if local_05:
            local_01.append((local_04, local_05))
    return local_01

def _load_model_objects(archive: zipfile.ZipFile, model_name: str, cache: dict[str, dict[str, tuple[list[tuple[float, float, float]], list[tuple[str | None, str | None, list[float]]]]]]) -> dict[str, tuple[list[tuple[float, float, float]], list[tuple[str | None, str | None, list[float]]]]]:
    if model_name in cache:
        return cache[model_name]
    try:
        local_00 = ET.fromstring(archive.read(model_name))
    except Exception:
        cache[model_name] = {}
        return {}
    local_01: dict[str, tuple[list[tuple[float, float, float]], list[tuple[str | None, str | None, list[float]]]]] = {}
    for local_02 in local_00.iter():
        if _xml_name(local_02.tag) != 'object' or not local_02.get('id'):
            continue
        local_03: list[tuple[float, float, float]] = []
        local_04: list[tuple[str | None, str | None, list[float]]] = []
        for local_05 in local_02.iter():
            if _xml_name(local_05.tag) == 'vertex':
                try:
                    local_03.append((float(local_05.get('x', '0')), float(local_05.get('y', '0')), float(local_05.get('z', '0'))))
                except ValueError:
                    continue
            elif _xml_name(local_05.tag) == 'component':
                local_06 = None
                for local_07, local_08 in local_05.attrib.items():
                    if local_07.endswith('path'):
                        local_06 = local_08.lstrip('/')
                        break
                local_04.append((local_06, local_05.get('objectid'), _parse_transform(local_05.get('transform'))))
        local_01[local_02.get('id', '')] = (local_03, local_04)
    cache[model_name] = local_01
    return local_01

def _object_points(archive: zipfile.ZipFile, model_name: str, object_id: str, transform: list[float], cache: dict[str, dict[str, tuple[list[tuple[float, float, float]], list[tuple[str | None, str | None, list[float]]]]]], seen: set[tuple[str, str]] | None=None) -> list[tuple[float, float, float]]:
    local_00 = seen or set()
    if (model_name, object_id) in local_00:
        return []
    local_00.add((model_name, object_id))
    local_01 = _load_model_objects(archive, model_name, cache).get(object_id)
    if not local_01:
        return []
    local_02, local_03 = local_01
    local_04 = [_apply_transform(local_05, transform) for local_05 in local_02]
    for local_06, local_07, local_08 in local_03:
        if not local_07:
            continue
        local_04.extend(_object_points(archive, local_06 or model_name, local_07, _compose_transform(transform, local_08), cache, local_00))
    return local_04

def _item_bboxes_by_object(archive: zipfile.ZipFile, model_xml: str) -> dict[str, tuple[float, float, float, float]]:
    try:
        local_00 = ET.fromstring(model_xml)
    except ET.ParseError:
        return {}
    local_01: dict[str, dict[str, tuple[list[tuple[float, float, float]], list[tuple[str | None, str | None, list[float]]]]]] = {}
    local_02: dict[str, tuple[float, float, float, float]] = {}
    for local_03 in local_00.iter():
        if _xml_name(local_03.tag) != 'item' or not local_03.get('objectid'):
            continue
        local_04 = local_03.get('objectid', '')
        local_05 = _object_points(archive, MODEL_3D, local_04, _parse_transform(local_03.get('transform')), local_01)
        if not local_05:
            continue
        local_06 = [local_07[0] for local_07 in local_05]
        local_08 = [local_07[1] for local_07 in local_05]
        local_02[local_04] = (min(local_06), min(local_08), max(local_06), max(local_08))
    return local_02

def _axis_correction(low: float, high: float, target_low: float, target_high: float) -> float:
    local_00 = target_high - target_low
    local_01 = high - low
    if local_01 > local_00:
        return target_low + (local_00 - local_01) / 2 - low
    if low < target_low:
        return target_low - low
    if high > target_high:
        return target_high - high
    return 0.0

def _axis_centering(low: float, high: float, target_low: float, target_high: float) -> float:
    local_00 = high - low
    local_01 = target_high - target_low
    if local_00 <= 0 or local_00 > local_01:
        return _axis_correction(low, high, target_low, target_high)
    return target_low + (local_01 - local_00) / 2 - low

def _plate_pitch(values: list[float], plate_size: float) -> float | None:
    local_00: list[float] = []
    local_01 = max(10.0, plate_size * 0.55)
    for local_02, local_03 in enumerate(values):
        for local_04 in values[local_02 + 1:]:
            local_05 = abs(local_04 - local_03)
            if local_05 > local_01:
                local_00.append(local_05)
    return min(local_00) if local_00 else None

def _single_plate_reframe(model_xml: str, src_printable_area: list[str], ref_printable_area: list[str], item_bboxes: dict[str, tuple[float, float, float, float]]) -> tuple[str, bool]:
    local_00, local_01, local_02, local_03 = _read_printable_bounds(src_printable_area)
    local_04, local_05, local_06, local_07 = _read_printable_bounds(ref_printable_area)
    local_08 = local_02 - local_00
    local_09 = local_03 - local_01
    local_10 = local_06 - local_04
    local_11 = local_07 - local_05
    if local_08 <= 0 or local_09 <= 0 or local_10 <= 0 or local_11 <= 0:
        return _bed_shift(model_xml, src_printable_area, ref_printable_area)
    local_12 = local_04 + local_10 / 2 - (local_00 + local_08 / 2)
    local_13 = local_05 + local_11 / 2 - (local_01 + local_09 / 2)
    if item_bboxes:
        local_14 = min(local_15[0] for local_15 in item_bboxes.values())
        local_16 = min(local_15[1] for local_15 in item_bboxes.values())
        local_17 = max(local_15[2] for local_15 in item_bboxes.values())
        local_18 = max(local_15[3] for local_15 in item_bboxes.values())
        local_12 += _axis_correction(local_14 + local_12, local_17 + local_12, local_04 + _BED_MARGIN_MM, local_06 - _BED_MARGIN_MM)
        local_13 += _axis_correction(local_16 + local_13, local_18 + local_13, local_05 + _BED_MARGIN_MM, local_07 - _BED_MARGIN_MM)
    if abs(local_12) < 1e-06 and abs(local_13) < 1e-06:
        return (model_xml, False)

    def _replace(match: re.Match) -> str:
        local_00 = match.group(0)
        local_01 = re.search('transform="([^"]+)"', local_00)
        if not local_01:
            return match.group(0)
        local_02 = local_01.group(1).split()
        if len(local_02) != 12:
            return match.group(0)
        local_02[9] = f'{float(local_02[9]) + local_12:.6g}'
        local_02[10] = f'{float(local_02[10]) + local_13:.6g}'
        return local_00[:local_01.start(1)] + ' '.join(local_02) + local_00[local_01.end(1):]
    return (re.sub('<item\\b[^>]*>', _replace, model_xml), True)

def _fit_build_items_to_plates(archive: zipfile.ZipFile, model_xml: str, model_settings_xml: str | None, src_printable_area: list[str], ref_printable_area: list[str]) -> tuple[str, bool, list[int]]:
    local_00 = _plate_object_groups(model_settings_xml)
    local_03 = _item_bboxes_by_object(archive, model_xml)
    if len(local_00) <= 1:
        local_01, local_02 = _single_plate_reframe(model_xml, src_printable_area, ref_printable_area, local_03)
        return (local_01, local_02, [local_00[0][0]] if local_02 and local_00 else [])
    if not local_03:
        return (model_xml, False, [])
    local_04, local_05, local_06, local_07 = _read_printable_bounds(src_printable_area)
    local_08, local_09, local_10, local_11 = _read_printable_bounds(ref_printable_area)
    local_25 = max(0.0, local_06 - local_04)
    local_26 = max(0.0, local_07 - local_05)
    local_27 = max(0.0, local_10 - local_08)
    local_28 = max(0.0, local_11 - local_09)
    if local_25 <= 0 or local_27 <= 0:
        return (model_xml, False, [])
    local_12: dict[str, tuple[float, float]] = {}
    local_13: list[int] = []
    local_29: list[tuple[int, list[str], tuple[float, float, float, float], float, float]] = []
    for local_14, local_15 in local_00:
        local_16 = [local_03[local_17] for local_17 in local_15 if local_17 in local_03]
        if not local_16:
            continue
        local_18 = min(local_19[0] for local_19 in local_16)
        local_20 = min(local_19[1] for local_19 in local_16)
        local_21 = max(local_19[2] for local_19 in local_16)
        local_22 = max(local_19[3] for local_19 in local_16)
        local_29.append((local_14, local_15, (local_18, local_20, local_21, local_22), (local_18 + local_21) / 2, (local_20 + local_22) / 2))
    if not local_29:
        return (model_xml, False, [])
    local_30 = _plate_pitch([local_31[3] for local_31 in local_29], local_25)
    local_32 = _plate_pitch([local_31[4] for local_31 in local_29], local_26) if local_26 > 0 and local_28 > 0 else None
    local_33 = min(local_29, key=lambda local_31: local_31[0])
    local_34 = local_33[3]
    local_35 = local_33[4]
    local_36 = local_27 + max(0.0, local_30 - local_25) if local_30 else None
    local_37 = local_28 + max(0.0, local_32 - local_26) if local_32 else None
    for local_14, local_15, local_38, local_39, local_40 in local_29:
        local_41 = round((local_39 - local_34) / local_30) if local_30 else 0
        local_42 = round((local_40 - local_35) / local_32) if local_32 else 0
        local_23 = local_41 * ((local_36 or 0.0) - (local_30 or 0.0))
        local_24 = local_42 * ((local_37 or 0.0) - (local_32 or 0.0))
        local_43, local_44, local_45, local_46 = local_38
        local_47 = local_41 * (local_36 or 0.0)
        local_48 = local_42 * (local_37 or 0.0)
        local_23 += _axis_centering(local_43 + local_23, local_45 + local_23, local_47 + local_08 + _BED_MARGIN_MM, local_47 + local_10 - _BED_MARGIN_MM)
        local_24 += _axis_centering(local_44 + local_24, local_46 + local_24, local_48 + local_09 + _BED_MARGIN_MM, local_48 + local_11 - _BED_MARGIN_MM)
        if abs(local_23) < 1e-06 and abs(local_24) < 1e-06:
            continue
        local_13.append(local_14)
        for local_17 in local_15:
            local_12[local_17] = (local_23, local_24)
    if not local_12:
        return (model_xml, False, [])

    def _replace_item(match: re.Match) -> str:
        local_00 = match.group(0)
        local_01 = re.search('objectid="([^"]+)"', local_00)
        local_02 = re.search('transform="([^"]+)"', local_00)
        if not local_01 or not local_02 or local_01.group(1) not in local_12:
            return local_00
        local_03 = local_02.group(1).split()
        if len(local_03) != 12:
            return local_00
        local_04, local_05 = local_12[local_01.group(1)]
        local_03[9] = f'{float(local_03[9]) + local_04:.6g}'
        local_03[10] = f'{float(local_03[10]) + local_05:.6g}'
        return local_00[:local_02.start(1)] + ' '.join(local_03) + local_00[local_02.end(1):]
    return (re.sub('<item\\b[^>]*>', _replace_item, model_xml), True, local_13)

def _plate_json_ids(model_settings_xml: str | None) -> list[int]:
    local_00 = [local_01 for local_01, _local_02 in _plate_object_groups(model_settings_xml)]
    return local_00 or [1]

def _write_output_archive(*, source_path: Path, reference_path: Path, output_path: Path, new_project_settings: dict[str, Any], remap: dict[int, int], diff: ChangeLedger, settings: BuildRequestSettings, custom_gcode_xml_override: str | None=None, preserve_source_metadata: bool=False, target_printer_model: str='Snapmaker U1') -> None:
    local_00 = json.dumps(new_project_settings, indent=4, ensure_ascii=False).encode('utf-8')
    with zipfile.ZipFile(source_path, 'r') as local_01:
        local_02 = (json.loads(local_01.read(PROJECT_SETTINGS).decode('utf-8')).get('printable_area') if PROJECT_SETTINGS in local_01.namelist() else None) or ['0x0']
    local_03 = new_project_settings.get('printable_area') or ['0x0']
    with zipfile.ZipFile(source_path, 'r') as local_04, zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED) as local_05:
        with zipfile.ZipFile(reference_path, 'r') as local_06:
            local_07 = local_06.read(MODEL_SETTINGS).decode('utf-8') if MODEL_SETTINGS in local_06.namelist() else None
        local_21 = local_04.read(MODEL_SETTINGS).decode('utf-8') if MODEL_SETTINGS in local_04.namelist() else None
        local_08: dict = {}
        if 'Metadata/plate_1.json' in local_04.namelist():
            try:
                local_08 = json.loads(local_04.read('Metadata/plate_1.json'))
            except Exception:
                pass
        for local_09 in local_04.infolist():
            local_10 = local_09.filename
            if local_10.startswith('/') or '..' in local_10.split('/'):
                continue
            local_11 = not preserve_source_metadata and local_10 in _SOURCE_ONLY_FILES
            local_12 = local_10 in _PRUSA_ONLY_FILES or local_10.startswith('Cura/')
            if _is_slice_artifact(local_10) or local_11 or local_12:
                diff.record_slice_artifact_stripped(local_10)
                continue
            if local_10 == PROJECT_SETTINGS:
                local_05.writestr(local_10, local_00)
                continue
            if local_10 == MODEL_3D and (not preserve_source_metadata):
                local_13 = local_04.read(MODEL_3D).decode('utf-8')
                if 'xmlns:slic3rpe=' in local_13:
                    local_13, local_14 = translate_prusa_mmu_paint(local_13)
                    local_13 = re.sub('\\s+xmlns:slic3rpe="[^"]*"', '', local_13)
                    local_13 = re.sub('\\s+slic3rpe:\\w+="[^"]*"', '', local_13)
                    local_13 = re.sub('\\s*<metadata\\s+name="slic3rpe:[^"]*">[^<]*</metadata>', '', local_13)
                    local_13 = re.sub('<metadata name="Application">[^<]*</metadata>', '<metadata name="Application">BambuStudio-2.3.1</metadata>', local_13, count=1)
                    local_13 = re.sub('(<model\\b[^>]*)(>)', '\\1 xmlns:BambuStudio="http://schemas.bambulab.com/package/2021"\\2', local_13, count=1)
                    if 'BambuStudio:3mfVersion' not in local_13:
                        local_13 = local_13.replace('<resources>', '<metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>', 1)
                    if local_14:
                        log.info('STAGE  prusa-paint: %d mmu_segmentation attrs converted to paint_color', local_14)
                local_15, local_16, local_22 = _fit_build_items_to_plates(local_04, local_13, local_21, local_02, local_03)
                local_05.writestr(local_09, local_15.encode('utf-8'))
                if local_16:
                    if local_22:
                        log.info('STAGE  bed-fit: adjusted plate(s) %s to U1 printable area', ','.join((str(local_23) for local_23 in local_22)))
                    else:
                        log.info('STAGE  bed-fit: build items shifted to U1 bed origin')
                else:
                    log.info('STAGE  bed-fit: no placement change needed')
                continue
            if local_10 == MODEL_SETTINGS and (not preserve_source_metadata):
                local_17 = _rewrite_model_settings(local_04.read(MODEL_SETTINGS).decode('utf-8'), remap)
                local_05.writestr(local_10, local_17)
                continue
            if local_10 == SLICE_INFO:
                local_17 = rewrite_slice_info(local_04.read(SLICE_INFO).decode('utf-8'), target_printer_model)
                local_05.writestr(local_10, local_17)
                continue
            if local_10 == CUSTOM_GCODE_XML:
                if custom_gcode_xml_override is not None:
                    local_05.writestr(local_10, custom_gcode_xml_override)
                else:
                    local_18 = new_project_settings.get('machine_pause_gcode', 'M600')
                    local_17 = rewrite_custom_gcode_per_layer(local_04.read(CUSTOM_GCODE_XML).decode('utf-8'), local_18)
                    local_05.writestr(local_10, local_17)
                continue
            local_05.writestr(local_09, local_04.read(local_10))
        with zipfile.ZipFile(source_path, 'r') as local_19:
            local_20 = local_19.namelist()
        for local_22 in _plate_json_ids(local_21):
            local_05.writestr(f'Metadata/plate_{local_22}.json', json.dumps({'filament_colors': new_project_settings.get('filament_colour') or [], 'filament_ids': new_project_settings.get('filament_settings_id') or [], 'first_extruder': 0, 'is_seq_print': bool(local_08.get('is_seq_print', False)), 'bed_type': local_08.get('bed_type', ''), 'version': 2}))
        if PROJECT_SETTINGS not in local_20:
            local_05.writestr(PROJECT_SETTINGS, local_00)
            if MODEL_SETTINGS not in local_20:
                local_05.writestr(MODEL_SETTINGS, minimal_model_settings(local_20, source_path))
            if SLICE_INFO not in local_20:
                local_05.writestr(SLICE_INFO, minimal_slice_info(target_printer_model))
        elif MODEL_SETTINGS not in local_20 and local_07:
            local_05.writestr(MODEL_SETTINGS, local_07)

def _is_slice_artifact(name: str) -> bool:
    return any((local_00.match(name) for local_00 in _SLICE_ARTIFACT_PATTERNS))

def _rewrite_model_settings(xml_text: str, remap: dict[int, int]) -> str:
    """Rewrite per-object ``extruder`` metadata and plate ``filament_maps``.

    The remap here is 0-indexed (source_slot -> target_slot). XML stores
    extruder values as 1-indexed strings, so we translate.
    """
    try:
        local_00 = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text
    local_01 = [local_02 for local_02 in local_00.iter('metadata') if local_02.get('key') == 'raft_layers']
    local_03 = {local_02.get('value', '0') for local_02 in local_01}
    if len(local_01) < sum((1 for local_04 in local_00.iter('object'))):
        local_03.add('0')
    if len(local_03) > 1:
        for local_02 in local_01:
            local_02.set('value', '0')
    for local_05 in local_00.iter('metadata'):
        local_06 = local_05.get('key')
        if local_06 in _VALUE_REMAP:
            local_07 = local_05.get('value')
            if local_07 in _VALUE_REMAP[local_06]:
                local_05.set('value', _VALUE_REMAP[local_06][local_07])
        if local_05.get('key') == 'extruder':
            local_08 = local_05.get('value')
            if local_08 is None:
                continue
            try:
                local_09 = int(local_08)
            except ValueError:
                continue
            local_10 = local_09 - 1
            if local_10 in remap:
                local_11 = remap[local_10]
                if local_11 < 0:
                    local_12 = 1
                else:
                    local_12 = local_11 + 1
                local_05.set('value', str(local_12))
        elif local_05.get('key') == 'filament_maps':
            local_08 = local_05.get('value', '')
            local_13 = local_08.split()
            local_14: list[str] = []
            for local_15 in range(len(local_13)):
                local_16 = local_15 % _U1_TOOLHEADS_DEFAULT + 1
                local_14.append(str(local_16))
            local_05.set('value', ' '.join(local_14) if local_14 else local_08)
    return ET.tostring(local_00, encoding='unicode', xml_declaration=False)
