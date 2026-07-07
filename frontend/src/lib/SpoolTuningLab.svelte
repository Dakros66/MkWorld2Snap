<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { EditorView, basicSetup } from 'codemirror';
  import { yaml } from '@codemirror/lang-yaml';
  import { oneDark } from '@codemirror/theme-one-dark';
  import {
    listRules, getRuleYaml, putRule, createRule, deleteRule, testMatch,
    type RuleSummary,
  } from './engineClient';
  import { tr } from './i18n';

  // ---- state ---------------------------------------------------------------
  let rules = $state<RuleSummary[]>([]);
  let selected = $state<string | null>(null);
  let editorYaml = $state('');
  let saving = $state(false);
  let saveError = $state('');
  let saveOk = $state(false);
  let loading = $state(true);
  let testFile = $state<File | null>(null);
  let testResult = $state<unknown>(null);
  let testError = $state('');
  let testLoading = $state(false);
  let testInputEl: HTMLInputElement | undefined = $state();
  const presetRecipes = [
    {
      key: 'pla_matte',
      label: 'PLA Matte',
      yaml: `name: PLA Matte safe tune
description: "Lower outer-wall speed and keep PLA Matte temperatures stable."
match:
  filament_settings_id_contains: "PLA Matte"
  filament_vendor: null
  filament_type: "PLA"
overrides:
  outer_wall_speed: 90
  inner_wall_speed: 140
  sparse_infill_speed: 180
  nozzle_temperature: 215
  hot_plate_temp: 60
priority: 20
enabled: true
`,
    },
    {
      key: 'petg',
      label: 'PETG',
      yaml: `name: PETG clean walls
description: "Moderate speeds and raise temperatures for PETG spools."
match:
  filament_settings_id_contains: null
  filament_vendor: null
  filament_type: "PETG"
overrides:
  outer_wall_speed: 80
  inner_wall_speed: 120
  sparse_infill_speed: 150
  nozzle_temperature: 245
  hot_plate_temp: 80
priority: 20
enabled: true
`,
    },
    {
      key: 'tpu',
      label: 'TPU',
      yaml: `name: TPU flexible slow pass
description: "Slow global motion when a TPU spool is present."
match:
  filament_settings_id_contains: null
  filament_vendor: null
  filament_type: "TPU"
overrides:
  outer_wall_speed: 35
  inner_wall_speed: 45
  sparse_infill_speed: 45
  travel_speed: 120
  nozzle_temperature: 225
  hot_plate_temp: 45
priority: 30
enabled: true
`,
    },
  ];

  // ---- CodeMirror ----------------------------------------------------------
  let editorContainer: HTMLElement | undefined = $state();
  let view: EditorView | undefined;

  function newRuleTemplate() {
    return `name: ${$tr('My Material Recipe')}
description: "${$tr('Describe what this spool needs')}"
match:
  filament_settings_id_contains: null
  filament_vendor: null
  filament_type: null
overrides:
  outer_wall_speed: 150
priority: 0
enabled: true
`;
  }

  function setupEditor(content: string) {
    if (view) { view.destroy(); view = undefined; }
    if (!editorContainer) return;
    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    view = new EditorView({
      doc: content,
      extensions: [
        basicSetup,
        yaml(),
        ...(isDark ? [oneDark] : []),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) editorYaml = view!.state.doc.toString();
        }),
        EditorView.theme({ '&': { fontSize: '13px', height: '340px' } }),
      ],
      parent: editorContainer,
    });
  }

  async function load() {
    loading = true;
    try {
      rules = await listRules();
    } catch { /* keep old list */ }
    loading = false;
  }

  async function selectRule(fileKey: string) {
    selected = fileKey;
    saveError = ''; saveOk = false;
    await tick(); // wait for {#if selected} to render cm-host
    const r = await getRuleYaml(fileKey);
    editorYaml = r.yaml_text;
    setupEditor(r.yaml_text);
  }

  async function newRule() {
    selected = '__new__';
    editorYaml = newRuleTemplate();
    saveError = ''; saveOk = false;
    await tick(); // wait for {#if selected} to render cm-host
    setupEditor(editorYaml);
  }

  async function usePreset(yamlText: string) {
    selected = '__new__';
    editorYaml = yamlText;
    saveError = ''; saveOk = false;
    await tick();
    setupEditor(editorYaml);
  }

  async function save() {
    saving = true; saveError = ''; saveOk = false;
    try {
      if (selected === '__new__') {
        await createRule(editorYaml);
      } else if (selected) {
        await putRule(selected, editorYaml);  // selected is already file_key
      }
      saveOk = true;
      await load();
      setTimeout(() => (saveOk = false), 2000);
    } catch (e: unknown) {
      saveError = e instanceof Error ? e.message : String(e);
    } finally {
      saving = false;
    }
  }

  async function remove(name: string, fileKey: string) {
    if (!confirm($tr('Delete recipe "{name}"?', { name }))) return;
    await deleteRule(fileKey);
    if (selected === fileKey) { selected = null; if (view) { view.destroy(); view = undefined; } }
    await load();
  }

  async function runTest() {
    if (!testFile) return;
    testLoading = true; testResult = null; testError = '';
    try {
      testResult = await testMatch(testFile);
    } catch (e: unknown) {
      testError = e instanceof Error ? e.message : String(e);
    } finally {
      testLoading = false;
    }
  }

  onMount(async () => {
    await load();
    if (rules.length > 0) await selectRule(rules[0].file_key);
  });

  onDestroy(() => { if (view) view.destroy(); });
