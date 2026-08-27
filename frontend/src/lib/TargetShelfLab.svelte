<script lang="ts">
  import { onMount } from 'svelte';
  import IntakeDeck from './IntakeDeck.svelte';
  import ArtifactReview from './ArtifactReview.svelte';
  import {
    chooseTargetShelfLocation,
    getTargetShelfLocation,
    listTargetShelfProfiles,
    convertTargetShelf,
    suggestProfile,
    type ConvertResult,
  } from './engineClient';
  import { tr } from './i18n';

  type Phase = 'idle' | 'ready' | 'converting' | 'done' | 'error';

  let phase = $state<Phase>('idle');
  let file = $state<File | null>(null);
  let result = $state<ConvertResult | null>(null);
  let error = $state('');

  let printers = $state<Array<{id: string; name: string}>>([]);
  let profilesError = $state('');
  let profilesPath = $state('');
  let profilesCount = $state(0);
  let choosingFolder = $state(false);
  let selectedProfile = $state('');
  let clampSpeeds = $state(true);
  let insertSwapPauses = $state(false);

  let detectedFilaments = $state<Array<{ colour: string | null; settings_id: string | null; filament_type: string | null }>>([]);
  let analysing = $state(false);

  async function loadProfiles() {
    try {
      profilesError = '';
      const location = await getTargetShelfLocation();
      profilesPath = location.path;
      profilesCount = location.count;
      printers = await listTargetShelfProfiles();
      selectedProfile = printers.length > 0 ? printers[0].id : '';
    } catch (e: unknown) {
      profilesError = e instanceof Error ? e.message : String(e);
    }
  }

  onMount(async () => {
    await loadProfiles();
  });

  async function chooseProfileFolder() {
    choosingFolder = true;
    profilesError = '';
    try {
      const result = await chooseTargetShelfLocation();
      if (!result.cancelled) {
        await loadProfiles();
      }
    } catch (e: unknown) {
      profilesError = e instanceof Error ? e.message : String(e);
    } finally {
      choosingFolder = false;
    }
  }

  async function onFile(f: File) {
    file = f;
    phase = f ? 'ready' : 'idle';
    result = null;
    error = '';
    detectedFilaments = [];
    if (f) {
      analysing = true;
      try {
        const s = await suggestProfile(f);
        detectedFilaments = s.filaments;
        insertSwapPauses = s.filaments.length > 4;
      } catch { /* keep defaults */ } finally {
        analysing = false;
      }
    }
  }

  async function runConvert() {
    if (!file || !selectedProfile) return;
    phase = 'converting';
    error = '';
    try {
      result = await convertTargetShelf({ file, reference_profile: selectedProfile, clamp_speeds: clampSpeeds, insert_swap_pauses: insertSwapPauses });
      phase = 'done';
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : String(e);
      phase = 'error';
    }
  }

  function reset() {
    file = null; result = null; error = ''; phase = 'idle';
    detectedFilaments = [];
  }
</script>

