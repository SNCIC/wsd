/**
 * 仓库 3D 运输看板 · 场景构建器
 * 被 OWL 组件调用：SnWarehouse3D.mount(el, { data }) → { update(data), destroy() }
 *
 * 约定：几何布局（货架位置、路径）固定在本文件；业务数据（占用率/拣货位/叉车任务）
 * 由后端 sn.wsd.warehouse.3d.screen.service 提供，前端只做映射。
 */
import * as THREE from 'three';
import { OrbitControls } from '../static/src/lib/three/controls/OrbitControls.js';
import { EffectComposer } from '../static/src/lib/three/postprocessing/EffectComposer.js';
import { RenderPass } from '../static/src/lib/three/postprocessing/RenderPass.js';
import { UnrealBloomPass } from '../static/src/lib/three/postprocessing/UnrealBloomPass.js';
import { OutputPass } from '../static/src/lib/three/postprocessing/OutputPass.js';

/* ================= 色板（科技蓝） ================= */
const C = {
  ground: 0x05192b, gridA: 0x0e3d5a, gridB: 0x0a2a42,
  wall: 0x081b2c, wallEdge: 0x11405c, door: 0x020b16,
  post: 0x0f3556, beam: 0x1f8fd6,
  wood: 0x5b4229, carton: [0x1b4463, 0x22587d, 0x143750], wrap: 0x0a7ea4,
  truckBody: 0x15628f, truckBox: 0x0a1f33, dark: 0x0a1c2c, metal: 0x3f7fa0,
  cyan: 0x00e5ff, amber: 0xffb020,
};

/* 货架固定布局 */
const LAYOUT = {
  A1: { x: 2, z: -15, rot: 0 },
  A2: { x: 17, z: -15, rot: 0 },
  B1: { x: 25.5, z: -1, rot: Math.PI / 2 },
};
const BAY_W = 2.3, RACK_DEPTH = 1.5, RACK_H = 4.2;

/* 叉车路线（世界坐标固定） */
const PATH_DEFS = {
  p1: [[-4, 0], [8, -1], [12, 8], [-2, 9]],
  p2: [[16, 2], [25, 4], [25, 11], [15, 10]],
  wp: [[-8, 3], [-2, 6], [2, 1], [-5, -2]],
};

