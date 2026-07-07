// Engine client — typed wrapper around local /engine/* endpoints.
// Everything returns Promises; callers handle errors.

export interface ProfileDescriptor {
  id: string;
  display_name: string;
  path: string;
  source: 'bundled' | 'user';
  layer_height: string | null;
  printer_variant: string | null;
}

export interface RuleSummary {
  name: string;
  file_key: string;
  description: string;
  enabled: boolean;
  priority: number;
  match: Record<string, unknown>;
  overrides: Record<string, unknown>;
  source_path: string | null;
}

export interface DiffSection {
  title: string;
  summary: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  details: any[];
}

export interface DiffPayload {
  report: {
    source_filename: string;
    output_filename: string;
    reference_profile: string;
    identity_swaps: Array<{ key: string; from_value: unknown; to_value: unknown }>;
    gcode_swaps: Array<{ key: string; from_bytes: number; to_bytes: number }>;
    keys_dropped: Array<{ key: string; reason: string }>;
    values_clamped: Array<{ key: string; from_value: unknown; to_value: unknown; ceiling: unknown }>;
    rules_matched: Array<{ rule_name: string; priority: number; matched_on: Record<string, unknown>; overrides_applied: Record<string, unknown>; overrides_skipped?: Record<string, string> }>;
    slot_remaps: Array<{ from_index: number; to_index: number; filament_id: string | null }>;
    slice_artifacts_stripped: string[];
    advanced_overrides_applied: Record<string, unknown>;
    swap_instructions: SwapInstruction[];
    swap_pauses_skipped_painted: boolean;
  };
  sections: DiffSection[];
  counts: Record<string, number>;
}

export interface ConvertResult {
  job_id: string;
  download_name: string;
  diff: DiffPayload;
}

export interface PreviewPlate {
  id: number;
  origin: [number, number, number];
  size: [number, number];
  object_ids: string[];
}

export interface PreviewMesh {
  id: string;
  name: string;
  plate_id: number;
  extruder: number | null;
  color: string;
  vertices: number[];
  indices: number[];
  triangle_colors: string[];
}

export interface PreviewScene {
  printer_model: string;
  print_settings_id: string;
  bed: { min_x: number; min_y: number; width: number; depth: number };
  plates: PreviewPlate[];
  meshes: PreviewMesh[];
  stats: { objects: number; triangles: number; truncated: boolean; max_triangles: number };
  bounds: { min: [number, number, number]; max: [number, number, number] };
}

export interface JobParameter {
  key: string;
  value: unknown;
  default_value: unknown;
  has_u1_default: boolean;
  changed_from_default: boolean;
  value_type: string;
}

export interface JobParameterGroup {
  name: 'Quality' | 'Strength' | 'Speed' | 'Supports' | 'Multimaterial' | 'Others' | string;
  items: JobParameter[];
}

export interface JobParameters {
  job_id: string;
  can_rebuild: boolean;
  groups: JobParameterGroup[];
}

export interface WatchRecord {
  path: string;
  name: string;
  suffix: string;
  status: 'converted' | 'running' | 'queued' | 'failed' | 'unsupported' | string;
  message?: string;
  output_path?: string;
  profile?: string;
  converted_at?: number;
  thumbnail?: string;
  size?: number;
  mtime_ns?: number;
  updated_at?: number;
}

export interface WatchStatus {
  enabled: boolean;
  exclude_object: boolean;
  paths: string[];
  scanning: boolean;
  known_count: number;
  converted_count: number;
  failed_count: number;
  unsupported_count: number;
  ignored_count?: number;
  pending_count: number;
  recent: WatchRecord[];
}

export interface HistoryRecord {
  job_id: string | null;
  mode: 'manual' | 'auto' | string;
  status: string;
  source_filename: string;
  output_filename?: string;
  source_path?: string | null;
  output_path?: string | null;
  reference_profile?: string | null;
  created_at?: number;
  message?: string;
  thumbnail?: string | null;
  counts?: Record<string, number>;
}

export interface DiagnosticsSummary {
  app_root: string;
  data_root: string;
  config_file: string;
  profiles_dir: string;
  user_profiles_dir: string;
  rules_dir: string;
  tmp_dir: string;
  failed_tmp_dir: string;
  history_count: number;
  tmp: { files: number; bytes: number };
  failed_tmp: { files: number; bytes: number };
  failed_cases: Array<Record<string, unknown>>;
}

