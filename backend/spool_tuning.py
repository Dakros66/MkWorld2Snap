"""Filament-specific tuning rules.

Each rule is one YAML file in ``/rules`` with:

  name, description
  match:
    filament_settings_id_contains: "…"   # case-insensitive substring
    filament_vendor: "…"                  # exact (optional)
    filament_type: "…"                    # exact (optional)
    base_profile_contains: "…"            # exact substring of print_settings_id
  overrides:
    <any_process_key>: <value>
  priority: 10          # higher wins
  enabled: true

Matching:

* All specified conditions must be true simultaneously (AND). Missing
  conditions are ignored.
* The source 3mf's filament arrays may contain multiple filaments — a rule
  records every filament row that satisfies the filament-scoped conditions.
  Scalar process keys are still project-wide; list-valued filament keys are
  only changed at the matched filament indices.
* If multiple rules match, they are applied in ascending ``priority`` order;
  later rules overwrite earlier ones on conflicting keys.
"""
from __future__ import annotations
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
from workshop_types import RecipeDefinition, RecipeHit

class RecipeLoadError(Exception):
    pass

def _coerce_orca_value(value: Any) -> Any:
    if isinstance(value, (int, float)) and (not isinstance(value, bool)):
        return str(value)
    return value

@dataclass(frozen=True)
class SpoolMatchContext:
    """Flattened view of the filament fields in the source 3mf."""
    settings_ids: tuple[str, ...]
    vendors: tuple[str, ...]
    types: tuple[str, ...]
    base_profile: str

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> 'SpoolMatchContext':

        def _as_tuple(v: Any) -> tuple[str, ...]:
            if v is None:
                return ()
            if isinstance(v, list):
                return tuple((str(local_00) for local_00 in v))
            return (str(v),)
        return cls(settings_ids=_as_tuple(settings.get('filament_settings_id')), vendors=_as_tuple(settings.get('filament_vendor')), types=_as_tuple(settings.get('filament_type')), base_profile=str(settings.get('print_settings_id', '')))

def load_recipe_file(path: Path) -> RecipeDefinition:
    """Parse a single YAML rule file. Raises RecipeLoadError on any problem."""
    try:
        local_00 = yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as err:
        raise RecipeLoadError(f'{path.name}: invalid YAML — {err}') from err
    if not isinstance(local_00, dict):
        raise RecipeLoadError(f'{path.name}: top-level must be a mapping')
    try:
        local_01 = RecipeDefinition(**local_00)
    except Exception as err:
        raise RecipeLoadError(f'{path.name}: {err}') from err
    return local_01.model_copy(update={'source_path': str(path)})

def load_recipe_book(rules_dir: Path) -> list[RecipeDefinition]:
    """Load every ``*.yaml``/``*.yml`` in ``rules_dir``.

    A malformed rule raises — one bad file shouldn't silently disable the
    others, but we want the user to know immediately which file is broken.
    """
    local_00: list[RecipeDefinition] = []
    if not rules_dir.exists():
        return local_00
    for local_01 in sorted(rules_dir.iterdir()):
        if local_01.suffix.lower() not in ('.yaml', '.yml'):
            continue
        local_00.append(load_recipe_file(local_01))
    return local_00

def serialise_recipe(rule: RecipeDefinition) -> str:
    """Serialise a rule back to YAML (for the web editor)."""
    local_00 = rule.model_dump(exclude={'source_path'})
    local_01 = {local_02: local_03 for local_02, local_03 in (local_00.get('match') or {}).items() if local_03 is not None}
    local_00['match'] = local_01
    return yaml.safe_dump(local_00, sort_keys=False, allow_unicode=True)

def _slot_value(value: Any, index: int) -> Any:
    if isinstance(value, list):
        if not value:
            return None
        if index < len(value):
            return _coerce_orca_value(value[index])
        return _coerce_orca_value(value[-1])
    return _coerce_orca_value(value)

def _apply_indexed_override(current: list[Any], value: Any, indices: list[int]) -> tuple[list[Any], list[int]]:
    local_00 = list(current)
    local_01: list[int] = []
    for local_02 in indices:
        if local_02 < 0 or local_02 >= len(local_00):
            continue
        local_00[local_02] = _slot_value(value, local_02)
        local_01.append(local_02)
    return (local_00, local_01)