</script>

<div class="tuning-editor">
  <div class="sidebar">
    <div class="sidebar-header">
      <h2>{$tr('Spool Tuning Lab')}</h2>
      <button class="primary" onclick={newRule}>{$tr('New recipe')}</button>
    </div>

    <div class="preset-card">
      <span>{$tr('Quick recipe presets')}</span>
      <div class="preset-buttons">
        {#each presetRecipes as preset}
          <button class="ghost" type="button" onclick={() => usePreset(preset.yaml)}>{preset.label}</button>
        {/each}
      </div>
    </div>

    {#if loading}
      <p class="muted" style="padding:0 4px">{$tr('Loading...')}</p>
    {:else if rules.length === 0}
      <p class="muted" style="padding:0 4px">{$tr('No recipes yet. Create one to tune a spool automatically.')}</p>
    {:else}
      <ul class="rule-list" role="listbox" aria-label={$tr('Spool tuning recipes')}>
        {#each rules as r (r.file_key)}
          <li
            class="rule-item"
            class:active={selected === r.file_key}
            role="option"
            aria-selected={selected === r.file_key}
            tabindex="0"
            onclick={() => selectRule(r.file_key)}
            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') selectRule(r.file_key); }}
          >
            <div class="rule-item-name">
              <span class:muted={!r.enabled}>{r.name}</span>
              {#if !r.enabled}<span class="pill">{$tr('disabled')}</span>{/if}
            </div>
            <div class="rule-item-meta subtle">{$tr('priority')} {r.priority} · {Object.keys(r.overrides).length} {$tr('tweaks')}</div>
          </li>
        {/each}
      </ul>
    {/if}

    <div class="test-review-card">
      <div class="test-header">{$tr('Try recipes on a 3MF')}</div>
      <input
        bind:this={testInputEl}
        type="file" accept=".3mf"
        style="display:none"
        onchange={(e) => {
          const f = (e.currentTarget as HTMLInputElement).files?.[0];
          if (f) { testFile = f; testResult = null; testError = ''; }
        }}
      />
      <div class="test-controls">
        <button class="ghost" onclick={() => testInputEl?.click()}>
          {testFile ? testFile.name : $tr('Choose .3mf...')}
        </button>
        <button
          class="primary"
          disabled={!testFile || testLoading}
          onclick={runTest}
        >
          {testLoading ? $tr('Checking...') : $tr('Run match')}
        </button>
      </div>
      {#if testError}
        <p class="err">{testError}</p>
      {/if}
      {#if testResult}
        {@const result = testResult as { matches: Array<{rule_name: string; priority: number}>; context: unknown }}
        <div class="test-result">
          {#if result.matches.length === 0}
            <p class="muted">{$tr('No recipes matched this package.')}</p>
          {:else}
            {#each result.matches as m}
              <div class="match-row">
                <span class="pill accent">✓</span> {m.rule_name}
                <span class="subtle">p{m.priority}</span>
              </div>
            {/each}
          {/if}
        </div>
      {/if}
    </div>
  </div>

  <div class="editor-pane">
    {#if selected}
      <div class="recipe-note">
        {$tr('Recipes match the source spool metadata. Global process keys, such as wall speed or acceleration, tune the whole project when a match appears. List-based material keys, such as nozzle or bed temperatures, are applied only to the matched spool slots. Unknown target-profile keys are skipped.')}
      </div>
      <div class="editor-header">
        <span class="editor-title">
          {selected === '__new__' ? $tr('New recipe') : selected}
        </span>
        <div class="editor-actions">
          {#if saveError}<span class="err">{saveError}</span>{/if}
          {#if saveOk}<span class="ok">{$tr('Saved')}</span>{/if}
          {#if selected !== '__new__'}
            {@const rule = rules.find(r => r.file_key === selected)}
            <button class="ghost danger" onclick={() => rule && remove(rule.name, rule.file_key)}>{$tr('Delete recipe')}</button>
          {/if}
          <button class="primary" onclick={save} disabled={saving}>
            {saving ? $tr('Saving...') : $tr('Save recipe')}
          </button>
        </div>
      </div>
      <div class="cm-host" bind:this={editorContainer}></div>
    {:else}
      <div class="empty-editor">
        <p class="muted">{$tr('Pick a recipe from the shelf or create a fresh one.')}</p>
      </div>
    {/if}
  </div>
</div>

<style>
  .tuning-editor {
    display: grid;
    grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
    gap: 20px;
    min-height: clamp(520px, calc(100vh - 260px), 760px);
  }

  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 18px;
    background:
      linear-gradient(150deg, color-mix(in srgb, var(--sun) 14%, transparent), transparent 45%),
      var(--bg-elev);
    border: 2px solid var(--border-strong);
    border-radius: 20px;
    box-shadow: var(--shadow);
  }
  .sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .sidebar-header h2 { margin: 0; font-size: 18px; font-weight: 950; }

  .preset-card {
    display: grid;
    gap: 8px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: color-mix(in srgb, var(--mint) 10%, var(--bg-elev));
  }

  .preset-card > span {
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 950;
    letter-spacing: .05em;
    text-transform: uppercase;
  }

  .preset-buttons {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .preset-buttons button {
    min-height: 30px;
    padding: 6px 9px;
    font-size: 11px;
  }

  .rule-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
    overflow-y: auto;
    min-height: 0;
  }
  .rule-item {
    padding: 10px 12px;
    border-radius: var(--radius);
    border: 1px solid transparent;
    cursor: pointer;
    transition: background var(--duration), border-color var(--duration);
  }
  .rule-item:hover { background: color-mix(in srgb, var(--sun) 18%, var(--bg-raised)); }
  .rule-item.active {
    background: color-mix(in srgb, var(--mint) 38%, var(--bg-raised));
    border-color: color-mix(in srgb, var(--teal) 45%, transparent);
  }
  .rule-item-name { font-weight: 900; font-size: 13px; display: flex; align-items: center; gap: 8px; }
  .rule-item-meta { font-size: 11.5px; margin-top: 2px; }

  .test-review-card {
    margin-top: auto;
    border-top: 1px solid var(--border);
    padding-top: 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .test-header { font-weight: 900; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }
  .test-controls { display: flex; gap: 8px; }
  .test-controls .ghost {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12px;
    text-align: left;
  }
  .test-result {
    background: var(--bg-raised);
    border-radius: var(--radius);
    padding: 10px 12px;
    font-size: 12.5px;
  }
  .match-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }

  .editor-pane {
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 2px solid var(--border-strong);
    border-radius: 20px;
    overflow: hidden;
    background: var(--bg-elev);
    box-shadow: var(--shadow);
  }
  .recipe-note {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    background: color-mix(in srgb, var(--mint) 20%, var(--bg-raised));
    color: var(--text-muted);
    font-size: 12.5px;
    line-height: 1.45;
  }
  .editor-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    gap: 12px;
    flex-wrap: wrap;
  }
  .editor-title { font-weight: 950; }
  .editor-actions { display: flex; align-items: center; gap: 10px; }
  .empty-editor {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .cm-host { flex: 1; overflow: hidden; }
  /* Let CodeMirror fill the pane */
  :global(.cm-host .cm-editor) { height: 100%; min-height: 340px; }
  :global(.cm-host .cm-scroller) { overflow: auto; }

  .err { color: var(--danger); font-size: 12px; margin: 0; }
  .ok { color: var(--success); font-size: 12px; }

  @media (max-width: 900px) {
    .tuning-editor {
      grid-template-columns: 1fr;
      min-height: 0;
    }
    .sidebar {
      min-height: 0;
    }
    .rule-list {
      max-height: 220px;
    }
    .test-review-card {
      margin-top: 0;
    }
    .editor-pane {
      min-height: 460px;
    }
  }

  @media (max-width: 560px) {
    .sidebar,
    .editor-pane {
      border-radius: 16px;
    }
    .sidebar-header,
    .editor-header,
    .editor-actions,
    .test-controls {
      align-items: stretch;
      flex-direction: column;
    }
    .editor-actions button,
    .test-controls button {
      width: 100%;
      justify-content: center;
      text-align: center;
    }
  }
</style>