async function handle<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let detail = text || response.statusText;
    try {
      const body = JSON.parse(text);
      detail = body.detail ?? JSON.stringify(body);
    } catch { /* plain text error */ }
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export async function listProfiles(): Promise<ProfileDescriptor[]> {
  return handle(await fetch('/engine/reference-shelf'));
}

export async function importReferenceProfiles(files: File[]): Promise<{ imported: Array<{ name: string; printer_model: string; layer_height: string }>; errors: Array<{ name: string; error: string }>; profiles: ProfileDescriptor[] }> {
  const form = new FormData();
  for (const file of files) form.append('files', file);
  return handle(await fetch('/engine/reference-shelf/import', { method: 'POST', body: form }));
}

export async function deleteReferenceProfile(profileId: string): Promise<{ ok: boolean; profiles: ProfileDescriptor[] }> {
  return handle(await fetch(`/engine/reference-shelf/${encodeURIComponent(profileId)}`, { method: 'DELETE' }));
}

export interface FilamentInfo {
  index: number;
  settings_id: string | null;
  filament_type: string | null;
  vendor: string | null;
  colour: string | null;
}

export interface LintIssue {
  key: string;
  value: unknown;
  severity: 'error' | 'warning' | string;
  message: string;
}

export async function suggestProfile(
  file: File,
): Promise<{ profile_id: string; display_name: string; source_printer: string; already_converted: boolean; filaments: FilamentInfo[]; is_painted_model: boolean; is_multiplate: boolean; is_oversized: boolean; is_colour_mixed: boolean; source_slicer: string | null; lint_issues: LintIssue[]; matched_on: Record<string, unknown> }> {
  const form = new FormData();
  form.append('file', file);
  return handle(await fetch('/engine/intake/inspect', { method: 'POST', body: form }));
}

export async function listRules(): Promise<RuleSummary[]> {
  return handle(await fetch('/engine/spool-tuning'));
}

export async function getRuleYaml(name: string): Promise<{ name: string; yaml_text: string }> {
  return handle(await fetch(`/engine/spool-tuning/${encodeURIComponent(name)}`));
}

