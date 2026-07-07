<script lang="ts">
  import { SlidersHorizontal } from 'lucide-svelte';
  
  import type { ProfileDescriptor } from './engineClient';
  import { tr } from './i18n';

  interface Props {
    profiles: ProfileDescriptor[];
    selectedProfile: string;
    applyRules: boolean;
    insertSwapPauses: boolean;
    excludeObjects: boolean;
    advancedOverrides: string;
    autoMatched?: boolean;
    disabled?: boolean;
  }

  let {
    profiles,
    selectedProfile = $bindable(),
    applyRules = $bindable(),
    insertSwapPauses = $bindable(),
    excludeObjects = $bindable(),
    advancedOverrides = $bindable(),
    autoMatched = false,
    disabled = false,
  }: Props = $props();

  let showAdvanced = $state(false);

  function applyPreset(kind: 'compat' | 'intent' | 'multicolor') {
    if (kind === 'compat') {
      applyRules = true;
      insertSwapPauses = false;
      excludeObjects = true;
      advancedOverrides = '{}';
    } else if (kind === 'intent') {
      applyRules = false;
      insertSwapPauses = false;
      excludeObjects = true;
      advancedOverrides = '{}';
    } else {
      applyRules = true;
      insertSwapPauses = true;
      excludeObjects = true;
      advancedOverrides = '{}';
    }
  }
</script>

