<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import { Box, Crosshair, Eye, RotateCcw } from 'lucide-svelte';
  import * as THREE from 'three';
  import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
  import { previewScene, previewSourceScene, previewUploadScene, type PreviewScene } from './engineClient';
  import { tr } from './i18n';

  interface Props {
    jobId?: string;
    sourceJob?: boolean;
    file?: File | null;
    compact?: boolean;
    heading?: string;
    eyebrow?: string;
  }

  let {
    jobId,
    sourceJob = false,
    file = null,
    compact = false,
    heading = 'Plate layout',
    eyebrow = '3D build preview',
  }: Props = $props();

  let host = $state<HTMLDivElement | null>(null);
  let sceneData = $state<PreviewScene | null>(null);
  let loading = $state(true);
  let error = $state('');
  let activePlate = $state<number | 'all'>('all');
  let cameraMode = $state<'iso' | 'top'>('iso');

  let renderer: THREE.WebGLRenderer | null = null;
  let threeScene: THREE.Scene | null = null;
  let camera: THREE.PerspectiveCamera | null = null;
  let controls: OrbitControls | null = null;
  let root: THREE.Group | null = null;
  let resizeObserver: ResizeObserver | null = null;
  let frame = 0;

  const visibleMeshes = $derived(
    sceneData
      ? activePlate === 'all'
        ? sceneData.stats.objects
        : sceneData.meshes.filter((mesh) => mesh.plate_id === activePlate).length
      : 0
  );

  onMount(async () => {
    await load();
  });

  onDestroy(() => {
    disposeThree();
  });

  async function load() {
    loading = true;
    error = '';
    try {
      if (jobId) {
        sceneData = sourceJob ? await previewSourceScene(jobId) : await previewScene(jobId);
      } else if (file) {
        sceneData = await previewUploadScene(file);
      } else {
        sceneData = null;
      }
      await tick();
      mountThree();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  function mountThree() {
    if (!host || !sceneData) return;
    disposeThree();

    threeScene = new THREE.Scene();
    threeScene.background = new THREE.Color(0xf3f5f4);
    root = new THREE.Group();
    threeScene.add(root);

    const bounds = sceneData.bounds;
    const centerX = (bounds.min[0] + bounds.max[0]) / 2;
    const centerY = (bounds.min[1] + bounds.max[1]) / 2;
    const maxSpan = Math.max(bounds.max[0] - bounds.min[0], bounds.max[1] - bounds.min[1], 160);
    root.position.set(-centerX, 0, centerY);

    addLighting(threeScene);
    addPlates(root, sceneData);
    addMeshes(root, sceneData);

    const width = Math.max(compact ? 220 : 320, host.clientWidth);
    const height = Math.max(compact ? 220 : 280, host.clientHeight);
    camera = new THREE.PerspectiveCamera(38, width / height, 0.1, maxSpan * 8);
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.appendChild(renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.target.set(0, 0, 0);
    controls.minDistance = maxSpan * 0.35;
    controls.maxDistance = maxSpan * 3.8;

    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(host);
    setCamera(cameraMode);
    animate();
  }

  function addLighting(scene: THREE.Scene) {
    scene.add(new THREE.HemisphereLight(0xffffff, 0xb8c2c0, 1.9));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(180, 260, 160);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xbfefff, 0.8);
    fill.position.set(-160, 120, -160);
    scene.add(fill);
  }

  function addPlates(group: THREE.Group, data: PreviewScene) {
    for (const plate of data.plates) {
      const [originX, originY] = plate.origin;
      const [width, depth] = plate.size;
      const plateGroup = new THREE.Group();
      plateGroup.name = `plate-${plate.id}`;
      plateGroup.userData.plateId = plate.id;

      const base = new THREE.Mesh(
        new THREE.BoxGeometry(width, 2.2, depth),
        new THREE.MeshStandardMaterial({
          color: plate.id === 1 ? 0x2f3837 : 0xd9dddc,
          roughness: 0.86,
          metalness: 0.05,
        })
      );
      base.position.set(originX + width / 2, -1.4, -(originY + depth / 2));
      base.receiveShadow = true;
      plateGroup.add(base);

      plateGroup.add(makeGrid(originX, originY, width, depth, plate.id === 1 ? 0x71807c : 0xffffff));
      plateGroup.add(makeOutline(originX, originY, width, depth, plate.id === 1 ? 0xff6540 : 0xff7a43));
      group.add(plateGroup);
    }
  }

  function makeGrid(originX: number, originY: number, width: number, depth: number, color: number) {
    const step = 10;
    const positions: number[] = [];
    for (let x = originX; x <= originX + width + 0.01; x += step) {
      positions.push(x, 0.06, -originY, x, 0.06, -(originY + depth));
    }
    for (let y = originY; y <= originY + depth + 0.01; y += step) {
      positions.push(originX, 0.06, -y, originX + width, 0.06, -y);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    return new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.42 })
    );
  }

  function makeOutline(originX: number, originY: number, width: number, depth: number, color: number) {
    const z0 = -originY;
    const z1 = -(originY + depth);
    const x0 = originX;
    const x1 = originX + width;
    const positions = [x0, 0.22, z0, x1, 0.22, z0, x1, 0.22, z0, x1, 0.22, z1, x1, 0.22, z1, x0, 0.22, z1, x0, 0.22, z1, x0, 0.22, z0];
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    return new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, linewidth: 2 }));
  }

  function addMeshes(group: THREE.Group, data: PreviewScene) {
    for (const mesh of data.meshes) {
      const geometry = new THREE.BufferGeometry();
      const positions: number[] = [];
      const colors: number[] = [];
      const fallback = new THREE.Color(mesh.color || '#d8d5ce');

      for (let i = 0; i < mesh.indices.length; i += 3) {
        const triColor = new THREE.Color(mesh.triangle_colors[Math.floor(i / 3)] || mesh.color || '#d8d5ce');
        for (let j = 0; j < 3; j += 1) {
          const vertexIndex = mesh.indices[i + j] * 3;
          const x = mesh.vertices[vertexIndex];
          const y = mesh.vertices[vertexIndex + 1];
          const z = mesh.vertices[vertexIndex + 2];
          positions.push(x, z, -y);
          colors.push(triColor.r, triColor.g, triColor.b);
        }
      }

      geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
      geometry.computeVertexNormals();

      const material = new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 0.72,
        metalness: 0.02,
        side: THREE.DoubleSide,
      });
      const rendered = new THREE.Mesh(geometry, material);
      rendered.name = mesh.name;
      rendered.castShadow = true;
      rendered.receiveShadow = true;
      rendered.userData.plateId = mesh.plate_id;
      group.add(rendered);
    }
  }

  function setCamera(mode: 'iso' | 'top') {
    cameraMode = mode;
    if (!camera || !controls || !sceneData) return;
    const bounds = sceneData.bounds;
    const span = Math.max(bounds.max[0] - bounds.min[0], bounds.max[1] - bounds.min[1], 160);
    if (mode === 'top') {
      camera.position.set(0, span * 1.55, 0.01);
    } else {
      camera.position.set(span * 0.62, span * 0.72, span * 0.92);
    }
    controls.target.set(0, 0, 0);
    controls.update();
  }

  function showPlate(value: number | 'all') {
    activePlate = value;
    if (!root) return;
    root.children.forEach((child) => {
      const plateId = child.userData.plateId as number | undefined;
      if (!plateId) return;
      child.visible = value === 'all' || plateId === value;
    });
  }

  function resize() {
    if (!host || !renderer || !camera) return;
    const width = Math.max(320, host.clientWidth);
    const height = Math.max(280, host.clientHeight);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }

  function animate() {
    if (!renderer || !threeScene || !camera) return;
    controls?.update();
    renderer.render(threeScene, camera);
    frame = requestAnimationFrame(animate);
  }

  function disposeThree() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    resizeObserver?.disconnect();
    resizeObserver = null;
    controls?.dispose();
    controls = null;
    if (renderer) {
      renderer.dispose();
      renderer.domElement.remove();
      renderer = null;
    }
    if (threeScene) {
      threeScene.traverse((object) => {
        const mesh = object as THREE.Mesh;
        mesh.geometry?.dispose?.();
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(material)) material.forEach((entry) => entry.dispose());
        else material?.dispose?.();
      });
      threeScene = null;
    }
    camera = null;
    root = null;
  }
