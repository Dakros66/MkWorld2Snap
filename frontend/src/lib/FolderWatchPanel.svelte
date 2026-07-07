<script module lang="ts">
  declare global {
    interface Window {
      pywebview?: {
        api?: {
          autostart_status?: () => Promise<{ supported: boolean; enabled: boolean; path?: string; error?: string }>;
          set_autostart?: (enabled: boolean) => Promise<{ supported: boolean; enabled: boolean; path?: string; error?: string }>;
        };
      };
    }
  }
</script>

<script lang="ts">
  import { onMount } from 'svelte';
  import {
    chooseWatchFolders,
    folderWatchStatus,
    ignoreWatchFile,
    removeWatchFolder,
    revealWatchPath,
    retryWatchFile,
    scanWatchFolders,
    setFolderWatchEnabled,
    setFolderWatchExcludeObject,
    type WatchRecord,
    type WatchStatus,
  } from './engineClient';
  import { EyeOff, FolderOpen, FolderPlus, Pause, Play, RefreshCw, RotateCcw, Search, Trash2, Zap } from 'lucide-svelte';
  import { tr } from './i18n';

  let status = $state<WatchStatus | null>(null);
  let autostart = $state<{ supported: boolean; enabled: boolean; path?: string; error?: string } | null>(null);
  let busy = $state(false);
  let autostartBusy = $state(false);
  let error = $state('');
  let thumbPreview = $state<{ src: string; top: number; left: number } | null>(null);
  let search = $state('');
  let filter = $state<'all' | 'converted' | 'failed' | 'unsupported' | 'ignored'>('all');
  let visibleLimit = $state(20);

  const recent = $derived((status?.recent ?? []).filter((item) => {
    const matchesFilter = filter === 'all' || item.status === filter;
    const haystack = `${item.name} ${item.path} ${item.profile ?? ''} ${item.message ?? ''}`.toLowerCase();
    return matchesFilter && (!search.trim() || haystack.includes(search.trim().toLowerCase()));
  }).slice(0, visibleLimit));

  onMount(() => {
    void refresh();
    void refreshAutostart();
    const timer = window.setInterval(() => {
      if (status?.enabled || status?.scanning) void refresh(false);
    }, 3000);
    return () => window.clearInterval(timer);
  });

  function desktopApi() {
    return window.pywebview?.api;
  }

  async function refresh(showBusy = true) {
    if (showBusy) busy = true;
    error = '';
    try {
      status = await folderWatchStatus();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      if (showBusy) busy = false;
    }
  }

  async function chooseFolders() {
    busy = true;
    error = '';
    try {
      const next = await chooseWatchFolders();
      if (!next.cancelled) status = next;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }

  async function toggle() {
    busy = true;
    error = '';
    try {
      status = await setFolderWatchEnabled(!(status?.enabled ?? false));
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }

  async function toggleExcludeObject() {
    busy = true;
    error = '';
    try {
      status = await setFolderWatchExcludeObject(!(status?.exclude_object ?? true));
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }

  async function scanNow() {
    busy = true;
    error = '';
    try {
      status = await scanWatchFolders();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }

  async function removePath(path: string) {
    busy = true;
    error = '';
    try {
      status = await removeWatchFolder(path);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }

  async function retryFile(path: string) {
    busy = true;
    error = '';
    try {
      status = await retryWatchFile(path);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }

  async function ignoreFile(path: string) {
    busy = true;
    error = '';
    try {
      status = await ignoreWatchFile(path);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }

  async function revealOutput(path: string | undefined) {
    if (!path) return;
    error = '';
    try {
      await revealWatchPath(path);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function refreshAutostart() {
    const api = desktopApi();
    if (!api?.autostart_status) {
      autostart = { supported: false, enabled: false };
      return;
    }
    try {
      autostart = await api.autostart_status();
    } catch (err) {
      autostart = { supported: false, enabled: false, error: err instanceof Error ? err.message : String(err) };
    }
  }

  async function toggleAutostart() {
    const api = desktopApi();
    if (!api?.set_autostart) return;
    autostartBusy = true;
    try {
      autostart = await api.set_autostart(!(autostart?.enabled ?? false));
    } catch (err) {
      autostart = { supported: false, enabled: false, error: err instanceof Error ? err.message : String(err) };
    } finally {
      autostartBusy = false;
    }
  }

  function shortPath(path: string): string {
    const parts = path.split('/');
    if (parts.length <= 3) return path;
    return `.../${parts.slice(-2).join('/')}`;
  }

  function statusLabel(record: WatchRecord): string {
    if (record.status === 'converted') return $tr('ready');
    if (record.status === 'running') return $tr('building');
    if (record.status === 'unsupported') return $tr('detected');
    if (record.status === 'failed') return $tr('needs review');
    if (record.status === 'ignored') return $tr('ignored');
    return record.status;
  }

  function convertedAt(record: WatchRecord): string {
    const stamp = record.converted_at ?? record.updated_at;
    if (!stamp) return '';
    return new Date(stamp * 1000).toLocaleString([], {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function showThumb(event: MouseEvent, src: string | undefined) {
    if (!src) return;
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    thumbPreview = {
      src,
      top: Math.max(12, Math.min(window.innerHeight - 220, rect.top - 82)),
      left: Math.max(12, Math.min(window.innerWidth - 236, rect.left - 194)),
    };
  }
</script>

<section class="watch-panel card card-padded" aria-label={$tr('Automatic folder conversion')}>
  <div class="watch-main">
    <div class="watch-title">
      <span class="watch-icon" aria-hidden="true"><Zap size={18} strokeWidth={2.5} /></span>
      <div>
        <h2>{$tr('Auto Output')}</h2>
        <p>
          {$tr('Watches selected folders and writes new builds into')} <code>OUTPUT_U1</code>.
          {$tr('3MF keeps its detected quality; STL uses 0.20 Standard because it has no print profile.')}
        </p>
      </div>
    </div>

    <div class="watch-actions">
      <button class="ghost watch-button" type="button" onclick={chooseFolders} disabled={busy}>
        <FolderPlus size={17} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Add folders')}
      </button>
      <button
        class="watch-button"
        class:active={status?.enabled}
        type="button"
        onclick={toggle}
        disabled={busy || !(status?.paths.length)}
      >
        {#if status?.enabled}
          <Pause size={17} strokeWidth={2.4} aria-hidden="true" />
          {$tr('Watching')}
        {:else}
          <Play size={17} strokeWidth={2.4} aria-hidden="true" />
          {$tr('Start')}
        {/if}
      </button>
      <button class="ghost icon-only" type="button" onclick={scanNow} disabled={busy || !(status?.paths.length)} title={$tr('Scan now')} aria-label={$tr('Scan now')}>
        <RefreshCw size={18} strokeWidth={2.4} aria-hidden="true" />
      </button>
    </div>
  </div>

  {#if error}
    <div class="watch-error" role="alert">{error}</div>
  {/if}

  {#if status?.paths.length}
    <div class="watch-paths" aria-label={$tr('Watched folders')}>
      {#each status.paths as path}
        <div class="watch-path" title={path}>
          <span>{shortPath(path)}</span>
          <button class="ghost tiny-icon" type="button" onclick={() => removePath(path)} aria-label={$tr('Remove folder')} disabled={busy}>
            <Trash2 size={14} strokeWidth={2.3} aria-hidden="true" />
          </button>
        </div>
      {/each}
    </div>
  {/if}

  {#if autostart?.supported}
    <div class="watch-option">
      <div>
        <strong>{$tr('Start with computer')}</strong>
        <span>{autostart.enabled ? $tr('MkWorld2Snap will open after login.') : $tr('Keep automatic conversion ready after login.')}</span>
      </div>
      <button class="watch-switch" class:on={autostart.enabled} type="button" onclick={toggleAutostart} disabled={autostartBusy} aria-pressed={autostart.enabled} aria-label={$tr('Toggle start with computer')}>
        <span></span>
      </button>
    </div>
  {/if}

  <div class="watch-option">
    <div>
      <strong>{$tr('Exclude objects')}</strong>
      <span>{$tr('Turns on Global > Others > Exclude objects for every automatic build.')}</span>
    </div>
    <button class="watch-switch" class:on={status?.exclude_object ?? true} type="button" onclick={toggleExcludeObject} disabled={busy} aria-pressed={status?.exclude_object ?? true} aria-label={$tr('Toggle object exclusion for automatic builds')}>
      <span></span>
    </button>
  </div>

  <div class="watch-stats">
    <span><strong>{status?.converted_count ?? 0}</strong> {$tr('built')}</span>
    <span><strong>{status?.pending_count ?? 0}</strong> {$tr('active')}</span>
    <span><strong>{status?.failed_count ?? 0}</strong> {$tr('failed')}</span>
    <span><strong>{status?.unsupported_count ?? 0}</strong> {$tr('detected only')}</span>
    <span><strong>{status?.ignored_count ?? 0}</strong> {$tr('ignored')}</span>
  </div>

  <div class="watch-tools">
    <label class="watch-search">
      <Search size={15} strokeWidth={2.4} aria-hidden="true" />
      <input type="search" bind:value={search} placeholder={$tr('Search automatic builds')} aria-label={$tr('Search automatic builds')} />
    </label>
    <div class="watch-filters" role="group" aria-label={$tr('Automatic build filter')}>
      <button type="button" class:active={filter === 'all'} onclick={() => (filter = 'all')}>{$tr('All')}</button>
      <button type="button" class:active={filter === 'converted'} onclick={() => (filter = 'converted')}>{$tr('Ready')}</button>
      <button type="button" class:active={filter === 'failed'} onclick={() => (filter = 'failed')}>{$tr('Failed')}</button>
      <button type="button" class:active={filter === 'unsupported'} onclick={() => (filter = 'unsupported')}>{$tr('Detected')}</button>
      <button type="button" class:active={filter === 'ignored'} onclick={() => (filter = 'ignored')}>{$tr('Ignored')}</button>
    </div>
  </div>

  {#if recent.length}
    <div class="watch-recent" aria-label={$tr('Recent automatic conversions')}>
      {#each recent as item}
        <div class="watch-row" class:bad={item.status === 'failed'} class:soft={item.status === 'unsupported' || item.status === 'ignored'}>
          <div class="watch-meta">
            <span class="watch-state">{statusLabel(item)}</span>
            {#if convertedAt(item)}
              <span class="watch-time">{convertedAt(item)}</span>
            {/if}
          </div>
          <div class="watch-copy">
            <span class="watch-file" title={item.path}>{item.name}</span>
            <span class="watch-note">{item.message ?? item.profile ?? ''}</span>
          </div>
          <div class="watch-row-actions">
            {#if item.status === 'failed'}
              <button class="ghost tiny-icon" type="button" onclick={() => retryFile(item.path)} title={$tr('Retry')} aria-label={$tr('Retry')}>
                <RotateCcw size={14} strokeWidth={2.4} aria-hidden="true" />
              </button>
            {/if}
            {#if item.status !== 'converted' && item.status !== 'running' && item.status !== 'ignored'}
              <button class="ghost tiny-icon" type="button" onclick={() => ignoreFile(item.path)} title={$tr('Ignore')} aria-label={$tr('Ignore')}>
                <EyeOff size={14} strokeWidth={2.4} aria-hidden="true" />
              </button>
            {/if}
            {#if item.status === 'ignored'}
              <button class="ghost tiny-icon" type="button" onclick={() => retryFile(item.path)} title={$tr('Retry')} aria-label={$tr('Retry')}>
                <RotateCcw size={14} strokeWidth={2.4} aria-hidden="true" />
              </button>
            {/if}
            {#if item.output_path}
              <button class="ghost tiny-icon" type="button" onclick={() => revealOutput(item.output_path)} title={$tr('Reveal')} aria-label={$tr('Reveal')}>
                <FolderOpen size={14} strokeWidth={2.4} aria-hidden="true" />
              </button>
            {/if}
          </div>
          <div class="watch-thumb" aria-hidden="true" onmouseenter={(event) => showThumb(event, item.thumbnail)} onmouseleave={() => (thumbPreview = null)}>
            {#if item.thumbnail}
              <img src={item.thumbnail} alt="" loading="lazy" />
            {:else}
              <span>{item.suffix.replace('.', '').toUpperCase()}</span>
            {/if}
          </div>
        </div>
      {/each}
    </div>
    {#if (status?.recent ?? []).length > visibleLimit}
      <button class="ghost more-button" type="button" onclick={() => (visibleLimit += 20)}>
        {$tr('Show more')}
      </button>
    {/if}
  {/if}

  {#if thumbPreview}
    <div class="thumb-popover" style="top:{thumbPreview.top}px; left:{thumbPreview.left}px">
      <img src={thumbPreview.src} alt="" />
    </div>
  {/if}
</section>

<style>
  .watch-panel {
    display: flex;
    flex-direction: column;
    gap: 14px;
    margin-bottom: 0;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--mint) 26%, transparent), transparent 44%),
      linear-gradient(315deg, color-mix(in srgb, var(--rose) 12%, transparent), transparent 52%),
      var(--bg-elev);
  }

  .watch-main {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
  }

  .watch-title {
    display: flex;
    gap: 12px;
    min-width: 0;
  }

  .watch-icon {
    width: 38px;
    height: 38px;
    border-radius: 12px;
    display: grid;
    place-items: center;
    flex: 0 0 auto;
    color: #fffdf8;
    background: var(--accent);
    box-shadow: 0 3px 0 var(--ink);
  }

  h2 {
    margin: 0;
    font-size: 18px;
    line-height: 1.1;
    font-weight: 950;
    color: var(--text);
  }

  p {
    margin: 4px 0 0;
    max-width: 760px;
    font-size: 13px;
    line-height: 1.45;
    color: var(--text-muted);
  }

  code {
    font-family: var(--font-mono);
    font-size: 11px;
    padding: 2px 5px;
    border-radius: 4px;
    background: var(--bg-raised);
    color: var(--text);
  }

  .watch-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 0 0 auto;
  }

  .watch-button,
  .icon-only,
  .tiny-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }

  .watch-button {
    min-height: 40px;
    padding: 9px 13px;
    font-size: 13px;
    font-weight: 900;
  }

  .watch-button.active {
    color: #fffdf8;
    background: var(--accent);
    border-color: var(--ink);
  }

  .icon-only {
    width: 42px;
    height: 40px;
    padding: 0;
  }

  .watch-paths {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .watch-option {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: color-mix(in srgb, var(--bg-raised) 72%, transparent);
  }

  .watch-option div {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .watch-option strong {
    font-size: 13px;
    font-weight: 950;
    color: var(--text);
  }

  .watch-option span {
    font-size: 12px;
    color: var(--text-muted);
  }

  .watch-switch {
    width: 48px;
    height: 28px;
    flex: 0 0 auto;
    padding: 3px;
    border-radius: 999px;
    border: 2px solid var(--border-strong);
    background: var(--bg-elev);
    box-shadow: none;
  }

  .watch-switch span {
    display: block;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--text-muted);
    transition: transform 0.16s ease, background 0.16s ease;
  }

  .watch-switch.on {
    background: var(--mint);
    border-color: var(--accent);
  }

  .watch-switch.on span {
    transform: translateX(18px);
    background: var(--accent);
  }

  .watch-path {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    padding: 4px 5px 4px 10px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: color-mix(in srgb, var(--bg-raised) 80%, transparent);
    font-size: 12px;
    font-weight: 800;
    color: var(--text-muted);
  }

  .tiny-icon {
    width: 24px;
    height: 24px;
    padding: 0;
    border-radius: 50%;
  }

  .watch-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .watch-stats span {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 9px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg-elev);
    font-size: 12px;
    color: var(--text-muted);
  }

  .watch-stats strong {
    color: var(--text);
    font-weight: 950;
  }

  .watch-tools {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
  }

  .watch-search {
    flex: 1 1 260px;
    min-width: 220px;
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 36px;
    padding: 7px 10px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: color-mix(in srgb, var(--bg-elev) 78%, transparent);
  }

  .watch-search input {
    width: 100%;
    border: 0;
    outline: 0;
    color: var(--text);
    background: transparent;
    font: inherit;
    font-size: 12px;
  }

  .watch-filters {
    display: flex;
    gap: 5px;
    padding: 3px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: color-mix(in srgb, var(--bg-raised) 72%, transparent);
  }

  .watch-filters button {
    border: 0;
    border-radius: 9px;
    padding: 7px 9px;
    background: transparent;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 900;
    cursor: pointer;
  }

  .watch-filters button.active {
    background: var(--ink);
    color: var(--bg-elev);
  }

  .watch-recent {
    display: grid;
    gap: 6px;
    max-height: 340px;
    overflow: auto;
    padding-right: 4px;
    overscroll-behavior: contain;
  }

  .watch-recent::-webkit-scrollbar {
    width: 8px;
  }

  .watch-recent::-webkit-scrollbar-thumb {
    background: color-mix(in srgb, var(--accent) 38%, transparent);
    border-radius: 999px;
  }

  .watch-row {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr) auto 54px;
    gap: 10px;
    align-items: center;
    min-height: 58px;
    padding: 6px 8px 6px 10px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--mint) 12%, var(--bg-elev));
    border: 1px solid color-mix(in srgb, var(--mint) 42%, var(--border));
    font-size: 12px;
  }

  .watch-row.bad {
    background: color-mix(in srgb, var(--danger) 8%, var(--bg-elev));
    border-color: color-mix(in srgb, var(--danger) 30%, var(--border));
  }

  .watch-row.soft {
    background: color-mix(in srgb, var(--sun) 15%, var(--bg-elev));
    border-color: color-mix(in srgb, var(--sun) 40%, var(--border));
  }

  .watch-meta,
  .watch-copy,
  .watch-row-actions {
    min-width: 0;
    display: flex;
  }

  .watch-meta,
  .watch-copy {
    flex-direction: column;
    gap: 4px;
  }

  .watch-row-actions {
    gap: 5px;
    justify-content: flex-end;
  }

  .more-button {
    align-self: center;
    min-height: 34px;
    font-size: 12px;
  }

  .watch-state {
    font-size: 10px;
    font-weight: 950;
    text-transform: uppercase;
    color: var(--accent);
  }

  .watch-time {
    font-size: 11px;
    font-weight: 850;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .watch-file {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 900;
    color: var(--text);
  }

  .watch-note {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-muted);
  }

  .watch-thumb {
    width: 54px;
    height: 46px;
    display: grid;
    place-items: center;
    border-radius: 9px;
    overflow: hidden;
    background: var(--bg-raised);
    border: 1px solid var(--border);
    position: relative;
    transition: box-shadow 0.16s ease, border-color 0.16s ease;
  }

  .watch-thumb:hover {
    border-color: var(--accent);
    box-shadow: 0 6px 18px color-mix(in srgb, var(--ink) 18%, transparent);
  }

  .watch-thumb img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
  }

  .watch-thumb span {
    font-size: 10px;
    font-weight: 950;
    color: var(--text-muted);
  }

  .thumb-popover {
    position: fixed;
    z-index: 2000;
    width: 210px;
    height: 190px;
    padding: 8px;
    border-radius: 18px;
    background: var(--bg-elev);
    border: 2px solid var(--accent);
    box-shadow: 0 22px 60px color-mix(in srgb, var(--ink) 32%, transparent);
    pointer-events: none;
  }

  .thumb-popover img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: contain;
    border-radius: 12px;
    background: var(--bg-raised);
  }

  .watch-error {
    padding: 9px 12px;
    border-radius: 10px;
    border: 1px solid color-mix(in srgb, var(--danger) 40%, var(--border));
    background: color-mix(in srgb, var(--danger) 9%, var(--bg-elev));
    color: var(--danger);
    font-size: 12px;
    font-weight: 800;
  }

  @media (max-width: 860px) {
    .watch-main {
      align-items: stretch;
      flex-direction: column;
    }

    .watch-actions {
      flex-wrap: wrap;
    }

    .watch-button {
      flex: 1 1 auto;
    }

    .watch-row {
      grid-template-columns: 76px minmax(0, 1fr) 46px;
      gap: 8px;
    }

    .watch-row-actions {
      grid-column: 2 / 3;
      grid-row: 2;
      justify-content: flex-start;
    }

    .watch-thumb {
      grid-column: 3;
      grid-row: 1 / span 2;
      width: 46px;
      height: 42px;
    }
  }
</style>
