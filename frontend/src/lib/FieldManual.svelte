<script lang="ts">
  import { tr } from './i18n';

  type Route = 'convert' | 'blconvert' | 'rules' | 'help';
  interface Props { onNavigate: (route: Route) => void; }
  let { onNavigate }: Props = $props();

  const sources = [
    {
      name: 'Bambu Studio projects',
      status: 'Primary',
      tone: 'ok',
      detail: 'Best covered path for MakerWorld packages with embedded project settings, model geometry, colours and process data.',
      keeps: 'profiles, material lists, paint data, settings intent',
    },
    {
      name: 'Orca-family projects',
      status: 'Supported with review',
      tone: 'work',
      detail: 'Reads the same project_settings layout used by Orca-derived slicers and rebuilds the machine side for U1.',
      keeps: 'layer/process console-panel when the file follows Orca structure',
    },
    {
      name: 'PrusaSlicer projects',
      status: 'Improved import',
      tone: 'work',
      detail: 'Reads Slic3r_PE config, maps available filament metadata, and translates supported MMU paint attributes.',
      keeps: 'geometry, layer height, filament hints, MMU paint where present',
    },
    {
      name: 'Cura and geometry-only 3MF',
      status: 'Fallback path',
      tone: 'care',
      detail: 'Uses available Cura layer metadata or a safe default U1 profile when slicer process data is missing.',
      keeps: 'geometry plus any readable layer-height signal',
    },
  ];
</script>