</script>

<section class="scene-shell card" class:compact aria-label={$tr('3D preview')}>
  <div class="scene-head">
    <div>
      <div class="scene-kicker">
        <Box size={15} strokeWidth={2.4} aria-hidden="true" />
        {eyebrow}
      </div>
      <h3>{heading}</h3>
    </div>
    <div class="scene-actions">
      <button type="button" class:active={cameraMode === 'iso'} onclick={() => setCamera('iso')} title={$tr('Isometric view')}>
        <Eye size={15} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Iso')}
      </button>
      <button type="button" class:active={cameraMode === 'top'} onclick={() => setCamera('top')} title={$tr('Top view')}>
        <Crosshair size={15} strokeWidth={2.4} aria-hidden="true" />
        {$tr('Top')}
      </button>
      <button type="button" onclick={() => setCamera(cameraMode)} title={$tr('Reset camera')}>
        <RotateCcw size={15} strokeWidth={2.4} aria-hidden="true" />
      </button>
    </div>
  </div>

  {#if sceneData}
    <div class="plate-tabs" aria-label={$tr('Visible plate')}>
      <button type="button" class:active={activePlate === 'all'} onclick={() => showPlate('all')}>{$tr('All')}</button>
      {#if !compact || sceneData.plates.length > 1}
        {#each sceneData.plates as plate (plate.id)}
          <button type="button" class:active={activePlate === plate.id} onclick={() => showPlate(plate.id)}>
            {$tr('Plate')} {plate.id}
          </button>
        {/each}
      {/if}
    </div>
  {/if}

  <div class="viewport-wrap">
    <div class="viewport" bind:this={host}>
      {#if loading}
        <div class="scene-overlay">{$tr('Loading geometry...')}</div>
      {:else if error}
        <div class="scene-overlay error">{error}</div>
      {/if}
    </div>
  </div>

  {#if sceneData}
    <div class="scene-foot">
      <span>{visibleMeshes} {visibleMeshes === 1 ? $tr('object') : $tr('objects')}</span>
      <span>{sceneData.stats.triangles.toLocaleString()} {$tr('triangles')}</span>
      <span>{sceneData.plates.length} {sceneData.plates.length === 1 ? $tr('plate') : $tr('plates')}</span>
      {#if sceneData.stats.truncated}
        <span class="warn">{$tr('preview capped at')} {sceneData.stats.max_triangles.toLocaleString()} {$tr('triangles')}</span>
      {/if}
    </div>
  {/if}
</section>

<style>
  .scene-shell {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 16px;
    border-radius: 18px;
    overflow: hidden;
    background:
      linear-gradient(145deg, color-mix(in srgb, var(--teal) 10%, transparent), transparent 42%),
      var(--bg-elev);
  }
  .scene-shell.compact {
    gap: 10px;
    padding: 12px;
    border-radius: 16px;
  }

  .scene-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .scene-kicker {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 900;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  h3 {
    margin: 3px 0 0;
    font-size: 21px;
    line-height: 1.1;
  }
  .compact h3 {
    font-size: 16px;
    margin-top: 1px;
  }
  .compact .scene-kicker {
    font-size: 10px;
  }

  .scene-actions,
  .plate-tabs,
  .scene-foot {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .scene-actions button,
  .plate-tabs button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 34px;
    padding: 7px 10px;
    border-radius: 10px;
    border: 1px solid var(--border-strong);
    background: var(--bg-raised);
    color: var(--text);
    font-weight: 850;
    cursor: pointer;
  }
  .compact .scene-actions button,
  .compact .plate-tabs button {
    min-height: 30px;
    padding: 5px 8px;
    border-radius: 9px;
    font-size: 12px;
  }
  .scene-actions button.active,
  .plate-tabs button.active {
    background: var(--ink);
    color: #fff;
    border-color: var(--ink);
  }

  .viewport-wrap {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid var(--border-strong);
    background: #eef1f0;
  }
  .viewport {
    position: relative;
    height: clamp(300px, 40vh, 520px);
    min-height: 300px;
  }
  .compact .viewport {
    height: 220px;
    min-height: 220px;
  }
  .viewport :global(canvas) {
    display: block;
    width: 100%;
    height: 100%;
  }
  .scene-overlay {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    padding: 24px;
    color: var(--text-muted);
    font-weight: 900;
    background: color-mix(in srgb, var(--bg-elev) 78%, transparent);
    z-index: 1;
  }
  .scene-overlay.error {
    color: var(--danger);
  }

  .scene-foot {
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 800;
  }
  .compact .scene-foot {
    gap: 5px;
    font-size: 11px;
  }
  .compact .scene-foot span {
    padding: 4px 7px;
  }
  .scene-foot span {
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg-raised);
  }
  .scene-foot .warn {
    color: var(--warn);
    border-color: color-mix(in srgb, var(--warn) 45%, var(--border));
  }

  @media (max-width: 720px) {
    .scene-head {
      align-items: flex-start;
      flex-direction: column;
    }
    .viewport {
      height: 320px;
    }
  }
</style>
