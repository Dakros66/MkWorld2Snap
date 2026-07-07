"""Swap Bambu custom G-code blocks for the U1 reference equivalents.

Bambu's start/end/layer/pause/change_filament G-code contains printer-specific
commands (AMS swaps, chamber control, gantry homing sequences) that would at
best do nothing on a Snapmaker U1 and at worst crash it. We unconditionally
replace every configured block with whatever the reference profile ships, and
record a ``GcodeSwapEvent`` per block so the diff view can show what changed.
"""
from __future__ import annotations
from typing import Any
from workshop_types import GcodeSwapEvent
GCODE_KEYS: tuple[str, ...] = ('machine_start_gcode', 'machine_end_gcode', 'before_layer_change_gcode', 'layer_change_gcode', 'change_filament_gcode', 'machine_pause_gcode', 'template_custom_gcode', 'printing_by_object_gcode', 'time_lapse_gcode')

def _byte_len(value: Any) -> int:
    """Bytes of a G-code value, whether stored as str or list[str]."""
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode('utf-8'))
    if isinstance(value, list):
        return sum((len(local_00.encode('utf-8')) for local_00 in value if isinstance(local_00, str)))
    return len(str(value).encode('utf-8'))

def swap_gcode(source: dict[str, Any], reference: dict[str, Any], *, keys: tuple[str, ...]=GCODE_KEYS) -> tuple[dict[str, Any], list[GcodeSwapEvent]]:
    """Return (new_settings, events).

    For each ``key`` in ``keys``:
      - if the reference defines the key, the source value is overwritten
        with the reference value (even if the reference value is empty — a
        blank reference means "U1 doesn't run anything here");
      - if the reference does *not* define the key, the key is deleted from
        source (source-specific block — shouldn't be emitted by U1);
      - a ``GcodeSwapEvent`` is recorded in every case where the byte count
        changed or the key was removed.
    """
    local_00 = dict(source)
    local_01: list[GcodeSwapEvent] = []
    for local_02 in keys:
        local_03 = local_02 in local_00
        local_04 = local_02 in reference
        local_05 = _byte_len(local_00.get(local_02))
        if local_04:
            local_00[local_02] = reference[local_02]
            local_06 = _byte_len(local_00[local_02])
        else:
            if local_03:
                del local_00[local_02]
            local_06 = 0
        if local_03 or local_04:
            local_01.append(GcodeSwapEvent(key=local_02, from_bytes=local_05, to_bytes=local_06))
    return (local_00, local_01)