<div class="console-panel card card-padded">
  <div class="row">
    <div class="shelf-label-line">
      <label for="profile">{$tr('U1 shelf profile')}</label>
      {#if autoMatched}
        <span class="auto-pick-chip">{$tr('picked by layer height')}</span>
      {/if}
    </div>
    <select
      id="profile"
      bind:value={selectedProfile}
      {disabled}
    >
      {#if profiles.length === 0}
        <option value="">{$tr('No shelf profiles found')}</option>
      {/if}
      {#each profiles as p (p.id)}
        <option value={p.id}>
          {p.display_name}
          {p.source === 'user' ? '(user)' : ''}
        </option>
      {/each}
    </select>
  </div>

  <div class="toggles">
    <label class="toggle">
      <input type="checkbox" bind:checked={applyRules} {disabled} />
      <span class="toggle-track"><span class="toggle-thumb"></span></span>
      <span class="toggle-label">
        <span class="toggle-title">{$tr('Use material recipes')}</span>
        <span class="subtle">{$tr('Match spool metadata, apply safe process tweaks, and keep material lists slot-aware')}</span>
      </span>
    </label>

    <label class="toggle">
      <input type="checkbox" bind:checked={insertSwapPauses} {disabled} />
      <span class="toggle-track"><span class="toggle-thumb"></span></span>
      <span class="toggle-label">
        <span class="toggle-title">{$tr('Add spool-swap stops')}</span>
        <span class="subtle">{$tr('For more than four colours, place pause notes before a toolhead needs a different spool.')}</span>
      </span>
    </label>

    <label class="toggle">
      <input type="checkbox" bind:checked={excludeObjects} {disabled} />
      <span class="toggle-track"><span class="toggle-thumb"></span></span>
      <span class="toggle-label">
        <span class="toggle-title">{$tr('Enable object exclusion')}</span>
        <span class="subtle">{$tr('Enable Global > Others > Exclude objects')}</span>
      </span>
    </label>

  </div>

  <div class="preset-strip" aria-label={$tr('Workflow presets')}>
    <button class="preset-button" type="button" onclick={() => applyPreset('compat')} {disabled}>
      <strong>{$tr('Max compatibility')}</strong>
      <span>{$tr('Clean, clamp, use recipes')}</span>
    </button>
    <button class="preset-button" type="button" onclick={() => applyPreset('intent')} {disabled}>
      <strong>{$tr('Keep source intent')}</strong>
      <span>{$tr('Only retarget and clean')}</span>
    </button>
    <button class="preset-button" type="button" onclick={() => applyPreset('multicolor')} {disabled}>
      <strong>{$tr('Manual multicolor')}</strong>
      <span>{$tr('Recipes plus swap stops')}</span>
    </button>
  </div>

  <button
    class="ghost override-drawer-button"
    onclick={() => (showAdvanced = !showAdvanced)}
    aria-expanded={showAdvanced}
  >
    <SlidersHorizontal size={15} strokeWidth={2.4} aria-hidden="true" />
    {showAdvanced ? $tr('Close override drawer') : $tr('Open override drawer')}
  </button>

  {#if showAdvanced}
    <div class="override-drawer">
      <p class="subtle">
        {$tr('YAML values applied at the very end of the build. These win over recipes and automatic clamps.')}
      </p>
      <pre class="yaml-sample mono">
layer_height: "0.24"
outer_wall_speed: 150</pre>
      <textarea
        bind:value={advancedOverrides}
        rows="6"
        spellcheck="false"
        placeholder={$tr('key: value')}
        {disabled}
      ></textarea>
    </div>
  {/if}
</div>

<style>
  .console-panel {
    display: flex;
    flex-direction: column;
    gap: 20px;
    border-radius: 22px;
    background:
      linear-gradient(160deg, color-mix(in srgb, var(--mint) 18%, transparent), transparent 45%),
      var(--bg-elev);
  }
  .row { display: flex; flex-direction: column; gap: 6px; }
  .row label { font-weight: 900; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }
  .shelf-label-line { display: flex; align-items: center; gap: 8px; }
  .auto-pick-chip {
    font-size: 10px;
    font-weight: 850;
    padding: 2px 7px;
    border-radius: 999px;
    background: var(--sun);
    color: var(--ink);
    border: 1px solid color-mix(in srgb, var(--warn) 45%, transparent);
    letter-spacing: 0.02em;
  }

  .toggles {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding-top: 4px;
  }

  .toggle {
    display: grid;
    grid-template-columns: 44px 1fr;
    align-items: center;
    gap: 12px;
    cursor: pointer;
    padding: 6px 0;
  }
  .toggle input { position: absolute; opacity: 0; pointer-events: none; }

  .toggle-track {
    width: 42px; height: 24px;
    background: var(--border);
    border-radius: 999px;
    position: relative;
    transition: background var(--duration);
  }
  .toggle-thumb {
    position: absolute;
    top: 2px; left: 2px;
    width: 20px; height: 20px;
    background: var(--bg-elev);
    border-radius: 50%;
    transition: transform var(--duration);
  }
  .toggle input:checked ~ .toggle-track { background: var(--teal); }
  .toggle input:checked ~ .toggle-track .toggle-thumb {
    transform: translateX(18px);
    background: #fff;
  }
  .toggle input:focus-visible ~ .toggle-track {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .toggle-label {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .toggle-title { font-weight: 900; }
  .toggle-label .subtle { font-size: 12px; }

  .preset-strip {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .preset-button {
    min-width: 0;
    min-height: 58px;
    display: grid;
    gap: 3px;
    align-content: center;
    padding: 8px 9px;
    border-radius: 14px;
    border: 1px solid var(--border);
    background: color-mix(in srgb, var(--sun) 10%, var(--bg-elev));
    color: var(--text);
    box-shadow: none;
    text-align: left;
  }

  .preset-button strong,
  .preset-button span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .preset-button strong {
    font-size: 12px;
    font-weight: 950;
  }

  .preset-button span {
    color: var(--text-muted);
    font-size: 11px;
  }

  .preset-button:hover {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--mint) 18%, var(--bg-elev));
  }

  .override-drawer-button {
    align-self: flex-start;
    padding: 8px 12px;
    font-size: 13px;
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    font-weight: 850;
  }

  .override-drawer {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px;
    background: var(--bg-raised);
    border-radius: 16px;
    border: 2px solid var(--border);
  }
  .override-drawer p { margin: 0; font-size: 12px; }
  .yaml-sample {
    margin: 0;
    font-size: 12px;
    background: var(--bg);
    padding: 10px 12px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    color: var(--text-muted);
  }
  textarea { font-family: var(--font-mono); font-size: 12px; resize: vertical; }

  @media (max-width: 760px) {
    .preset-strip {
      grid-template-columns: 1fr;
    }
  }
</style>