<div class="guide">
  <section class="guide-banner">
    <div>
      <p class="eyebrow">{$tr('Workshop guide')}</p>
      <h2>{$tr('Know what will be rebuilt before you print')}</h2>
      <p>
        {$tr('MkWorld2Snap creates a fresh U1-ready project package. It does not reuse stale machine output; the saved file should be opened and sliced again in Snapmaker Orca.')}
      </p>
    </div>
    <div class="banner-stack" aria-hidden="true">
      <span>3MF</span>
      <span>U1</span>
      <span>QA</span>
    </div>
  </section>

  <section class="guide-grid">
    <div class="guide-panel intake-panel">
      <h3>{$tr('Package Intake')}</h3>
      <div class="intake-list">
        <div><strong>{$tr('Needs')}</strong><span>{@html $tr('Editable <code>.3mf</code> geometry and project metadata where available.')}</span></div>
        <div><strong>{$tr('Rejects')}</strong><span>{@html $tr('Machine-only <code>.gcode.3mf</code> packages without model geometry.')}</span></div>
        <div><strong>{$tr('Outputs')}</strong><span>{$tr('A new project file for review and slicing in Snapmaker Orca.')}</span></div>
      </div>
    </div>

    <div class="guide-panel">
      <h3>{$tr('What changes')}</h3>
      <div class="change-strip">
        <span>{$tr('Printer identity')}</span>
        <span>{$tr('Startup scripts')}</span>
        <span>{$tr('Unsupported keys')}</span>
        <span>{$tr('Motion limits')}</span>
        <span>{$tr('Spool routing')}</span>
      </div>
    </div>
  </section>

  <section class="guide-panel">
    <div class="panel-head">
      <h3>{$tr('Source Compatibility')}</h3>
      <button class="inline-link" type="button" onclick={() => onNavigate('convert')}>{$tr('Open builder')}</button>
    </div>
    <div class="source-grid">
      {#each sources as source}
        <article class="source-card {source.tone}">
          <div class="source-top">
            <strong>{$tr(source.name)}</strong>
            <span>{$tr(source.status)}</span>
          </div>
          <p>{$tr(source.detail)}</p>
          <small>{$tr(source.keeps)}</small>
        </article>
      {/each}
    </div>
  </section>

  <section class="guide-grid">
    <div class="guide-panel">
      <h3>{$tr('Colour decisions')}</h3>
      <div class="decision-list">
        <div>
          <span class="decision-mark">{$tr('Bands')}</span>
          <p>{$tr('Layer-range colour changes can receive spool-stop notes before a toolhead needs a new spool.')}</p>
        </div>
        <div>
          <span class="decision-mark">{$tr('Paint')}</span>
          <p>{$tr('Painted geometry is decided by Orca while slicing, so review mappings there before printing.')}</p>
        </div>
      </div>
    </div>

    <div class="guide-panel">
      <h3>{$tr('Final inspection')}</h3>
      <ul class="ok-token-list">
        <li>{$tr('Confirm bed placement and object scale.')}</li>
        <li>{$tr('Review material slots and colour mapping.')}</li>
        <li>{$tr('Slice the saved package in Snapmaker Orca.')}</li>
        <li>{$tr('Move prime tower/model if Orca reports a plate conflict.')}</li>
      </ul>
    </div>
  </section>

  <section class="guide-panel faq-panel">
    <h3>{$tr('Quick answers')}</h3>
    <div class="faq">
      <details><summary>{$tr('Can I tune materials?')}</summary><p>{$tr('Yes. Use')} <button class="inline-link" type="button" onclick={() => onNavigate('rules')}>{$tr('Spool Tuning Lab')}</button> {$tr('to match spool metadata and apply repeatable process tweaks.')}</p></details>
      <details><summary>{$tr('Do I still need Snapmaker Orca?')}</summary><p>{$tr('Yes. MkWorld2Snap prepares the project package; Orca should create the final toolpaths.')}</p></details>
      <details><summary>{$tr('What happens to temporary files?')}</summary><p>{$tr('Temporary output files are kept briefly for saving, then cleaned automatically.')}</p></details>
      <details><summary>{$tr('What is the default upload limit?')}</summary><p>{@html $tr('500 MB unless you change <code>MAX_UPLOAD_MB</code>.')}</p></details>
    </div>
  </section>
</div>

<style>
  .guide { display: flex; flex-direction: column; gap: 16px; }

  h2, h3, p { margin: 0; }
  h2 { font-size: 21px; line-height: 1.15; }
  h3 { font-size: 14px; font-weight: 800; }
  p { font-size: 13.5px; line-height: 1.6; color: var(--text-muted); }
  .guide :global(code) { font-family: var(--font-mono); font-size: 12px; background: var(--bg-raised); padding: 1px 5px; border-radius: 3px; }

  .guide-banner {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 18px;
    align-items: stretch;
    padding: 20px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--sun) 22%, transparent), transparent 44%),
      var(--bg-elev);
  }
  .guide-banner p:last-child { max-width: 700px; margin-top: 9px; }
  .eyebrow {
    margin-bottom: 8px;
    font-size: 11px;
    font-weight: 950;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--accent);
  }
  .banner-stack {
    min-width: 128px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .banner-stack span {
    display: grid;
    place-items: center;
    min-height: 46px;
    border-radius: 10px;
    background: var(--ink);
    color: #fffdf8;
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 900;
  }
  .banner-stack span:nth-child(2) { background: var(--mint); color: #073b2d; }
  .banner-stack span:nth-child(3) { grid-column: 1 / -1; background: var(--rose); color: #4b1115; }

  .guide-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 16px;
  }
  .guide-panel {
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg-elev);
  }
  .guide-panel h3 { margin-bottom: 12px; }
  .panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
  .panel-head h3 { margin: 0; }

  .intake-list { display: grid; gap: 10px; }
  .intake-list div {
    display: grid;
    grid-template-columns: 82px minmax(0, 1fr);
    gap: 10px;
    align-items: baseline;
    padding: 10px;
    border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
    border-radius: 10px;
    background: var(--bg-raised);
  }
  .intake-list strong { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink); }
  .intake-list span { font-size: 13px; color: var(--text-muted); line-height: 1.45; }

  .change-strip {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 8px;
  }
  .change-strip span {
    min-height: 72px;
    display: flex;
    align-items: flex-end;
    padding: 10px;
    border-radius: 10px;
    background: var(--bg-raised);
    border: 1px solid var(--border);
    font-size: 12px;
    font-weight: 800;
  }

  .source-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
  }
  .source-card {
    min-height: 184px;
    padding: 13px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--bg-raised);
  }
  .source-top { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }
  .source-top strong { font-size: 13px; line-height: 1.25; }
  .source-top span {
    align-self: flex-start;
    padding: 3px 7px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 900;
    letter-spacing: .03em;
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: var(--accent);
  }
  .source-card.ok .source-top span { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
  .source-card.care .source-top span { background: color-mix(in srgb, var(--warning) 18%, transparent); color: #a16207; }
  .source-card p { font-size: 12.5px; line-height: 1.5; }
  .source-card small {
    display: block;
    margin-top: 10px;
    color: var(--text-subtle);
    font-size: 11px;
    line-height: 1.35;
  }

  .decision-list { display: grid; gap: 10px; }
  .decision-list div {
    display: grid;
    grid-template-columns: 62px minmax(0, 1fr);
    gap: 10px;
    padding: 11px;
    border-radius: 10px;
    background: var(--bg-raised);
    border: 1px solid var(--border);
  }
  .decision-mark {
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 900;
    color: var(--accent);
  }
  .decision-list p { font-size: 12.5px; }

  .ok-token-list { margin: 0; padding: 0; display: grid; gap: 8px; list-style: none; }
  .ok-token-list li {
    padding: 9px 10px;
    border-radius: 9px;
    background: var(--bg-raised);
    border: 1px solid color-mix(in srgb, var(--border) 65%, transparent);
    font-size: 13px;
    color: var(--text-muted);
  }

  .faq { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  details { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; background: var(--bg-raised); }
  summary { font-size: 13px; font-weight: 700; padding: 11px 12px; cursor: pointer; list-style: none; display: flex; justify-content: space-between; gap: 10px; }
  summary::-webkit-details-marker { display: none; }
  summary::after { content: '+'; color: var(--text-muted); font-size: 16px; font-weight: 400; }
  details[open] summary::after { content: '-'; }
  details p { padding: 0 12px 12px; font-size: 12.5px; }
  .inline-link {
    width: auto;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: var(--accent);
    font-weight: 900;
    box-shadow: none;
    vertical-align: baseline;
  }
  .inline-link:hover:not(:disabled) {
    background: transparent;
    color: var(--accent-hover);
    text-decoration: underline;
    transform: none;
  }

  @media (max-width: 720px) {
    .guide-banner, .guide-grid, .faq { grid-template-columns: 1fr; }
    .banner-stack { min-width: 0; }
    .change-strip, .source-grid { grid-template-columns: 1fr; }
  }
  @media (min-width: 721px) and (max-width: 1120px) {
    .source-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .change-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  }
</style>
