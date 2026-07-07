<script lang="ts">
  import { onMount } from 'svelte';
  import IntakeDeck from './lib/IntakeDeck.svelte';
  import BuildConsole from './lib/BuildConsole.svelte';
  import ArtifactReview from './lib/ArtifactReview.svelte';
  import TargetShelfLab from './lib/TargetShelfLab.svelte';
  import SpoolTuningLab from './lib/SpoolTuningLab.svelte';
  import FieldManual from './lib/FieldManual.svelte';
  import ScenePreview from './lib/ScenePreview.svelte';
  import FolderWatchPanel from './lib/FolderWatchPanel.svelte';
  import ConversionHistory from './lib/ConversionHistory.svelte';
  import ProfileManager from './lib/ProfileManager.svelte';
  import MaintenancePanel from './lib/MaintenancePanel.svelte';
  import FilamentStudio from './lib/FilamentStudio.svelte';
  import { listProfiles, suggestProfile, convert, getJob, type ProfileDescriptor, type ConvertResult, type LintIssue } from './lib/engineClient';
  import HeadMapDialog from './lib/HeadMapDialog.svelte';
  import { Boxes, BookOpen, Files, FlaskConical, History, Moon, PackageOpen, Route, Settings, Sun } from 'lucide-svelte';
  import { locale, localeOptions, tr } from './lib/i18n';
  
  
  
  
  
  
  

  // ---- routing (hash-based, zero deps) ------------------------------------
  type AppRoute = 'convert' | 'blconvert' | 'rules' | 'history' | 'settings' | 'help';
  let route = $state<AppRoute>('convert');

  function navigate(r: AppRoute) {
    route = r;
    window.location.hash = r === 'convert' ? '' : r;
  }

  onMount(() => {
    const syncRoute = () => {
      const h = window.location.hash;
      if (h.startsWith('#job=')) {
        route = 'convert';
        void openJob(h.slice(5));
        return;
      }
      route = h === '#rules' ? 'rules' : h === '#help' ? 'help' : h === '#history' ? 'history' : h === '#settings' ? 'settings' : h === '#blconvert' ? 'blconvert' : 'convert';
    };
    syncRoute();
    window.addEventListener('hashchange', syncRoute);
    return () => window.removeEventListener('hashchange', syncRoute);
  });

  // ---- theme toggle --------------------------------------------------------
  let theme = $state<'dark' | 'light'>('light');

  function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('mkworld2snap-theme', theme); } catch { /* ok */ }
  }

  onMount(() => {
    try {
      const saved = localStorage.getItem('mkworld2snap-theme') as 'dark' | 'light' | null;
      if (saved) { theme = saved; document.documentElement.setAttribute('data-theme', theme); }
    } catch { /* ok */ }
  });

  // ---- profiles -----------------------------------------------------------
  let profiles = $state<ProfileDescriptor[]>([]);
  let profilesError = $state('');

  onMount(async () => {
    try {
      profiles = await listProfiles();
    } catch (e: unknown) {
      profilesError = e instanceof Error ? e.message : String(e);
    }
  });

  // ---- build state machine ------------------------------------------------
  type ConvertPhase = 'idle' | 'ready' | 'converting' | 'done' | 'error';
  let phase = $state<ConvertPhase>('idle');
  let analysing = $state(false);
  let analyseAttempted = $state(false);
  let file = $state<File | null>(null);
  let result = $state<ConvertResult | null>(null);
  let convertError = $state('');
  let analyseError = $state('');
  let batchInputEl: HTMLInputElement | undefined = $state();
  let batchBusy = $state(false);
  let batchError = $state('');
  let batchResults = $state<Array<{ name: string; status: 'done' | 'failed' | 'skipped'; message: string; jobId?: string }>>([]);

  // build controls
  let selectedProfile = $state('');
  let profileAutoMatched = $state(false);
  let alreadyConverted = $state(false);
  let isPaintedModel = $state(false);
  let isMultiplate = $state(false);
  let isOversized = $state(false);
  let isColourMixed = $state(false);
  let sourceSlicer = $state<string | null>(null);
  let lintIssues = $state<LintIssue[]>([]);
  let paintedSlotMap = $state<Record<number, number>>({});
  let detectedFilaments = $state<Array<{index:number;settings_id:string|null;filament_type:string|null;vendor:string|null;colour:string|null}>>([]);
  let applyRules = $state(true);
  let insertSwapPauses = $state(false);
  let excludeObjects = $state(true);
  let showSlotModal = $state(false);
  let advancedOverrides = $state('{}');

  const preflightItems = $derived([
    {
      label: $tr('Profile match'),
      value: profileAutoMatched
        ? profiles.find((p) => p.id === selectedProfile)?.display_name ?? selectedProfile
        : $tr('Waiting for inspection'),
      tone: profileAutoMatched ? 'ok' : 'warn',
    },
    {
      label: $tr('Machine state'),
      value: alreadyConverted ? $tr('Already marked for Snapmaker U1') : $tr('Will be retargeted to Snapmaker U1'),
      tone: alreadyConverted ? 'warn' : 'ok',
    },
    {
      label: $tr('Plate layout'),
      value: isMultiplate ? $tr('Multiple plates detected') : $tr('Single plate or compact layout'),
      tone: isMultiplate ? 'warn' : 'ok',
    },
    {
      label: $tr('Build area'),
      value: isOversized ? $tr('May exceed the 270 x 270 mm U1 bed') : $tr('No large-bed warning detected'),
      tone: isOversized ? 'danger' : 'ok',
    },
    {
      label: $tr('Filaments'),
      value: detectedFilaments.length
        ? $tr('{count} spool slots detected', { count: detectedFilaments.length })
        : $tr('No spool metadata found yet'),
      tone: detectedFilaments.length > 4 ? 'warn' : 'ok',
    },
    {
      label: $tr('3MF lint'),
      value: lintIssues.length ? $tr('{count} issue(s) found', { count: lintIssues.length }) : $tr('No known range issues found'),
      tone: lintIssues.length ? 'danger' : 'ok',
    },
  ]);

  // ---- conversion progress simulation ------------------------------------
  let convertProgress = $state(0);
  let _progressTimer: ReturnType<typeof setInterval> | null = null;

  function _startProgress(fileSize: number) {
    convertProgress = 0;
    const tau = fileSize < 1e6 ? 1500 : fileSize < 10e6 ? 4000 : fileSize < 50e6 ? 10000 : 18000;
    const start = Date.now();
    _progressTimer = setInterval(() => {
      const t = Date.now() - start;
      convertProgress = Math.min(89, 89 * (1 - Math.exp(-t / tau)));
    }, 80);
  }

  function _stopProgress() {
    if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null; }
  }

  const _progressStage = $derived(
    convertProgress < 12 ? $tr('Preparing the package...') :
    convertProgress < 28 ? $tr('Reading slicer settings...') :
    convertProgress < 46 ? $tr('Updating printer identity...') :
    convertProgress < 62 ? $tr('Removing incompatible settings...') :
    convertProgress < 76 ? $tr('Applying material recipes...') :
    convertProgress < 89 ? $tr('Writing the 3MF archive...') :
    $tr('Final checks...')
  );

  $effect(() => {
    if (profiles.length > 0 && !selectedProfile) {
      const def = profiles.find((p) => p.id.includes('0.20') && p.id.includes('standard') && !p.id.includes('palette'))
        ?? profiles[0];
      selectedProfile = def.id;
    }
    // If a file was dropped before profiles finished loading, run analysis now.
    if (profiles.length > 0 && file && !profileAutoMatched && !analyseAttempted && !analysing && phase === 'ready') {
      analyseFile(file);
    }
  });

  async function analyseFile(f: File) {
    analysing = true;
    analyseAttempted = true;
    try {
      const s = await suggestProfile(f);
      selectedProfile = s.profile_id;
      profileAutoMatched = true;
      alreadyConverted = s.already_converted;
      isPaintedModel = s.is_painted_model;
      isMultiplate = s.is_multiplate;
      isOversized = s.is_oversized;
      isColourMixed = s.is_colour_mixed;
      sourceSlicer = s.source_slicer ?? null;
      lintIssues = s.lint_issues ?? [];
      detectedFilaments = s.filaments;
      insertSwapPauses = s.filaments.length > 4 && !s.is_painted_model;
    } catch (err) {
      const message = err instanceof Error ? err.message.replace(/^\d+:\s*/, '') : '';
      analyseError = message || $tr('Could not read file - is this a valid .3mf file?');
      phase = 'error';
    } finally {
      analysing = false;
    }
  }

  async function onFile(f: File) {
    file = f;
    phase = f ? 'ready' : 'idle';
    result = null;
    convertError = '';
    analyseError = '';
    profileAutoMatched = false;
    analyseAttempted = false;
    alreadyConverted = false;
    isPaintedModel = false;
    isMultiplate = false;
    isOversized = false;
    sourceSlicer = null;
    lintIssues = [];
    paintedSlotMap = {};
    detectedFilaments = [];
    if (f && profiles.length > 0) {
      await analyseFile(f);
    }
  }

  function handleConvert() {
    if (isPaintedModel && detectedFilaments.length > 4) {
      showSlotModal = true;
    } else {
      runConvert({});
    }
  }

  async function runConvert(slotMap: Record<number, number>) {
    if (!file || !selectedProfile) return;
    showSlotModal = false;
    paintedSlotMap = slotMap;
    phase = 'converting';
    convertError = '';
    _startProgress(file.size);
    try {
      result = await convert({
        file,
        reference_profile: selectedProfile,
        apply_rules: applyRules,
        clamp_speeds: true,
        preserve_color_painting: true,
        insert_swap_pauses: insertSwapPauses,
        advanced_overrides: advancedOverrides,
        slot_map: Object.keys(slotMap).length > 0 ? slotMap : undefined,
        exclude_object: excludeObjects,
      });
      _stopProgress();
      convertProgress = 100;
      await new Promise(r => setTimeout(r, 350));
      phase = 'done';
      window.location.hash = `job=${result.job_id}`;
    } catch (e: unknown) {
      _stopProgress();
      convertProgress = 0;
      convertError = e instanceof Error ? e.message : String(e);
      phase = 'error';
    }
  }

  async function openJob(jobId: string) {
    if (!jobId || result?.job_id === jobId) return;
    phase = 'converting';
    convertError = '';
    try {
      result = await getJob(jobId);
      file = null;
      phase = 'done';
    } catch (e: unknown) {
      result = null;
      convertError = e instanceof Error ? e.message : String(e);
      phase = 'error';
    }
  }

  async function runBatch(files: FileList | null | undefined) {
    const candidates = Array.from(files ?? []).filter((entry) => entry.name.toLowerCase().endsWith('.3mf'));
    if (!candidates.length) return;
    batchBusy = true;
    batchError = '';
    batchResults = candidates.map((entry) => ({ name: entry.name, status: 'skipped', message: $tr('Queued') }));
    try {
      for (let index = 0; index < candidates.length; index += 1) {
        const entry = candidates[index];
        batchResults = batchResults.map((row, rowIndex) => rowIndex === index ? { ...row, status: 'skipped', message: $tr('Inspecting') } : row);
        try {
          const inspected = await suggestProfile(entry);
          if (inspected.already_converted) {
            batchResults = batchResults.map((row, rowIndex) => rowIndex === index ? { ...row, status: 'skipped', message: $tr('Already marked for Snapmaker U1') } : row);
            continue;
          }
          batchResults = batchResults.map((row, rowIndex) => rowIndex === index ? { ...row, status: 'skipped', message: $tr('Building package') } : row);
          const built = await convert({
            file: entry,
            reference_profile: inspected.profile_id,
            apply_rules: applyRules,
            clamp_speeds: true,
            preserve_color_painting: true,
            advanced_overrides: advancedOverrides,
            insert_swap_pauses: inspected.filaments.length > 4 && !inspected.is_painted_model,
            exclude_object: excludeObjects,
          });
          batchResults = batchResults.map((row, rowIndex) => rowIndex === index ? {
            ...row,
            status: 'done',
            message: built.download_name,
            jobId: built.job_id,
          } : row);
        } catch (err) {
          batchResults = batchResults.map((row, rowIndex) => rowIndex === index ? {
            ...row,
            status: 'failed',
            message: err instanceof Error ? err.message : String(err),
          } : row);
        }
      }
    } catch (err) {
      batchError = err instanceof Error ? err.message : String(err);
    } finally {
      batchBusy = false;
      if (batchInputEl) batchInputEl.value = '';
    }
  }

  function reset() {
    if (window.location.hash.startsWith('#job=')) {
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    file = null;
    result = null;
    convertError = '';
    analyseError = '';
    phase = 'idle';
    detectedFilaments = [];
    profileAutoMatched = false;
    analyseAttempted = false;
    alreadyConverted = false;
    isPaintedModel = false;
    isMultiplate = false;
    isOversized = false;
    sourceSlicer = null;
    lintIssues = [];
    paintedSlotMap = {};
    excludeObjects = true;
  }
</script>

<div class="layout">
  <!-- ---- nav ------------------------------------------------------------ -->
  <header class="nav">
    <div class="wordmark-wrap">
      <button class="wordmark ghost" onclick={() => navigate('convert')} aria-label={$tr('Home')}>
        <span class="brand-mark" aria-hidden="true">
          <span></span><span></span><span></span>
        </span>
        <span class="brand-copy">
          <span class="brand-name">MkWorld2Snap</span>
          <span class="brand-tag">{$tr('print file workshop')}</span>
          <span class="brand-version">v1.0.0</span>
        </span>
      </button>
      <div class="wordmark-tooltip" role="tooltip">
        {$tr('A local desktop workbench for turning downloaded .3mf projects into Snapmaker-ready files.')}
      </div>
    </div>

    <nav aria-label={$tr('Main navigation')}>
      <button
        class="nav-link"
        class:active={route === 'convert'}
        onclick={() => navigate('convert')}
      >
        <span class="nav-label-full">{$tr('Snapmaker Lab')}</span>
        <PackageOpen size={16} strokeWidth={2.4} aria-hidden="true" />
        <span class="nav-label-short">Snap</span>
        <span class="nav-badge beta">READY</span>
      </button>
      <button
        class="nav-link"
        class:active={route === 'blconvert'}
        onclick={() => navigate('blconvert')}
      >
        <span class="nav-label-full">{$tr('Target Shelf')}</span>
        <Boxes size={16} strokeWidth={2.4} aria-hidden="true" />
        <span class="nav-label-short">{$tr('Profiles')}</span>
        <span class="nav-badge beta">BETA</span>
      </button>
      <button
        class="nav-link"
        class:active={route === 'rules'}
        onclick={() => navigate('rules')}
      >
        <span class="nav-label-full">{$tr('Spool Tuning Lab')}</span>
        <FlaskConical size={16} strokeWidth={2.4} aria-hidden="true" />
        <span class="nav-label-short">{$tr('Recipes')}</span>
        <span class="nav-badge beta">BETA</span>
      </button>
      <button
        class="nav-link"
        class:active={route === 'history'}
        onclick={() => navigate('history')}
      ><History size={16} strokeWidth={2.4} aria-hidden="true" />{$tr('History')}</button>
      <button
        class="nav-link"
        class:active={route === 'settings'}
        onclick={() => navigate('settings')}
      ><Settings size={16} strokeWidth={2.4} aria-hidden="true" />{$tr('Settings')}</button>
      <button
        class="nav-link"
        class:active={route === 'help'}
        onclick={() => navigate('help')}
      ><BookOpen size={16} strokeWidth={2.4} aria-hidden="true" />{$tr('Guide')}</button>
    </nav>

    <div class="nav-right">
      <div class="release-links" aria-label="Version and source">
        <a
          class="repo-link"
          href="https://github.com/Dakros66/MkWorld2Snap"
          target="_blank"
          rel="noreferrer"
          title="Dakros66/MkWorld2Snap"
        >GitHub</a>
      </div>
      <label class="language-picker" title={$tr('Language')}>
        <span class="sr-only">{$tr('Language')}</span>
        <select bind:value={$locale} aria-label={$tr('Language')}>
          {#each localeOptions as option}
            <option value={option.code}>{option.label}</option>
          {/each}
        </select>
      </label>
      <span class="desktop-tag-token" title={$tr('Runs locally on this computer')}>{$tr('Offline')}</span>
      <button
        class="ghost icon-btn"
        onclick={toggleTheme}
        aria-label={theme === 'dark' ? $tr('Switch to light mode') : $tr('Switch to dark mode')}
        title={theme === 'dark' ? $tr('Light mode') : $tr('Dark mode')}
      >
        {#if theme === 'dark'}
          <Sun size={18} strokeWidth={2.3} aria-hidden="true" />
        {:else}
          <Moon size={18} strokeWidth={2.3} aria-hidden="true" />
        {/if}
      </button>
    </div>
  </header>

  <!-- ---- main ----------------------------------------------------------- -->
  <main>
    {#if route === 'blconvert'}
      <TargetShelfLab />

    {:else if route === 'help'}
      <div class="page-header">
          <h1>{$tr('Workshop Guide')}</h1>
        <p class="muted">{$tr('Formats, colour handling, profiles, safety checks, and what to review before printing.')}</p>
      </div>
      <FieldManual onNavigate={navigate} />

    {:else if route === 'rules'}
      <div class="page-header">
        <div class="title-row">
          <h1>{$tr('Spool Tuning Lab')}</h1>
          <span class="beta-tag-token">BETA</span>
        </div>
        <p class="muted">
          {$tr('Create guarded YAML recipes that react to matching spool metadata while keeping global process tweaks separate from per-slot material values.')}
        </p>
      </div>
      <SpoolTuningLab />

    {:else if route === 'history'}
      <div class="page-header">
        <h1>{$tr('Control center')}</h1>
        <p class="muted">{$tr('Browse completed work, reopen recent manual builds, and find generated OUTPUT_U1 files quickly.')}</p>
      </div>
      <ConversionHistory onOpenJob={(jobId) => {
        window.location.hash = `job=${jobId}`;
        void openJob(jobId);
      }} />

    {:else if route === 'settings'}
      <div class="page-header">
        <h1>{$tr('Settings')}</h1>
        <p class="muted">{$tr('Manage U1 reference profiles, local storage, diagnostics, and maintenance tools.')}</p>
      </div>
      <ProfileManager />
      <MaintenancePanel />

    {:else}
      <!-- convert flow -->
      {#if phase === 'done' && result}
        <ArtifactReview
          diff={result.diff}
          jobId={result.job_id}
          downloadName={result.download_name}
          onreset={reset}
        />

      {:else}
        <div class="page-header tight">
          <h1>{$tr('Drop a MakerWorld 3MF. Pop out a Snapmaker-ready project.')}</h1>
          <p class="muted">
            {$tr('The local engine swaps machine identity, cleans incompatible slicer data, keeps useful print intent, and prepares a file for Snapmaker Orca.')}
          </p>
        </div>

        <div class="forge-grid" class:idle={phase === 'idle' && !analysing}>
          <!-- left: upload + status -->
          <div class="intake-column">
            <IntakeDeck
              onfile={onFile}
              bind:file
              disabled={phase === 'converting' || analysing}
            />

            <input
              bind:this={batchInputEl}
              type="file"
              multiple
              accept=".3mf"
              style="display:none"
              onchange={(event) => runBatch(event.currentTarget.files)}
            />
            <div class="batch-card card card-padded">
              <div>
                <strong>{$tr('Batch manual conversion')}</strong>
                <span>{$tr('Pick several 3MF files and build them with their detected U1 quality profile.')}</span>
              </div>
              <button class="ghost" type="button" onclick={() => batchInputEl?.click()} disabled={batchBusy || phase === 'converting'}>
                <Files size={16} strokeWidth={2.4} aria-hidden="true" />
                {batchBusy ? $tr('Building package') : $tr('Choose 3MF files')}
              </button>
            </div>

            {#if batchError}
              <div class="error-banner" role="alert">{batchError}</div>
            {/if}

            {#if batchResults.length}
              <div class="batch-results card card-padded" aria-label={$tr('Batch results')}>
                {#each batchResults as item}
                  <div class="batch-row" class:done={item.status === 'done'} class:failed={item.status === 'failed'}>
                    <span>{item.name}</span>
                    <strong>{item.message}</strong>
                    {#if item.jobId}
                      <button class="ghost tiny-batch" type="button" onclick={() => {
                        window.location.hash = `job=${item.jobId}`;
                        void openJob(item.jobId ?? '');
                      }}>{$tr('Open job')}</button>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}

            {#if file}
              {#key `${file.name}-${file.size}-${file.lastModified}`}
                <ScenePreview
                  {file}
                  compact
                  eyebrow={$tr('3D intake preview')}
                  heading={$tr('Loaded layout')}
                />
              {/key}
            {/if}

            {#if file && phase !== 'error'}
              <section class="preflight-card card card-padded" aria-label={$tr('Preflight Doctor')}>
                <div class="preflight-head">
                  <span>{$tr('Preflight Doctor')}</span>
                  <strong>{analysing ? $tr('Inspecting') : $tr('Ready')}</strong>
                </div>
                <div class="preflight-grid">
                  {#each preflightItems as item}
                    <div class="preflight-item" class:warn={item.tone === 'warn'} class:danger={item.tone === 'danger'}>
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                    </div>
                  {/each}
                </div>
                {#if lintIssues.length}
                  <div class="lint-list" role="alert">
                    {#each lintIssues.slice(0, 5) as issue}
                      <span><strong>{issue.key}</strong>: {String(issue.value)} · {issue.message}</span>
                    {/each}
                  </div>
                {/if}
              </section>
            {/if}

            {#if analysing}
              <div class="status-toast" role="status" aria-live="polite">
                <span class="spinner-sm" aria-hidden="true"></span>
                {$tr('Inspecting the 3MF package...')}
              </div>
            {/if}

            {#if alreadyConverted}
              <div class="warn-banner" role="alert">
                <strong>{$tr('Already set for Snapmaker:')}</strong> {$tr('this project is already tagged for U1. Use the source download if you need a fresh pass.')}
              </div>
            {/if}

            {#if isPaintedModel && detectedFilaments.length > 4}
              <div class="warn-banner" role="alert">
                <strong>{$tr('Paint map detected:')}</strong> {$tr('colour decisions will be made by Snapmaker Orca when you slice. Manual pause notes cannot be inserted ahead of time.')}
              </div>
            {/if}

            {#if isMultiplate}
              <div class="warn-banner" role="alert">
                <strong>{$tr('Multi-plate layout:')}</strong> {$tr('review placement after import. Use Orca arrange tools before slicing.')}
              </div>
            {/if}

            {#if isOversized}
              <div class="warn-banner" role="alert">
                <strong>{$tr('Large-bed source:')}</strong> {$tr('this project may exceed the 270 x 270 mm U1 area. Check placement before slicing.')}
              </div>
            {/if}

            {#if isColourMixed}
              <div class="warn-banner" role="alert">
                <strong>{$tr('Colour blending found:')}</strong> {$tr('blended source colours are kept as separate slots. Inspect the result carefully in Orca.')}
              </div>
            {/if}

            {#if sourceSlicer}
              <div class="warn-banner" role="alert">
                <strong>{$tr('Experimental source:')}</strong> {$tr('detected')} <em>{sourceSlicer}</em>. {$tr('The engine matched a profile from layer height; verify settings in Orca.')}
              </div>
            {/if}

            {#if phase === 'error' && analyseError}
              <div class="error-banner" role="alert">
                <strong>{$tr('Could not open package:')}</strong> {analyseError}
              </div>
            {:else if phase === 'error' && convertError}
              <div class="error-banner" role="alert">
                <strong>{$tr('Build failed:')}</strong> {convertError}
                <button class="ghost" onclick={() => (phase = 'ready')}>{$tr('Retry')}</button>
              </div>
            {/if}

            {#if profilesError}
              <div class="error-banner" role="alert">
                {$tr('Could not load the profile shelf:')} {profilesError}
              </div>
            {/if}
          </div>

          <!-- right: controls + convert button (only show when a file is picked and analysed) -->
          {#if phase !== 'idle' && !analysing}
            <div class="control-column">
              <button
                class="primary forge-action forge-action-top"
                onclick={handleConvert}
                disabled={!file || !selectedProfile || phase === 'converting' || analysing || alreadyConverted}
              >
                <Route size={18} strokeWidth={2.4} aria-hidden="true" />
                {$tr('Build Snapmaker file')}
              </button>

              <BuildConsole
                {profiles}
                bind:selectedProfile
                bind:applyRules
                bind:insertSwapPauses
                bind:excludeObjects
                bind:advancedOverrides
                autoMatched={profileAutoMatched}
                disabled={phase === 'converting' || analysing}
              />

              {#if detectedFilaments.length > 0}
                <FilamentStudio
                  filaments={detectedFilaments}
                  painted={isPaintedModel}
                  {insertSwapPauses}
                  onTogglePauses={(value) => (insertSwapPauses = value)}
                />
                <div class="spool-strip card card-padded">
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
                onclick={handleConvert}
                disabled={!file || !selectedProfile || phase === 'converting' || analysing || alreadyConverted}
              >
                <Route size={18} strokeWidth={2.4} aria-hidden="true" />
                {$tr('Build Snapmaker file')}
              </button>
            </div>
          {/if}
        </div>

        {#if phase === 'idle' && !analysing}
          <div class="auto-output-wide">
            <FolderWatchPanel />
          </div>
        {/if}
      {/if}

      {#if phase === 'idle' && !analysing}
        <div class="capability-strip" aria-label={$tr('What MkWorld2Snap checks before saving')}>
          <div class="capability-tile">
            <span class="capability-mark">3MF</span>
            <strong>{$tr('Project-first input')}</strong>
            <span>{$tr('Editable packages only; stale sliced caches are rejected or stripped.')}</span>
          </div>
          <div class="capability-tile">
            <span class="capability-mark">U1</span>
            <strong>{$tr('Local rebuild')}</strong>
            <span>{$tr('Machine identity, startup scripts and filament assignments are rebuilt locally on this computer.')}</span>
          </div>
          <div class="capability-tile">
            <span class="capability-mark">QA</span>
            <strong>{$tr('Review before slicing')}</strong>
            <span>{$tr('The report shows every important change before you save the new file.')}</span>
          </div>
        </div>
      {/if}
    {/if}
  </main>

  <footer>
    <div class="footer-links">
      <span class="subtle">{$tr('MkWorld2Snap desktop workshop')}</span>
      <span class="subtle">·</span>
      <a href="#rules" onclick={() => navigate('rules')}>{$tr('Spool Lab')}</a>
      <span class="subtle">·</span>
      <a href="#blconvert" onclick={() => navigate('blconvert')}>{$tr('Target Shelf')}</a>
      <span class="subtle">·</span>
      <a href="#help" onclick={() => navigate('help')}>{$tr('Guide')}</a>
      <span class="subtle">·</span>
      <a href="/privacy.html">{$tr('Privacy')}</a>
    </div>
  </footer>
</div>

{#if phase === 'converting'}
  <div class="build-veil" role="status" aria-live="polite">
    <div class="build-veil-card">
      <div class="build-veil-head">
        <span class="build-veil-title">{$tr('Building package')}</span>
        <span class="build-veil-percent">{Math.round(convertProgress)}%</span>
      </div>
      <span class="build-veil-file">{file?.name ?? ''}</span>
      <div class="build-meter-track">
        <div class="build-meter-fill" style="width:{convertProgress}%"></div>
      </div>
      <span class="build-veil-stage">{_progressStage}</span>
    </div>
  </div>
{/if}

{#if showSlotModal}
  <HeadMapDialog
    filaments={detectedFilaments}
    onconfirm={(map) => runConvert(map)}
    onskip={() => runConvert({})}
  />
{/if}

<style>
  .layout {
    min-height: 100vh;
    width: 100%;
    max-width: 100vw;
    display: grid;
    grid-template-rows: auto 1fr auto;
    position: relative;
    overflow-x: clip;
  }
  .layout::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    background-image:
      linear-gradient(color-mix(in srgb, var(--text) 8%, transparent) 1px, transparent 1px),
      linear-gradient(90deg, color-mix(in srgb, var(--text) 8%, transparent) 1px, transparent 1px);
    background-size: 34px 34px;
    mask-image: linear-gradient(to bottom, rgba(0,0,0,.3), transparent 62%);
  }

  .preflight-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--mint) 16%, transparent), transparent 52%),
      var(--bg-elev);
  }

  .preflight-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 950;
    letter-spacing: .06em;
    text-transform: uppercase;
  }

  .preflight-head strong {
    color: var(--accent);
  }

  .preflight-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 8px;
  }

  .preflight-item {
    min-height: 58px;
    padding: 9px 10px;
    border-radius: 12px;
    border: 1px solid color-mix(in srgb, var(--mint) 38%, var(--border));
    background: color-mix(in srgb, var(--mint) 10%, var(--bg-elev));
  }

  .preflight-item.warn {
    border-color: color-mix(in srgb, var(--warn) 45%, var(--border));
    background: color-mix(in srgb, var(--warn) 10%, var(--bg-elev));
  }

  .preflight-item.danger {
    border-color: color-mix(in srgb, var(--danger) 45%, var(--border));
    background: color-mix(in srgb, var(--danger) 8%, var(--bg-elev));
  }

  .preflight-item span,
  .preflight-item strong {
    display: block;
  }

  .preflight-item span {
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 900;
    text-transform: uppercase;
  }

  .preflight-item strong {
    margin-top: 4px;
    color: var(--text);
    font-size: 12px;
    line-height: 1.25;
  }

  .lint-list {
    display: grid;
    gap: 5px;
    padding: 9px 10px;
    border-radius: 12px;
    border: 1px solid color-mix(in srgb, var(--danger) 38%, var(--border));
    background: color-mix(in srgb, var(--danger) 8%, var(--bg-elev));
    color: var(--danger);
    font-size: 12px;
  }

  .lint-list span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .batch-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    background: color-mix(in srgb, var(--sun) 10%, var(--bg-elev));
  }

  .batch-card div {
    display: grid;
    gap: 3px;
    min-width: 0;
  }

  .batch-card strong {
    color: var(--text);
    font-weight: 950;
  }

  .batch-card span {
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.35;
  }

  .batch-results {
    display: grid;
    gap: 6px;
    max-height: 220px;
    overflow: auto;
    background: color-mix(in srgb, var(--mint) 8%, var(--bg-elev));
  }

  .batch-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
    gap: 8px;
    align-items: center;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--bg-elev);
    font-size: 12px;
  }

  .batch-row.done {
    border-color: color-mix(in srgb, var(--success) 40%, var(--border));
  }

  .batch-row.failed {
    border-color: color-mix(in srgb, var(--danger) 42%, var(--border));
  }

  .batch-row span,
  .batch-row strong {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .batch-row strong {
    color: var(--text-muted);
    font-weight: 850;
  }

  .tiny-batch {
    min-height: 28px;
    padding: 5px 8px;
    font-size: 11px;
  }

  /* ---- nav ---- */
  .nav {
    position: sticky;
    top: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 4px;
    width: 100%;
    max-width: 100vw;
    padding: 10px 24px;
    min-height: 70px;
    border-bottom: 2px solid var(--border-strong);
    background: color-mix(in srgb, var(--bg-elev) 86%, transparent);
    backdrop-filter: blur(14px);
    box-shadow: 0 8px 0 color-mix(in srgb, var(--mint) 30%, transparent);
  }
  .wordmark-wrap { position: relative; margin-right: 8px; }
  .wordmark-wrap:hover .wordmark-tooltip { opacity: 1; pointer-events: auto; }

  .wordmark-tooltip {
    position: absolute;
    top: calc(100% + 10px);
    left: 0;
    width: 290px;
    background: var(--bg-elev);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 14px;
    font-size: 12.5px;
    line-height: 1.55;
    color: var(--text-muted);
    box-shadow: var(--shadow);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.15s;
    z-index: 200;
  }

  .wordmark {
    display: flex;
    align-items: center;
    gap: 12px;
    white-space: nowrap;
    font-weight: 900;
    font-size: 16px;
    color: var(--text);
    background: transparent;
    border: none;
    padding: 6px 8px;
    min-width: 0;
  }
  .wordmark:hover { background: transparent; }
  .brand-mark {
    width: 38px;
    height: 38px;
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    grid-template-rows: repeat(2, 1fr);
    gap: 3px;
    padding: 6px;
    border-radius: 12px;
    background: var(--ink);
    box-shadow: 0 4px 0 var(--sun);
    transform: rotate(-3deg);
  }
  .brand-mark span { border-radius: 4px; background: var(--sun); }
  .brand-mark span:nth-child(2) { background: var(--mint); }
  .brand-mark span:nth-child(3) { grid-column: span 2; background: var(--rose); }
  .brand-copy { display: flex; flex-direction: column; line-height: 1.05; align-items: flex-start; }
  .brand-name { font-size: 16px; font-weight: 950; }
  .brand-tag { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .08em; font-weight: 900; }
  .brand-version {
    margin-top: 2px;
    color: var(--text-subtle);
    font-size: 9px;
    font-weight: 900;
    letter-spacing: .06em;
    text-transform: uppercase;
  }

  nav {
    display: flex;
    gap: 2px;
    min-width: 0;
    flex: 1 1 auto;
    overflow: visible;
  }
  .nav-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: none;
    font-size: 13px;
    color: var(--text-muted);
    padding: 6px 12px;
    border-radius: 999px;
    font-weight: 850;
    transition: color var(--duration), background var(--duration);
    white-space: nowrap;
  }
  .nav-link:hover { background: color-mix(in srgb, var(--sun) 26%, var(--bg-elev)); color: var(--text); border-color: transparent; }
  .nav-link.active {
    color: var(--ink);
    background: var(--sun);
    box-shadow: 0 3px 0 color-mix(in srgb, var(--warn) 70%, var(--ink));
  }
  .nav-label-short { display: none; }

  .nav-badge {
    font-size: 9px; font-weight: 700; letter-spacing: 0.04em;
    padding: 1px 4px; border-radius: 3px; vertical-align: middle;
  }
  .nav-badge.beta { background: var(--ink); color: #fffdf8; }

  .nav-right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex: 0 0 auto;
  }
  .release-links {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
    min-height: 30px;
    padding: 3px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: color-mix(in srgb, var(--bg-elev) 82%, transparent);
    white-space: nowrap;
  }
  .repo-link {
    font-size: 11px;
    font-weight: 900;
    line-height: 1;
  }
  .repo-link {
    color: var(--accent);
    text-decoration: none;
  }
  .repo-link:hover {
    color: var(--accent-hover);
    text-decoration: underline;
  }
  .icon-btn { padding: 6px 10px; font-size: 16px; border: none; }
  .desktop-tag-token {
    display: inline-flex;
    align-items: center;
    white-space: nowrap;
    height: 30px;
    padding: 0 10px;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--teal) 50%, transparent);
    color: var(--ink);
    background: var(--mint);
    font-size: 12px;
    font-weight: 850;
  }
  .language-picker {
    display: inline-flex;
    align-items: center;
    flex: 0 0 auto;
  }
  .language-picker select {
    width: 112px;
    min-height: 30px;
    padding: 4px 28px 4px 10px;
    border-radius: 999px;
    background: var(--bg-elev);
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 850;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  /* ---- main ---- */
  main {
    width: min(100%, var(--app-shell-max));
    min-width: 0;
    max-width: 100vw;
    margin: 0 auto;
    padding: clamp(16px, 3vw, 36px) clamp(14px, 3vw, 36px);
    position: relative;
  }

  .page-header { margin-bottom: 20px; }
  .page-header.tight { margin-bottom: 14px; }
  .title-row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .page-header h1 {
    margin: 0;
    font-size: clamp(28px, 4.4vw, 48px);
    line-height: .96;
    font-weight: 950;
    max-width: min(900px, 100%);
  }
  .page-header p { margin: 0; font-size: 16px; max-width: 680px; color: var(--text-muted); }
  .page-header h1 + p,
  .title-row + p { margin-top: 10px; }

  /* ---- convert layout ---- */
  .forge-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 24px;
    align-items: start;
  }
  .forge-grid.idle {
    grid-template-columns: 1fr;
    max-width: 640px;
    margin: 0 auto;
  }
  .auto-output-wide {
    margin-top: 24px;
  }
  @media (max-width: 920px) {
    .forge-grid { grid-template-columns: 1fr; }
  }

  @media (max-width: 1540px) {
    .nav-label-full {
      display: none;
    }
    .nav-label-short {
      display: inline;
    }
    .nav-link {
      padding-inline: 8px;
    }
    .language-picker select { width: 104px; }
    .release-links {
      padding-inline: 7px;
    }
  }

  @media (max-width: 1360px) {
    .nav {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas:
        "brand actions"
        "tabs tabs";
      gap: 6px 8px;
      padding: 8px clamp(12px, 3vw, 20px);
    }
    .wordmark-wrap {
      grid-area: brand;
      min-width: 0;
      margin-right: 0;
    }
    .wordmark {
      max-width: 100%;
      padding-left: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .wordmark-tooltip {
      display: none;
    }
    nav {
      grid-area: tabs;
      width: 100%;
      gap: 6px;
      overflow: visible;
      padding-bottom: 4px;
    }
    .nav-link {
      flex: 1 1 0;
      justify-content: center;
      min-height: 36px;
      padding: 7px 10px;
    }
    .nav-right {
      grid-area: actions;
      margin-left: 0;
      justify-content: flex-end;
      gap: 6px;
      min-width: max-content;
    }
    .desktop-tag-token {
      display: none;
    }
    .repo-link {
      font-size: 10px;
    }
    .icon-btn {
      min-width: 34px;
      min-height: 34px;
      padding: 6px 8px;
    }
  }

  @media (max-width: 1180px) {
    .nav-label-full {
      display: none;
    }
    .nav-label-short {
      display: inline;
    }
  }

  @media (max-width: 880px) {
    nav {
      overflow-x: auto;
      scrollbar-width: thin;
    }
    .nav-link {
      flex: 1 0 max(96px, 20%);
    }
    .brand-tag {
      display: none;
    }
    .brand-version {
      display: none;
    }
  }

  @media (max-width: 380px) {
    .nav {
      padding-left: 12px;
      padding-right: 12px;
    }
    .wordmark {
      font-size: 14px;
      gap: 7px;
    }
  }

  .intake-column { display: flex; flex-direction: column; gap: 16px; }
  .control-column {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .forge-action {
    width: 100%;
    padding: 12px 20px;
    font-size: 15px;
    font-weight: 900;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .spool-strip { display: flex; flex-direction: column; gap: 8px; }
  .spool-strip-title { font-size: 12px; font-weight: 900; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
  .spool-strip-row { display: flex; flex-wrap: wrap; gap: 6px; }
  .spool-dot {
    width: 30px;
    height: 30px;
    border-radius: 10px;
    border: 2px solid #fffdf8;
    box-shadow: 0 2px 0 var(--border-strong);
  }

  .status-toast {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--sky) 24%, var(--bg-elev));
    border: 2px solid color-mix(in srgb, var(--sky) 55%, var(--border));
    border-radius: var(--radius);
    font-size: 13px;
    color: var(--text-muted);
  }
  .spinner-sm {
    width: 13px; height: 13px; flex-shrink: 0;
    border: 2px solid color-mix(in srgb, var(--accent) 30%, transparent);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    display: inline-block;
  }

  .warn-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: color-mix(in srgb, var(--sun) 28%, var(--bg-elev));
    border: 2px solid color-mix(in srgb, var(--warn) 38%, transparent);
    border-radius: var(--radius);
    color: var(--warn);
    font-size: 13px;
  }

  .error-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: color-mix(in srgb, var(--danger) 10%, var(--bg-elev));
    border: 2px solid color-mix(in srgb, var(--danger) 35%, transparent);
    border-radius: var(--radius);
    color: var(--danger);
    font-size: 13px;
  }

  /* ---- readiness strip ---- */
  .capability-strip {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 14px;
    margin-top: 48px;
  }
  .capability-tile {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-height: 150px;
    padding: 18px;
    border: 2px solid var(--border-strong);
    border-radius: 18px;
    background:
      linear-gradient(145deg, color-mix(in srgb, var(--mint) 18%, transparent), transparent 58%),
      var(--bg-elev);
    box-shadow: var(--shadow-sm);
  }
  .capability-mark {
    align-self: flex-start;
    padding: 4px 8px;
    border-radius: 8px;
    background: var(--accent);
    color: #fffdf8;
    font-size: 11px;
    font-weight: 950;
    letter-spacing: 0.04em;
  }
  .capability-tile strong {
    font-size: 15px;
    font-weight: 950;
    color: var(--text);
  }
  .capability-tile span:last-child {
    font-size: 12.5px;
    color: var(--text-muted);
    line-height: 1.45;
  }

  @media (max-width: 820px) {
    .capability-strip {
      grid-template-columns: 1fr;
      margin-top: 32px;
    }
    .capability-tile {
      min-height: 0;
    }
  }

  footer {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 16px 24px;
    border-top: 2px solid var(--border-strong);
    background: color-mix(in srgb, var(--ink) 94%, #000);
    color: #fffdf8;
    font-size: 12px;
  }
  .footer-links {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  footer .subtle { color: color-mix(in srgb, #fffdf8 72%, transparent); }
  footer a { color: #fffdf8; font-weight: 850; }

  /* ---- converting overlay ---- */
  .build-veil {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: color-mix(in srgb, var(--ink) 62%, transparent);
    backdrop-filter: blur(4px);
    z-index: 800;
  }
  .build-veil-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 28px 32px;
    background: var(--bg-elev);
    border: 2px solid var(--border-strong);
    border-radius: 20px;
    box-shadow: var(--shadow-lg);
    width: 380px;
    max-width: calc(100vw - 48px);
  }
  .build-veil-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }
  .build-veil-title { font-size: 16px; font-weight: 900; color: var(--text); }
  .build-veil-percent { font-size: 20px; font-weight: 700; color: var(--accent); font-variant-numeric: tabular-nums; }
  .build-veil-file { font-size: 12px; color: var(--text-muted); word-break: break-all; line-height: 1.4; margin-top: -4px; }
  .build-meter-track {
    width: 100%; height: 8px;
    background: var(--bg-raised);
    border-radius: 999px;
    overflow: hidden;
  }
  .build-meter-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent), var(--sun), var(--teal));
    border-radius: 999px;
    transition: width 0.15s ease-out;
  }
  .build-veil-stage { font-size: 12px; color: var(--text-muted); }
</style>