{#if phase === 'done' && result}
  <ArtifactReview diff={result.diff} jobId={result.job_id} downloadName={result.download_name} onreset={reset} />

{:else}
  <div class="page-header tight">
    <div class="title-row">
      <h1>{$tr('Target Shelf')}</h1>
      <span class="beta-tag-token">BETA</span>
    </div>
    <p class="muted">
      {$tr('Retarget a Bambu/Orca project to another Bambu/Orca printer profile.')}
    </p>
  </div>

  <div class="profile-note card card-padded">
    <div>
      <h2>{$tr('What this needs')}</h2>
      <p>
        {@html $tr('This tool is for Bambu/Orca-to-Bambu/Orca profile remixes. It needs one or more reference <code>.3mf</code> projects exported from Bambu Studio or Orca for the target printer. It is not the Snapmaker conversion flow; use <strong>Snapmaker Lab</strong> for MakerWorld to Snapmaker U1.')}
      </p>
      <p class="folder-line">
        {$tr('Reading profiles from')} <code>{profilesPath || $tr('not set')}</code>
        <span class="count-badge">{profilesCount} {profilesCount === 1 ? $tr('file') : $tr('files')}</span>
      </p>
    </div>
    <button class="folder-btn" type="button" onclick={chooseProfileFolder} disabled={choosingFolder || phase === 'converting'}>
      {choosingFolder ? $tr('Choosing...') : $tr('Choose profile folder')}
    </button>
  </div>

  <div class="forge-grid" class:idle={phase === 'idle' && !analysing}>
    <div class="intake-column">
      <IntakeDeck onfile={onFile} bind:file disabled={phase === 'converting' || analysing} />

      {#if analysing}
        <div class="analysing-toast" role="status" aria-live="polite">
          <span class="spinner-sm" aria-hidden="true"></span>
          {$tr('Reading package notes...')}
        </div>
      {/if}

      {#if error}
        <div class="error-banner" role="alert">
          <strong>{$tr('Remix failed:')}</strong> {error}
          <button class="ghost" onclick={() => (phase = 'ready')}>{$tr('Retry')}</button>
        </div>
      {/if}

      {#if profilesError}
        <div class="error-banner" role="alert">{$tr('Could not load target shelves:')} {profilesError}</div>
      {/if}
    </div>

    {#if phase !== 'idle' && !analysing}
      <div class="control-column" class:converting={phase === 'converting'}>
        <div class="card card-padded console-panel-card">
          <label class="console-panel-label" for="target-profile">{$tr('Target shelf profile')}</label>
          <select id="target-profile" bind:value={selectedProfile} disabled={phase === 'converting'}>
            {#if printers.length === 0}
              <option value="">{$tr('No Bambu/Orca reference profiles found')}</option>
            {/if}
            {#each printers as p}
              <option value={p.id}>{p.name}</option>
            {/each}
          </select>

          <div class="toggle-row">
            <label>
              <input type="checkbox" bind:checked={clampSpeeds} disabled={phase === 'converting'} />
              {$tr('Keep motion inside target limits')}
            </label>
          </div>

          <div class="toggle-row">
            <label>
              <input type="checkbox" bind:checked={insertSwapPauses} disabled={phase === 'converting'} />
              {$tr('Add spool-swap stops')} {#if detectedFilaments.length > 4}<span class="auto-pick-chip">{$tr('auto')}</span>{/if}
            </label>
          </div>
        </div>

        {#if detectedFilaments.length > 0}
          <div class="card card-padded spool-strip">
            <span class="spool-strip-title">{$tr('Spools found in package')}</span>
            <div class="spool-strip-row">
              {#each detectedFilaments as f}
                <div
                  class="spool-dot"
                  style="background:{f.colour ?? '#888'}"
                  title="{f.settings_id ?? f.filament_type ?? 'Unknown'}"
                ></div>
              {/each}
            </div>
          </div>
        {/if}

        <button
          class="primary forge-action"
          onclick={runConvert}
          disabled={!file || !selectedProfile || phase === 'converting'}
          aria-live="polite"
        >
          {#if phase === 'converting'}
            <span class="spinner" aria-hidden="true"></span>
            {$tr('Mixing...')}
          {:else}
            {$tr('Build retargeted file')}
          {/if}
        </button>
      </div>
    {/if}
  </div>
{/if}

<style>
  .forge-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 28px;
    align-items: start;
  }
  .forge-grid.idle {
    grid-template-columns: 1fr;
    max-width: 480px;
    margin: 0 auto;
  }
  @media (max-width: 920px) { .forge-grid { grid-template-columns: 1fr; } }

  .analysing-toast {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--accent) 10%, var(--bg-elev));
    border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
    border-radius: var(--radius); font-size: 13px; color: var(--text-muted);
  }
  .spinner-sm {
    width: 13px; height: 13px; flex-shrink: 0;
    border: 2px solid color-mix(in srgb, var(--accent) 30%, transparent);
    border-top-color: var(--accent); border-radius: 50%;
    animation: spin 0.7s linear infinite; display: inline-block;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .intake-column { display: flex; flex-direction: column; gap: 16px; }
  .control-column { display: flex; flex-direction: column; gap: 16px; transition: opacity var(--duration); }
  .control-column.converting { opacity: 0.7; pointer-events: none; }

  .page-header { margin-bottom: 28px; }
  .page-header.tight { margin-bottom: 20px; }
  .title-row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .page-header h1 { margin: 0; font-size: clamp(30px, 5vw, 52px); line-height: .96; font-weight: 950; }
  .page-header p { margin: 0; font-size: 16px; max-width: 620px; }
  .title-row + p { margin-top: 10px; }

  .profile-note {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 18px;
    align-items: center;
    margin-bottom: 22px;
    border-radius: 22px;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--sun) 22%, transparent), transparent 50%),
      color-mix(in srgb, var(--bg-elev) 92%, transparent);
  }
  .profile-note h2 {
    margin: 0 0 8px;
    font-size: 18px;
    line-height: 1.05;
    font-weight: 950;
  }
  .profile-note p {
    margin: 0;
    color: var(--text-muted);
    font-size: 13.5px;
    line-height: 1.55;
  }
  .profile-note code {
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text);
    background: color-mix(in srgb, var(--bg-raised) 86%, transparent);
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 1px 6px;
    overflow-wrap: anywhere;
  }
  .folder-line {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-top: 10px !important;
  }
  .count-badge {
    display: inline-flex;
    align-items: center;
    min-height: 22px;
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--mint);
    color: var(--ink);
    font-size: 11px;
    font-weight: 900;
  }
  .folder-btn {
    white-space: nowrap;
    font-weight: 900;
    background: var(--ink);
    color: #fffdf8;
    border-color: var(--ink);
  }
  .folder-btn:hover:not(:disabled) {
    background: var(--accent);
    border-color: var(--accent);
    color: #fffdf8;
  }

  .console-panel-card {
    display: flex;
    flex-direction: column;
    gap: 14px;
    border-radius: 22px;
    background:
      linear-gradient(160deg, color-mix(in srgb, var(--sky) 18%, transparent), transparent 45%),
      var(--bg-elev);
  }
  .console-panel-label { font-size: 12px; font-weight: 900; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
  select { width: 100%; }
  .toggle-row label { display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; }

  .auto-pick-chip {
    font-size: 10px; font-weight: 850; padding: 1px 6px;
    background: var(--sun); color: var(--ink); border-radius: 999px;
  }

  .forge-action {
    width: 100%; padding: 12px 20px; font-size: 15px; font-weight: 900;
    display: flex; align-items: center; justify-content: center; gap: 10px;
  }

  .spinner {
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,0.35);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    display: inline-block;
  }

  @media (max-width: 760px) {
    .profile-note { grid-template-columns: 1fr; }
    .folder-btn { width: 100%; justify-content: center; }
  }
  @media (max-width: 560px) {
    .profile-note,
    .console-panel-card {
      border-radius: 16px;
      padding: 16px;
    }
    .spool-dot {
      width: 26px;
      height: 26px;
      border-radius: 8px;
    }
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .spool-strip { display: flex; flex-direction: column; gap: 8px; }
  .spool-strip-title { font-size: 12px; font-weight: 900; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
  .spool-strip-row { display: flex; flex-wrap: wrap; gap: 6px; }
  .spool-dot { width: 30px; height: 30px; border-radius: 10px; border: 2px solid #fffdf8; box-shadow: 0 2px 0 var(--border-strong); }

  .error-banner {
    display: flex; align-items: center; gap: 12px;
    padding: 12px 16px;
    background: color-mix(in srgb, var(--danger) 12%, var(--bg-elev));
    border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
    border-radius: var(--radius); color: var(--danger); font-size: 13px;
  }
</style>