def _rule_matches(rule: RecipeDefinition, ctx: SpoolMatchContext) -> dict[str, Any]:
    """Return the match evidence dict if ``rule`` matches, else empty dict.

    Evidence is what we record in the diff report so the user can see *why*
    the rule fired.
    """
    local_00 = rule.match
    local_01: dict[str, Any] = {}
    if local_00.base_profile_contains:
        if local_00.base_profile_contains not in ctx.base_profile:
            return {}
        local_01['base_profile'] = ctx.base_profile
    local_02 = (local_00.filament_settings_id_contains or '').lower()
    local_03 = local_00.filament_vendor
    local_04 = local_00.filament_type
    local_05 = (local_00.filament_settings_id_contains, local_00.filament_vendor, local_00.filament_type)
    if any((local_06 is not None for local_06 in local_05)):
        local_07 = max(len(ctx.settings_ids), len(ctx.vendors), len(ctx.types))
        local_08: list[int] = []
        for local_09 in range(local_07):
            local_10 = ctx.settings_ids[local_09] if local_09 < len(ctx.settings_ids) else ''
            local_11 = ctx.vendors[local_09] if local_09 < len(ctx.vendors) else ''
            local_12 = ctx.types[local_09] if local_09 < len(ctx.types) else ''
            if local_02 and local_02 not in local_10.lower():
                continue
            if local_03 is not None and local_11 != local_03:
                continue
            if local_04 is not None and local_12 != local_04:
                continue
            local_08.append(local_09)
        if not local_08:
            return {}
        local_13 = local_08[0]
        local_01['filament_index'] = local_13
        local_01['filament_indices'] = local_08
        local_01['filament_settings_id'] = ctx.settings_ids[local_13] if local_13 < len(ctx.settings_ids) else None
        if local_13 < len(ctx.vendors):
            local_01['filament_vendor'] = ctx.vendors[local_13]
        if local_13 < len(ctx.types):
            local_01['filament_type'] = ctx.types[local_13]
    if not local_01:
        local_01['matched'] = 'unconditional'
    return local_01

def find_recipe_hits(rules: Iterable[RecipeDefinition], ctx: SpoolMatchContext) -> list[tuple[RecipeDefinition, dict[str, Any]]]:
    """Return (rule, evidence) pairs for every matching enabled rule,
    ordered by ascending priority (later entries win)."""
    local_00: list[tuple[RecipeDefinition, dict[str, Any]]] = []
    for local_01 in rules:
        if not local_01.enabled:
            continue
        local_02 = _rule_matches(local_01, ctx)
        if local_02:
            local_00.append((local_01, local_02))
    local_00.sort(key=lambda pair: pair[0].priority)
    return local_00

def apply_recipe_book(settings: dict[str, Any], rules: Iterable[RecipeDefinition], ctx: SpoolMatchContext, *, valid_keys: Iterable[str] | None=None) -> tuple[dict[str, Any], list[RecipeHit]]:
    """Apply all matching rules to ``settings`` (non-mutating).

    Returns (new_settings, rule_match_events). Later (higher-priority) rules
    overwrite earlier ones on conflicting keys.
    """
    local_00 = dict(settings)
    local_01 = set(valid_keys) if valid_keys is not None else None
    local_02: list[RecipeHit] = []
    for local_03, local_04 in find_recipe_hits(rules, ctx):
        local_05: dict[str, Any] = {}
        local_06: dict[str, str] = {}
        local_07 = [int(local_08) for local_08 in local_04.get('filament_indices', []) if isinstance(local_08, int)]
        for local_09, local_10 in local_03.overrides.items():
            if local_01 is not None and local_09 not in local_01:
                local_06[local_09] = 'not in the selected target profile'
                continue
            local_11 = local_00.get(local_09)
            if local_07 and isinstance(local_11, list):
                local_12, local_13 = _apply_indexed_override(local_11, local_10, local_07)
                if not local_13:
                    local_06[local_09] = 'matched filament slot is not present in this setting'
                    continue
                local_00[local_09] = local_12
                local_05[local_09] = {'slots': [local_08 + 1 for local_08 in local_13], 'value': [_slot_value(local_10, local_08) for local_08 in local_13]}
                continue
            local_10 = _coerce_orca_value(local_10)
            local_00[local_09] = local_10
            local_05[local_09] = local_10
        local_02.append(RecipeHit(rule_name=local_03.name, priority=local_03.priority, matched_on=local_04, overrides_applied=local_05, overrides_skipped=local_06))
    return (local_00, local_02)
