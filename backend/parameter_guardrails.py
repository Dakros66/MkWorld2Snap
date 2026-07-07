"""Key filtering and value clamping.

Two related operations that run after identity + gcode swap:

1.  ``filter_to_schema`` — drop any key in the source settings that is not in
    the U1 reference schema. Bambu ships a superset of keys; Snapmaker Orca
    ignores unknowns but in some versions will warn or silently misread, so we
    quietly strip them.

2.  ``clamp_numeric_ceilings`` — for a configured set of speed / acceleration
    keys, enforce the U1 reference profile's value as an upper bound. Values
    are stored in Orca profiles as *strings* (e.g. ``"200"``), sometimes as
    lists of strings; we preserve the original type when clamping.
"""
from __future__ import annotations
from collections.abc import Iterable
from typing import Any
from workshop_types import ClampEvent, KeyDropEvent
DEFAULT_CLAMP_KEYS: frozenset[str] = frozenset({'outer_wall_speed', 'inner_wall_speed', 'sparse_infill_speed', 'internal_solid_infill_speed', 'top_surface_speed', 'gap_infill_speed', 'travel_speed', 'initial_layer_speed', 'initial_layer_infill_speed', 'initial_layer_travel_speed', 'overhang_1_4_speed', 'overhang_2_4_speed', 'overhang_3_4_speed', 'overhang_4_4_speed', 'bridge_speed', 'support_speed', 'support_interface_speed', 'default_acceleration', 'outer_wall_acceleration', 'inner_wall_acceleration', 'sparse_infill_acceleration', 'top_surface_acceleration', 'initial_layer_acceleration', 'travel_acceleration', 'bridge_acceleration', 'prime_tower_brim_width'})
IDENTITY_KEYS: frozenset[str] = frozenset({'printer_settings_id', 'printer_model', 'printer_variant', 'printable_area', 'printable_height', 'nozzle_diameter', 'extruder_count', 'compatible_printers', 'compatible_printers_condition', 'print_settings_id'})

def _to_float(value: Any) -> float | None:
    """Parse Orca's string-or-number settings into a float, or None on fail."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None

def _preserve_type(original: Any, new_value: float) -> Any:
    """Return ``new_value`` coerced to the same representation as ``original``.

    Orca stores most numeric settings as strings. We keep whatever string
    formatting the original used where possible; ints stay ints.
    """
    if isinstance(original, str):
        if new_value.is_integer():
            return str(int(new_value))
        return f'{new_value:g}'
    if isinstance(original, int) and (not isinstance(original, bool)):
        return int(new_value)
    return new_value

def filter_to_schema(source: dict[str, Any], schema_keys: Iterable[str], *, keep_keys: Iterable[str]=()) -> tuple[dict[str, Any], list[KeyDropEvent]]:
    """Return (filtered_dict, dropped_events).

    ``source`` is mutated-free; we return a new dict containing only keys in
    ``schema_keys`` (plus any in ``keep_keys``). Identity keys are always kept
    even if absent from the schema, since the identity-swap stage writes them.
    """
    local_00 = set(schema_keys) | set(keep_keys) | IDENTITY_KEYS
    local_01: dict[str, Any] = {}
    local_02: list[KeyDropEvent] = []
    for local_03, local_04 in source.items():
        if local_03 in local_00:
            local_01[local_03] = local_04
        else:
            local_02.append(KeyDropEvent(key=local_03, reason='not-in-target-schema'))
    return (local_01, local_02)

def clamp_numeric_ceilings(settings: dict[str, Any], reference: dict[str, Any], *, clamp_keys: Iterable[str]=DEFAULT_CLAMP_KEYS) -> tuple[dict[str, Any], list[ClampEvent]]:
    """Clamp ``settings`` values against ceilings from ``reference``.

    For each key in ``clamp_keys`` that exists in both dicts and parses as a
    number (scalar or list of scalars), enforce reference-value as an upper
    bound. Values above the ceiling are lowered; values at or below are left
    alone. Lists are clamped element-wise (one ClampEvent per affected index).

    Returns ``(new_settings, events)`` without mutating the input.
    """
    local_00 = dict(settings)
    local_01: list[ClampEvent] = []
    for local_02 in clamp_keys:
        if local_02 not in local_00 or local_02 not in reference:
            continue
        local_03 = reference[local_02]
        local_04 = local_00[local_02]
        if isinstance(local_04, list) and isinstance(local_03, list) and local_03:
            local_05 = list(local_04)
            local_06 = False
            for local_07, local_08 in enumerate(local_05):
                local_09 = local_03[local_07] if local_07 < len(local_03) else local_03[-1]
                local_10 = _to_float(local_09)
                local_11 = _to_float(local_08)
                if local_10 is None or local_11 is None:
                    continue
                if local_11 > local_10:
                    local_12 = _preserve_type(local_08, local_10)
                    local_01.append(ClampEvent(key=f'{local_02}[{local_07}]', from_value=local_08, to_value=local_12, ceiling=local_09))
                    local_05[local_07] = local_12
                    local_06 = True
            if local_06:
                local_00[local_02] = local_05
            continue
        local_10 = _to_float(local_03)
        local_11 = _to_float(local_04)
        if local_10 is None or local_11 is None:
            continue
        if local_11 in (0, -1) and local_10 > 0:
            local_13 = _preserve_type(local_04, local_10)
            local_01.append(ClampEvent(key=local_02, from_value=local_04, to_value=local_13, ceiling=local_03))
            local_00[local_02] = local_13
        elif local_11 > local_10:
            local_13 = _preserve_type(local_04, local_10)
            local_01.append(ClampEvent(key=local_02, from_value=local_04, to_value=local_13, ceiling=local_03))
            local_00[local_02] = local_13
    return (local_00, local_01)
