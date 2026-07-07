<script lang="ts">
  import type { FilamentInfo } from './engineClient';
  import { tr } from './i18n';

  interface Props {
    filaments: FilamentInfo[];
    onconfirm: (map: Record<number, number>) => void;
    onskip: () => void;
  }

  let { filaments, onconfirm, onskip }: Props = $props();

  // Colours 1-4 default to T1-T4; colours 5+ start unassigned.
  const initial: Record<number, number> = {};
  // svelte-ignore state_referenced_locally
  filaments.forEach((f) => { if (f.index < 4) initial[f.index] = f.index; });
  let assignments = $state<Record<number, number>>({ ...initial });

  const toolheads = [0, 1, 2, 3];

  import { onMount } from 'svelte';

  let modalEl: HTMLDivElement;
  let firstFocusable: HTMLElement | null = null;
  let lastFocusable: HTMLElement | null = null;

  onMount(() => {
    const focusable = modalEl.querySelectorAll<HTMLElement>(
      'button, select, [tabindex]:not([tabindex="-1"])'
    );
    firstFocusable = focusable[0] ?? null;
    lastFocusable = focusable[focusable.length - 1] ?? null;
    firstFocusable?.focus();
  });

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') { onskip(); return; }
    if (e.key === 'Tab') {
      if (e.shiftKey) {
        if (document.activeElement === firstFocusable) { e.preventDefault(); lastFocusable?.focus(); }
      } else {
        if (document.activeElement === lastFocusable) { e.preventDefault(); firstFocusable?.focus(); }
      }
    }
  }

  function assign(sourceIdx: number, value: string) {
    const next = { ...assignments };
    if (value === '') {
      delete next[sourceIdx];
    } else {
      next[sourceIdx] = parseInt(value, 10);
    }
    assignments = next;
  }

  function confirm() {
    onconfirm(assignments);
  }

  const unassignedOverflow = $derived(
    filaments.filter((f) => f.index >= 4 && assignments[f.index] === undefined).length
  );
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="th-title" tabindex="-1" onkeydown={onKeydown}>
  <div class="modal" bind:this={modalEl}>
    <h2 class="modal-title" id="th-title">{$tr('Colour routing')}</h2>
    <p class="modal-desc">
      {@html $tr('This painted package has {count} colours. Assign them to the four physical U1 toolheads now, or keep every colour and let Snapmaker Orca resolve them when slicing.', { count: `<strong>${filaments.length}</strong>` })}
      {$tr('Unassigned colours are skipped if you confirm this routing.')}
    </p>

    <div class="rows">
      {#each filaments as f}
        {@const isOverflow = f.index >= 4}
        {@const assigned = assignments[f.index] !== undefined}
        <div class="row" class:overflow={isOverflow && !assigned}>
          <span
            class="swatch"
            style="background:{f.colour ?? '#888'}"
            title={f.settings_id ?? f.filament_type ?? 'Unknown'}
          ></span>
          <span class="label">
            {f.filament_type ?? f.settings_id ?? `Colour ${f.index + 1}`}
          </span>
          {#if isOverflow && !assigned}
            <span class="drop-badge">{$tr('skipped')}</span>
          {/if}
          <select
            class="sel"
            class:unset={isOverflow && !assigned}
            value={assigned ? String(assignments[f.index]) : ''}
            onchange={(e) => assign(f.index, (e.target as HTMLSelectElement).value)}
          >
            {#if isOverflow}<option value="">{$tr('unassigned')}</option>{/if}
            {#each toolheads as t}
              <option value={String(t)}>T{t + 1}</option>
            {/each}
          </select>
        </div>
      {/each}
    </div>

    {#if unassignedOverflow > 0}
      <p class="warn-note">
        {$tr('Some colours are not assigned. Assign them above if you want them preserved in the rebuilt package.', { count: unassignedOverflow })}
      </p>
    {/if}

    <div class="actions">
      <button class="primary" onclick={onskip}>
        {$tr('Keep all colours', { count: filaments.length })}
      </button>
      <button class="ghost" onclick={confirm}>{$tr('Use routing')}</button>
    </div>
  </div>
</div>

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(17, 24, 32, 0.58);
    backdrop-filter: blur(14px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 24px;
  }

  .modal {
    background: linear-gradient(135deg, color-mix(in srgb, var(--bg-elev) 92%, transparent), color-mix(in srgb, var(--sky) 10%, var(--bg-elev)));
    border: 1px solid var(--border);
    border-radius: 24px;
    padding: 24px;
    width: 100%;
    max-width: 440px;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    gap: 16px;
    box-shadow: 0 28px 70px rgba(29, 36, 48, 0.34);
    overflow: hidden;
  }

  .modal-title { margin: 0; font-size: 21px; font-weight: 950; letter-spacing: 0; }

  .modal-desc { margin: 0; font-size: 13px; color: var(--text-muted); line-height: 1.5; }

  .rows {
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow-y: auto;
    flex-shrink: 1;
    min-height: 0;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px;
    border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
    border-radius: 14px;
    background: color-mix(in srgb, var(--bg-elev) 80%, transparent);
  }

  .row.overflow { opacity: 0.65; }

  .swatch {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    flex-shrink: 0;
    border: 1px solid rgba(255, 255, 255, 0.12);
  }

  .label {
    flex: 1;
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .drop-badge {
    font-size: 10px;
    color: var(--warn);
    background: color-mix(in srgb, var(--warn) 15%, transparent);
    border-radius: 999px;
    padding: 1px 6px;
    flex-shrink: 0;
  }

  .sel {
    font-size: 12px;
    padding: 3px 6px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    background: var(--bg-elev);
    color: var(--text);
    cursor: pointer;
    width: 88px;
    flex-shrink: 0;
  }

  .sel.unset { border-color: color-mix(in srgb, var(--warn) 50%, transparent); }

  .warn-note {
    margin: 0;
    font-size: 12px;
    color: var(--warn);
    background: color-mix(in srgb, var(--warn) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--warn) 25%, transparent);
    border-radius: var(--radius);
    padding: 8px 12px;
  }

  .actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
    align-items: center;
    padding-top: 4px;
    flex-shrink: 0;
    flex-wrap: wrap;
  }
</style>
