"""Insert M600 filament-swap pauses into custom_gcode_per_layer.xml.

When a source file has more colours than physical toolheads, multiple source
slots share one physical head.  The slicer cannot know it must pause and let
the user swap the physical spool before each colour transition.

Algorithm
---------
1. Build a full source-to-head mapping from the slot remap (all slots, not just
   conflicting ones).
2. Simulate the print sequence in layer order, tracking the slot currently
   loaded on each physical head.  Any type=2 entry where loaded_slot ≠
   requested_slot is a *swap event*.
3. Greedily batch swap events into the fewest pauses possible:
   a group can share one M600 if max(last_use_idx) < min(first_needed_idx).
4. Insert one M600 pause element AFTER the layer at max(last_use_idx) in each
   batch — so the pause fires after the last colour in the group finishes, well
   before the next colour starts, with no Z overlap.
"""
from __future__ import annotations
from xml.etree import ElementTree as ET
from workshop_types import SwapInstruction
_N_PHYSICAL = 4

def detect_conflicts(remap: dict[int, int], n_physical: int=_N_PHYSICAL) -> dict[int, list[int]]:
    """Return physical_head to source extruder lists for heads with >1 source."""
    local_00: dict[int, list[int]] = {}
    for local_01, local_02 in remap.items():
        if local_02 < 0:
            continue
        local_03 = local_02 % n_physical
        local_00.setdefault(local_03, []).append(local_01 + 1)
    return {local_04: sorted(local_05) for local_04, local_05 in local_00.items() if len(local_05) > 1}

def insert_swap_pauses(xml_text: str, remap: dict[int, int], filament_colours: list[str], pause_gcode: str, n_physical: int=_N_PHYSICAL) -> tuple[str, list[SwapInstruction]]:
    """Rewrite XML inserting batched M600 pauses at optimal Z heights.

    Returns (modified_xml, instructions).
    """
    if not detect_conflicts(remap, n_physical):
        return (xml_text, [])
    local_00: dict[int, int] = {local_01 + 1: local_02 % n_physical for local_01, local_02 in remap.items() if local_02 >= 0}
    local_03: dict[int, int] = {}
    for local_01 in sorted(remap):
        local_02 = remap[local_01]
        if local_02 < 0:
            continue
        local_04 = local_02 % n_physical
        local_03.setdefault(local_04, local_01 + 1)
    try:
        local_05 = ET.fromstring(xml_text)
    except ET.ParseError:
        return (xml_text, [])
    local_06: list[SwapInstruction] = []
    for local_07 in local_05.iter('plate'):
        local_08 = [local_09 for local_09 in local_07 if local_09.tag == 'layer']
        local_10 = sorted({float(local_11.get('top_z', 0)) for local_11 in local_08 if local_11.get('top_z')})
        local_12 = min((local_14 - local_13 for local_13, local_14 in zip(local_10, local_10[1:]) if local_14 > local_13), default=0.2)
        local_15 = dict
        local_16: list[local_15] = []
        local_17 = dict(local_03)
        local_18: dict[int, int] = {}
        for local_19, local_20 in enumerate(local_08):
            if local_20.get('type') != '2':
                continue
            local_21 = int(local_20.get('extruder', '0'))
            local_04 = local_00.get(local_21)
            if local_04 is None:
                continue
            local_22 = local_17.get(local_04)
            if local_22 != local_21:
                local_23 = filament_colours[local_22 - 1] if local_22 and local_22 <= len(filament_colours) else ''
                local_16.append({'first_needed_idx': local_19, 'last_use_idx': local_18.get(local_04, -1), 'phys': local_04, 'from_slot': local_22 or local_21, 'to_slot': local_21, 'from_colour': local_23, 'to_colour': local_20.get('color', '')})
                local_17[local_04] = local_21
            local_18[local_04] = local_19
        if not local_16:
            continue
        local_24: list[list[local_15]] = []
        local_25: list[local_15] = []
        for local_26 in local_16:
            if not local_25:
                local_25 = [local_26]
                continue
            local_27 = max((local_28['last_use_idx'] for local_28 in local_25 + [local_26]))
            local_29 = min((local_28['first_needed_idx'] for local_28 in local_25 + [local_26]))
            if local_27 < local_29:
                local_25.append(local_26)
            else:
                local_24.append(local_25)
                local_25 = [local_26]
        local_24.append(local_25)
        local_30 = list(local_07)
        local_31: list[tuple[int, str, list[local_15]]] = []
        for local_32 in local_24:
            local_33 = min((local_28['first_needed_idx'] for local_28 in local_32))
            local_34 = local_08[local_33]
            local_35 = float(local_34.get('top_z', '0'))
            local_36 = f'{max(local_12, local_35 - local_12):g}'
            local_37 = local_30.index(local_34)
            local_31.append((local_37, local_36, local_32))
            for local_26 in local_32:
                local_06.append(SwapInstruction(z=float(local_36), toolhead=local_26['phys'] + 1, from_slot=local_26['from_slot'], to_slot=local_26['to_slot'], from_colour=local_26['from_colour'], to_colour=local_26['to_colour'], label=f"T{local_26['phys'] + 1}: {local_26['from_colour'] or '?'} to {local_26['to_colour'] or '?'}"))
        for local_37, local_36, local_38 in sorted(local_31, key=lambda x: x[0], reverse=True):
            local_39 = ET.Element('layer')
            local_39.set('top_z', local_36)
            local_39.set('type', '1')
            local_39.set('extruder', '1')
            local_39.set('color', '')
            local_39.set('extra', '')
            local_39.set('gcode', pause_gcode)
            local_07.insert(local_37, local_39)
            local_30 = list(local_07)
    local_40 = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(local_05, encoding='unicode')
    return (local_40, local_06)
