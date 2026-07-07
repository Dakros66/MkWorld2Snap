"""Assemble the final BuildReport from per-stage events.

Each pipeline module emits event lists (IdentitySwap, GcodeSwapEvent, etc).
This module collects them into a single structured BuildReport and provides a
human-readable summary suitable for the frontend's collapsible sections.
"""
from __future__ import annotations
from typing import Any
from workshop_types import ClampEvent, BuildReport, GcodeSwapEvent, IdentitySwap, KeyDropEvent, RecipeHit, SlotRemapEvent

class ChangeLedger:
    """Mutable accumulator used by the package rebuild pipeline."""

    def __init__(self, *, source_filename: str, output_filename: str, reference_profile: str) -> None:
        self._report = BuildReport(source_filename=source_filename, output_filename=output_filename, reference_profile=reference_profile)

    def record_identity_swap(self, key: str, from_value: Any, to_value: Any) -> None:
        self._report.identity_swaps.append(IdentitySwap(key=key, from_value=from_value, to_value=to_value))

    def extend_gcode_swaps(self, events: list[GcodeSwapEvent]) -> None:
        self._report.gcode_swaps.extend(events)

    def extend_keys_dropped(self, events: list[KeyDropEvent]) -> None:
        self._report.keys_dropped.extend(events)

    def extend_values_clamped(self, events: list[ClampEvent]) -> None:
        self._report.values_clamped.extend(events)

    def extend_rules_matched(self, events: list[RecipeHit]) -> None:
        self._report.rules_matched.extend(events)

    def extend_slot_remaps(self, events: list[SlotRemapEvent]) -> None:
        self._report.slot_remaps.extend(events)

    def extend_model_keys_dropped(self, events: list[KeyDropEvent]) -> None:
        self._report.model_keys_dropped.extend(events)

    def record_slice_artifact_stripped(self, name: str) -> None:
        self._report.slice_artifacts_stripped.append(name)

    def record_advanced_override(self, key: str, value: Any) -> None:
        self._report.advanced_overrides_applied[key] = value

    def build(self) -> BuildReport:
        return self._report

def compose_report_sections(report: BuildReport) -> list[dict[str, Any]]:
    """Flatten a BuildReport into UI-friendly sections.

    Each section has a ``title``, a one-line ``summary`` for the collapsed
    header, and a ``details`` payload the frontend can render expanded.
    """
    local_00: list[dict[str, Any]] = []
    if report.identity_swaps:
        local_01 = [local_02 for local_02 in report.identity_swaps if local_02.key in {'printer_model', 'printer_settings_id'}]
        local_03 = f'Identity swapped ({len(report.identity_swaps)} keys)'
        if local_01:
            local_04 = next((local_02 for local_02 in local_01 if local_02.key == 'printer_model'), local_01[0])
            local_03 = f'Identity swapped: {local_04.from_value} to {local_04.to_value}'
        local_00.append({'title': 'Printer identity', 'summary': local_03, 'details': [local_02.model_dump() for local_02 in report.identity_swaps]})
    if report.gcode_swaps:
        local_00.append({'title': 'Custom G-code', 'summary': f'{len(report.gcode_swaps)} blocks replaced', 'details': [local_05.model_dump() for local_05 in report.gcode_swaps]})
    if report.keys_dropped:
        local_00.append({'title': 'Keys dropped', 'summary': f'{len(report.keys_dropped)} source-specific keys removed', 'details': [local_05.model_dump() for local_05 in report.keys_dropped]})
    if report.values_clamped:
        local_00.append({'title': 'Values clamped', 'summary': f'{len(report.values_clamped)} values reduced to U1 max', 'details': [local_05.model_dump() for local_05 in report.values_clamped]})
    if report.rules_matched:
        local_06 = ', '.join((local_07.rule_name for local_07 in report.rules_matched))
        local_08 = sum((len(local_07.overrides_skipped) for local_07 in report.rules_matched))
        local_03 = f'{len(report.rules_matched)} rules matched: {local_06}'
        if local_08:
            local_03 += f' ({local_08} unsafe keys skipped)'
        local_00.append({'title': 'Filament rules applied', 'summary': local_03, 'details': [local_07.model_dump() for local_07 in report.rules_matched]})
    if report.slot_remaps:
        local_00.append({'title': 'Filament slots', 'summary': f'{len(report.slot_remaps)} filaments remapped', 'details': [local_02.model_dump() for local_02 in report.slot_remaps]})
    if report.model_keys_dropped:
        local_00.append({'title': 'Model settings filtered', 'summary': f'{len(report.model_keys_dropped)} per-object keys dropped', 'details': [local_05.model_dump() for local_05 in report.model_keys_dropped]})
    if report.slice_artifacts_stripped:
        local_00.append({'title': 'Slice caches stripped', 'summary': f'{len(report.slice_artifacts_stripped)} stale plate_*.gcode / plate_*.json files removed', 'details': list(report.slice_artifacts_stripped)})
    if report.advanced_overrides_applied:
        local_00.append({'title': 'Advanced overrides', 'summary': f'{len(report.advanced_overrides_applied)} per-key overrides applied from the UI', 'details': dict(report.advanced_overrides_applied)})
    if report.swap_instructions:
        local_00.append({'title': 'Filament swap pauses', 'summary': f"{len(report.swap_instructions)} M600 pause{('s' if len(report.swap_instructions) > 1 else '')} inserted", 'details': [local_02.model_dump() for local_02 in report.swap_instructions]})
    return local_00
