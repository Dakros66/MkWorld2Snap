"""Helpers for rewriting 3mf metadata sidecar files."""
from __future__ import annotations
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
U1_TOOLHEADS_DEFAULT = 4

def minimal_model_settings(src_names: list[str], source_path: Path) -> str:
    """Generate a minimal model_settings.config for non-Orca source files."""
    local_00 = _model_object_ids(src_names, source_path)
    local_01 = _build_object_ids(src_names, source_path)
    local_02 = _prusa_object_extruders(src_names, source_path)
    local_03 = _source_filament_count(src_names, source_path)
    local_04 = ''
    if local_03 > 1:
        local_05 = ' '.join((str(local_06 % U1_TOOLHEADS_DEFAULT + 1) for local_06 in range(local_03)))
        local_04 = f'  <metadata key="filament_maps" value="{local_05}"/>\n'
    local_07 = '\n'.join((f'  <model_instance>\n   <metadata key="object_id" value="{local_08}"/>\n   <metadata key="instance_id" value="0"/>\n   <metadata key="identify_id" value="{local_08}"/>\n  </model_instance>' for local_08 in local_01 or local_00))
    local_09 = '\n'.join((f'''  <object id="{local_08}">\n   <metadata key="extruder" value="{local_02.get(local_08, '1')}"/>\n  </object>''' for local_08 in local_00))
    local_10 = ' <plate>\n  <metadata key="plater_id" value="1"/>\n  <metadata key="plater_name" value="plate-1"/>\n  <metadata key="locked" value="false"/>\n  <metadata key="filament_map_mode" value="Auto For Flush"/>\n' + local_04 + (local_07 + '\n' if local_07 else '') + ' </plate>\n'
    return '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + local_10 + (local_09 + '\n' if local_09 else '') + '</config>\n'

def translate_prusa_mmu_paint(model_xml: str) -> tuple[str, int]:
    """Convert Prusa MMU face painting to Orca/Bambu paint metadata."""
    local_00 = model_xml.count('slic3rpe:mmu_segmentation')
    if not local_00:
        return (model_xml, 0)
    return (re.sub('\\s+slic3rpe:mmu_segmentation="([^"]*)"', ' paint_color="\\1"', model_xml), local_00)

def minimal_slice_info(printer_model: str='Snapmaker U1') -> str:
    """Minimal slice_info.config so Orca recognises the file as a project."""
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n <header>\n  <header_item key="X-BBL-Client-Type" value="slicer"/>\n  <header_item key="X-BBL-Client-Version" value="02.00.00.00"/>\n </header>\n <plate>\n  <metadata key="index" value="1"/>\n  <metadata key="printer_model_id" value="{printer_model}"/>\n </plate>\n</config>\n'

def rewrite_slice_info(xml_text: str, printer_model: str='Snapmaker U1') -> str:
    """Swap printer_model_id in slice_info.config if it exists."""
    try:
        local_00 = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text
    for local_01 in local_00.iter():
        if local_01.get('key') == 'printer_model_id':
            local_01.set('value', printer_model)
    return ET.tostring(local_00, encoding='unicode', xml_declaration=False)

def rewrite_custom_gcode_per_layer(xml_text: str, pause_gcode: str) -> str:
    """Rewrite per-layer pause commands to use U1-compatible G-code."""
    try:
        local_00 = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text
    for local_01 in local_00.iter('layer'):
        if local_01.get('type') == '1':
            local_01.set('gcode', pause_gcode)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(local_00, encoding='unicode')

def _model_object_ids(src_names: list[str], source_path: Path) -> list[str]:
    if '3D/3dmodel.model' not in src_names:
        return []
    local_00 = _read_zip_text(source_path, '3D/3dmodel.model')
    return re.findall('<object\\b[^>]*\\bid=["\\\'](\\d+)["\\\']', local_00)

def _build_object_ids(src_names: list[str], source_path: Path) -> list[str]:
    if '3D/3dmodel.model' not in src_names:
        return []
    local_00 = _read_zip_text(source_path, '3D/3dmodel.model')
    return re.findall('<item\\b[^>]*\\bobjectid=["\\\'](\\d+)["\\\']', local_00)

def _prusa_object_extruders(src_names: list[str], source_path: Path) -> dict[str, str]:
    if 'Metadata/Slic3r_PE_model.config' not in src_names:
        return {}
    local_00 = _read_zip_text(source_path, 'Metadata/Slic3r_PE_model.config')
    return {local_01.group(1): local_01.group(2) for local_01 in re.finditer('<object\\s+id="(\\d+)"[^>]*>.*?<metadata\\s+type="object"\\s+key="extruder"\\s+value="(\\d+)"', local_00, re.DOTALL)}

def _source_filament_count(src_names: list[str], source_path: Path) -> int:
    if 'Metadata/Slic3r_PE.config' not in src_names:
        local_00 = [local_01 for local_01 in src_names if local_01.startswith('Cura/') and local_01.endswith('.cfg') and re.search('extruder[_-]?\\d+', Path(local_01).stem, re.IGNORECASE)]
        if local_00:
            return len(local_00)
        if any((local_01.startswith('Cura/') and local_01.endswith('.cfg') for local_01 in src_names)):
            return 1
        if '3D/3dmodel.model' in src_names:
            return 1
        return 0
    local_02 = _read_zip_text(source_path, 'Metadata/Slic3r_PE.config')
    local_03 = re.search('^\\s*;?\\s*filament_settings_id\\s*=\\s*(.+)$', local_02, re.MULTILINE)
    if not local_03:
        local_03 = re.search('^\\s*;?\\s*filament_type\\s*=\\s*(.+)$', local_02, re.MULTILINE)
    if not local_03:
        return 0
    return len([local_04 for local_04 in local_03.group(1).split(';') if local_04.strip()])

def _read_zip_text(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as local_00:
        return local_00.read(name).decode('utf-8', errors='replace')