export function mount(el, opts = {}) {
  const state = {
    disposed: false,
    raf: 0,
    movers: [],
    racks: new Map(),
    pick: null,
    pickLabel: null,
    pickLabelKey: '',
    ring1: null, ring2: null, beam: null,
    tipped: null,
  };

  /* ---------- 渲染器 ---------- */
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(el.clientWidth || 1, el.clientHeight || 1);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.domElement.style.display = 'block';
  el.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x02101f, 78, 160);

  const camera = new THREE.PerspectiveCamera(42, (el.clientWidth || 1) / (el.clientHeight || 1), 0.1, 400);
  camera.position.set(45, 35, 48);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(7, 0, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.minDistance = 18;
  controls.maxDistance = 78;
  controls.maxPolarAngle = Math.PI / 2.15;
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };

  /* ---------- 灯光 ---------- */
  scene.add(new THREE.HemisphereLight(0x1b4a70, 0x01060e, 1.5));
  const keyLight = new THREE.DirectionalLight(0xbfeaff, 1.5);
  keyLight.position.set(24, 38, 18);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(2048, 2048);
  keyLight.shadow.camera.left = -45; keyLight.shadow.camera.right = 45;
  keyLight.shadow.camera.top = 42; keyLight.shadow.camera.bottom = -42;
  keyLight.shadow.bias = -0.0005;
  scene.add(keyLight);
  const rim = new THREE.DirectionalLight(0x2b7bff, 0.85);
  rim.position.set(-22, 14, -18);
  scene.add(rim);
  const pickLight = new THREE.PointLight(C.cyan, 22, 12, 2);
  pickLight.position.set(17.5, 3.2, -13.4);
  scene.add(pickLight);

  /* ---------- 材质 / 盒子 ---------- */
  const matCache = new Map();
  function mat(color, o = {}) {
    const k = `${color}|${o.rough ?? 0.85}|${o.metal ?? 0.05}|${o.emissive ?? 0}|${o.ei ?? 1}|${o.opacity ?? 1}`;
    if (!matCache.has(k)) {
      matCache.set(k, new THREE.MeshStandardMaterial({
        color,
        roughness: o.rough ?? 0.85,
        metalness: o.metal ?? 0.05,
        emissive: o.emissive ?? 0x000000,
        emissiveIntensity: o.ei ?? 1,
        transparent: o.opacity !== undefined && o.opacity < 1,
        opacity: o.opacity ?? 1,
      }));
    }
    return matCache.get(k);
  }
  function box(w, h, d, color, { x = 0, y = 0, z = 0, cast = true, recv = false, ...o } = {}) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(color, o));
    m.position.set(x, y + h / 2, z);
    m.castShadow = cast;
    m.receiveShadow = recv;
    return m;
  }

  const root = new THREE.Group();
  scene.add(root);

  /* ---------- 地面 ---------- */
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(96, 74), mat(C.ground, { rough: 0.95 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  root.add(ground);

  const grid = new THREE.GridHelper(96, 48, C.gridA, C.gridB);
  grid.position.y = 0.012;
  grid.material.transparent = true;
  grid.material.opacity = 0.55;
  root.add(grid);

  const halo = new THREE.Mesh(
    new THREE.RingGeometry(40, 46, 64),
    new THREE.MeshBasicMaterial({ color: C.cyan, transparent: true, opacity: 0.05, side: THREE.DoubleSide, depthWrite: false })
  );
  halo.rotation.x = -Math.PI / 2;
  halo.position.y = 0.015;
  root.add(halo);

  /* ---------- 文字精灵 ---------- */
  function textSprite(text, { w = 5, h = 1.3, fs = 150, sub = '' } = {}) {
    const c = document.createElement('canvas');
    c.width = 512;
    c.height = Math.round(512 * h / w);
    const g = c.getContext('2d');
    const r = 22, W = c.width, H = c.height;
    g.beginPath();
    g.moveTo(r, 0); g.arcTo(W, 0, W, H, r); g.arcTo(W, H, 0, H, r);
    g.arcTo(0, H, 0, 0, r); g.arcTo(0, 0, W, 0, r); g.closePath();
    g.fillStyle = 'rgba(4,26,48,.92)';
    g.fill();
    g.strokeStyle = 'rgba(0,229,255,.5)';
    g.lineWidth = 5;
    g.stroke();
    g.fillStyle = '#00e5ff';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.shadowColor = '#00e5ff';
    g.shadowBlur = 16;
    // 按可用宽度自动缩小字号，长单号不裁切
    const fit = (content, baseFs, weight) => {
      let size = baseFs;
      g.font = `${weight} ${size}px "Microsoft YaHei", sans-serif`;
      const measured = g.measureText(content).width;
      if (measured > W - 44) {
        size = Math.max(18, Math.floor(baseFs * (W - 44) / measured));
        g.font = `${weight} ${size}px "Microsoft YaHei", sans-serif`;
      }
      return size;
    };
    if (sub) {
      const mainFs = fit(text, fs * 0.78, 900);
      g.fillText(text, W / 2, H * 0.36);
      fit(sub, fs * 0.44, 600);
      g.fillStyle = 'rgba(0,229,255,.75)';
      g.fillText(sub, W / 2, H * 0.73);
      void mainFs;
    } else {
      const mainFs = fit(text, fs, 900);
      g.fillText(text, W / 2, H / 2 + mainFs * 0.05);
    }
    const tex = new THREE.CanvasTexture(c);
    tex.anisotropy = 8;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    sp.scale.set(w, h, 1);
    return sp;
  }

  function floorText(text, x, z, { size = 3.6 } = {}) {
    const c = document.createElement('canvas');
    c.width = 1024; c.height = 256;
    const g = c.getContext('2d');
    g.font = '900 120px "Microsoft YaHei", sans-serif';
    g.fillStyle = 'rgba(0,229,255,.20)';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(text, 512, 132);
    const tex = new THREE.CanvasTexture(c);
    tex.anisotropy = 8;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(size * 4, size),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }));
    m.rotation.x = -Math.PI / 2;
    m.position.set(x, 0.03, z);
    root.add(m);
  }

  /* ---------- 墙体 / 库门（静态布景） ---------- */
  root.add(box(68, 8.5, 0.6, C.wall, { z: -22, cast: false, recv: true }));
  root.add(box(68, 0.22, 0.8, C.wallEdge, { y: 8.5, z: -22, cast: false, emissive: C.cyan, ei: 0.5 }));
  [-24, -10].forEach((x, i) => {
    root.add(box(5, 5.4, 0.3, C.door, { x, z: -21.7, cast: false }));
    root.add(box(5.6, 0.22, 0.5, C.wallEdge, { x, y: 5.4, z: -21.7, cast: false }));
    [-2.65, 2.65].forEach(dx => {
      root.add(box(0.24, 5.4, 0.5, C.wallEdge, { x: x + dx, z: -21.7, cast: false, emissive: C.cyan, ei: 0.35 }));
    });
    const sign = textSprite(`0${i + 1}`, { w: 2.2, h: 0.95, fs: 170 });
    sign.position.set(x, 6.5, -21.3);
    root.add(sign);
  });
  root.add(box(2.2, 4.2, 0.25, 0x0a5f8a, { x: 10, z: -21.75, cast: false, emissive: C.cyan, ei: 0.35 }));

  // 地面分区
  [[-19, 7, 16, 18, '收货区 INBOUND'], [2, 4, 30, 22, '拣货区 PICKING'], [22, 16, 18, 12, '出库暂存 OUTBOUND']]
    .forEach(([x, z, w, d, label]) => {
      const p = new THREE.Mesh(new THREE.PlaneGeometry(w, d),
        new THREE.MeshBasicMaterial({ color: C.cyan, transparent: true, opacity: 0.045, depthWrite: false, blending: THREE.AdditiveBlending }));
      p.rotation.x = -Math.PI / 2;
      p.position.set(x, 0.02, z);
      root.add(p);
      floorText(label, x, z);
    });

  /* ---------- 托盘 ---------- */
  function seededRand(seed) {
    let s = seed % 2147483647;
    if (s <= 0) s += 2147483646;
    return () => (s = s * 16807 % 2147483647) / 2147483647;
  }
  function buildPallet({ boxes = 2, wrap = false, highlight = false } = {}) {
    const g = new THREE.Group();
    g.add(box(1.15, 0.12, 1.15, C.wood));
    const rnd = seededRand(boxes * 97 + (wrap ? 5 : 1));
    const placed = [];
    for (let i = 0; i < boxes; i++) {
      const s = 0.55 + rnd() * 0.35;
      const px = (rnd() - 0.5) * (1.0 - s);
      const pz = (rnd() - 0.5) * (1.0 - s);
      let py = 0.12;
      for (const [ox, oz, os] of placed) {
        if (Math.abs(px - ox) < (s + os) / 2 + 0.02 && Math.abs(pz - oz) < (s + os) / 2 + 0.02) py += 0.62;
      }
      g.add(box(s, 0.6, s, C.carton[i % C.carton.length], { x: px, y: py, z: pz }));
      if (wrap) g.add(box(s + 0.02, 0.1, s + 0.02, C.wrap, { x: px, y: py + 0.2, z: pz, cast: false, emissive: C.wrap, ei: 0.8 }));
      placed.push([px, pz, s]);
    }
    if (highlight) {
      g.add(box(0.72, 0.66, 0.72, 0x0a4a66, { y: 0.12, emissive: C.cyan, ei: 0.45 }));
      g.add(box(0.78, 0.09, 0.78, C.cyan, { y: 0.6, cast: false, emissive: C.cyan, ei: 1.6 }));
    }
    return g;
  }

  /* ---------- 货架 ---------- */
  function buildRack(cfg) {
    const lay = LAYOUT[cfg.id] || LAYOUT.A1;
    const bays = Math.max(2, cfg.bays || 5);
    const g = new THREE.Group();
    g.position.set(lay.x, 0, lay.z);
    g.rotation.y = lay.rot;
    const totalW = bays * BAY_W;

    for (let i = 0; i <= bays; i++) {
      const px = -totalW / 2 + i * BAY_W;
      [-RACK_DEPTH / 2, RACK_DEPTH / 2].forEach(pz => {
        g.add(box(0.12, RACK_H, 0.12, C.post, { x: px, z: pz, emissive: 0x0a4a72, ei: 0.4 }));
      });
    }
    const levels = [0.55, 1.85, 3.15];
    levels.forEach(ly => {
      [-RACK_DEPTH / 2 + 0.1, RACK_DEPTH / 2 - 0.1].forEach(pz => {
        g.add(box(totalW, 0.09, 0.08, C.beam, { y: ly, z: pz, emissive: C.cyan, ei: 0.35 }));
      });
    });

    const goods = new THREE.Group();
    const cells = [];
    const rnd = seededRand(cfg.id.charCodeAt(0) * 31 + cfg.id.charCodeAt(1));
    for (let b = 0; b < bays; b++) {
      levels.forEach(ly => {
        const v = rnd();
        const p = buildPallet({ boxes: 1 + Math.floor(rnd() * 3), wrap: rnd() < 0.4 });
        p.position.set(-totalW / 2 + (b + 0.5) * BAY_W, ly, 0);
        p.visible = v <= (cfg.occupancy ?? 0.8);
        goods.add(p);
        cells.push({ obj: p, v });
      });
    }
    g.add(goods);

    const sign = textSprite(cfg.id, { w: 2.4, h: 1.6, fs: 190 });
    sign.position.set(totalW / 2 + 0.6, RACK_H + 0.95, 0);
    g.add(sign);

    g.userData = {
      id: cfg.id, cells, bays,
      info: { title: cfg.title || `货架 ${cfg.id}`, lines: cfg.stats || [] },
    };
    g.traverse(o => { if (o.isMesh) o.userData.owner = g; });
    root.add(g);
    state.racks.set(cfg.id, g);
    return g;
  }

  /* ---------- 叉车 ---------- */
  function buildForklift({ body = 0x1f8fd6, carry = false, info = null } = {}) {
    const g = new THREE.Group();
    g.add(box(1.3, 0.52, 2.1, body, { z: -0.15 }));
    g.add(box(1.1, 0.48, 0.9, C.dark, { y: 0.52, z: -0.85 }));
    g.add(box(1.18, 0.07, 1.4, 0x123a55, { y: 0.52, z: -0.1 }));
    g.add(box(1.2, 0.1, 0.14, C.cyan, { y: 0.62, z: -1.0, cast: false, emissive: C.cyan, ei: 1.2 }));
    [-0.5, 0.5].forEach(px => g.add(box(0.07, 1.3, 0.07, 0x0e2c44, { x: px, y: 0.58, z: 0.1 })));
    g.add(box(1.12, 0.06, 0.98, 0x0e2c44, { y: 1.86, z: 0.1 }));
    [-0.42, 0.42].forEach(px => g.add(box(0.09, 2.4, 0.1, 0x14344f, { x: px, y: 0.34, z: 1.0 })));
    [-0.3, 0.3].forEach(px => g.add(box(0.15, 0.05, 1.1, C.metal, { x: px, y: 0.34, z: 1.65, metal: 0.6, rough: 0.35 })));
    const wheelGeo = new THREE.CylinderGeometry(0.31, 0.31, 0.21, 18);
    [[-0.68, 0.7], [0.68, 0.7], [-0.62, -0.75], [0.62, -0.75]].forEach(([px, pz]) => {
      const w = new THREE.Mesh(wheelGeo, mat(0x061420, { rough: 0.9 }));
      w.rotation.z = Math.PI / 2;
      w.position.set(px, 0.31, pz);
      w.castShadow = true;
      g.add(w);
    });
    g.add(box(0.38, 0.44, 0.28, 0x0a5f8a, { y: 0.6, z: -0.15, emissive: C.cyan, ei: 0.25 }));
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 12), mat(0xe8c49e));
    head.position.set(0, 1.26, -0.15);
    head.castShadow = true;
    g.add(head);
    g.add(box(0.34, 0.09, 0.34, C.cyan, { y: 1.37, z: -0.15, emissive: C.cyan, ei: 0.5 }));
    if (carry) {
      const p = buildPallet({ boxes: 2, highlight: true });
      p.position.set(0, 0.39, 1.6);
      g.add(p);
    }
    g.userData.info = info || { title: '叉车', lines: [] };
    root.add(g);
    g.traverse(o => { if (o.isMesh) o.userData.owner = g; });
    return g;
  }

  function addMover(obj, points, speed) {
    const curve = new THREE.CatmullRomCurve3(
      points.map(([x, z]) => new THREE.Vector3(x, 0, z)), true, 'catmullrom', 0.4
    );
    state.movers.push({ obj, curve, t: Math.random(), speed });
    const pts = curve.getPoints(160).map(p => new THREE.Vector3(p.x, 0.05, p.z));
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineDashedMaterial({ color: C.cyan, dashSize: 0.55, gapSize: 0.35, transparent: true, opacity: 0.5 }));
    line.computeLineDistances();
    root.add(line);
  }

  /* ---------- 卡车 ---------- */
  function buildTruck(info) {
    const g = new THREE.Group();
    g.position.set(-27.5, 0, -15.5);
    g.rotation.y = Math.PI / 2;
    g.add(box(2.2, 1.9, 2.4, C.truckBody, { z: 4.4 }));
    g.add(box(2.0, 0.7, 0.5, 0x0a3d5c, { y: 1.1, z: 5.55, emissive: C.cyan, ei: 0.25 }));
    g.add(box(2.4, 2.6, 6.4, C.truckBox, { z: 0.2 }));
    g.add(box(2.5, 0.14, 6.6, 0x155a86, { z: 0.2, emissive: C.cyan, ei: 0.3 }));
    const wg = new THREE.CylinderGeometry(0.42, 0.42, 0.3, 18);
    [4.6, 1.6, -1.4, -2.6].forEach(pz => [-1.15, 1.15].forEach(px => {
      const w = new THREE.Mesh(wg, mat(0x061420));
      w.rotation.z = Math.PI / 2;
      w.position.set(px, 0.42, pz);
      w.castShadow = true;
      g.add(w);
    }));
    g.userData.info = info;
    root.add(g);
    g.traverse(o => { if (o.isMesh) o.userData.owner = g; });
    return g;
  }

  /* ---------- 输送线 ---------- */
  const conveyor = new THREE.Group();
  conveyor.position.set(6, 0, 13);
  conveyor.add(box(9, 0.32, 1.1, C.dark, { y: 0.55 }));
  for (let i = -4; i <= 4; i++) {
    const roller = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 1.0, 14), mat(C.metal, { metal: 0.65, rough: 0.3 }));
    roller.rotation.x = Math.PI / 2;
    roller.position.set(i, 0.8, 0);
    roller.castShadow = true;
    roller.userData.roller = true;
    conveyor.add(roller);
  }
  [-4, 0, 4].forEach(px => [-0.4, 0.4].forEach(pz => conveyor.add(box(0.1, 0.55, 0.1, 0x0e2c44, { x: px, z: pz }))));
  conveyor.add(box(9, 0.05, 0.06, C.cyan, { y: 0.72, z: 0.5, cast: false, emissive: C.cyan, ei: 1.1 }));
  const convPallet = buildPallet({ boxes: 2, wrap: true });
  convPallet.position.set(-2.2, 0.92, 0);
  conveyor.add(convPallet);
  conveyor.userData.info = { title: '输送分拣线', lines: ['包裹分拣中', '节拍 620 件/小时', '直通率 99.2%'] };
  root.add(conveyor);

  /* ---------- 工人 ---------- */
  function buildWorker(vest = C.cyan) {
    const g = new THREE.Group();
    g.add(box(0.32, 0.55, 0.19, 0x0a1c2c, { x: -0.1 }));
    g.add(box(0.32, 0.55, 0.19, 0x0a1c2c, { x: 0.1 }));
    g.add(box(0.48, 0.54, 0.26, 0x0a5f8a, { y: 0.55, emissive: C.cyan, ei: 0.2 }));
    g.add(box(0.12, 0.5, 0.27, vest, { y: 0.56, cast: false, emissive: vest, ei: 0.9 }));
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.14, 16, 12), mat(0xe8c49e));
    head.position.y = 1.28;
    head.castShadow = true;
    g.add(head);
    g.add(box(0.3, 0.08, 0.3, 0xdff8ff, { y: 1.37, emissive: C.cyan, ei: 0.35 }));
    g.userData.info = { title: '现场作业员', lines: ['班组：蓝组'] };
    root.add(g);
    g.traverse(o => { if (o.isMesh) o.userData.owner = g; });
    return g;
  }

  /* ---------- 静态布景 ---------- */
  function buildStatic() {
    [[13, 5, 3, true], [21, 13, 4, false], [24, 9, 2, true], [-16, 2, 3, false], [-20, -4, 2, false]]
      .forEach(([x, z, n, wrap]) => {
        for (let i = 0; i < n; i++) {
          const p = buildPallet({ boxes: 2, wrap });
          p.position.set(x + (i % 2) * 1.4, 0, z + Math.floor(i / 2) * 1.5);
          p.rotation.y = i % 2 ? 0.1 : -0.08;
          root.add(p);
        }
      });
    const wk1 = buildWorker();
    addMover(wk1, PATH_DEFS.wp, 0.03);
    const wk2 = buildWorker(C.amber);
    wk2.position.set(7.5, 0, 12.2);
    wk2.rotation.y = -1.2;
    state.truck = buildTruck({ title: '发运货车 · 月台 01', lines: [] });
    [[-4, -2], [10, 6], [-14, 6], [22, 4]].forEach(([x, z]) => {
      const lamp = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.06, 8), mat(C.cyan, { emissive: C.cyan, ei: 2.2 }));
      lamp.position.set(x, 0.09, z);
      root.add(lamp);
    });
  }
  buildStatic();

  /* ---------- 拣货位高亮 ---------- */
  function pickWorldPos(rackId, bay) {
    const lay = LAYOUT[rackId] || LAYOUT.A1;
    const rack = state.racks.get(rackId);
    const bays = rack ? rack.userData.bays : 5;
    const totalW = bays * BAY_W;
    const b = Math.min(Math.max(bay || 1, 1), bays);
    const lx = -totalW / 2 + (b - 0.5) * BAY_W;
    const lz = 2.0;
    const cos = Math.cos(lay.rot), sin = Math.sin(lay.rot);
    return { x: lay.x + lx * cos + lz * sin, z: lay.z - lx * sin + lz * cos };
  }

  function ensurePick() {
    if (state.pick) return;
    const g = new THREE.Group();
    const hi = buildPallet({ boxes: 2, highlight: true });
    g.add(hi);
    state.ring1 = new THREE.Mesh(new THREE.RingGeometry(0.95, 1.16, 48),
      new THREE.MeshBasicMaterial({ color: C.cyan, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false }));
    state.ring1.rotation.x = -Math.PI / 2;
    state.ring1.position.y = 0.06;
    g.add(state.ring1);
    state.ring2 = new THREE.Mesh(new THREE.RingGeometry(1.25, 1.32, 48),
      new THREE.MeshBasicMaterial({ color: C.cyan, transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false }));
    state.ring2.rotation.x = -Math.PI / 2;
    state.ring2.position.y = 0.06;
    g.add(state.ring2);
    state.beam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.9, 1.15, 3.2, 24, 1, true),
      new THREE.MeshBasicMaterial({ color: C.cyan, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending })
    );
    state.beam.position.y = 1.6;
    g.add(state.beam);
    g.userData.info = { title: '', lines: [] };
    g.traverse(o => { if (o.isMesh) o.userData.owner = g; });
    root.add(g);
    state.pick = g;
  }

  function setPickLabel(pick) {
    const key = `${pick.title}|${pick.sub || ''}`;
    if (state.pickLabelKey === key) return;
    state.pickLabelKey = key;
    if (state.pickLabel) {
      state.pickLabel.material.map.dispose();
      state.pickLabel.material.dispose();
      root.remove(state.pickLabel);
    }
    state.pickLabel = textSprite(pick.title || '', { w: 7.2, h: 1.42, fs: 74, sub: pick.sub || '' });
    state.pickLabel.position.set(state.pick.position.x, 3.5, state.pick.position.z);
    root.add(state.pickLabel);
  }

  /* ---------- 后期辉光 ---------- */
  let composer = null;
  try {
    composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    composer.addPass(new UnrealBloomPass(new THREE.Vector2(el.clientWidth || 1, el.clientHeight || 1), 0.62, 0.75, 0.62));
    composer.addPass(new OutputPass());
    composer.setSize(el.clientWidth || 1, el.clientHeight || 1);
  } catch (e) {
    composer = null; // 降级为普通渲染
  }

  /* ---------- 数据应用 ---------- */
  function applyData(data) {
    const sc = (data && data.scene) || {};
    // 货架
    (sc.racks || []).forEach(cfg => {
      let rack = state.racks.get(cfg.id);
      if (!rack) rack = buildRack(cfg);
      const occ = Math.max(0, Math.min(1, cfg.occupancy ?? 0.8));
      rack.userData.cells.forEach(cell => { cell.obj.visible = cell.v <= occ; });
      rack.userData.info = { title: cfg.title || `货架 ${cfg.id}`, lines: cfg.stats || [] };
    });

    // 拣货位
    const pick = sc.pick;
    if (pick && pick.rack) {
      ensurePick();
      const pos = pickWorldPos(pick.rack, pick.bay);
      state.pick.position.set(pos.x, 0, pos.z);
      pickLight.position.set(pos.x, 3.2, pos.z);
      state.pick.userData.info = {
        title: pick.title || '拣货任务',
        lines: pick.lines || [],
      };
      setPickLabel({ title: pick.title, sub: pick.sub });
      if (state.pickLabel) {
        state.pickLabel.position.set(pos.x, 3.5, pos.z);
      }
    }

    // 叉车（首次创建，之后仅更新信息）
    if (!state.forklifts) {
      state.forklifts = {};
      const colorMap = { blue: 0x1f8fd6, dark: 0x0e2c44, amber: C.amber };
      (sc.forklifts || []).forEach(f => {
        const fl = buildForklift({
          body: colorMap[f.color] || 0x1f8fd6,
          carry: !!f.carry,
          info: { title: `叉车 ${f.id}`, lines: f.info || [] },
        });
        if (f.path && PATH_DEFS[f.path]) {
          addMover(fl, PATH_DEFS[f.path], 0.014 + Math.random() * 0.006);
        } else {
          fl.position.set(f.x || 0, 0, f.z || 0);
          fl.rotation.y = f.rot || 0;
        }
        state.forklifts[f.id] = fl;
      });
    } else {
      (sc.forklifts || []).forEach(f => {
        const fl = state.forklifts[f.id];
        if (fl) fl.userData.info = { title: `叉车 ${f.id}`, lines: f.info || [] };
      });
    }

    // 卡车
    if (state.truck && sc.truck) {
      state.truck.userData.info = { title: sc.truck.title, lines: sc.truck.info || [] };
    }
  }

  /* ---------- 交互：点击拾取 ---------- */
  const ray = new THREE.Raycaster();
  const ptr = new THREE.Vector2();
  const tip = document.createElement('div');
  tip.className = 'o_w3d_tip';
  tip.hidden = true;
  el.appendChild(tip);
  let tipTimer = null;
  let downXY = null;

  function findInfo(obj) {
    while (obj) {
      if (obj.userData && obj.userData.info) return obj.userData.info;
      obj = obj.parent;
    }
    return null;
  }
  function onDown(e) { downXY = [e.clientX, e.clientY]; }
  function onUp(e) {
    if (!downXY) return;
    const dx = e.clientX - downXY[0], dy = e.clientY - downXY[1];
    downXY = null;
    if (dx * dx + dy * dy > 25) return;
    ptr.x = (e.clientX / window.innerWidth) * 2 - 1;
    ptr.y = -(e.clientY / window.innerHeight) * 2 + 1;
    ray.setFromCamera(ptr, camera);
    const hits = ray.intersectObjects(root.children, true);
    for (const h of hits) {
      const info = findInfo(h.object);
      if (info && info.title) {
        tip.innerHTML = `<b>${info.title}</b>` + (info.lines || []).map(l => `<br>${l}`).join('');
        tip.hidden = false;
        const box = el.getBoundingClientRect();
        tip.style.left = Math.min(e.clientX - box.left + 14, box.width - 250) + 'px';
        tip.style.top = (e.clientY - box.top + 14) + 'px';
        clearTimeout(tipTimer);
        tipTimer = setTimeout(() => { tip.hidden = true; }, 4200);
        return;
      }
    }
    tip.hidden = true;
  }
  function onMove(e) {
    ptr.x = (e.clientX / window.innerWidth) * 2 - 1;
    ptr.y = -(e.clientY / window.innerHeight) * 2 + 1;
    ray.setFromCamera(ptr, camera);
    renderer.domElement.style.cursor =
      ray.intersectObjects(root.children, true).some(h => {
        const info = findInfo(h.object);
        return info && info.title;
      }) ? 'pointer' : 'grab';
  }
  renderer.domElement.addEventListener('pointerdown', onDown);
  renderer.domElement.addEventListener('pointerup', onUp);
  renderer.domElement.addEventListener('pointermove', onMove);

  /* ---------- 尺寸自适应 ---------- */
  function resize() {
    const w = el.clientWidth || 1, h = el.clientHeight || 1;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    if (composer) composer.setSize(w, h);
  }
  let ro = null;
  if (window.ResizeObserver) {
    ro = new ResizeObserver(resize);
    ro.observe(el);
  }
  window.addEventListener('resize', resize);

  /* ---------- 动画 ---------- */
  const clock = new THREE.Clock();
  function animate() {
    if (state.disposed) return;
    state.raf = requestAnimationFrame(animate);
    const dt = Math.min(clock.getDelta(), 0.05);
    const t = clock.elapsedTime;

    state.movers.forEach(m => {
      m.t = (m.t + dt * m.speed) % 1;
      const pos = m.curve.getPointAt(m.t);
      const tan = m.curve.getTangentAt(m.t);
      m.obj.position.x = pos.x;
      m.obj.position.z = pos.z;
      m.obj.rotation.y = Math.atan2(tan.x, tan.z);
    });

    if (state.ring1) {
      const s = 1 + 0.09 * Math.sin(t * 3);
      state.ring1.scale.set(s, s, 1);
      state.ring1.material.opacity = 0.55 + 0.3 * Math.sin(t * 3);
      const s2 = 1 + 0.16 * Math.sin(t * 3 + 1.2);
      state.ring2.scale.set(s2, s2, 1);
      state.ring2.material.opacity = 0.22 + 0.16 * Math.sin(t * 3 + 1.2);
    }
    if (state.pickLabel) state.pickLabel.position.y = 3.5 + 0.12 * Math.sin(t * 2.2);
    if (state.beam) state.beam.material.opacity = 0.05 + 0.03 * Math.sin(t * 2);

    conveyor.children.forEach(o => { if (o.userData.roller) o.rotation.y += dt * 2.2; });

    controls.update();
    if (composer) composer.render();
    else renderer.render(scene, camera);
  }

  applyData(opts.data || {});
  animate();

  return {
    update(data) {
      if (state.disposed) return;
      applyData(data || {});
    },
    resetView() {
      camera.position.set(45, 35, 48);
      controls.target.set(7, 0, 0);
      controls.update();
    },
    destroy() {
      state.disposed = true;
      cancelAnimationFrame(state.raf);
      clearTimeout(tipTimer);
      window.removeEventListener('resize', resize);
      if (ro) ro.disconnect();
      renderer.domElement.removeEventListener('pointerdown', onDown);
      renderer.domElement.removeEventListener('pointerup', onUp);
      renderer.domElement.removeEventListener('pointermove', onMove);
      controls.dispose();
      scene.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material && obj.material.map) obj.material.map.dispose();
        if (obj.material && obj.material.dispose) obj.material.dispose();
      });
      renderer.dispose();
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      if (tip.parentNode) tip.parentNode.removeChild(tip);
    },
  };
}
