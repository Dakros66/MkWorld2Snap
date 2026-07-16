<script lang="ts">
  import { CircleHelp, Download, FileText, MoreHorizontal, RotateCcw, Save, SlidersHorizontal, X } from 'lucide-svelte';
  
  
  import type { DiffPayload, JobParameter, JobParameterGroup } from './engineClient';
  import { downloadUrl, jobParameters, rebuildJob } from './engineClient';
  import ScenePreview from './ScenePreview.svelte';
  import { tr as i18n } from './i18n';

  interface Props {
    diff: DiffPayload;
    jobId: string;
    downloadName: string;
    onreset: () => void;
  }

  let { diff, jobId, downloadName, onreset }: Props = $props();

  type ParamMode = 'keep' | 'default' | 'custom';
  type EditableParam = { key: string; current: unknown; source: string; defaultValue?: unknown; editable?: boolean; changed?: boolean };

  const initialDiff = () => diff;
  const initialJobId = () => jobId;
  const initialDownloadName = () => downloadName;
  let activeDiff = $state(initialDiff());
  let activeJobId = $state(initialJobId());
  let activeDownloadName = $state(initialDownloadName());
  let expanded = $state<Set<number>>(new Set());
  let saveStatus = $state('');
  let saving = $state(false);
  let showParamEditor = $state(false);
  let paramModes = $state<Record<string, ParamMode>>({});
  let customValues = $state<Record<string, string>>({});
  let rebuildStatus = $state('');
  let rebuilding = $state(false);
  let showReportPopup = $state(false);
  let reviewExcludeObjects = $state(true);
  let baselineExcludeObjects = $state(true);
  let paramGroups = $state<JobParameterGroup[]>([]);
  let paramsLoading = $state(false);
  let paramsError = $state('');
  let activeParamGroup = $state('Quality');
  let paramSearch = $state('');
  let showChangedOnly = $state(true);
  let hasNativeSave = $state(false);
  let saveMenuOpen = $state<'' | 'header' | 'dock'>('');
  const saveStatusIsError = $derived(
    /\b(fail|failed|error|not found|expired|cleaned|could not|download failed)\b/i.test(saveStatus)
  );

  function toggle(i: number) {
    const s = new Set(expanded);
    if (s.has(i)) s.delete(i); else s.add(i);
    expanded = s;
  }

  function inferExcludeObject(d: DiffPayload): boolean {
    const value = d.report.advanced_overrides_applied?.exclude_object;
    return !(value === '0' || value === 0 || value === false);
  }

  $effect(() => {
    activeDiff = diff;
    activeJobId = jobId;
    activeDownloadName = downloadName;
    const exclude = inferExcludeObject(diff);
    reviewExcludeObjects = exclude;
    baselineExcludeObjects = exclude;
    paramModes = {};
    customValues = {};
    rebuildStatus = '';
    showChangedOnly = true;
  });

  $effect(() => {
    const id = activeJobId;
    void loadJobParameters(id);
  });

  $effect(() => {
    let cancelled = false;
    void waitForDesktopBridge(900).then((bridge) => {
      if (!cancelled) hasNativeSave = Boolean(bridge?.api?.save_converted_file);
    });
    return () => {
      cancelled = true;
    };
  });

  // Auto-expand swap instructions card if present.
  $effect(() => {
    const idx = activeDiff.sections.findIndex(s => s.title === 'Filament swap pauses');
    if (idx >= 0) expanded = new Set([idx]);
  });

  function formatValue(v: unknown): string {
    if (v === null || v === undefined) return '—';
    if (Array.isArray(v)) return v.join(', ');
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }

  let counts = $derived(activeDiff.counts);

  async function loadJobParameters(id: string) {
    paramsLoading = true;
    paramsError = '';
    try {
      const payload = await jobParameters(id);
      paramGroups = payload.groups;
      if (!payload.groups.some((group) => group.name === activeParamGroup)) {
        activeParamGroup = payload.groups[0]?.name ?? 'Quality';
      }
    } catch (err) {
      paramsError = err instanceof Error ? err.message : String(err);
      paramGroups = [];
    } finally {
      paramsLoading = false;
    }
  }

  function addEditable(map: Map<string, EditableParam>, key: string, current: unknown, source: string, extra: Partial<EditableParam> = {}) {
    if (!key || key === 'exclude_object') return;
    if (!map.has(key)) {
      map.set(key, { key, current, source, ...extra });
      return;
    }
    const row = map.get(key);
    if (row) row.source = `${row.source}, ${source}`;
  }

  function fallbackChangedParameters(): EditableParam[] {
    const rows = new Map<string, EditableParam>();
    for (const row of activeDiff.report.values_clamped ?? []) {
      addEditable(rows, row.key, row.to_value, 'clamped', { editable: true, changed: true });
    }
    for (const rule of activeDiff.report.rules_matched ?? []) {
      for (const [key, value] of Object.entries(rule.overrides_applied ?? {})) {
        addEditable(rows, key, value, `recipe: ${rule.rule_name}`, { editable: true, changed: true });
      }
    }
    for (const [key, value] of Object.entries(activeDiff.report.advanced_overrides_applied ?? {})) {
      addEditable(rows, key, value, 'override', { editable: true, changed: true });
    }
    return [...rows.values()].sort((a, b) => a.key.localeCompare(b.key));
  }

  function editableParameters(): EditableParam[] {
    if (!paramGroups.length) return fallbackChangedParameters();
    const rows: EditableParam[] = [];
    for (const group of paramGroups) {
      for (const item of group.items) {
        if (item.key === 'exclude_object') continue;
        rows.push({
          key: item.key,
          current: item.value,
          defaultValue: item.default_value,
          source: group.name,
          editable: item.has_u1_default,
          changed: item.changed_from_default,
        });
      }
    }
    return rows.sort((a, b) => a.key.localeCompare(b.key));
  }

  function visibleParamRows(): EditableParam[] {
    if (!paramGroups.length) return fallbackChangedParameters();
    const needle = paramSearch.trim().toLowerCase();
    return editableParameters().filter((row) => {
      if (row.source !== activeParamGroup) return false;
      if (showChangedOnly && !row.changed) return false;
      if (!needle) return true;
      return row.key.toLowerCase().includes(needle) || formatValue(row.current).toLowerCase().includes(needle);
    });
  }

  function groupChangedCount(group: JobParameterGroup): number {
    return group.items.filter((item) => item.key !== 'exclude_object' && item.changed_from_default).length;
  }

  function groupEditableCount(group: JobParameterGroup): number {
    return group.items.filter((item) => item.key !== 'exclude_object').length;
  }

  function totalChangedCount(): number {
    return paramGroups.reduce((total, group) => total + groupChangedCount(group), 0);
  }

  function parameterTitle(key: string): string {
    const exact: Record<string, string> = {
      layer_height: 'Layer height',
      line_width: 'Line width',
      wall_loops: 'Wall loops',
      sparse_infill_density: 'Infill density',
      sparse_infill_pattern: 'Infill pattern',
      top_shell_layers: 'Top layers',
      bottom_shell_layers: 'Bottom layers',
      outer_wall_speed: 'Outer wall speed',
      inner_wall_speed: 'Inner wall speed',
      travel_speed: 'Travel speed',
      default_acceleration: 'Default acceleration',
      outer_wall_acceleration: 'Outer wall acceleration',
      support_type: 'Support type',
      support_enable: 'Support enabled',
      brim_width: 'Brim width',
      raft_first_layer_expansion: 'Raft first layer expansion',
      nozzle_temperature: 'Nozzle temperature',
      nozzle_temperature_initial_layer: 'Initial nozzle temperature',
      hot_plate_temp: 'Bed temperature',
      hot_plate_temp_initial_layer: 'Initial bed temperature',
      filament_settings_id: 'Filament profile',
      filament_type: 'Filament type',
      filament_colour: 'Filament colour',
      enable_prime_tower: 'Prime tower',
      flush_multiplier: 'Flush multiplier',
      sparse_infill_speed: 'Infill speed',
      internal_solid_infill_speed: 'Solid infill speed',
      top_surface_speed: 'Top surface speed',
      gap_infill_speed: 'Gap infill speed',
      initial_layer_speed: 'Initial layer speed',
      initial_layer_infill_speed: 'Initial layer infill speed',
      initial_layer_travel_speed: 'Initial layer travel speed',
      bridge_speed: 'Bridge speed',
      support_speed: 'Support speed',
      support_interface_speed: 'Support interface speed',
      inner_wall_acceleration: 'Inner wall acceleration',
      sparse_infill_acceleration: 'Infill acceleration',
      top_surface_acceleration: 'Top surface acceleration',
      initial_layer_acceleration: 'Initial layer acceleration',
      travel_acceleration: 'Travel acceleration',
      bridge_acceleration: 'Bridge acceleration',
      wall_filament: 'Wall filament slot',
      sparse_infill_filament: 'Infill filament slot',
      solid_infill_filament: 'Solid infill filament slot',
      support_filament: 'Support filament slot',
      support_interface_filament: 'Support interface filament slot',
      wipe_tower_filament: 'Wipe tower filament slot',
      tree_support_wall_count: 'Tree support wall count',
      prime_tower_lift_height: 'Prime tower lift height',
      prime_tower_brim_width: 'Prime tower brim width',
      ensure_vertical_shell_thickness: 'Vertical shell thickness',
      support_style: 'Support style',
      wipe_tower_wall_type: 'Wipe tower wall type',
    };
    if (exact[key]) return $i18n(exact[key]);
    return key
      .split('_')
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  function parameterUnit(key: string): string {
    const lower = key.toLowerCase();
    if (lower.includes('temperature') || lower.includes('temp')) return '°C';
    if (lower.includes('accel')) return 'mm/s²';
    if (lower.includes('speed')) return 'mm/s';
    if (lower.includes('density') || lower.includes('percent') || lower.includes('ratio')) return '%';
    if (lower.includes('width') || lower.includes('height') || lower.includes('distance') || lower.includes('spacing') || lower.includes('expansion')) return 'mm';
    return '';
  }

  function parameterHelp(key: string): string {
    const lower = key.toLowerCase();
    const exact: Record<string, string> = {
      layer_height: 'Controls the vertical resolution of each printed layer. Lower values improve detail and increase print time.',
      line_width: 'Sets the extrusion line width used for toolpaths. Zero or mismatched values can create import warnings or weak walls.',
      wall_loops: 'Controls how many perimeter walls are printed before infill. More walls usually increase strength and print time.',
      sparse_infill_density: 'Controls how much internal infill is printed. Higher density increases strength, material use, and print time.',
      sparse_infill_pattern: 'Chooses the internal infill pattern. Some patterns trade speed for strength or surface support.',
      top_shell_layers: 'Sets how many solid layers close the top of the model. More layers improve sealing and top-surface quality.',
      bottom_shell_layers: 'Sets how many solid layers form the bottom skin. More layers improve bed-side strength and sealing.',
      outer_wall_speed: 'Controls visible outer wall speed. Lower values usually improve surface quality.',
      inner_wall_speed: 'Controls inner perimeter speed. It affects strength and total print time.',
      travel_speed: 'Controls non-printing movement speed. Too high can increase ringing or skipped steps.',
      default_acceleration: 'Sets general motion acceleration. The app clamps this against the U1 reference profile when safety clamps are enabled.',
      outer_wall_acceleration: 'Sets acceleration for visible outer walls. Lower values can reduce ringing on cosmetic surfaces.',
      support_type: 'Selects the support strategy. Tree supports may be changed when variable layer height data would conflict.',
      support_enable: 'Turns generated support structures on or off.',
      brim_width: 'Adds a brim around the model to improve bed adhesion. Wider brims use more material and take longer to remove.',
      raft_first_layer_expansion: 'Controls raft first-layer expansion. Negative values are unsafe for Snapmaker Orca and are flagged.',
      nozzle_temperature: 'Sets nozzle temperature for each filament slot. Wrong temperatures can cause under-extrusion, stringing, or clogs.',
      nozzle_temperature_initial_layer: 'Sets nozzle temperature for the first layer. It is often higher to improve adhesion and first-layer flow.',
      hot_plate_temp: 'Sets bed temperature. It affects adhesion and material warping.',
      hot_plate_temp_initial_layer: 'Sets bed temperature for the first layer. It helps the part stick before normal printing starts.',
      filament_settings_id: 'Identifies the source filament profiles. The converter keeps useful material intent while retargeting to U1.',
      filament_type: 'Describes the material family for each slot, such as PLA or PETG. It helps Orca apply compatible material behaviour.',
      filament_colour: 'Stores the preview colour for each filament slot. It affects visual review, not the physical spool loaded in the printer.',
      enable_prime_tower: 'Controls whether a prime tower is used for material changes. It may be disabled for incompatible variable-layer projects.',
      flush_multiplier: 'Controls purge volume multiplier during colour/material changes.',
      sparse_infill_speed: 'Controls how fast internal infill is printed. Higher values reduce time but can weaken infill quality.',
      internal_solid_infill_speed: 'Controls the speed of solid internal infill layers. It affects strength, surface support, and print time.',
      top_surface_speed: 'Controls the speed of visible top surfaces. Lower values usually improve the final top finish.',
      gap_infill_speed: 'Controls how fast narrow gaps are filled between walls. Too fast can leave small weak or messy areas.',
      initial_layer_speed: 'Controls first-layer print speed. Slower first layers usually improve bed adhesion and reliability.',
      initial_layer_infill_speed: 'Controls infill speed on the first layer. It helps balance adhesion, flow, and first-layer time.',
      initial_layer_travel_speed: 'Controls travel speed during the first layer. Lower values can reduce first-layer disturbance.',
      bridge_speed: 'Controls speed while printing unsupported bridge spans. It affects sagging and bridge surface quality.',
      support_speed: 'Controls how fast support material is printed. It affects support stability and overall print time.',
      support_interface_speed: 'Controls speed for the support contact layers under the model. It affects underside quality and support removal.',
      inner_wall_acceleration: 'Sets acceleration for inner walls. It affects print time and how consistently the part structure is formed.',
      sparse_infill_acceleration: 'Sets acceleration for infill moves. Higher values reduce time but can increase vibration inside the part.',
      top_surface_acceleration: 'Sets acceleration on visible top surfaces. Lower values can improve finish on cosmetic top areas.',
      initial_layer_acceleration: 'Sets acceleration on the first layer. Lower values help adhesion and reduce early print failures.',
      travel_acceleration: 'Sets acceleration for non-printing travel moves. High values can increase vibration or skipped steps.',
      bridge_acceleration: 'Sets acceleration while bridging. It affects how cleanly unsupported spans are laid down.',
      wall_filament: 'Chooses which filament slot is used for perimeter walls. Invalid slot 0 values are corrected to a real U1 slot.',
      sparse_infill_filament: 'Chooses which filament slot is used for sparse infill. Invalid slot 0 values are corrected to a real U1 slot.',
      solid_infill_filament: 'Chooses which filament slot is used for solid infill. It matters on multicolour or multimaterial projects.',
      support_filament: 'Chooses which filament slot prints supports. Use it carefully when supports should use a different material.',
      support_interface_filament: 'Chooses the filament slot for support interface layers that touch the model.',
      wipe_tower_filament: 'Chooses which filament slot is used by the wipe tower during material changes.',
      tree_support_wall_count: 'Controls wall count for tree supports. Negative values are invalid in Snapmaker Orca and are corrected.',
      prime_tower_lift_height: 'Controls Z lift around the prime tower. Negative values are unsafe and are corrected.',
      prime_tower_brim_width: 'Controls brim width around the prime tower to keep it stable during colour changes.',
      ensure_vertical_shell_thickness: 'Controls how Orca reinforces thin vertical shell areas. The converter maps unsupported source values to U1-safe values.',
      support_style: 'Chooses the support generation style. Unsupported tree-style values may be converted to a U1-compatible style.',
      wipe_tower_wall_type: 'Controls wipe tower wall shape. The converter normalizes unsupported values for Snapmaker Orca compatibility.',
    };
    if (exact[key]) return $i18n(exact[key]);
    if (/^overhang_[1-4]_4_speed$/.test(lower)) return $i18n('Controls speed for overhang ranges. Slower overhangs usually improve underside quality and reduce curling.');
    if (lower.includes('fan') || lower.includes('cooling')) return $i18n('Controls part cooling behaviour. Cooling affects bridges, overhangs, stringing, and layer bonding.');
    if (lower.includes('flow')) return $i18n('Controls extrusion flow. Too much flow can cause blobs; too little can weaken walls or leave gaps.');
    if (lower.includes('jerk')) return $i18n('Controls how abruptly motion changes direction. High values can increase ringing and mechanical stress.');
    if (lower.includes('seam')) return $i18n('Controls where perimeter start and end points are placed. It affects the visibility of the vertical seam.');
    if (lower.includes('ironing')) return $i18n('Controls ironing passes over top surfaces. It can improve smoothness but adds print time.');
    if (lower.includes('skirt')) return $i18n('Controls skirt lines printed before the model. Skirts help prime flow and verify bed leveling.');
    if (lower.includes('bridge')) return $i18n('Bridge setting. It affects unsupported spans between two supported areas.');
    if (lower.includes('overhang')) return $i18n('Overhang setting. It affects surfaces printed without much support underneath.');
    if (lower.includes('prime_tower') || lower.includes('wipe_tower')) return $i18n('Prime tower setting used during colour or material changes. It affects purge reliability and tower stability.');
    if (lower.includes('temperature') || lower.includes('temp')) return $i18n('Temperature-related setting. Review it against the material manufacturer recommendations.');
    if (lower.includes('speed')) return $i18n('Motion speed setting. The converter clamps known speed keys against the selected U1 reference profile.');
    if (lower.includes('accel')) return $i18n('Motion acceleration setting. High values can affect print quality and mechanical reliability.');
    if (lower.includes('filament') || lower.includes('extruder')) return $i18n('Material or toolhead assignment setting. Review carefully for multi-colour projects.');
    if (lower.includes('support') || lower.includes('raft') || lower.includes('brim')) return $i18n('Adhesion or support setting. It can change how the model is held during printing.');
    if (lower.includes('infill') || lower.includes('wall') || lower.includes('shell')) return $i18n('Strength and structure setting. It affects material use, print time, and part strength.');
    return $i18n('Slicer project setting imported from the source package and compared with the selected U1 reference profile.');
  }

  function valueWithUnit(key: string, value: unknown): string {
    const text = formatValue(value);
    const unit = parameterUnit(key);
    if (!unit || text === '—' || /[a-zA-Z%°]/.test(text)) return text;
    return `${text} ${unit}`;
  }

  function groupLabel(name: string): string {
    return $i18n(name);
  }

  function modeFor(key: string): ParamMode {
    return paramModes[key] ?? 'keep';
  }

  function setMode(key: string, mode: ParamMode, current: unknown) {
    paramModes = { ...paramModes, [key]: mode };
    if (mode === 'custom' && customValues[key] === undefined) {
      customValues = { ...customValues, [key]: formatValue(current) };
    }
  }

  function setCustomValue(key: string, value: string) {
    customValues = { ...customValues, [key]: value };
  }

  function parseCustomValue(value: string): unknown {
    const trimmed = value.trim();
    if (!trimmed) return '';
    if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
      try { return JSON.parse(trimmed); } catch { return trimmed; }
    }
    return trimmed;
  }

  function hasRebuildChanges(): boolean {
    return Object.values(paramModes).some(mode => mode !== 'keep') || reviewExcludeObjects !== baselineExcludeObjects;
  }

  function isRebuildError(status: string): boolean {
    return /^\d+:|fail|error|not|unsupported/i.test(status);
  }

  async function rebuildWithEdits() {
    const default_keys: string[] = [];
    const custom_overrides: Record<string, unknown> = {};
    for (const row of editableParameters()) {
      const mode = modeFor(row.key);
      if (!row.editable) continue;
      if (mode === 'default') default_keys.push(row.key);
      if (mode === 'custom') custom_overrides[row.key] = parseCustomValue(customValues[row.key] ?? '');
    }
    if (!default_keys.length && !Object.keys(custom_overrides).length && reviewExcludeObjects === baselineExcludeObjects) {
      rebuildStatus = 'No parameter changes selected.';
      return;
    }
    rebuilding = true;
    rebuildStatus = '';
    try {
      const next = await rebuildJob(activeJobId, {
        default_keys,
        custom_overrides,
        exclude_object: reviewExcludeObjects,
      });
      activeDiff = next.diff;
      activeJobId = next.job_id;
      activeDownloadName = next.download_name;
      baselineExcludeObjects = reviewExcludeObjects;
      paramModes = {};
      customValues = {};
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#job=${next.job_id}`);
      rebuildStatus = $i18n('Package rebuilt with the selected parameter edits.');
    } catch (err) {
      rebuildStatus = err instanceof Error ? err.message : String(err);
    } finally {
      rebuilding = false;
    }
  }

  function displayTitle(title: string): string {
    const mapped = ({
      'Printer identity': 'Machine passport',
      'Custom G-code': 'Startup scripts',
      'Keys dropped': 'Cleaned leftovers',
      'Values clamped': 'Motion limits',
      'Filament rules applied': 'Spool tuning',
      'Filament slots': 'Spool routing',
      'Model settings filtered': 'Object settings',
      'Slice caches stripped': 'Old slice cache',
      'Advanced overrides': 'Manual overrides',
      'Filament swap pauses': 'Spool-stop notes',
    } as Record<string, string>)[title] ?? title;
    return $i18n(mapped);
  }

  function displaySummary(title: string, detailCount: number): string {
    return ({
      'Printer identity': $i18n('Printer identity updated.'),
      'Custom G-code': $i18n('Startup scripts replaced.'),
      'Keys dropped': $i18n('Incompatible settings removed.'),
      'Values clamped': $i18n('Values adjusted to U1 limits.'),
      'Filament rules applied': $i18n('Material recipes applied.'),
      'Filament slots': $i18n('Filament slots remapped.'),
      'Model settings filtered': $i18n('Object settings cleaned.'),
      'Slice caches stripped': $i18n('Old slicing cache removed.'),
      'Advanced overrides': $i18n('Manual overrides applied.'),
      'Filament swap pauses': $i18n('Spool change pauses inserted.'),
    } as Record<string, string>)[title] ?? $i18n('Items changed', { count: detailCount });
  }

  type DesktopBridge = {
    api?: {
      save_converted_file?: (
        jobId: string,
        downloadName: string,
      ) => Promise<{ ok: boolean; path?: string; error?: string; cancelled?: boolean; revealed?: boolean }>;
    };
  };

  async function waitForDesktopBridge(timeoutMs = 1200): Promise<DesktopBridge | undefined> {
    const current = (window as unknown as { pywebview?: DesktopBridge }).pywebview;
    if (current?.api?.save_converted_file) return current;

    return new Promise((resolve) => {
      const timer = window.setTimeout(() => {
        window.removeEventListener('pywebviewready', onReady);
        resolve((window as unknown as { pywebview?: DesktopBridge }).pywebview);
      }, timeoutMs);

      function onReady() {
        window.clearTimeout(timer);
        resolve((window as unknown as { pywebview?: DesktopBridge }).pywebview);
      }

      window.addEventListener('pywebviewready', onReady, { once: true });
    });
  }

  async function browserDownloadConverted() {
    const response = await fetch(downloadUrl(activeJobId));
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = body.detail ?? JSON.stringify(body);
      } catch {
        detail = await response.text();
      }
      throw new Error($i18n('Download failed: {detail}', { detail }));
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = activeDownloadName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function nativeSaveConverted(): Promise<'saved' | 'cancelled' | 'unavailable'> {
    const pywebview = await waitForDesktopBridge();
    if (!pywebview?.api?.save_converted_file) return 'unavailable';

    const result = await pywebview.api.save_converted_file(activeJobId, activeDownloadName);
    if (result.ok) {
      saveStatus = result.path
        ? $i18n('Saved to {path}{suffix}', { path: result.path, suffix: result.revealed ? ` - ${$i18n('shown in file manager')}` : '' })
        : $i18n('Saved');
      return 'saved';
    }
    if (result.cancelled) return 'cancelled';
    throw new Error(result.error || $i18n('Save failed'));
  }

  async function saveOrDownloadConverted() {
    saveStatus = '';
    saveMenuOpen = '';
    saving = true;
    try {
      if (hasNativeSave) {
        const result = await nativeSaveConverted();
        if (result === 'saved' || result === 'cancelled') return;
      }

      await browserDownloadConverted();
      saveStatus = $i18n('Download started');
    } catch (err) {
      if (hasNativeSave) {
        try {
          await browserDownloadConverted();
          saveStatus = $i18n('Native save failed, browser download started');
          return;
        } catch {
          // Surface the original native-save error if the fallback also fails.
        }
      }
      saveStatus = err instanceof Error ? err.message : $i18n('Download failed');
    } finally {
      saving = false;
    }
  }

  async function forceNativeSave() {
    saveStatus = '';
    saveMenuOpen = '';
    if (!hasNativeSave) {
      saveStatus = $i18n('Desktop save is unavailable in this browser');
      return;
    }
    saving = true;
    try {
      const result = await nativeSaveConverted();
      if (result === 'unavailable') saveStatus = $i18n('Desktop save is unavailable in this browser');
    } catch (err) {
      saveStatus = err instanceof Error ? err.message : $i18n('Save failed');
    } finally {
      saving = false;
    }
  }

  async function forceBrowserDownload() {
    saveStatus = '';
    saveMenuOpen = '';
    saving = true;
    try {
      await browserDownloadConverted();
      saveStatus = $i18n('Download started');
    } catch (err) {
      saveStatus = err instanceof Error ? err.message : $i18n('Download failed');
    } finally {
      saving = false;
    }
  }

  function reportText(): string {
    const lines = [
      'MkWorld2Snap conversion report',
      '',
      `Source: ${activeDiff.report.source_filename}`,
      `Output: ${activeDiff.report.output_filename}`,
      `Reference profile: ${activeDiff.report.reference_profile}`,
      '',
      'Summary:',
      ...Object.entries(activeDiff.counts).map(([key, value]) => `- ${key}: ${value}`),
      '',
      'Sections:',
      ...activeDiff.sections.flatMap((section) => [
        '',
        `## ${displayTitle(section.title)}`,
        displaySummary(section.title, section.details?.length ?? 0),
        JSON.stringify(section.details ?? [], null, 2),
      ]),
    ];
    return lines.join('\n');
  }

  function exportReport() {
    showReportPopup = true;
  }

  function downloadReport() {
    const blob = new Blob([reportText()], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${activeDownloadName.replace(/\.3mf$/i, '')}-report.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
</script>

<div class="artifact-review">
  <div class="header">
    <div class="header-left">
      <h2>{$i18n('Build Ready')}</h2>
      <div class="meta muted">
        {activeDiff.report.source_filename}
        <span class="file-separator">{$i18n('converted as')}</span>
        <strong class="accent">{activeDiff.report.output_filename}</strong>
      </div>
    </div>
    <div class="header-actions">
      <button class="ghost" onclick={onreset}>
        <RotateCcw size={15} strokeWidth={2.4} aria-hidden="true" />
        {$i18n('Start a new build')}
      </button>
      <button class="ghost" type="button" onclick={exportReport}>
        <FileText size={15} strokeWidth={2.4} aria-hidden="true" />
        {$i18n('Export report')}
      </button>
      <div class="save-split">
        <button type="button" class="artifact-save split-main" onclick={saveOrDownloadConverted} disabled={saving}>
          {#if hasNativeSave}
            <Save size={15} strokeWidth={2.4} aria-hidden="true" />
            {saving ? $i18n('Saving...') : $i18n('Save 3MF')}
          {:else}
            <Download size={15} strokeWidth={2.4} aria-hidden="true" />
            {saving ? $i18n('Downloading...') : $i18n('Download 3MF')}
          {/if}
        </button>
        <button
          type="button"
          class="save-menu-trigger"
          onclick={() => (saveMenuOpen = saveMenuOpen === 'header' ? '' : 'header')}
          disabled={saving}
          aria-label={$i18n('More save options')}
          aria-expanded={saveMenuOpen === 'header'}
        >
          <MoreHorizontal size={18} strokeWidth={2.7} aria-hidden="true" />
        </button>
        {#if saveMenuOpen === 'header'}
          <div class="save-menu" role="menu">
            <button type="button" role="menuitem" onclick={forceNativeSave} disabled={!hasNativeSave || saving} title={!hasNativeSave ? $i18n('Desktop save is unavailable in this browser') : ''}>
              <Save size={15} strokeWidth={2.4} aria-hidden="true" />
              {$i18n('Save with dialog')}
            </button>
            <button type="button" role="menuitem" onclick={forceBrowserDownload} disabled={saving}>
              <Download size={15} strokeWidth={2.4} aria-hidden="true" />
              {$i18n('Download through browser')}
            </button>
          </div>
        {/if}
      </div>
    </div>
  </div>

  {#if saveStatus}
    <div class:save-status={true} class:error={saveStatusIsError}>
      {saveStatus}
    </div>
  {/if}

  {#if activeDiff.report.swap_pauses_skipped_painted}
    <div class="paint-alert" role="alert">
      <strong>{$i18n('No pause notes added:')}</strong> {$i18n('this package uses painted geometry, so colour changes are generated when you slice in Snapmaker Orca.')}
    </div>
  {/if}

  <div class="metric-badges">
    {#if counts.identity_swaps}
      <span class="pill success">✓ {counts.identity_swaps} {$i18n('machine tags')}</span>
    {/if}
    {#if counts.gcode_swaps}
      <span class="pill success">✓ {counts.gcode_swaps} {$i18n('startup scripts')}</span>
    {/if}
    {#if counts.keys_dropped}
      <span class="pill">✕ {counts.keys_dropped} {$i18n('incompatible keys')}</span>
    {/if}
    {#if counts.values_clamped}
      <span class="pill warn">⇩ {counts.values_clamped} {$i18n('values clamped')}</span>
    {/if}
    {#if counts.rules_matched}
      <span class="pill accent">+ {counts.rules_matched} {$i18n('recipes')}</span>
    {/if}
    {#if counts.slot_remaps}
      <span class="pill">⇆ {counts.slot_remaps} {$i18n('filament slots')}</span>
    {/if}
    {#if counts.slice_artifacts_stripped}
      <span class="pill">✕ {counts.slice_artifacts_stripped} {$i18n('caches stripped')}</span>
    {/if}
    {#if counts.advanced_overrides_applied}
      <span class="pill accent">+ {counts.advanced_overrides_applied} {$i18n('overrides')}</span>
    {/if}
    {#if counts.swap_instructions}
      <span class="pill warn">! {counts.swap_instructions} {$i18n(counts.swap_instructions === 1 ? 'spool stop' : 'spool stops')}</span>
    {/if}
  </div>

  <div class="parameter-console card card-padded" class:editor-open={showParamEditor}>
      <div class="parameter-head">
        <div>
          <span class="parameter-eyebrow">{$i18n('Process tuning')}</span>
          <h3>{$i18n('Build parameters')}</h3>
        </div>
        <button class="ghost parameter-toggle" type="button" onclick={() => (showParamEditor = !showParamEditor)} aria-expanded={showParamEditor}>
          <SlidersHorizontal size={15} strokeWidth={2.4} aria-hidden="true" />
          {showParamEditor ? $i18n('Close editor') : $i18n('Edit changed values')}
        </button>
      </div>

      {#if paramGroups.length}
        <div class="parameter-summary" aria-label={$i18n('Changed parameter summary')}>
          <span class="summary-total">
            <strong>{totalChangedCount()}</strong>
            {$i18n('changed values')}
          </span>
          {#each paramGroups as group (group.name)}
            <button
              type="button"
              class="summary-chip"
              class:active={activeParamGroup === group.name}
              onclick={() => {
                activeParamGroup = group.name;
                showParamEditor = true;
              }}
            >
              <span>{groupLabel(group.name)}</span>
              <strong>{groupChangedCount(group)}</strong>
              <small>/ {groupEditableCount(group)}</small>
            </button>
          {/each}
        </div>
      {/if}

      <label class="exclude-line">
        <input type="checkbox" bind:checked={reviewExcludeObjects} />
        <span>
          <strong>{$i18n('Enable Global > Others > Exclude objects')}</strong>
          <small>{$i18n('Rebuild with object exclusion available in Snapmaker Orca.')}</small>
        </span>
      </label>

      {#if showParamEditor}
        <div class="param-browser">
          <div class="param-browser-head">
            <input
              class="param-search"
              type="search"
              bind:value={paramSearch}
              placeholder={$i18n('Search parameters')}
              aria-label={$i18n('Search parameters')}
            />
          </div>

          <label class="changed-filter">
            <input type="checkbox" bind:checked={showChangedOnly} />
            <span>{$i18n('Only changed parameters')}</span>
          </label>

          {#if paramsLoading}
            <p class="muted small-note">{$i18n('Loading parameters...')}</p>
          {:else if paramsError}
            <p class="muted small-note">{paramsError}</p>
          {:else if visibleParamRows().length}
            <div class="param-table" aria-label={$i18n('Editable slicer parameters')}>
              {#each visibleParamRows() as row (row.key)}
              <article class="param-row" class:changed-row={row.changed}>
                <div class="param-card-head">
                  <div class="param-copy">
                    <div class="param-title-line">
                      <strong>{parameterTitle(row.key)}</strong>
                      {#if row.changed}
                        <span class="changed-badge">{$i18n('Changed')}</span>
                      {:else}
                        <span class="steady-badge">{$i18n('U1 default')}</span>
                      {/if}
                    </div>
                    <span class="mono param-key">{row.key}</span>
                  </div>
                  <div class="param-help-wrap">
                    <button class="param-help" type="button" aria-label={`${$i18n('What does this parameter do?')} ${row.key}`}>
                      <CircleHelp size={16} strokeWidth={2.4} aria-hidden="true" />
                    </button>
                    <span class="param-tooltip">{parameterHelp(row.key)}</span>
                  </div>
                </div>

                <div class="param-detail-plane">
                  <p class="param-description">{parameterHelp(row.key)}</p>

                  <div class="param-right-rail">
                    <div class="param-value-grid">
                      <div class="value-box current-value">
                        <span>{$i18n('Current')}</span>
                        <strong>{valueWithUnit(row.key, row.current)}</strong>
                      </div>
                      <div class="value-box default-value" class:missing={row.defaultValue === undefined}>
                        <span>{$i18n('U1 reference')}</span>
                        <strong>{row.defaultValue === undefined ? $i18n('Not available') : valueWithUnit(row.key, row.defaultValue)}</strong>
                      </div>
                    </div>

                    <div class="param-command-line">
                      <div class="param-actions" role="group" aria-label={`${$i18n('Edit mode for')} ${row.key}`}>
                        <button type="button" class:active={modeFor(row.key) === 'keep'} onclick={() => setMode(row.key, 'keep', row.current)}>{$i18n('Keep')}</button>
                        <button type="button" class:active={modeFor(row.key) === 'default'} disabled={!row.editable} onclick={() => setMode(row.key, 'default', row.current)}>{$i18n('U1 default')}</button>
                        <button type="button" class:active={modeFor(row.key) === 'custom'} disabled={!row.editable} onclick={() => setMode(row.key, 'custom', row.current)}>{$i18n('Custom')}</button>
                      </div>
                      {#if !row.editable}
                        <span class="protected-note">{$i18n('No editable U1 reference value')}</span>
                      {/if}
                    </div>
                  </div>
                </div>

                {#if modeFor(row.key) === 'custom'}
                  <input
                    class="param-input mono"
                    value={customValues[row.key] ?? formatValue(row.current)}
                    oninput={(event) => setCustomValue(row.key, event.currentTarget.value)}
                    spellcheck="false"
                    aria-label={`${$i18n('Custom value for')} ${row.key}`}
                  />
                {/if}
              </article>
            {/each}
          </div>
          {:else}
            <p class="muted small-note">{$i18n('No parameters in this group.')}</p>
          {/if}
        </div>
      {/if}

      <div class="parameter-footer">
        {#if rebuildStatus}
          <span class:error-note={isRebuildError(rebuildStatus)} class:ok-note={!isRebuildError(rebuildStatus)}>{rebuildStatus}</span>
        {/if}
        <button class="artifact-save compact" type="button" onclick={rebuildWithEdits} disabled={rebuilding || !hasRebuildChanges()}>
          {rebuilding ? $i18n('Rebuilding...') : $i18n('Rebuild with edits')}
        </button>
      </div>
  </div>

  <div class="compare-preview">
    <ScenePreview
      jobId={activeJobId}
      sourceJob
      compact
      eyebrow={$i18n('Original layout')}
      heading={$i18n('Before conversion')}
    />
    <ScenePreview
      jobId={activeJobId}
      compact
      eyebrow={$i18n('Converted layout')}
      heading={$i18n('After conversion')}
    />
  </div>

  {#if activeDiff.sections.length === 0}
    <p class="muted">{$i18n('No edits were needed. The package may already match the selected profile.')}</p>
  {:else}
    <div class="review-grid">
      {#each activeDiff.sections as section, i (section.title)}
        <div class="review-card card" class:expanded={expanded.has(i)}>
          <button
            class="review-card-button"
            onclick={() => toggle(i)}
            aria-expanded={expanded.has(i)}
          >
            <span class="ok-token">OK</span>
            <span class="review-title">{displayTitle(section.title)}</span>
            <span class="review-summary muted">{displaySummary(section.title, section.details?.length ?? 0)}</span>
            <span class="turn-indicator" class:open={expanded.has(i)}>›</span>
          </button>

          {#if expanded.has(i)}
            <div class="review-body">
              {#if section.title === 'Printer identity'}
                <table>
                  <thead><tr><th>{$i18n('Key')}</th><th>{$i18n('From')}</th><th>{$i18n('To')}</th></tr></thead>
                  <tbody>
                    {#each section.details as row}
                      <tr>
                        <td class="mono">{row.key}</td>
                        <td class="from">{formatValue(row.from_value)}</td>
                        <td class="to">{formatValue(row.to_value)}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>

              {:else if section.title === 'Custom G-code'}
                <table>
                  <thead><tr><th>{$i18n('Block')}</th><th>{$i18n('Before')}</th><th>{$i18n('After')}</th></tr></thead>
                  <tbody>
                    {#each section.details as row}
                      <tr>
                        <td class="mono">{row.key}</td>
                        <td class="muted">{row.from_bytes} B</td>
                        <td>{row.to_bytes} B</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>

              {:else if section.title === 'Keys dropped'}
                <div class="tag-flow">
                  {#each section.details as row}
                    <span class="tag-token mono">{row.key}</span>
                  {/each}
                </div>

              {:else if section.title === 'Values clamped'}
                <table>
                  <thead><tr><th>{$i18n('Key')}</th><th>{$i18n('Was')}</th><th>{$i18n('Clamped to')}</th></tr></thead>
                  <tbody>
                    {#each section.details as row}
                      <tr>
                        <td class="mono">{row.key}</td>
                        <td class="from">{formatValue(row.from_value)}</td>
                        <td>{formatValue(row.to_value)}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>

              {:else if section.title === 'Filament rules applied'}
                {#each section.details as rule}
                  <div class="recipe-hit">
                    <div class="recipe-hit-title">
                      {rule.rule_name}
                      <span class="pill">{$i18n('priority')} {rule.priority}</span>
                    </div>
                    <div class="recipe-hit-grid">
                      <div>
                        <div class="label muted">{$i18n('Matched on')}</div>
                        {#each Object.entries(rule.matched_on) as [k, v]}
                          <div class="kv"><span class="mono">{k}</span>: {formatValue(v)}</div>
                        {/each}
                      </div>
                      <div>
                        <div class="label muted">{$i18n('Overrides applied')}</div>
                        {#if Object.keys(rule.overrides_applied).length}
                          {#each Object.entries(rule.overrides_applied) as [k, v]}
                            <div class="kv"><span class="mono">{k}</span>: {formatValue(v)}</div>
                          {/each}
                        {:else}
                          <div class="kv muted">{$i18n('No safe overrides were applied.')}</div>
                        {/if}
                        {#if rule.overrides_skipped && Object.keys(rule.overrides_skipped).length}
                          <div class="label muted skip-label">{$i18n('Skipped')}</div>
                          {#each Object.entries(rule.overrides_skipped) as [k, v]}
                            <div class="kv skipped"><span class="mono">{k}</span>: {v}</div>
                          {/each}
                        {/if}
                      </div>
                    </div>
                  </div>
                {/each}

              {:else if section.title === 'Filament slots'}
                <table>
                  <thead><tr><th>{$i18n('Filament')}</th><th>{$i18n('Source slot')}</th><th>{$i18n('Output')}</th></tr></thead>
                  <tbody>
                    {#each section.details as row}
                      <tr>
                        <td class="muted">{row.filament_id ?? '—'}</td>
                        <td>{row.from_index + 1}</td>
                        <td class:dropped={row.to_index < 0} class:passthrough={row.to_index >= 4}>
                          {#if row.to_index < 0}
                            {$i18n('dropped')}
                          {:else if row.to_index >= 4}
                            {$i18n('slot')} {row.to_index + 1} ({$i18n('Orca assigns')})
                          {:else}
                            T{row.to_index + 1}
                          {/if}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>

              {:else if section.title === 'Slice caches stripped'}
                <div class="tag-flow">
                  {#each section.details as name}
                    <span class="tag-token mono">{name}</span>
                  {/each}
                </div>

              {:else if section.title === 'Filament swap pauses'}
                {@const byZ = Object.entries(
                  section.details.reduce((acc: Record<string, typeof section.details>, instr: typeof section.details[0]) => {
                    const key = String(instr.z);
                    (acc[key] = acc[key] || []).push(instr);
                    return acc;
                  }, {})
                ).sort(([a], [b]) => parseFloat(a) - parseFloat(b))}
                <div class="pause-plan">
                  {#each byZ as [zKey, instrs], gi}
                    <div class="pause-stop-card">
                      <div class="pause-stop-head">
                        <span class="pause-stop-label">{$i18n('Stop')} {gi + 1}</span>
                        <span class="pause-z mono">{$i18n('after Z =')} {parseFloat(zKey).toFixed(2)} mm</span>
                        <span class="subtle pause-count">{instrs.length} {$i18n(instrs.length === 1 ? 'spool to swap' : 'spools to swap')}</span>
                      </div>
                      {#each instrs as instr}
                        <div class="pause-action-row">
                          <span class="head-token">T{instr.toolhead}</span>
                          <div class="colour-transfer">
                            <span class="mini-colour" style="background:{instr.from_colour || '#888'}" title="{$i18n('Current')}: {$i18n('slot')} {instr.from_slot}"></span>
                            <span class="transfer-word">{$i18n('loads')}</span>
                            <span class="mini-colour" style="background:{instr.to_colour || '#888'}" title="{$i18n('Load')}: {$i18n('slot')} {instr.to_slot}"></span>
                          </div>
                          <div class="pause-copy">
                            <span class="pause-copy-title">{$i18n('Toolhead')} {instr.toolhead} - {$i18n('remove spool and load new one')}</span>
                            <span class="subtle pause-copy-sub">
                              {$i18n('Unload')} {instr.from_colour || $i18n('current')} · {$i18n('Load')} {instr.to_colour || $i18n('new colour')}
                            </span>
                          </div>
                        </div>
                      {/each}
                    </div>
                  {/each}
                  <p class="subtle pause-note">{$i18n('When the print pauses, swap the listed spools, then press Resume. Each stop may require multiple spool changes; do them all before resuming.')}</p>
                </div>

              {:else}
                <pre class="raw-detail">{JSON.stringify(section.details, null, 2)}</pre>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}

  <div class="artifact-save-dock">
    <div class="save-split dock-split">
      <button type="button" class="artifact-save large split-main" onclick={saveOrDownloadConverted} disabled={saving}>
        {#if hasNativeSave}
          <Save size={16} strokeWidth={2.4} aria-hidden="true" />
          {saving ? $i18n('Saving...') : `${$i18n('Save')} ${activeDownloadName}`}
        {:else}
          <Download size={16} strokeWidth={2.4} aria-hidden="true" />
          {saving ? $i18n('Downloading...') : `${$i18n('Download')} ${activeDownloadName}`}
        {/if}
      </button>
      <button
        type="button"
        class="save-menu-trigger large"
        onclick={() => (saveMenuOpen = saveMenuOpen === 'dock' ? '' : 'dock')}
        disabled={saving}
        aria-label={$i18n('More save options')}
        aria-expanded={saveMenuOpen === 'dock'}
      >
        <MoreHorizontal size={20} strokeWidth={2.7} aria-hidden="true" />
      </button>
      {#if saveMenuOpen === 'dock'}
        <div class="save-menu dock-menu" role="menu">
          <button type="button" role="menuitem" onclick={forceNativeSave} disabled={!hasNativeSave || saving} title={!hasNativeSave ? $i18n('Desktop save is unavailable in this browser') : ''}>
            <Save size={15} strokeWidth={2.4} aria-hidden="true" />
            {$i18n('Save with dialog')}
          </button>
          <button type="button" role="menuitem" onclick={forceBrowserDownload} disabled={saving}>
            <Download size={15} strokeWidth={2.4} aria-hidden="true" />
            {$i18n('Download through browser')}
          </button>
        </div>
      {/if}
    </div>
  </div>

  {#if showReportPopup}
    <div class="report-backdrop" role="dialog" aria-modal="true" aria-labelledby="report-title" tabindex="-1" onkeydown={(event) => { if (event.key === 'Escape') showReportPopup = false; }}>
      <div class="report-modal">
        <div class="report-head">
          <div>
            <span class="parameter-eyebrow">{$i18n('Export report')}</span>
            <h2 id="report-title">{$i18n('Conversion report')}</h2>
          </div>
          <button class="ghost report-close" type="button" onclick={() => (showReportPopup = false)} aria-label={$i18n('Close')}>
            <X size={18} strokeWidth={2.5} aria-hidden="true" />
          </button>
        </div>

        <pre class="report-body">{reportText()}</pre>

        <div class="report-actions">
          <button class="ghost" type="button" onclick={() => (showReportPopup = false)}>{$i18n('Close')}</button>
          <button class="artifact-save compact" type="button" onclick={downloadReport}>
            <FileText size={15} strokeWidth={2.4} aria-hidden="true" />
            {$i18n('Save .txt')}
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .artifact-review { display: flex; flex-direction: column; gap: 20px; }

  .header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }
  .header h2 { margin: 0 0 6px; font-size: 32px; line-height: 1; font-weight: 950; }
  .header-left { flex: 1; }
  .header-actions { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
  .accent { color: var(--accent); }
  .meta { font-size: 13px; display: flex; gap: 8px; flex-wrap: wrap; align-items: baseline; }
  .file-separator { color: var(--text-subtle); font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.04em; }

  .paint-alert {
    padding: 12px 16px;
    background: color-mix(in srgb, var(--warn) 12%, var(--bg-elev));
    border: 2px solid color-mix(in srgb, var(--warn) 35%, transparent);
    border-radius: 16px;
    color: var(--warn);
    font-size: 13px;
    margin-bottom: 4px;
  }

  .metric-badges { display: flex; flex-wrap: wrap; gap: 8px; }

  .compare-preview {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
  }

  .parameter-console {
    display: flex;
    flex-direction: column;
    gap: 14px;
    border-radius: 18px;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--sun) 18%, transparent), transparent 48%),
      var(--bg-elev);
  }
  .parameter-console.editor-open {
    gap: 18px;
    padding: clamp(18px, 2vw, 26px);
    border-color: color-mix(in srgb, var(--ink) 24%, var(--border));
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--mint) 16%, transparent), transparent 44%),
      linear-gradient(180deg, color-mix(in srgb, var(--sun) 10%, transparent), transparent 58%),
      var(--bg-elev);
  }
  .parameter-head,
  .parameter-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }
  .parameter-eyebrow {
    display: block;
    margin-bottom: 3px;
    color: var(--text-muted);
    font-size: 10px;
    font-weight: 950;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .parameter-head h3 {
    margin: 0;
    font-size: 18px;
    line-height: 1.1;
    font-weight: 950;
  }
  .parameter-toggle,
  .artifact-save.compact {
    min-height: 34px;
    padding: 7px 12px;
    font-size: 12.5px;
    gap: 7px;
  }
  .parameter-toggle {
    min-height: 38px;
    padding: 8px 13px;
    border: 1px solid color-mix(in srgb, var(--warn) 58%, var(--border));
    background: color-mix(in srgb, var(--sun) 72%, var(--bg-elev));
    color: var(--ink);
    box-shadow: 0 2px 0 color-mix(in srgb, var(--warn) 58%, var(--ink));
    font-size: 13px;
    font-weight: 950;
  }
  .parameter-toggle:hover {
    background: var(--sun);
  }
  .parameter-summary {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: color-mix(in srgb, var(--bg-raised) 70%, transparent);
  }
  .summary-total,
  .summary-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 900;
  }
  .summary-total {
    padding: 6px 10px;
    color: var(--text);
    background: color-mix(in srgb, var(--sun) 24%, var(--bg-elev));
    border: 1px solid color-mix(in srgb, var(--warn) 35%, var(--border));
  }
  .summary-total strong,
  .summary-chip strong {
    font-weight: 950;
  }
  .summary-chip {
    padding: 5px 9px;
    border: 1px solid var(--border);
    background: var(--bg-elev);
    color: var(--text-muted);
    box-shadow: none;
  }
  .summary-chip.active {
    border-color: var(--ink);
    background: var(--ink);
    color: #fffdf8;
  }
  .summary-chip small {
    color: inherit;
    opacity: 0.68;
    font-size: 11px;
  }
  .exclude-line {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: color-mix(in srgb, var(--bg-raised) 70%, transparent);
  }
  .exclude-line input {
    width: 18px;
    height: 18px;
    accent-color: var(--accent);
  }
  .exclude-line span {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .exclude-line strong {
    font-size: 13px;
    color: var(--text);
  }
  .exclude-line small {
    font-size: 12px;
    color: var(--text-muted);
  }
  .param-table {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 540px), 1fr));
    gap: 12px;
    max-height: min(72vh, 760px);
    overflow: auto;
    padding: 2px 6px 2px 2px;
    scrollbar-gutter: stable;
  }
  .param-browser {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .param-browser-head {
    display: flex;
    justify-content: flex-end;
  }
  .param-search {
    width: min(360px, 100%);
    min-height: 34px;
    font-size: 12px;
  }
  .changed-filter {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    align-self: flex-start;
    min-height: 34px;
    padding: 7px 10px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: color-mix(in srgb, var(--sun) 12%, var(--bg-elev));
    color: var(--text);
    font-size: 12px;
    font-weight: 900;
  }
  .changed-filter input {
    width: 15px;
    height: 15px;
    accent-color: var(--accent);
  }
  .param-row {
    display: grid;
    gap: 12px;
    align-content: start;
    padding: 15px;
    border: 1px solid var(--border);
    border-radius: 18px;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--mint) 8%, transparent), transparent 52%),
      color-mix(in srgb, var(--bg-elev) 92%, transparent);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--ink) 7%, transparent);
  }
  .param-row.changed-row {
    border-color: color-mix(in srgb, var(--accent) 36%, var(--border));
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--sun) 13%, transparent), transparent 50%),
      color-mix(in srgb, var(--mint) 8%, var(--bg-elev));
  }
  .param-card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 10px;
  }
  .param-copy {
    min-width: 0;
    display: grid;
    gap: 4px;
  }
  .param-title-line {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex-wrap: wrap;
  }
  .param-title-line strong {
    color: var(--text);
    font-size: 15.5px;
    font-weight: 950;
    line-height: 1.15;
  }
  .changed-badge,
  .steady-badge {
    padding: 3px 7px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 950;
    text-transform: uppercase;
  }
  .changed-badge {
    color: #fffdf8;
    background: var(--accent);
  }
  .steady-badge {
    color: var(--text-muted);
    background: color-mix(in srgb, var(--text) 8%, transparent);
  }
  .param-key {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-muted);
    font-size: 11.5px;
    font-weight: 900;
  }
  .param-help-wrap {
    position: relative;
    flex: 0 0 auto;
  }
  .param-help {
    width: 30px;
    height: 30px;
    display: grid;
    place-items: center;
    padding: 0;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: var(--bg-raised);
    color: var(--text-muted);
    box-shadow: none;
  }
  .param-tooltip {
    position: absolute;
    z-index: 30;
    top: calc(100% + 8px);
    right: 0;
    width: min(380px, 72vw);
    padding: 10px 12px;
    border: 1px solid var(--border-strong);
    border-radius: 12px;
    background: var(--ink);
    color: #fffdf8;
    font-size: 12px;
    line-height: 1.4;
    box-shadow: 0 14px 34px color-mix(in srgb, var(--ink) 36%, transparent);
    opacity: 0;
    pointer-events: none;
    transform: translateY(-3px);
    transition: opacity 0.14s ease, transform 0.14s ease;
  }
  .param-help-wrap:hover .param-tooltip,
  .param-help:focus + .param-tooltip {
    opacity: 1;
    transform: translateY(0);
  }
  .param-description {
    margin: 0;
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.48;
  }
  .param-detail-plane {
    display: grid;
    grid-template-columns: minmax(220px, 1fr) minmax(300px, 0.95fr);
    gap: 14px;
    align-items: start;
  }
  .param-right-rail {
    display: grid;
    gap: 10px;
    min-width: 0;
  }
  .param-value-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }
  .value-box {
    min-width: 0;
    display: grid;
    gap: 4px;
    padding: 11px 12px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: color-mix(in srgb, var(--bg-raised) 74%, transparent);
  }
  .value-box span {
    color: var(--text-muted);
    font-size: 10px;
    font-weight: 950;
    letter-spacing: .05em;
    text-transform: uppercase;
  }
  .value-box strong {
    min-width: 0;
    overflow-wrap: anywhere;
    color: var(--text);
    font-size: 14px;
    line-height: 1.25;
    font-weight: 950;
  }
  .current-value {
    border-color: color-mix(in srgb, var(--accent) 24%, var(--border));
  }
  .default-value.missing {
    opacity: 0.68;
  }
  .param-command-line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
  }
  .param-actions {
    display: inline-flex;
    gap: 4px;
    padding: 3px;
    border-radius: 999px;
    background: var(--bg-raised);
    border: 1px solid var(--border);
  }
  .param-actions button {
    min-height: 28px;
    padding: 4px 9px;
    border: 0;
    border-radius: 999px;
    background: transparent;
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 900;
  }
  .param-actions button.active {
    background: var(--ink);
    color: #fffdf8;
  }
  .param-actions button:disabled {
    opacity: 0.36;
    cursor: not-allowed;
  }
  .protected-note {
    color: var(--text-muted);
    font-size: 11.5px;
    font-weight: 850;
  }
  .param-input {
    grid-column: 1 / -1;
    width: 100%;
    min-height: 38px;
    font-size: 13px;
  }
  .small-note {
    margin: 0;
    font-size: 12px;
  }
  .ok-note,
  .error-note {
    font-size: 12px;
    font-weight: 850;
  }
  .ok-note { color: var(--success); }
  .error-note { color: var(--danger); }

  @media (max-width: 760px) {
    .compare-preview {
      grid-template-columns: 1fr;
    }
    .param-browser-head { justify-content: stretch; }
    .param-search { width: 100%; }
    .param-detail-plane,
    .param-value-grid {
      grid-template-columns: 1fr;
    }
    .param-actions {
      width: 100%;
      justify-content: stretch;
    }
    .param-actions button {
      flex: 1;
    }
  }

  .review-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px;
    align-items: stretch;
  }

  .review-card {
    overflow: hidden;
    min-height: 176px;
    display: flex;
    flex-direction: column;
    border-radius: 20px;
  }
  .review-card.expanded {
    grid-column: 1 / -1;
    min-height: auto;
  }

  .review-card-button {
    display: grid;
    grid-template-columns: 1fr auto;
    grid-template-rows: auto 1fr auto;
    align-items: start;
    gap: 12px;
    width: 100%;
    min-height: 176px;
    flex: 1;
    padding: 18px;
    background:
      linear-gradient(145deg, color-mix(in srgb, var(--mint) 16%, transparent), transparent 54%),
      transparent;
    border: none;
    border-radius: 20px;
    cursor: pointer;
    text-align: left;
    font-size: 14px;
    transition: background var(--duration);
  }
  .review-card.expanded .review-card-button {
    min-height: 120px;
    flex: 0 0 auto;
  }
  .review-card-button:hover {
    background:
      linear-gradient(145deg, color-mix(in srgb, var(--sun) 20%, transparent), transparent 60%),
      var(--bg-raised);
  }

  .ok-token {
    display: inline-flex;
    justify-content: center;
    align-items: center;
    justify-self: start;
    min-width: 36px;
    min-height: 28px;
    padding: 3px 8px;
    border-radius: 999px;
    color: var(--ink);
    background: var(--mint);
    font-weight: 950;
    font-size: 10px;
  }
  .review-title {
    grid-column: 1 / -1;
    align-self: end;
    font-weight: 950;
    font-size: 20px;
    line-height: 1.08;
  }
  .review-summary {
    grid-column: 1 / -1;
    align-self: end;
    font-size: 13px;
    line-height: 1.35;
  }
  .turn-indicator {
    grid-column: 2;
    grid-row: 1;
    justify-self: end;
    color: var(--accent);
    transition: transform var(--duration);
    font-size: 26px;
    line-height: 1;
    font-weight: 950;
  }
  .turn-indicator.open { transform: rotate(90deg); }

  .review-body {
    padding: 0 18px 18px;
    border-top: 1px solid var(--border);
    margin-top: 0;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
    margin-top: 10px;
  }
  th {
    text-align: left;
    color: var(--text-subtle);
    font-weight: 900;
    padding: 6px 10px 6px 0;
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  td {
    padding: 7px 10px 7px 0;
    border-bottom: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
    color: var(--text);
    max-width: 280px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  td.from { color: var(--text-subtle); }
  td.dropped { color: var(--warn); }
  td.passthrough { color: var(--text-muted); font-style: italic; }

  .tag-flow {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding-top: 10px;
  }
  .tag-token {
    font-size: 11px;
    padding: 2px 8px;
    background: var(--bg-raised);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-muted);
  }

  .recipe-hit {
    background: var(--bg-raised);
    border-radius: var(--radius);
    padding: 12px 14px;
    margin-top: 10px;
  }
  .recipe-hit-title { font-weight: 500; display: flex; align-items: center; gap: 10px; }
  .recipe-hit-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px; }
  .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; }
  .kv { font-size: 12px; }
  .skip-label { margin-top: 8px; }
  .kv.skipped { color: var(--warn); }

  .raw-detail {
    font-size: 11.5px;
    font-family: var(--font-mono);
    background: var(--bg-raised);
    padding: 10px 12px;
    border-radius: var(--radius);
    overflow: auto;
    max-height: 300px;
    color: var(--text-muted);
    margin-top: 10px;
  }

  .artifact-save {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 44px;
    background:
      linear-gradient(180deg, color-mix(in srgb, var(--ink) 94%, var(--mint)), var(--ink));
    color: #fffdf8;
    border: 2px solid color-mix(in srgb, var(--mint) 58%, var(--ink));
    padding: 10px 18px;
    border-radius: 14px;
    font-weight: 950;
    cursor: pointer;
    transition: transform var(--duration), filter var(--duration), box-shadow var(--duration);
    font-size: 14.5px;
    text-decoration: none;
    font-family: inherit;
    box-shadow:
      0 5px 0 color-mix(in srgb, var(--mint) 42%, #071b17),
      0 14px 28px color-mix(in srgb, var(--ink) 24%, transparent);
  }

  .save-split {
    position: relative;
    display: inline-flex;
    align-items: stretch;
    isolation: isolate;
  }

  .save-split .split-main {
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
    border-right-width: 1px;
  }

  .save-menu-trigger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    min-height: 44px;
    border: 2px solid color-mix(in srgb, var(--mint) 58%, var(--ink));
    border-left: 0;
    border-radius: 0 14px 14px 0;
    background:
      linear-gradient(180deg, color-mix(in srgb, var(--ink) 88%, var(--mint)), color-mix(in srgb, var(--ink) 98%, #000));
    color: #fffdf8;
    cursor: pointer;
    box-shadow:
      0 5px 0 color-mix(in srgb, var(--mint) 42%, #071b17),
      0 14px 28px color-mix(in srgb, var(--ink) 24%, transparent);
  }

  .save-menu-trigger.large {
    width: 50px;
    min-height: 50px;
  }

  .save-menu-trigger:hover {
    filter: saturate(1.05) brightness(1.08);
  }

  .save-menu-trigger:disabled {
    opacity: 0.65;
    cursor: wait;
  }

  .save-menu {
    position: absolute;
    top: calc(100% + 10px);
    right: 0;
    z-index: 120;
    display: grid;
    gap: 6px;
    min-width: 235px;
    padding: 8px;
    border: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
    border-radius: 14px;
    background: color-mix(in srgb, var(--bg) 94%, #fff);
    box-shadow:
      0 20px 38px color-mix(in srgb, var(--ink) 18%, transparent),
      0 0 0 1px color-mix(in srgb, var(--mint) 15%, transparent);
  }

  .dock-menu {
    top: auto;
    bottom: calc(100% + 10px);
  }

  .save-menu button {
    display: flex;
    align-items: center;
    gap: 9px;
    width: 100%;
    padding: 10px 12px;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--text);
    font: inherit;
    font-weight: 850;
    text-align: left;
    cursor: pointer;
  }

  .save-menu button:hover:not(:disabled) {
    background: color-mix(in srgb, var(--mint) 18%, transparent);
  }

  .save-menu button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .artifact-save:hover {
    background:
      linear-gradient(180deg, color-mix(in srgb, var(--ink) 86%, var(--mint)), color-mix(in srgb, var(--ink) 96%, #000));
    filter: saturate(1.05) brightness(1.08);
    color: #fffdf8;
    transform: translateY(1px);
    box-shadow:
      0 4px 0 color-mix(in srgb, var(--mint) 42%, #071b17),
      0 10px 22px color-mix(in srgb, var(--ink) 24%, transparent);
  }
  .artifact-save:disabled { opacity: 0.65; cursor: wait; }
  .artifact-save:disabled + .save-menu-trigger { opacity: 0.8; }
  .artifact-save.large { min-height: 50px; padding: 14px 34px; font-size: 16px; }
  .artifact-save.compact {
    min-height: 38px;
    padding: 8px 14px;
    border-width: 1px;
    border-radius: 12px;
    box-shadow: 0 3px 0 color-mix(in srgb, var(--mint) 42%, #071b17);
    font-size: 12.5px;
  }
  .parameter-footer .artifact-save.compact {
    background: color-mix(in srgb, var(--sun) 82%, var(--bg-elev));
    border-color: color-mix(in srgb, var(--warn) 58%, var(--border));
    color: var(--ink);
    box-shadow: 0 3px 0 color-mix(in srgb, var(--warn) 62%, var(--ink));
  }
  .parameter-footer .artifact-save.compact:hover {
    background: var(--sun);
    color: var(--ink);
    box-shadow: 0 2px 0 color-mix(in srgb, var(--warn) 62%, var(--ink));
  }
  .save-status {
    padding: 10px 14px;
    border-radius: var(--radius);
    border: 1px solid color-mix(in srgb, var(--success) 35%, transparent);
    color: var(--success);
    background: color-mix(in srgb, var(--success) 10%, transparent);
    overflow-wrap: anywhere;
    font-size: 13px;
  }
  .save-status.error {
    border-color: color-mix(in srgb, var(--danger) 35%, transparent);
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
  }

  .pause-plan { display: flex; flex-direction: column; gap: 12px; padding-top: 10px; }
  .pause-stop-card {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .pause-stop-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    background: var(--bg-raised);
    border-bottom: 1px solid var(--border);
    font-size: 13px;
  }
  .pause-stop-label { font-weight: 600; color: var(--warn); }
  .pause-z { font-size: 12px; color: var(--text-muted); }
  .pause-count { margin-left: auto; font-size: 12px; }
  .pause-action-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-bottom: 1px solid color-mix(in srgb, var(--border) 40%, transparent);
    font-size: 13px;
  }
  .pause-action-row:last-child { border-bottom: none; }
  .head-token {
    font-weight: 700;
    font-size: 12px;
    padding: 2px 7px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--accent) 15%, transparent);
    color: var(--accent);
    flex-shrink: 0;
    min-width: 28px;
    text-align: center;
  }
  .colour-transfer { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
  .transfer-word { font-size: 14px; color: var(--text-muted); }
  .pause-copy { display: flex; flex-direction: column; gap: 2px; }
  .pause-copy-title { font-weight: 500; }
  .pause-copy-sub { font-size: 11.5px; }
  .mini-colour { width: 20px; height: 20px; border-radius: 4px; border: 1px solid color-mix(in srgb, var(--border) 60%, transparent); flex-shrink: 0; }
  .pause-note { margin: 4px 0 0; font-size: 12px; }

  .artifact-save-dock {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 20px;
    border-top: 1px solid var(--border);
  }

  .report-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1500;
    display: grid;
    place-items: center;
    padding: 24px;
    background: rgba(17, 24, 32, 0.56);
    backdrop-filter: blur(12px);
  }

  .report-modal {
    width: min(920px, 100%);
    max-height: min(820px, 90vh);
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 20px;
    border-radius: 22px;
    border: 2px solid var(--border-strong);
    background: var(--bg-elev);
    box-shadow: 0 28px 70px color-mix(in srgb, var(--ink) 34%, transparent);
  }

  .report-head,
  .report-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .report-head h2 {
    margin: 2px 0 0;
    color: var(--text);
    font-size: 24px;
    line-height: 1;
    font-weight: 950;
  }

  .report-close {
    width: 36px;
    height: 36px;
    padding: 0;
    flex: 0 0 auto;
  }

  .report-body {
    min-height: 340px;
    max-height: 58vh;
    overflow: auto;
    margin: 0;
    padding: 14px;
    border-radius: 14px;
    border: 1px solid var(--border);
    background: var(--bg-raised);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 12.5px;
    line-height: 1.55;
    white-space: pre-wrap;
  }

  .report-actions {
    justify-content: flex-end;
    flex-wrap: wrap;
  }

  .report-actions button {
    min-height: 36px;
  }
</style>
