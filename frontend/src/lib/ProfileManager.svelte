<script lang="ts">
  import { onMount } from 'svelte';
  import { FolderPlus, RefreshCw, Trash2 } from 'lucide-svelte';
  import { deleteReferenceProfile, importReferenceProfiles, listProfiles, type ProfileDescriptor } from './engineClient';
  import { tr } from './i18n';

  let profiles = $state<ProfileDescriptor[]>([]);
  let loading = $state(false);
  let importing = $state(false);
  let message = $state('');
  let error = $state('');
  let inputEl: HTMLInputElement | undefined = $state();

  const userCount = $derived(profiles.filter((profile) => profile.source === 'user').length);

  onMount(() => {
    void refresh();
  });

  async function refresh() {
    loading = true;
    error = '';
    try {
      profiles = await listProfiles();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  async function importFiles(files: FileList | null | undefined) {
    const picked = Array.from(files ?? []).filter((file) => file.name.toLowerCase().endsWith('.3mf'));
    if (!picked.length) return;
    importing = true;
    message = '';
    error = '';
    try {
      const result = await importReferenceProfiles(picked);
      profiles = result.profiles;
      const imported = result.imported.length;
      const failed = result.errors.length;
      message = $tr('Imported {count} profile(s)', { count: imported });
      if (failed) {
        error = result.errors.map((entry) => `${entry.name}: ${entry.error}`).join('\n');
      }
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      importing = false;
      if (inputEl) inputEl.value = '';
    }
  }

  async function remove(profile: ProfileDescriptor) {
    if (profile.source !== 'user') return;
    if (!confirm($tr('Delete imported profile "{name}"?', { name: profile.display_name }))) return;
    error = '';
    try {
      profiles = (await deleteReferenceProfile(profile.id)).profiles;
      message = $tr('Profile deleted');
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  function profileLocationLabel(profile: ProfileDescriptor): string {
    return profile.source === 'user'
      ? $tr('Stored in imported profiles')
      : $tr('Stored in bundled U1 profiles');
  }
</script>

<section class="profile-manager card card-padded" aria-label={$tr('U1 profile manager')}>
  <div class="profile-head">
    <div>
      <span class="eyebrow">{$tr('U1 profile manager')}</span>
      <h2>{$tr('Reference profiles')}</h2>
      <p>{$tr('Import Snapmaker Orca 3MF projects as selectable U1 reference profiles. Bundled profiles stay read-only.')}</p>
    </div>
    <div class="profile-actions">
      <input
        bind:this={inputEl}
        type="file"
        accept=".3mf"
        multiple
        style="display:none"
        onchange={(event) => importFiles(event.currentTarget.files)}
      />
      <button class="ghost" type="button" onclick={refresh} disabled={loading || importing}>
        <RefreshCw size={16} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Refresh')}
      </button>
      <button class="primary" type="button" onclick={() => inputEl?.click()} disabled={importing}>
        <FolderPlus size={16} strokeWidth={2.4} aria-hidden="true" />
        {importing ? $tr('Importing...') : $tr('Import profiles')}
      </button>
    </div>
  </div>

  <div class="profile-stats">
    <span><strong>{profiles.length}</strong> {$tr('profiles')}</span>
    <span><strong>{userCount}</strong> {$tr('imported')}</span>
  </div>

  {#if message}
    <div class="profile-message">{message}</div>
  {/if}
  {#if error}
    <div class="profile-error" role="alert">{error}</div>
  {/if}

  <div class="profile-list">
    {#each profiles as profile (profile.id)}
      <article class="profile-row" class:user={profile.source === 'user'}>
        <div class="profile-copy">
          <strong>{profile.display_name}</strong>
          <span>{profileLocationLabel(profile)}</span>
        </div>
        <div class="profile-tags">
          <span>{profile.source === 'user' ? $tr('Imported') : $tr('Bundled')}</span>
          {#if profile.layer_height}<span>{profile.layer_height} mm</span>{/if}
          {#if profile.printer_variant}<span>{profile.printer_variant}</span>{/if}
        </div>
        <button class="ghost delete-profile" type="button" disabled={profile.source !== 'user'} onclick={() => remove(profile)} title={$tr('Delete imported profile')}>
          <Trash2 size={15} strokeWidth={2.4} aria-hidden="true" />
        </button>
      </article>
    {/each}
  </div>
</section>

<style>
  .profile-manager {
    display: flex;
    flex-direction: column;
    gap: 14px;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--sun) 15%, transparent), transparent 52%),
      var(--bg-elev);
  }

  .profile-head,
  .profile-actions,
  .profile-stats,
  .profile-row,
  .profile-tags {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .profile-head {
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

  .profile-actions {
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .profile-stats {
    flex-wrap: wrap;
  }

  .profile-stats span {
    padding: 6px 9px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg-elev);
    color: var(--text-muted);
    font-size: 12px;
  }

  .profile-stats strong {
    color: var(--text);
    font-weight: 950;
  }

  .profile-message,
  .profile-error {
    white-space: pre-wrap;
    padding: 9px 11px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 850;
  }

  .profile-message {
    color: var(--success);
    background: color-mix(in srgb, var(--success) 10%, var(--bg-elev));
  }

  .profile-error {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, var(--bg-elev));
  }

  .profile-list {
    display: grid;
    gap: 7px;
    max-height: 420px;
    overflow: auto;
    padding-right: 4px;
  }

  .profile-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto 34px;
    padding: 9px 10px;
    border-radius: 12px;
    border: 1px solid var(--border);
    background: color-mix(in srgb, var(--bg-elev) 82%, transparent);
  }

  .profile-row.user {
    border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  }

  .profile-copy {
    min-width: 0;
    display: grid;
    gap: 3px;
  }

  .profile-copy strong,
  .profile-copy span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .profile-copy strong {
    color: var(--text);
    font-size: 13px;
    font-weight: 950;
  }

  .profile-copy span {
    color: var(--text-muted);
    font-size: 11px;
  }

  .profile-tags {
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .profile-tags span {
    padding: 4px 7px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--mint) 18%, var(--bg-raised));
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 850;
  }

  .delete-profile {
    width: 30px;
    height: 30px;
    padding: 0;
  }

  @media (max-width: 760px) {
    .profile-head {
      flex-direction: column;
    }
    .profile-row {
      grid-template-columns: minmax(0, 1fr) 34px;
    }
    .profile-tags {
      grid-column: 1 / -1;
      justify-content: flex-start;
    }
  }
</style>
