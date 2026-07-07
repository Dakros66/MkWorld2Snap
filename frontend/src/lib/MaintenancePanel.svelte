<script lang="ts">
  import { onMount } from 'svelte';
  import { Database, FolderOpen, RefreshCw, Trash2 } from 'lucide-svelte';
  import { clearHistory, clearTempFiles, diagnosticsSummary, revealDataFolder, supportPackUrl, type DiagnosticsSummary } from './engineClient';
  import { tr } from './i18n';

  let info = $state<DiagnosticsSummary | null>(null);
  let loading = $state(false);
  let error = $state('');
  let message = $state('');

  onMount(() => {
    void refresh();
  });

  async function refresh() {
    loading = true;
    error = '';
    try {
      info = await diagnosticsSummary();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  async function revealData() {
    error = '';
    try {
      await revealDataFolder();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function wipeHistory() {
    if (!confirm($tr('Clear conversion history? Generated 3MF files are not deleted.'))) return;
    error = '';
    try {
      info = await clearHistory();
      message = $tr('History cleared');
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function wipeTemp() {
    if (!confirm($tr('Clear temporary files? Active jobs are kept.'))) return;
    error = '';
    try {
      info = await clearTempFiles();
      message = $tr('Temporary files cleared');
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  function size(bytes: number | undefined): string {
    const value = bytes ?? 0;
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  function short(path: string | undefined): string {
    if (!path) return '';
    const parts = path.split('/');
    return parts.length > 4 ? `.../${parts.slice(-3).join('/')}` : path;
  }

  function downloadSupportPack() {
    const a = document.createElement('a');
    a.href = supportPackUrl();
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
</script>

<section class="maintenance card card-padded" aria-label={$tr('Maintenance and diagnostics')}>
  <div class="maintenance-head">
    <div>
      <span class="eyebrow">{$tr('Diagnostics')}</span>
      <h2>{$tr('Maintenance')}</h2>
      <p>{$tr('Inspect local data folders, retained failures, temporary files, and app storage without sending anything online.')}</p>
    </div>
    <div class="maintenance-actions">
      <button class="ghost" type="button" onclick={refresh} disabled={loading}>
        <RefreshCw size={16} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Refresh')}
      </button>
      <button class="ghost" type="button" onclick={revealData}>
        <FolderOpen size={16} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Reveal data folder')}
      </button>
      <button class="ghost" type="button" onclick={downloadSupportPack}>
        <Database size={16} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Export support pack')}
      </button>
    </div>
  </div>

  {#if error}
    <div class="maintenance-error" role="alert">{error}</div>
  {/if}
  {#if message}
    <div class="maintenance-message">{message}</div>
  {/if}

  {#if info}
    <div class="maintenance-grid">
      <div class="maintenance-tile">
        <Database size={18} strokeWidth={2.4} aria-hidden="true" />
        <span>{$tr('History records')}</span>
        <strong>{info.history_count}</strong>
      </div>
      <div class="maintenance-tile">
        <Database size={18} strokeWidth={2.4} aria-hidden="true" />
        <span>{$tr('Temporary storage')}</span>
        <strong>{info.tmp.files} · {size(info.tmp.bytes)}</strong>
      </div>
      <div class="maintenance-tile">
        <Database size={18} strokeWidth={2.4} aria-hidden="true" />
        <span>{$tr('Retained failures')}</span>
        <strong>{info.failed_cases.length}</strong>
      </div>
    </div>

    <div class="path-list">
      <div><span>{$tr('Data')}</span><strong title={info.data_root}>{short(info.data_root)}</strong></div>
      <div><span>{$tr('User profiles')}</span><strong title={info.user_profiles_dir}>{short(info.user_profiles_dir)}</strong></div>
      <div><span>{$tr('Recipes')}</span><strong title={info.rules_dir}>{short(info.rules_dir)}</strong></div>
      <div><span>{$tr('Temp')}</span><strong title={info.tmp_dir}>{short(info.tmp_dir)}</strong></div>
    </div>

    {#if info.failed_cases.length}
      <div class="failure-list">
        {#each info.failed_cases as failure}
          <article>
            <strong>{String(failure.filename ?? failure.job_id ?? $tr('Failed job'))}</strong>
            <span>{String(failure.detail ?? failure.error_type ?? '')}</span>
          </article>
        {/each}
      </div>
    {/if}

    <div class="danger-actions">
      <button class="ghost danger-button" type="button" onclick={wipeHistory}>
        <Trash2 size={15} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Clear history')}
      </button>
      <button class="ghost danger-button" type="button" onclick={wipeTemp}>
        <Trash2 size={15} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Clear temp files')}
      </button>
    </div>
  {/if}
</section>

<style>
  .maintenance {
    display: flex;
    flex-direction: column;
    gap: 14px;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--rose) 10%, transparent), transparent 46%),
      var(--bg-elev);
  }

  .maintenance-head,
  .maintenance-actions,
  .maintenance-grid,
  .danger-actions {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .maintenance-head {
    align-items: flex-start;
    justify-content: space-between;
  }

  .eyebrow {
    display: block;
    color: var(--text-muted);
    font-size: 10px;
    font-weight: 950;
    letter-spacing: .07em;
    text-transform: uppercase;
  }

  h2 {
    margin: 2px 0 4px;
    font-size: 22px;
    line-height: 1;
    font-weight: 950;
  }

  p {
    margin: 0;
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.4;
  }

  .maintenance-actions,
  .danger-actions,
  .maintenance-grid {
    flex-wrap: wrap;
  }

  .maintenance-tile {
    min-width: 170px;
    flex: 1 1 170px;
    display: grid;
    gap: 4px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: var(--bg-elev);
  }

  .maintenance-tile span {
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 900;
    text-transform: uppercase;
  }

  .maintenance-tile strong {
    color: var(--text);
    font-size: 16px;
    font-weight: 950;
  }

  .path-list {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 8px;
  }

  .path-list div,
  .failure-list article {
    display: grid;
    gap: 3px;
    padding: 9px 10px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: color-mix(in srgb, var(--bg-elev) 78%, transparent);
  }

  .path-list span,
  .failure-list span {
    color: var(--text-muted);
    font-size: 11px;
  }

  .path-list strong,
  .failure-list strong {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text);
    font-size: 12px;
  }

  .failure-list {
    display: grid;
    gap: 7px;
    max-height: 190px;
    overflow: auto;
  }

  .maintenance-error,
  .maintenance-message {
    padding: 9px 11px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 850;
  }

  .maintenance-error {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, var(--bg-elev));
  }

  .maintenance-message {
    color: var(--success);
    background: color-mix(in srgb, var(--success) 10%, var(--bg-elev));
  }

  .danger-button {
    color: var(--danger);
  }

  @media (max-width: 760px) {
    .maintenance-head {
      flex-direction: column;
    }
  }
</style>