export async function putRule(name: string, yamlText: string): Promise<unknown> {
  return handle(
    await fetch(`/engine/spool-tuning/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ yaml_text: yamlText }),
    }),
  );
}

export async function createRule(yamlText: string): Promise<{ name: string }> {
  return handle(
    await fetch('/engine/spool-tuning', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ yaml_text: yamlText }),
    }),
  );
}

export async function deleteRule(name: string): Promise<unknown> {
  return handle(
    await fetch(`/engine/spool-tuning/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  );
}

export async function testMatch(file: File): Promise<unknown> {
  const form = new FormData();
  form.append('file', file);
  return handle(
    await fetch('/engine/spool-tuning/probe', { method: 'POST', body: form }),
  );
}

export interface SwapInstruction {
  z: number;
  toolhead: number;
  from_slot: number;
  to_slot: number;
  from_colour: string;
  to_colour: string;
  label: string;
}

export interface ConvertOptions {
  file: File;
  reference_profile: string;
  apply_rules: boolean;
  clamp_speeds: boolean;
  preserve_color_painting: boolean;
  advanced_overrides: string;
  slot_map?: Record<number, number>;
  insert_swap_pauses: boolean;
  exclude_object: boolean;
}

export async function convert(opts: ConvertOptions): Promise<ConvertResult> {
  const form = new FormData();
  form.append('file', opts.file);
  form.append('reference_profile', opts.reference_profile);
  form.append('apply_recipe_book', String(opts.apply_rules));
  form.append('clamp_speeds', String(opts.clamp_speeds));
  form.append('preserve_color_painting', String(opts.preserve_color_painting));
  form.append('advanced_overrides', opts.advanced_overrides);
  form.append('slot_map', JSON.stringify(opts.slot_map ?? {}));
  form.append('insert_swap_pauses', String(opts.insert_swap_pauses));
  form.append('exclude_object', String(opts.exclude_object));
  return handle(await fetch('/engine/jobs/u1', { method: 'POST', body: form }));
}

export async function listTargetShelfProfiles(): Promise<Array<{id: string; name: string}>> {
  return handle(await fetch('/engine/target-shelf'));
}

export async function getTargetShelfLocation(): Promise<{ path: string; exists: boolean; count: number; default_path: string }> {
  return handle(await fetch('/engine/target-shelf/location'));
}

export async function chooseTargetShelfLocation(): Promise<{ ok: boolean; path?: string; count?: number; cancelled?: boolean }> {
  return handle(
    await fetch('/engine/target-shelf/location/select', { method: 'POST' }),
  );
}

export async function convertTargetShelf(opts: { file: File; reference_profile: string; clamp_speeds: boolean; insert_swap_pauses: boolean }): Promise<ConvertResult> {
  const form = new FormData();
  form.append('file', opts.file);
  form.append('reference_profile', opts.reference_profile);
  form.append('clamp_speeds', String(opts.clamp_speeds));
  form.append('insert_swap_pauses', String(opts.insert_swap_pauses));
  return handle(await fetch('/engine/jobs/target-profile', { method: 'POST', body: form }));
}

export function downloadUrl(jobId: string): string {
  return `/engine/jobs/${encodeURIComponent(jobId)}/artifact`;
}

export async function getJob(jobId: string): Promise<ConvertResult> {
  return handle(await fetch(`/engine/jobs/${encodeURIComponent(jobId)}`));
}

export async function previewScene(jobId: string): Promise<PreviewScene> {
  return handle(await fetch(`/engine/jobs/${encodeURIComponent(jobId)}/scene`));
}

export async function previewSourceScene(jobId: string): Promise<PreviewScene> {
  return handle(await fetch(`/engine/jobs/${encodeURIComponent(jobId)}/source-scene`));
}

export async function jobParameters(jobId: string): Promise<JobParameters> {
  return handle(await fetch(`/engine/jobs/${encodeURIComponent(jobId)}/parameters`));
}

export async function previewUploadScene(file: File): Promise<PreviewScene> {
  const form = new FormData();
  form.append('file', file);
  return handle(await fetch('/engine/intake/scene', { method: 'POST', body: form }));
}

export async function saveAs(jobId: string): Promise<{ ok: boolean; path?: string; revealed?: boolean; cancelled?: boolean }> {
  return handle(
    await fetch(`/engine/jobs/${encodeURIComponent(jobId)}/save-dialog`, { method: 'POST' }),
  );
}

export async function rebuildJob(
  jobId: string,
  payload: { default_keys?: string[]; custom_overrides?: Record<string, unknown>; exclude_object?: boolean },
): Promise<ConvertResult> {
  return handle(
    await fetch(`/engine/jobs/${encodeURIComponent(jobId)}/rebuild`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  );
}

export async function folderWatchStatus(): Promise<WatchStatus> {
  return handle(await fetch('/engine/folder-watch'));
}

export async function chooseWatchFolders(): Promise<(WatchStatus & { ok: boolean; cancelled?: boolean })> {
  return handle(await fetch('/engine/folder-watch/select', { method: 'POST' }));
}

export async function setFolderWatchEnabled(enabled: boolean): Promise<WatchStatus> {
  return handle(
    await fetch('/engine/folder-watch/enabled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  );
}

export async function setFolderWatchExcludeObject(enabled: boolean): Promise<WatchStatus> {
  return handle(
    await fetch('/engine/folder-watch/exclude-object', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  );
}

export async function scanWatchFolders(): Promise<WatchStatus> {
  return handle(await fetch('/engine/folder-watch/scan', { method: 'POST' }));
}

export async function removeWatchFolder(path: string): Promise<WatchStatus> {
  return handle(
    await fetch('/engine/folder-watch/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  );
}

export async function retryWatchFile(path: string): Promise<WatchStatus> {
  return handle(
    await fetch('/engine/folder-watch/retry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  );
}

export async function ignoreWatchFile(path: string): Promise<WatchStatus> {
  return handle(
    await fetch('/engine/folder-watch/ignore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  );
}

export async function revealWatchPath(path: string): Promise<{ ok: boolean }> {
  return handle(
    await fetch('/engine/folder-watch/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  );
}

export async function listHistory(): Promise<{ records: HistoryRecord[] }> {
  return handle(await fetch('/engine/history'));
}

export async function revealHistoryPath(path: string): Promise<{ ok: boolean }> {
  return handle(
    await fetch('/engine/history/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  );
}

export async function diagnosticsSummary(): Promise<DiagnosticsSummary> {
  return handle(await fetch('/engine/diagnostics'));
}

export async function revealDataFolder(): Promise<{ ok: boolean }> {
  return handle(await fetch('/engine/diagnostics/reveal-data', { method: 'POST' }));
}

export async function clearHistory(): Promise<DiagnosticsSummary> {
  return handle(await fetch('/engine/diagnostics/clear-history', { method: 'POST' }));
}

export async function clearTempFiles(): Promise<DiagnosticsSummary> {
  return handle(await fetch('/engine/diagnostics/clear-temp', { method: 'POST' }));
}

export function supportPackUrl(): string {
  return '/engine/diagnostics/support-pack';
}
