<script lang="ts">
  import { RefreshCcw, Upload } from 'lucide-svelte';
  import { tr } from './i18n';
  
  

  interface Props {
    onfile: (file: File) => void;
    file: File | null;
    disabled?: boolean;
  }

  let { onfile, file = $bindable(), disabled = false }: Props = $props();

  let dragOver = $state(false);
  let inputEl: HTMLInputElement | undefined = $state();

  function pick(ev: Event) {
    const target = ev.currentTarget as HTMLInputElement;
    const f = target.files?.[0];
    if (f) onfile(f);
  }

  function drop(ev: DragEvent) {
    ev.preventDefault();
    dragOver = false;
    if (disabled) return;
    const f = ev.dataTransfer?.files?.[0];
    if (f && f.name.toLowerCase().endsWith('.3mf')) onfile(f);
  }

  function over(ev: DragEvent) {
    ev.preventDefault();
    if (!disabled) dragOver = true;
  }
</script>

<div
  class="intake-pad"
  class:intake-hover={dragOver}
  class:intake-loaded={!!file}
  class:disabled
  ondragover={over}
  ondragleave={() => (dragOver = false)}
  ondrop={drop}
  onclick={() => !disabled && inputEl?.click()}
  onkeydown={(e) => {
    if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      inputEl?.click();
    }
  }}
  role="button"
  tabindex={disabled ? -1 : 0}
  aria-label={$tr('Choose a 3MF project file')}
  aria-disabled={disabled}
>
  <input
    bind:this={inputEl}
    type="file"
    accept=".3mf"
    onchange={pick}
    {disabled}
    hidden
  />

  {#if file}
    <div class="intake-summary">
      <div class="file-token" aria-hidden="true"><span></span></div>
      <div class="file-name">{file.name}</div>
      <div class="meta subtle">{(file.size / 1024 / 1024).toFixed(2)} MB</div>
      <button class="ghost" onclick={(e) => { e.stopPropagation(); onfile(null as unknown as File); }}>
        <RefreshCcw size={15} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Swap file')}
      </button>
    </div>
  {:else}
    <div class="intake-prompt">
      <div class="intake-emblem" aria-hidden="true">
        <Upload size={42} strokeWidth={2.2} />
      </div>
      <div class="title">{$tr('Drop a 3MF package on the workbench')}</div>
      <div class="subtle">{$tr('or click anywhere in this tray to pick one')}</div>
    </div>
  {/if}
</div>

<style>
  .intake-pad {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 210px;
    border: 3px dashed color-mix(in srgb, var(--ink) 28%, transparent);
    border-radius: 24px;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--sun) 20%, transparent), transparent 42%),
      var(--bg-elev);
    padding: 34px;
    cursor: pointer;
    box-shadow: var(--shadow);
    transition: border-color var(--duration), background var(--duration), transform var(--duration), box-shadow var(--duration);
  }
  .intake-pad:hover:not(.disabled) {
    border-color: var(--accent);
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--accent) 16%, transparent), transparent 42%),
      var(--bg-elev);
    transform: translateY(-2px);
  }
  .intake-pad.intake-hover {
    border-color: var(--accent);
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--mint) 48%, transparent), transparent 48%),
      var(--bg-elev);
    transform: scale(1.012) rotate(-.4deg);
  }
  .intake-pad.intake-loaded {
    border-style: solid;
    border-color: var(--border);
  }
  .intake-pad.disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .intake-prompt { text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px; }
  .intake-emblem {
    width: 74px;
    height: 74px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    grid-template-rows: repeat(3, 1fr);
    gap: 5px;
    padding: 10px;
    border-radius: 22px;
    background: var(--ink);
    color: #fffdf8;
    box-shadow: 0 7px 0 var(--sun);
    transform: rotate(3deg);
  }
  .intake-emblem :global(svg) {
    display: block;
    margin: auto;
    stroke: currentColor;
  }
  .file-token {
    width: 44px;
    height: 44px;
    border-radius: 14px;
    background: var(--ink);
    padding: 9px;
    box-shadow: 0 4px 0 var(--sun);
    flex-shrink: 0;
  }
  .file-token span {
    display: block;
    width: 100%;
    height: 100%;
    border-radius: 8px;
    background: linear-gradient(135deg, var(--mint), var(--sky));
  }
  .intake-prompt .title {
    font-size: 20px;
    line-height: 1.15;
    font-weight: 950;
    margin-bottom: 4px;
  }

  .intake-summary {
    display: flex;
    align-items: center;
    gap: 14px;
    width: 100%;
  }
  .intake-summary .file-name {
    font-weight: 900;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .intake-summary .meta { flex-shrink: 0; font-size: 12px; }
</style>
