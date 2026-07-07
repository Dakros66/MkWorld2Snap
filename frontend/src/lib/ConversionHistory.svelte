<script lang="ts">
  import { onMount } from 'svelte';
  import { ExternalLink, FolderOpen, RefreshCw, Search } from 'lucide-svelte';
  import { listHistory, revealHistoryPath, type HistoryRecord } from './engineClient';
  import { tr } from './i18n';

  interface Props {
    onOpenJob?: (jobId: string) => void;
  }

  let { onOpenJob }: Props = $props();

  let records = $state<HistoryRecord[]>([]);
  let loading = $state(false);
  let error = $state('');
  let query = $state('');
  let filter = $state<'all' | 'manual' | 'auto' | 'failed'>('all');
  let actionStatus = $state('');

  const filtered = $derived(records.filter((record) => {
    const haystack = [
      record.source_filename,
      record.output_filename,
      record.reference_profile,
      record.message,
      record.source_path,
      record.output_path,
    ].join(' ').toLowerCase();
    const matchesQuery = !query.trim() || haystack.includes(query.trim().toLowerCase());
    const matchesFilter =
      filter === 'all'
      || (filter === 'failed' ? record.status === 'failed' : record.mode === filter);
    return matchesQuery && matchesFilter;
  }));

  onMount(() => {
    void refresh();
  });

  async function refresh() {
    loading = true;
    error = '';
    try {
      records = (await listHistory()).records;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  async function reveal(path: string | null | undefined) {
    if (!path) return;
    actionStatus = '';
    try {
      await revealHistoryPath(path);
    } catch (err) {
      actionStatus = err instanceof Error ? err.message : String(err);
    }
  }

  function openRecord(record: HistoryRecord) {
    if (record.job_id) onOpenJob?.(record.job_id);
  }

  function formatDate(stamp: number | undefined): string {
    if (!stamp) return '';
    return new Date(stamp * 1000).toLocaleString([], {
      year: '2-digit',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function statusText(record: HistoryRecord): string {
    if (record.status === 'converted') return $tr('ready');
    if (record.status === 'failed') return $tr('failed');
    if (record.status === 'unsupported') return $tr('detected');
    return record.status || $tr('unknown');
  }
</script>

<section class="history-panel card card-padded" aria-label={$tr('Conversion history')}>
  <div class="history-head">
    <div>
      <span class="eyebrow">{$tr('Control center')}</span>
      <h2>{$tr('Conversion history')}</h2>
      <p>{$tr('Review manual and automatic builds, open recent jobs, and reveal generated files.')}</p>
    </div>
    <button class="ghost refresh-button" type="button" onclick={refresh} disabled={loading}>
      <RefreshCw size={17} strokeWidth={2.4} aria-hidden="true" />
      {loading ? $tr('Loading...') : $tr('Refresh')}
    </button>
  </div>

  <div class="history-tools">
    <label class="history-search">
      <Search size={16} strokeWidth={2.4} aria-hidden="true" />
      <input bind:value={query} type="search" placeholder={$tr('Search files, profiles, or folders')} aria-label={$tr('Search history')} />
    </label>
    <div class="history-filter" role="group" aria-label={$tr('History filter')}>
      <button type="button" class:active={filter === 'all'} onclick={() => (filter = 'all')}>{$tr('All')}</button>
      <button type="button" class:active={filter === 'manual'} onclick={() => (filter = 'manual')}>{$tr('Manual')}</button>
      <button type="button" class:active={filter === 'auto'} onclick={() => (filter = 'auto')}>{$tr('Auto')}</button>
      <button type="button" class:active={filter === 'failed'} onclick={() => (filter = 'failed')}>{$tr('Failed')}</button>
    </div>
  </div>

  {#if error}
    <div class="history-error" role="alert">{error}</div>
  {/if}
  {#if actionStatus}
    <div class="history-error" role="alert">{actionStatus}</div>
  {/if}

  <div class="history-list">
    {#if filtered.length}
      {#each filtered as record, index (`${record.mode}-${record.job_id ?? record.source_path ?? index}`)}
        <article class="history-row" class:bad={record.status === 'failed'}>
          <div class="history-thumb" aria-hidden="true">
            {#if record.thumbnail}
              <img src={record.thumbnail} alt="" loading="lazy" />
            {:else}
              <span>{record.mode === 'auto' ? 'A' : 'M'}</span>
            {/if}
          </div>
          <div class="history-copy">
            <div class="history-title-line">
              <strong title={record.source_path ?? record.source_filename}>{record.source_filename}</strong>
              <span class="history-mode">{record.mode === 'auto' ? $tr('Automatic') : $tr('Manual')}</span>
              <span class="history-status">{statusText(record)}</span>
            </div>
            <div class="history-sub">
              {#if record.output_filename}
                <span>{record.output_filename}</span>
              {/if}
              {#if record.reference_profile}
                <span>{record.reference_profile}</span>
              {/if}
              {#if formatDate(record.created_at)}
                <span>{formatDate(record.created_at)}</span>
              {/if}
            </div>
            {#if record.message}
              <p>{record.message}</p>
            {/if}
          </div>
          <div class="history-actions">
            {#if record.job_id}
              <button class="ghost small-action" type="button" onclick={() => openRecord(record)}>
                <ExternalLink size={15} strokeWidth={2.4} aria-hidden="true" />
                {$tr('Open job')}
              </button>
            {/if}
            {#if record.output_path}
              <button class="ghost small-action" type="button" onclick={() => reveal(record.output_path)}>
                <FolderOpen size={15} strokeWidth={2.4} aria-hidden="true" />
                {$tr('Reveal')}
              </button>
            {/if}
          </div>
        </article>
      {/each}
    {:else}
      <div class="history-empty">
        {$tr('No conversion records match the current filter.')}
      </div>
    {/if}
  </div>
</section>

<style>
  .history-panel {
    display: flex;
    flex-direction: column;
    gap: 14px;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--mint) 20%, transparent), transparent 46%),
      linear-gradient(315deg, color-mix(in srgb, var(--sun) 18%, transparent), transparent 55%),
      var(--bg-elev);
  }

  .history-head,
  .history-tools,
  .history-title-line,
  .history-sub,
  .history-actions {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .history-head {
    justify-content: space-between;
    align-items: flex-start;
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
    font-size: 24px;
    line-height: 1;
    font-weight: 950;
  }

  p {
    margin: 0;
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.4;
  }

  .refresh-button { flex: 0 0 auto; }

  .history-tools {
    justify-content: space-between;
    flex-wrap: wrap;
  }

  .history-search {
    flex: 1 1 320px;
    min-width: 220px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: color-mix(in srgb, var(--bg-elev) 88%, transparent);
  }

  .history-search input {
    width: 100%;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
  }

  .history-filter {
    display: flex;
    gap: 6px;
    padding: 4px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: color-mix(in srgb, var(--bg) 72%, transparent);
  }

  .history-filter button {
    border: 0;
    border-radius: 10px;
    padding: 8px 10px;
    background: transparent;
    color: var(--text-muted);
    font-weight: 850;
    cursor: pointer;
  }

  .history-filter button.active {
    background: var(--ink);
    color: var(--bg-elev);
  }

  .history-list {
    display: grid;
    gap: 8px;
    max-height: min(58vh, 620px);
    overflow: auto;
    padding-right: 4px;
  }

  .history-row {
    display: grid;
    grid-template-columns: 58px minmax(0, 1fr) auto;
    gap: 12px;
    align-items: center;
    padding: 10px;
    border: 1px solid color-mix(in srgb, var(--mint) 35%, var(--border));
    border-radius: 16px;
    background: color-mix(in srgb, var(--bg-elev) 78%, transparent);
  }

  .history-row.bad {
    border-color: color-mix(in srgb, var(--danger) 45%, var(--border));
  }

  .history-thumb {
    width: 58px;
    height: 58px;
    border-radius: 14px;
    overflow: hidden;
    display: grid;
    place-items: center;
    background: color-mix(in srgb, var(--text) 9%, transparent);
    font-weight: 950;
  }

  .history-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .history-copy {
    min-width: 0;
  }

  .history-title-line {
    min-width: 0;
    flex-wrap: wrap;
  }

  .history-title-line strong {
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text);
  }

  .history-mode,
  .history-status {
    padding: 3px 7px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--mint) 24%, transparent);
    color: var(--text-muted);
    font-size: 10px;
    font-weight: 900;
    text-transform: uppercase;
  }

  .history-status { color: var(--accent); }

  .history-sub {
    flex-wrap: wrap;
    margin-top: 3px;
    color: var(--text-muted);
    font-size: 12px;
  }

  .history-sub span:not(:last-child)::after {
    content: "·";
    margin-left: 10px;
    color: var(--text-subtle);
  }

  .history-copy p {
    margin-top: 4px;
    font-size: 12px;
  }

  .history-actions {
    justify-content: flex-end;
    flex-wrap: wrap;
  }

  .small-action {
    min-height: 34px;
    padding: 7px 10px;
    font-size: 12px;
  }

  .history-error,
  .history-empty {
    padding: 10px 12px;
    border-radius: 12px;
    background: color-mix(in srgb, var(--danger) 10%, var(--bg-elev));
    color: var(--danger);
    font-size: 13px;
  }

  .history-empty {
    background: color-mix(in srgb, var(--text) 7%, transparent);
    color: var(--text-muted);
  }

  @media (max-width: 760px) {
    .history-row {
      grid-template-columns: 48px minmax(0, 1fr);
    }
    .history-actions {
      grid-column: 1 / -1;
      justify-content: flex-start;
    }
  }
</style>
