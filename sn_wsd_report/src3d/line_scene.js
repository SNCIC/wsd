/**
 * 整机自动线 3D 看板 · 工艺流程流水线场景
 * 被 OWL 组件调用：SnAssemblyLine3D.mount(el, { data }) → { update(data), resetView(), destroy() }
 *
 * 排布原则：**按工艺流程顺序串联**，不再按现场平面图分区。
 *   OP10 装配 → OP20 耐压 → OP30 初调 → OP40 复检1 → OP50 复检2 → OP60 参数设置 → OP70 包装
 *   采用 S 型双排：第一排自左向右（装配→耐压→初调→复检1），
 *   到右端折返，第二排自右向左（复检2→参数设置→包装），出料在左端。
 *   输送线贯穿两排，工序号、流向箭头、在制品随线流动共同表达工艺流向。
 *
 * 设备运行表达：每台设备带运行状态灯 + 表架扫描光带 + 通电立柱光条 + 地面脉冲光环，
 *   工区状态 run/slow/ng 时高亮运行，idle 时全部熄灭；在测表位再叠一层滚动扫描波。
 *
 * 约定：工区位置、设备形态、表位排布固定在客户端；工区状态/设备数/在测数由后端
 * sn.wsd.assembly.line.3d.screen.service 提供，前端只做映射。
 */
import * as THREE from 'three';
import { OrbitControls } from '../static/src/lib/three/controls/OrbitControls.js';
import { EffectComposer } from '../static/src/lib/three/postprocessing/EffectComposer.js';
import { RenderPass } from '../static/src/lib/three/postprocessing/RenderPass.js';
import { UnrealBloomPass } from '../static/src/lib/three/postprocessing/UnrealBloomPass.js';
import { OutputPass } from '../static/src/lib/three/postprocessing/OutputPass.js';

/* ================= 色板（科技蓝） ================= */
const C = {
  ground: 0x04172a, gridA: 0x0e3d5a, gridB: 0x0a2a42,
  frame: 0x11405c, panel: 0x0a2438, panelHi: 0x123c58,
  metal: 0x3f7fa0, dark: 0x081a2a, belt: 0x0a2033,
  cyan: 0x00e5ff, amber: 0xffb020, red: 0xff3b52, idle: 0x3f7fa0,
  green: 0x2ee6a0, blue: 0x2b8cff, violet: 0x9a7bff, steel: 0x7f9db5,
};

const STATUS_COLOR = { run: C.cyan, slow: C.amber, ng: C.red, idle: C.idle };

/* ================= 工区平面坐标：S 型双排，按工艺顺序 =================
 * x 向右，z 向观察者；上方（远处）为 -z，即流程起点。
 * 第一排 z -28..-14 自左向右：装配 → 耐压 → 初调 → 复检1（OP10~OP40）
 * 第二排 z  -9..  5 自右向左：复检2 → 参数设置 → 包装（OP50~OP70）
 */
const AREA_LAYOUT = {
  ASM: { x0: -44, x1: -29, z0: -28, z1: -14, accent: C.amber },
  HV: { x0: -27, x1: -15, z0: -28, z1: -14, accent: C.violet },
  CAL: { x0: -13, x1: 13, z0: -28, z1: -14, accent: C.green },
  T1: { x0: 15, x1: 46, z0: -28, z1: -14, accent: C.blue },
  T2: { x0: 15, x1: 46, z0: -9, z1: 5, accent: C.cyan },
  PARAM: { x0: -13, x1: 13, z0: -9, z1: 5, accent: C.steel },
  PACK: { x0: -44, x1: -15, z0: -9, z1: 5, accent: C.green },
};

/* 输送线路径：进料 → 第一排下沿东行 → 右端折返 → 第二排下沿西行 → 出料 */
const PATH_PTS = [
  [-50, -11.5], [48, -11.5], [48, 7.8], [-50, 7.8],
];
const BELT_W = 1.5;
const BELT_Y = 0.82;

/* 相机默认视角（俯视约 69°；距离按 7 工区全宽留出余量，避免两侧工区被裁） */
const CAM_HOME = { pos: [1, 154, 57], target: [1, 0, -8.5] };

/** 设备阵列排布：行数从 1 开始试，取第一个满足最小间距的方案；间距设上限避免过散 */
function gridFor(count, w, d) {
  const m = 2.0;
  const uw = Math.max(0.1, w - m * 2);
  const ud = Math.max(0.1, d - m * 2);
  for (let rows = 1; rows <= count; rows++) {
    const cols = Math.ceil(count / rows);
    const sx = cols > 1 ? uw / (cols - 1) : 0;
    const sz = rows > 1 ? ud / (rows - 1) : 0;
    if (cols > 1 && sx < 3.05) continue;
    if (rows > 1 && sz < 2.35) continue;
    return { rows, cols, sx: Math.min(sx, 6.4), sz: Math.min(sz, 6.8) };
  }
  return { rows: count, cols: 1, sx: 0, sz: 0 };
}

/* 共享几何体（几十台设备复用，避免重复创建） */
const GEO = {
  led: new THREE.SphereGeometry(0.13, 12, 10),
  ring: new THREE.RingGeometry(0.96, 1.1, 44),
  scan: new THREE.PlaneGeometry(2.3, 0.5),
  arrow: new THREE.PlaneGeometry(1.5, 1.5),
};

export function mount(el, opts = {}) {
  const state = {
    disposed: false,
    raf: 0,
    areas: [],
    products: [],
    arms: [],
    scanners: [],
    probes: [],
    units: [],
    slotMesh: null,
    speed: 2.2,
    lastCfgs: [],
    lastPaint: 0,
  };

  /* ---------- 渲染器 ---------- */
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(el.clientWidth || 1, el.clientHeight || 1);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.12;
  renderer.domElement.style.display = 'block';
  el.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x02101f, 210, 440);

  const camera = new THREE.PerspectiveCamera(26, (el.clientWidth || 1) / (el.clientHeight || 1), 0.1, 700);
  camera.position.fromArray(CAM_HOME.pos);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.fromArray(CAM_HOME.target);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.minDistance = 55;
  controls.maxDistance = 280;
  controls.maxPolarAngle = Math.PI / 2.1;
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };

  /* ---------- 灯光 ---------- */
  scene.add(new THREE.HemisphereLight(0x245880, 0x020a16, 1.8));
  const keyLight = new THREE.DirectionalLight(0xd6f2ff, 2.0);
  keyLight.position.set(34, 86, 46);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(2048, 2048);
  keyLight.shadow.camera.left = -60; keyLight.shadow.camera.right = 60;
  keyLight.shadow.camera.top = 52; keyLight.shadow.camera.bottom = -52;
  keyLight.shadow.camera.far = 250;
  keyLight.shadow.bias = -0.0007;
  scene.add(keyLight);
  const rim = new THREE.DirectionalLight(0x2b7bff, 0.75);
  rim.position.set(-38, 26, -30);
  scene.add(rim);

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
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(150, 120), mat(C.ground, { rough: 0.96 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  root.add(ground);

  const grid = new THREE.GridHelper(150, 75, C.gridA, C.gridB);
  grid.position.y = 0.012;
  grid.material.transparent = true;
  grid.material.opacity = 0.4;
  root.add(grid);

  /* ---------- 文字精灵 ---------- */
  function textSprite(text, { w = 4.6, h = 1.5, fs = 150, sub = '', color = '#00e5ff' } = {}) {
    const c = document.createElement('canvas');
    c.width = 768;
    c.height = Math.round(768 * h / w);
    const g = c.getContext('2d');
    const r = 26, W = c.width, H = c.height;
    g.beginPath();
    g.moveTo(r, 0); g.arcTo(W, 0, W, H, r); g.arcTo(W, H, 0, H, r);
    g.arcTo(0, H, 0, 0, r); g.arcTo(0, 0, W, 0, r); g.closePath();
    g.fillStyle = 'rgba(4,26,48,.92)';
    g.fill();
    g.strokeStyle = color;
    g.globalAlpha = 0.6;
    g.lineWidth = 5;
    g.stroke();
    g.globalAlpha = 1;
    g.fillStyle = color;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.shadowColor = color;
    g.shadowBlur = 7;
    const fit = (content, baseFs, weight) => {
      let size = baseFs;
      g.font = `${weight} ${size}px "Microsoft YaHei", sans-serif`;
      const measured = g.measureText(content).width;
      if (measured > W - 40) {
        size = Math.max(16, Math.floor(baseFs * (W - 40) / measured));
        g.font = `${weight} ${size}px "Microsoft YaHei", sans-serif`;
      }
      return size;
    };
    if (sub) {
      fit(text, fs * 0.74, 900);
      g.fillText(text, W / 2, H * 0.34);
      g.fillStyle = 'rgba(190,232,255,.78)';
      fit(sub, fs * 0.4, 600);
      g.fillText(sub, W / 2, H * 0.71);
    } else {
      const size = fit(text, fs, 900);
      g.fillText(text, W / 2, H / 2 + size * 0.05);
    }
    const tex = new THREE.CanvasTexture(c);
    tex.anisotropy = 8;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    sp.scale.set(w, h, 1);
    return sp;
  }

  function makeFloorText(text, x, z, { size = 2.6, alpha = 0.2, color = '0,229,255', rot = 0 } = {}) {
    const c = document.createElement('canvas');
    c.width = 512; c.height = 256;
    const g = c.getContext('2d');
    g.font = '900 118px "Microsoft YaHei", sans-serif';
    g.fillStyle = `rgba(${color},${alpha})`;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(text, 256, 134);
    const tex = new THREE.CanvasTexture(c);
    tex.anisotropy = 8;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(size * 2, size),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }));
    m.rotation.x = -Math.PI / 2;
    m.rotation.z = rot;
    m.position.set(x, 0.032, z);
    return m;
  }
  function cssColor(hex) {
    return `${(hex >> 16) & 255},${(hex >> 8) & 255},${hex & 255}`;
  }

  /* ---------- 设备级 MES 过站数据标签 ----------
   * 每台被点亮的设备头顶挂一块小铭牌：过站台数 + OK/NG + 设备编号，
   * 数据由后端按 MES 过站记录/工序台账分配到设备。
   */
  function roundRectPath(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  function makeDeviceLabel() {
    const c = document.createElement('canvas');
    c.width = 200; c.height = 88;
    const tex = new THREE.CanvasTexture(c);
    tex.anisotropy = 8;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    sp.scale.set(2.6, 1.14, 1);
    sp.userData = { canvas: c, tex, lastKey: '' };
    return sp;
  }

  function drawDeviceLabel(sp, d) {
    const key = `${d.code}|${d.pass}|${d.ok}|${d.ng}`;
    if (sp.userData.lastKey === key) {
      return;
    }
    sp.userData.lastKey = key;
    const c = sp.userData.canvas;
    const g = c.getContext('2d');
    g.clearRect(0, 0, c.width, c.height);
    roundRectPath(g, 3, 3, 194, 82, 12);
    g.fillStyle = 'rgba(3,22,40,.88)';
    g.fill();
    g.strokeStyle = 'rgba(0,229,255,.6)';
    g.lineWidth = 2.5;
    g.stroke();
    g.textBaseline = 'middle';
    // 设备编号（右上）
    g.font = '600 17px "Microsoft YaHei", sans-serif';
    g.fillStyle = 'rgba(140,220,255,.78)';
    g.textAlign = 'right';
    g.fillText(d.code, 190, 16);
    // 过站台数（主数字）
    g.textAlign = 'left';
    g.fillStyle = '#7ff3ff';
    g.font = '900 36px "Microsoft YaHei", sans-serif';
    g.shadowColor = 'rgba(0,229,255,.8)';
    g.shadowBlur = 8;
    g.fillText(`过站 ${d.pass}`, 12, 34);
    g.shadowBlur = 0;
    // OK / NG
    g.font = '700 22px "Microsoft YaHei", sans-serif';
    g.fillStyle = 'rgba(190,232,255,.8)';
    g.fillText(`OK ${d.ok}`, 14, 66);
    g.fillStyle = d.ng > 0 ? '#ff8a95' : 'rgba(190,232,255,.42)';
    g.fillText(`NG ${d.ng}`, 96, 66);
    sp.userData.tex.needsUpdate = true;
  }

  /* ---------- 输送线 ---------- */
  const path = (() => {
    const segs = [];
    let total = 0;
    for (let i = 0; i < PATH_PTS.length - 1; i++) {
      const a = new THREE.Vector3(PATH_PTS[i][0], 0, PATH_PTS[i][1]);
      const b = new THREE.Vector3(PATH_PTS[i + 1][0], 0, PATH_PTS[i + 1][1]);
      const len = a.distanceTo(b);
      segs.push({ a, b, len, start: total });
      total += len;
    }
    return { segs, total };
  })();

  function pathPoint(dist) {
    const d = ((dist % path.total) + path.total) % path.total;
    for (const s of path.segs) {
      if (d <= s.start + s.len + 1e-6) {
        const t = s.len ? (d - s.start) / s.len : 0;
        return {
          x: s.a.x + (s.b.x - s.a.x) * t,
          z: s.a.z + (s.b.z - s.a.z) * t,
          dx: (s.b.x - s.a.x) / (s.len || 1),
          dz: (s.b.z - s.a.z) / (s.len || 1),
        };
      }
    }
    const last = path.segs[path.segs.length - 1];
    return { x: last.b.x, z: last.b.z, dx: 1, dz: 0 };
  }

  function buildConveyor() {
    const g = new THREE.Group();
    path.segs.forEach(seg => {
      const cx = (seg.a.x + seg.b.x) / 2;
      const cz = (seg.a.z + seg.b.z) / 2;
      const alongX = Math.abs(seg.b.x - seg.a.x) > Math.abs(seg.b.z - seg.a.z);
      const w = alongX ? seg.len : BELT_W;
      const d = alongX ? BELT_W : seg.len;

      g.add(box(w, 0.24, d, C.dark, { x: cx, y: BELT_Y - 0.34, z: cz }));
      g.add(box(w - 0.08, 0.05, d - 0.08, C.belt, { x: cx, y: BELT_Y - 0.06, z: cz, cast: false }));

      // 侧边发光线
      [-1, 1].forEach(s => {
        const sx = alongX ? cx : cx + s * (BELT_W / 2 - 0.04);
        const sz = alongX ? cz + s * (BELT_W / 2 - 0.04) : cz;
        g.add(box(alongX ? seg.len : 0.08, 0.06, alongX ? 0.08 : seg.len, C.cyan, {
          x: sx, y: BELT_Y - 0.02, z: sz, cast: false, emissive: C.cyan, ei: 0.95,
        }));
      });

      // 滚筒（静态细条，表现带面纹理）
      const step = 0.9;
      for (let t = 0.5; t < seg.len; t += step) {
        const px = seg.a.x + (seg.b.x - seg.a.x) * (t / seg.len);
        const pz = seg.a.z + (seg.b.z - seg.a.z) * (t / seg.len);
        g.add(box(alongX ? 0.1 : BELT_W - 0.16, 0.02, alongX ? BELT_W - 0.16 : 0.1, 0x2f6a86, {
          x: px, y: BELT_Y - 0.03, z: pz, cast: false,
        }));
      }

      // 支腿
      const legs = Math.max(2, Math.round(seg.len / 4.5));
      for (let i = 0; i <= legs; i++) {
        const t = i / legs;
        const px = seg.a.x + (seg.b.x - seg.a.x) * t;
        const pz = seg.a.z + (seg.b.z - seg.a.z) * t;
        [-1, 1].forEach(s => g.add(box(0.12, BELT_Y - 0.4, 0.12, C.frame, {
          x: px + (alongX ? 0 : s * (BELT_W / 2 - 0.24)),
          z: pz + (alongX ? s * (BELT_W / 2 - 0.24) : 0),
        })));
      }
    });

    // 转角平台
    PATH_PTS.slice(1, -1).forEach(([px, pz]) => {
      g.add(box(BELT_W, 0.24, BELT_W, C.dark, { x: px, y: BELT_Y - 0.34, z: pz }));
      g.add(box(BELT_W - 0.1, 0.05, BELT_W - 0.1, C.belt, { x: px, y: BELT_Y - 0.06, z: pz, cast: false }));
    });
    root.add(g);
  }
  buildConveyor();

  /* ---------- 流向箭头（沿输送线均布，指向工艺流向） ---------- */
  function arrowTexture() {
    const c = document.createElement('canvas');
    c.width = 128; c.height = 128;
    const g = c.getContext('2d');
    g.strokeStyle = 'rgba(0,229,255,.55)';
    g.lineWidth = 12;
    g.lineJoin = 'round';
    g.beginPath();
    g.moveTo(28, 100); g.lineTo(64, 96); g.lineTo(64, 34);
    g.stroke();
    g.fillStyle = 'rgba(0,229,255,.75)';
    g.beginPath();
    g.moveTo(40, 44); g.lineTo(88, 44); g.lineTo(64, 14); g.closePath();
    g.fill();
    const tex = new THREE.CanvasTexture(c);
    tex.anisotropy = 8;
    return tex;
  }
  function arrowAngle(dx, dz) {
    if (Math.abs(dx) > Math.abs(dz)) return dx > 0 ? -Math.PI / 2 : Math.PI / 2;
    return dz > 0 ? Math.PI : 0;
  }
  function buildArrows() {
    const tex = arrowTexture();
    const m = new THREE.MeshBasicMaterial({
      map: tex, transparent: true, depthWrite: false, opacity: 0.85,
    });
    const g = new THREE.Group();
    path.segs.forEach(seg => {
      const ang = arrowAngle(seg.b.x - seg.a.x, seg.b.z - seg.a.z);
      for (let t = 4; t < seg.len - 3; t += 7.5) {
        const px = seg.a.x + (seg.b.x - seg.a.x) * (t / seg.len);
        const pz = seg.a.z + (seg.b.z - seg.a.z) * (t / seg.len);
        const a = new THREE.Mesh(GEO.arrow, m);
        a.rotation.x = -Math.PI / 2;
        a.rotation.z = ang;
        a.position.set(px, BELT_Y + 0.02, pz);
        a.scale.setScalar(0.62);
        g.add(a);
      }
    });
    root.add(g);
  }
  buildArrows();

  /* ---------- 产品（三相表） ---------- */
  function buildProduct() {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({
      color: 0x123c58, emissive: C.cyan, emissiveIntensity: 0.4, roughness: 0.55, metalness: 0.15,
    });
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.26, 0.48), bodyMat);
    body.position.y = 0.11;
    body.castShadow = true;
    g.add(body);
    const face = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.15, 0.02),
      mat(0xdff6ff, { emissive: 0xa8ecff, ei: 0.55, rough: 0.4 }));
    face.position.set(0, 0.12, 0.205);
    g.add(face);
    const led = new THREE.Mesh(new THREE.BoxGeometry(0.09, 0.03, 0.09),
      new THREE.MeshStandardMaterial({ color: 0x06202e, emissive: C.cyan, emissiveIntensity: 1.9 }));
    led.position.set(0, 0.23, 0);
    g.add(led);
    g.userData = { bodyMat, ledMat: led.material };
    return g;
  }

  /* ---------- 设备构件 ---------- */
  /** 表架：slots>=40 双侧，每侧 3 层；其他单侧。返回该设备的表位世界坐标 */
  function buildRack(g, dx, dz, slots, accent) {
    const two = slots >= 40;
    const racks = two ? 2 : 1;
    const perShelf = Math.max(1, Math.round(slots / 3 / racks));
    const rackXs = two ? [-0.86, 0.86] : [0];
    const positions = [];

    rackXs.forEach(rackX => {
      // 立柱
      [-1, 1].forEach(s => {
        g.add(box(0.06, 1.42, 0.06, C.frame, { x: dx + rackX, y: 0.06, z: dz + s * 0.52 }));
      });
      for (let level = 0; level < 3; level++) {
        const y = 0.42 + level * 0.4;
        g.add(box(0.13, 0.03, 1.12, 0x1a5a78, {
          x: dx + rackX, y, z: dz, emissive: accent, ei: 0.12,
        }));
        // 表位：沿 z 均布，左右略微收边
        for (let i = 0; i < perShelf; i++) {
          const t = perShelf > 1 ? i / (perShelf - 1) : 0.5;
          positions.push([
            dx + rackX,
            y + 0.075,
            dz - 0.49 + t * 0.98,
          ]);
        }
      }
    });
    return positions;
  }

  function deviceBase(g, dx, dz, accent) {
    g.add(box(2.6, 0.05, 1.7, 0x08202f, {
      x: dx, y: 0.015, z: dz, cast: false, recv: true, emissive: accent, ei: 0.1,
    }));
    g.add(box(2.6, 0.05, 0.07, accent, {
      x: dx, y: 0.075, z: dz + 0.86, cast: false, emissive: accent, ei: 0.55,
    }));
    g.add(box(2.6, 0.05, 0.07, accent, {
      x: dx, y: 0.075, z: dz - 0.86, cast: false, emissive: accent, ei: 0.3,
    }));
  }

  function deviceCabinet(g, dx, dz, accent, { w = 0.9, h = 1.15 } = {}) {
    g.add(box(w, h, 1.05, C.panel, { x: dx, z: dz - 0.1 }));
    g.add(box(w + 0.05, 0.06, 1.1, C.panelHi, {
      x: dx, y: h, z: dz - 0.1, emissive: accent, ei: 0.6,
    }));
    g.add(box(w + 0.02, 0.02, 0.02, accent, {
      x: dx, y: h * 0.62, z: dz + 0.44, cast: false, emissive: accent, ei: 1.0,
    }));
  }

  const DEVICE_BUILDERS = {
    /* 初调 / 校表：双表架 + 中间柜 + 双显示器 + 探针排 */
    cal(g, dx, dz, slots, accent) {
      deviceBase(g, dx, dz, accent);
      deviceCabinet(g, dx, dz, accent);
      [-1, 1].forEach(s => {
        g.add(box(0.08, 0.42, 0.08, C.frame, { x: dx + s * 0.62, y: 1.2, z: dz + 0.62 }));
        g.add(box(0.66, 0.44, 0.05, 0x06283c, { x: dx + s * 0.62, y: 1.62, z: dz + 0.62 }));
        g.add(box(0.58, 0.34, 0.01, C.cyan, {
          x: dx + s * 0.62, y: 1.67, z: dz + 0.65, cast: false, emissive: C.cyan, ei: 0.5,
        }));
      });
      // 探针横梁
      g.add(box(1.5, 0.07, 0.09, C.metal, { x: dx, y: 1.34, z: dz + 0.34, metal: 0.5, rough: 0.4 }));
      for (let i = -1; i <= 1; i++) {
        const probe = box(0.04, 0.34, 0.04, 0xdff6ff, {
          x: dx + i * 0.42, y: 1.02, z: dz + 0.34, emissive: C.cyan, ei: 0.9, cast: false,
        });
        g.add(probe);
        state.probes.push({ obj: probe, base: 1.02, phase: i * 0.9 + dx });
      }
      return buildRack(g, dx, dz, slots, accent);
    },

    /* 复检：双表架 + 测试柜 */
    test(g, dx, dz, slots, accent) {
      deviceBase(g, dx, dz, accent);
      deviceCabinet(g, dx, dz, accent, { w: 0.95, h: 1.2 });
      // 上料指示灯
      [-1, 1].forEach(s => {
        g.add(box(0.16, 0.16, 0.16, 0x0a2438, { x: dx + s * 1.18, y: 1.32, z: dz + 0.66 }));
        g.add(box(0.1, 0.05, 0.1, accent, {
          x: dx + s * 1.18, y: 1.48, z: dz + 0.66, cast: false, emissive: accent, ei: 1.4,
        }));
      });
      return buildRack(g, dx, dz, slots, accent);
    },

    /* 参数设置：单表架 15 位 + 红外写入头 */
    param(g, dx, dz, slots, accent) {
      deviceBase(g, dx, dz, accent);
      deviceCabinet(g, dx, dz, accent, { w: 0.8, h: 1.05 });
      g.add(box(1.15, 0.09, 0.11, C.metal, { x: dx, y: 1.62, z: dz + 0.36, metal: 0.55, rough: 0.38 }));
      g.add(box(0.16, 0.34, 0.16, 0x123c58, { x: dx, y: 1.28, z: dz + 0.36 }));
      g.add(box(0.1, 0.07, 0.1, accent, {
        x: dx, y: 1.22, z: dz + 0.36, cast: false, emissive: accent, ei: 1.6,
      }));
      return buildRack(g, dx, dz, slots, accent);
    },

    /* 装配：首台装配机械臂，其余为装配工位（工作台 + 料盒 + 拧紧轴） */
    asm(g, dx, dz, slots, accent, index) {
      deviceBase(g, dx, dz, accent);
      if (index === 0) {
        deviceCabinet(g, dx, dz, accent, { w: 1.0, h: 1.0 });
        const base = new THREE.Group();
        base.position.set(dx + 0.9, 1.06, dz + 0.5);
        base.add(box(0.56, 0.2, 0.56, 0x123c58, { y: 0.1 }));
        const pivot = new THREE.Group();
        pivot.position.y = 0.22;
        pivot.add(box(0.22, 1.05, 0.24, C.metal, { y: 0.52, metal: 0.5, rough: 0.35 }));
        const elbow = new THREE.Group();
        elbow.position.y = 1.02;
        elbow.add(box(0.18, 0.86, 0.2, 0x2a6d8e, { y: 0.42, metal: 0.45, rough: 0.4 }));
        const grip = new THREE.Group();
        grip.position.y = 0.84;
        grip.add(box(0.26, 0.1, 0.26, C.cyan, { emissive: C.cyan, ei: 1.2, cast: false }));
        [-1, 1].forEach(s => grip.add(box(0.04, 0.2, 0.04, C.metal, { x: s * 0.1, y: -0.14, metal: 0.6 })));
        elbow.add(grip);
        pivot.add(elbow);
        base.add(pivot);
        g.add(base);
        state.arms.push({ pivot, elbow, phase: Math.random() * Math.PI * 2 });
      } else {
        // 装配工位：工作台 + 料盒 + 拧紧轴
        g.add(box(1.7, 0.08, 1.1, C.panelHi, { x: dx, y: 0.92, z: dz - 0.15 }));
        [-1, 1].forEach(s => g.add(box(0.08, 0.9, 0.08, C.frame, { x: dx + s * 0.78, z: dz - 0.62 })));
        g.add(box(0.5, 0.2, 0.42, 0x123c58, { x: dx - 0.5, y: 1.0, z: dz - 0.3 }));
        g.add(box(0.16, 0.5, 0.16, C.metal, { x: dx + 0.5, y: 1.0, z: dz + 0.1, metal: 0.55 }));
        g.add(box(0.12, 0.08, 0.12, accent, {
          x: dx + 0.5, y: 0.94, z: dz + 0.1, cast: false, emissive: accent, ei: 1.5,
        }));
        [-1, 1].forEach(s => g.add(box(0.06, 0.06, 1.0, accent, {
          x: dx + s * 0.86, y: 1.0, z: dz - 0.15, cast: false, emissive: accent, ei: 0.7,
        })));
      }
      return buildRack(g, dx, dz, slots, accent);
    },

    /* 耐压：高压试验柜 + 端子排 + 绝缘围栏 */
    hv(g, dx, dz, slots, accent) {
      deviceBase(g, dx, dz, accent);
      g.add(box(1.9, 2.1, 1.2, 0x0c2c42, { x: dx, z: dz - 0.15 }));
      g.add(box(1.94, 0.1, 1.24, accent, {
        x: dx, y: 1.98, z: dz - 0.15, cast: false, emissive: accent, ei: 0.9,
      }));
      for (let i = -1; i <= 1; i++) {
        g.add(box(0.3, 0.5, 0.08, accent, {
          x: dx + i * 0.55, y: 1.15, z: dz + 0.46, cast: false, emissive: accent, ei: 0.6,
        }));
      }
      // 绝缘围栏立柱
      [-1, 1].forEach(s => g.add(box(0.1, 1.8, 0.1, accent, {
        x: dx + s * 1.36, y: 0.04, z: dz + 0.9, cast: false, emissive: accent, ei: 0.3,
      })));
      g.add(box(2.7, 0.04, 0.05, accent, {
        x: dx, y: 1.7, z: dz + 0.9, cast: false, emissive: accent, ei: 0.35,
      }));
      return buildRack(g, dx, dz, slots, accent);
    },

    /* 包装：封箱拱门 + 纸箱堆 + 缠绕膜 */
    pack(g, dx, dz, slots, accent) {
      deviceBase(g, dx, dz, accent);
      [-1, 1].forEach(s => g.add(box(0.14, 2.0, 0.14, C.frame, { x: dx + s * 1.1, z: dz + 0.1 })));
      g.add(box(2.4, 0.2, 0.2, C.frame, { x: dx, y: 2.0, z: dz + 0.1 }));
      g.add(box(2.2, 0.05, 0.06, accent, {
        x: dx, y: 1.9, z: dz + 0.22, cast: false, emissive: accent, ei: 1.2,
      }));
      for (let i = 0; i < 4; i++) {
        const px = dx - 0.95 + (i % 2) * 0.85;
        const py = i < 2 ? 0 : 0.72;
        g.add(box(0.76, 0.66, 0.76, 0x1b4463, { x: px, y: py + 0.06, z: dz - 0.55 }));
        g.add(box(0.78, 0.05, 0.78, accent, {
          x: px, y: py + 0.4, z: dz - 0.55, cast: false, emissive: accent, ei: 0.5,
        }));
      }
      const roll = new THREE.Mesh(new THREE.CylinderGeometry(0.36, 0.36, 0.44, 18), mat(0x0a7ea4, { rough: 0.5 }));
      roll.position.set(dx + 1.1, 1.0, dz - 0.4);
      roll.castShadow = true;
      g.add(roll);
      return buildRack(g, dx, dz, slots, accent);
    },
  };

  /* ---------- 设备运行标识（状态灯 / 扫描光带 / 通电立柱 / 地面光环 / 过站产品） ----------
   * 独立材质：每台设备按工区状态单独着色与启停，无法共享缓存材质。
   * 每台被点亮的设备带一个过站循环：产品从设备前缘滑入表架 → 加工（随扫描光带微动）→ 出料，
   * 是否运行由后端 MES 过站数量折算的点亮设备数决定。
   */
  function addUnitFx(g, dx, dz, accent, index) {
    const phase = Math.random() * Math.PI * 2;

    // 顶部运行状态灯（球灯 + 细灯杆）
    g.add(box(0.05, 1.5, 0.05, C.frame, { x: dx + 1.14, z: dz + 0.82 }));
    const ledMat = new THREE.MeshStandardMaterial({
      color: 0x0a2438, emissive: accent, emissiveIntensity: 1.6, roughness: 0.35, metalness: 0.2,
    });
    const led = new THREE.Mesh(GEO.led, ledMat);
    led.position.set(dx + 1.14, 1.62, dz + 0.82);
    g.add(led);

    // 表架扫描光带：沿 z 往返，模拟测试头巡检表位
    const scanMat = new THREE.MeshBasicMaterial({
      color: accent, transparent: true, opacity: 0.3, depthWrite: false,
      blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    });
    const scan = new THREE.Mesh(GEO.scan, scanMat);
    scan.rotation.x = -Math.PI / 2;
    scan.position.set(dx, 1.24, dz);
    g.add(scan);

    // 通电立柱光条（设备后侧两根）
    const barMat = new THREE.MeshBasicMaterial({
      color: accent, transparent: true, opacity: 0.5, depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const bars = [-1, 1].map(s => {
      const b = new THREE.Mesh(new THREE.BoxGeometry(0.05, 1.45, 0.05), barMat);
      b.position.set(dx + s * 1.2, 0.78, dz - 0.78);
      g.add(b);
      return b;
    });

    // 地面脉冲光环
    const haloMat = new THREE.MeshBasicMaterial({
      color: accent, transparent: true, opacity: 0.32, depthWrite: false,
      blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    });
    const halo = new THREE.Mesh(GEO.ring, haloMat);
    halo.rotation.x = -Math.PI / 2;
    halo.position.set(dx, 0.055, dz);
    g.add(halo);

    // 过站产品：进设备 → 加工 → 出料的循环演示
    const cycleProd = buildProduct();
    cycleProd.rotation.y = Math.PI / 2;
    cycleProd.position.set(dx, 0.12, dz + 1.9);
    g.add(cycleProd);

    state.units.push({
      ledMat, scan, scanMat, bars, barMat, halo, haloMat,
      dz, phase, index, running: true,
      cycleProd,
      cyclePhase: (index * 2.7) % 11,
      cyclePeriod: 9 + (index % 5) * 1.3,
    });
  }

  /* ---------- 工区 ---------- */
  function buildArea(cfg) {
    const L = AREA_LAYOUT[cfg.code];
    if (!L) {
      return null;
    }
    const w = L.x1 - L.x0;
    const d = L.z1 - L.z0;
    const cx = (L.x0 + L.x1) / 2;
    const cz = (L.z0 + L.z1) / 2;
    const accent = L.accent;
    const g = new THREE.Group();

    // 地坪色块
    const padMat = new THREE.MeshStandardMaterial({
      color: 0x07202f, roughness: 0.95, metalness: 0.04,
      transparent: true, opacity: 0.9, emissive: accent, emissiveIntensity: 0.06,
    });
    const pad = new THREE.Mesh(new THREE.PlaneGeometry(w - 0.5, d - 0.5), padMat);
    pad.rotation.x = -Math.PI / 2;
    pad.position.set(cx, 0.022, cz);
    pad.receiveShadow = true;
    g.add(pad);

    // 工区边框
    const borderMats = [];
    const t = 0.16;
    const mkBorder = (bw, bd, bx, bz) => {
      const m = new THREE.MeshStandardMaterial({
        color: 0x061a26, emissive: accent, emissiveIntensity: 0.75, roughness: 0.5,
      });
      borderMats.push(m);
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(bw, 0.07, bd), m);
      mesh.position.set(bx, 0.05, bz);
      g.add(mesh);
    };
    mkBorder(w, t, cx, L.z0 + t / 2);
    mkBorder(w, t, cx, L.z1 - t / 2);
    mkBorder(t, d, L.x0 + t / 2, cz);
    mkBorder(t, d, L.x1 - t / 2, cz);

    // 地面工序号 + 工区名
    const size = Math.min(5.2, Math.max(3.2, w * 0.16));
    g.add(makeFloorText(`${cfg.op || ''} ${cfg.name}`.trim(), cx, L.z0 + 2.2, {
      size, alpha: 0.18, color: cssColor(accent),
    }));

    // 设备阵列（按区域居中）
    const count = Math.max(1, cfg.devices || 1);
    const slots = Math.max(1, cfg.slots || 60);
    const grid = gridFor(count, w, d);
    const gw = grid.cols > 1 ? (grid.cols - 1) * grid.sx : 0;
    const gd = grid.rows > 1 ? (grid.rows - 1) * grid.sz : 0;
    const x0 = cx - gw / 2;
    const z0 = cz - gd / 2;
    const slotPos = [];
    const deviceRanges = [];
    const devicePos = [];
    const unitFrom = state.units.length;   // 本次工区新增的设备运行标识起点
    const builder = DEVICE_BUILDERS[cfg.kind] || DEVICE_BUILDERS.test;

    for (let i = 0; i < count; i++) {
      const r = Math.floor(i / grid.cols);
      const c = i % grid.cols;
      const dx = grid.cols > 1 ? x0 + c * grid.sx : cx;
      const dz = grid.rows > 1 ? z0 + r * grid.sz : cz;
      const start = slotPos.length;
      const positions = builder(g, dx, dz, slots, accent, i) || [];
      positions.forEach(p => slotPos.push(p));
      addUnitFx(g, dx, dz, accent, i);
      devicePos.push([dx, dz]);
      deviceRanges.push([start, slotPos.length]);
    }

    // 设备级过站数据铭牌（默认隐藏，数据刷新时按 MES 数量点亮显示）
    const deviceLabels = devicePos.map(([dx, dz]) => {
      const sp = makeDeviceLabel();
      sp.position.set(dx, 2.18, dz);
      sp.visible = false;
      g.add(sp);
      return sp;
    });

    // 装配 / 包装区补充物料暂存，避免大面积空场
    if (cfg.kind === 'asm' || cfg.kind === 'pack') {
      const stZ = L.z1 - 2.4;
      const startX = cx - Math.min(6.0, w * 0.28);
      for (let i = 0; i < 4; i++) {
        const px = startX + i * 1.55;
        for (let level = 0; level < 2; level++) {
          g.add(box(0.86, 0.62, 0.8, 0x1b4463, { x: px, y: 0.06 + level * 0.66, z: stZ }));
          g.add(box(0.88, 0.05, 0.82, accent, {
            x: px, y: 0.4 + level * 0.66, z: stZ, cast: false, emissive: accent, ei: 0.4,
          }));
        }
      }
      g.add(makeFloorText(cfg.kind === 'pack' ? '成品待发运' : '待装表暂存', startX + 2.3, stZ + 1.2, {
        size: 1.7, alpha: 0.12, color: cssColor(accent),
      }));
    }

    // 悬浮工区标签
    const label = textSprite(`${cfg.op || ''} ${cfg.name}`.trim(), {
      w: 8.0, h: 2.2, fs: 122, sub: cfg.sub || '', color: `#${accent.toString(16).padStart(6, '0')}`,
    });
    label.position.set(cx, 2.6, L.z0 - 1.1);
    g.add(label);

    g.userData = {
      code: cfg.code,
      status: cfg.status || 'run',
      label,
      labelKey: `${cfg.op || ''}|${cfg.name}|${cfg.sub || ''}`,
      borderMats,
      padMat,
      slotPos,
      deviceRanges,
      deviceLabels,
      units: state.units.slice(unitFrom),
      info: { title: `${cfg.op || ''} ${cfg.name}`.trim(), lines: cfg.lines || [] },
    };
    g.traverse(o => { if (o.isMesh) o.userData.owner = g; });
    root.add(g);
    return g;
  }

  /* ---------- 表位实例化 ---------- */
  function disposeSlots() {
    if (!state.slotMesh) {
      return;
    }
    root.remove(state.slotMesh);
    state.slotMesh.geometry.dispose();
    state.slotMesh.material.dispose();
    state.slotMesh = null;
  }

  function rebuildSlots() {
    disposeSlots();
    const total = state.areas.reduce((n, a) => n + a.userData.slotPos.length, 0);
    if (!total) {
      return;
    }
    const geo = new THREE.BoxGeometry(0.115, 0.085, 0.075);
    const material = new THREE.MeshStandardMaterial({
      color: 0xffffff, roughness: 0.4, metalness: 0.3,
      emissive: 0x0a2a3c, emissiveIntensity: 0.9,
    });
    const mesh = new THREE.InstancedMesh(geo, material, total);
    mesh.instanceMatrix.setUsage(THREE.StaticDrawUsage);
    const dummy = new THREE.Object3D();
    const color = new THREE.Color(0x1d4a60);
    let i = 0;
    state.areas.forEach(area => {
      area.userData.slotPos.forEach(p => {
        dummy.position.set(p[0], p[1], p[2]);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
        mesh.setColorAt(i, color);
        i += 1;
      });
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.frustumCulled = false;
    mesh.castShadow = false;
    root.add(mesh);
    state.slotMesh = mesh;
  }

  const COL_ACTIVE = new THREE.Color(0x35f0ff);
  const COL_HOT = new THREE.Color(0xd8fdff);
  const COL_IDLE = new THREE.Color(0x1d4a60);
  const COL_NG = new THREE.Color(0xff7a86);

  /** 表位点亮：按 MES 数量折算的点亮设备数，从 1 号设备开始顺序填充表位，
   *  并叠一层沿表位序列滚动的扫描波（体现设备正在测试）。 */
  function paintSlots(areaCfgs, now) {
    const mesh = state.slotMesh;
    if (!mesh) {
      return;
    }
    const color = new THREE.Color();
    let base = 0;
    areaCfgs.forEach(cfg => {
      const area = state.areas.find(a => a.userData.code === cfg.code);
      if (!area) {
        return;
      }
      const ranges = area.userData.deviceRanges;
      const devices = ranges.length;
      const active = Math.max(0, Math.min(cfg.capacity || 0, cfg.active || 0));
      const lit = Math.max(0, Math.min(devices, cfg.litDevices || 0));
      const per = lit > 0 ? active / lit : 0;
      const activeColor = cfg.status === 'ng' ? COL_NG : COL_ACTIVE;
      const running = cfg.status !== 'idle';

      ranges.forEach(([s, e], di) => {
        const want = running && di < lit ? Math.min(e - s, Math.round(per)) : 0;
        // 每台设备的扫描波位置错开，波峰沿表位序列滚动
        const head = want > 4 ? ((now * 7 + di * 5.5) % (want + 10)) - 5 : -99;
        for (let i = s; i < e; i++) {
          const local = i - s;
          if (local >= want) {
            color.copy(COL_IDLE);
          } else if (running && want > 4) {
            const d = Math.abs(local - head);
            color.copy(activeColor).lerp(COL_HOT, Math.max(0, 1 - d / 4) * 0.9);
          } else {
            color.copy(activeColor);
          }
          mesh.setColorAt(base + i, color);
        }
      });
      base += area.userData.slotPos.length;
    });
    if (mesh.instanceColor) {
      mesh.instanceColor.needsUpdate = true;
    }
  }

  /* ---------- 厂房静态布景 ---------- */
  function buildStatic() {
    // 主通道标线
    const aisle = (x0, z0, x1, z1) => {
      const alongX = Math.abs(x1 - x0) > Math.abs(z1 - z0);
      const len = Math.hypot(x1 - x0, z1 - z0);
      const cx = (x0 + x1) / 2;
      const cz = (z0 + z1) / 2;
      const m = new THREE.Mesh(new THREE.PlaneGeometry(alongX ? len : 0.14, alongX ? 0.14 : len),
        new THREE.MeshBasicMaterial({ color: C.cyan, transparent: true, opacity: 0.12, depthWrite: false }));
      m.rotation.x = -Math.PI / 2;
      m.position.set(cx, 0.028, cz);
      root.add(m);
    };
    aisle(-52, -11.5, 50, -11.5);
    aisle(-52, 7.8, 50, 7.8);

    // 场地两端出入口标识（贴地，不压工区）
    root.add(makeFloorText('物流入口', -50.5, -11.5, { size: 1.9, alpha: 0.16, rot: Math.PI / 2 }));
    root.add(makeFloorText('成品出口', -50.5, 7.8, { size: 1.9, alpha: 0.16, rot: Math.PI / 2 }));
  }
  buildStatic();

  /* ---------- 上线产品 ---------- */
  function buildProducts() {
    const n = 18;
    for (let i = 0; i < n; i++) {
      const p = buildProduct();
      p.userData.dist = (path.total / n) * i;
      const pt = pathPoint(p.userData.dist);
      p.position.set(pt.x, BELT_Y, pt.z);
      root.add(p);
      state.products.push(p);
    }
  }
  buildProducts();

  /* ---------- 后期辉光 ---------- */
  let composer = null;
  try {
    composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    composer.addPass(new UnrealBloomPass(
      new THREE.Vector2(el.clientWidth || 1, el.clientHeight || 1), 0.5, 0.7, 0.8));
    composer.addPass(new OutputPass());
    composer.setSize(el.clientWidth || 1, el.clientHeight || 1);
  } catch (e) {
    composer = null;
  }

  /* ---------- 数据应用 ---------- */
  function applyArea(area, cfg) {
    const color = STATUS_COLOR[cfg.status] || C.cyan;
    area.userData.status = cfg.status || 'run';
    const running = cfg.status !== 'idle';

    area.userData.borderMats.forEach(m => {
      m.emissive.setHex(color);
      m.emissiveIntensity = running ? 0.8 : 0.32;
    });
    if (area.userData.padMat) {
      area.userData.padMat.emissive.setHex(color);
      area.userData.padMat.emissiveIntensity = running ? 0.08 : 0.03;
    }
    // 设备运行标识着色 + 启停：MES 过站数量折算的点亮设备数决定哪些设备开机
    const lit = Math.max(0, Math.min(cfg.devices || 0, cfg.litDevices || 0));
    area.userData.units.forEach((u, i) => {
      u.running = running && i < lit;
      u.ledMat.emissive.setHex(color);
      u.scanMat.color.setHex(color);
      u.barMat.color.setHex(color);
      u.haloMat.color.setHex(color);
    });

    const key = `${cfg.op || ''}|${cfg.name}|${cfg.sub || ''}`;
    if (area.userData.labelKey !== key) {
      area.userData.labelKey = key;
      const old = area.userData.label;
      const next = textSprite(`${cfg.op || ''} ${cfg.name}`.trim(), {
        w: 8.0, h: 2.2, fs: 122, sub: cfg.sub || '',
        color: cfg.status === 'ng' ? '#ff8a95' : cfg.status === 'slow' ? '#ffd27a' : `#${color.toString(16).padStart(6, '0')}`,
      });
      next.position.copy(old.position);
      area.remove(old);
      if (old.material.map) old.material.map.dispose();
      old.material.dispose();
      area.add(next);
      area.userData.label = next;
    }
    area.userData.info = { title: `${cfg.op || ''} ${cfg.name}`.trim(), lines: cfg.lines || [] };
  }

  function applyData(data) {
    const sc = (data && data.scene) || {};
    const list = sc.areas || [];

    // 首次或工区结构变化时重建场景
    const signature = list.map(a => `${a.code}:${a.devices}x${a.slots}`).join('|');
    if (signature !== state.signature) {
      state.areas.forEach(a => root.remove(a));
      state.areas = [];
      state.units.length = 0;
      state.probes.length = 0;
      state.scanners.length = 0;
      state.arms.length = 0;
      list.forEach(cfg => {
        const area = buildArea(cfg);
        if (area) {
          state.areas.push(area);
        }
      });
      rebuildSlots();
      state.signature = signature;
    }

    list.forEach(cfg => {
      const area = state.areas.find(a => a.userData.code === cfg.code);
      if (area) {
        applyArea(area, cfg);
      }
    });

    // 设备级 MES 过站数据铭牌：点亮设备显示过站/OK/NG，未点亮隐藏
    state.areas.forEach(area => {
      const cfg = list.find(c => c.code === area.userData.code);
      const devs = (cfg && cfg.deviceList) || [];
      area.userData.deviceLabels.forEach((sp, i) => {
        const d = devs[i];
        if (d && d.running && d.pass > 0) {
          drawDeviceLabel(sp, d);
          sp.visible = true;
        } else {
          sp.visible = false;
        }
      });
    });

    state.lastCfgs = list;
    paintSlots(list, clock.elapsedTime);
  }

  /* ---------- 交互 ---------- */
  const ray = new THREE.Raycaster();
  const ptr = new THREE.Vector2();
  const tip = document.createElement('div');
  tip.className = 'o_al3d_tip';
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
    for (const h of ray.intersectObjects(root.children, true)) {
      const info = findInfo(h.object);
      if (info && info.title) {
        tip.innerHTML = `<b>${info.title}</b>` + (info.lines || []).map(l => `<br>${l}`).join('');
        tip.hidden = false;
        const rect = el.getBoundingClientRect();
        tip.style.left = Math.min(e.clientX - rect.left + 14, rect.width - 280) + 'px';
        tip.style.top = (e.clientY - rect.top + 14) + 'px';
        clearTimeout(tipTimer);
        tipTimer = setTimeout(() => { tip.hidden = true; }, 5000);
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

  /* ---------- 尺寸 ---------- */
  function applyViewOffset() {
    const w = el.clientWidth || 1, h = el.clientHeight || 1;
    // 主体左移约 6% 屏宽：右侧浮层宽 336px，避免最右侧工区被遮住又不过度裁掉左侧
    try {
      camera.setViewOffset(w, h, Math.round(w * 0.06), Math.round(h * 0.012), w, h);
    } catch (e) {
      /* 老版本 three 不支持时忽略 */
    }
  }

  function resize() {
    const w = el.clientWidth || 1, h = el.clientHeight || 1;
    camera.aspect = w / h;
    applyViewOffset();
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
  const tmpColor = new THREE.Color();

  function animate() {
    if (state.disposed) return;
    state.raf = requestAnimationFrame(animate);
    const dt = Math.min(clock.getDelta(), 0.05);
    const t = clock.elapsedTime;

    // 机械臂
    state.arms.forEach(a => {
      a.pivot.rotation.x = Math.sin(t * 1.1 + a.phase) * 0.36 - 0.12;
      a.elbow.rotation.x = Math.sin(t * 1.1 + a.phase + 1.05) * 0.4;
    });

    // 探针
    state.probes.forEach(p => {
      p.obj.position.y = p.base + 0.08 * Math.sin(t * 2.2 + p.phase);
    });

    // 设备运行标识：状态灯脉动 / 扫描光带往返 / 立柱呼吸 / 地面光环扩散 / 过站产品循环
    state.units.forEach(u => {
      const on = u.running;
      if (on) {
        const pulse = 0.5 + 0.5 * Math.sin(t * 3.2 + u.phase);
        u.ledMat.emissiveIntensity = 1.1 + 1.7 * pulse;
        u.scan.position.z = u.dz + Math.sin(t * 1.6 + u.phase) * 0.52;
        u.scanMat.opacity = 0.1 + 0.26 * pulse;
        u.barMat.opacity = 0.28 + 0.4 * pulse;
        const k = (t * 0.5 + u.phase / 6.2832) % 1;
        u.halo.scale.setScalar(1 + k * 0.95);
        u.haloMat.opacity = 0.26 * (1 - k);
      } else {
        u.ledMat.emissiveIntensity = 0.1;
        u.scanMat.opacity = 0;
        u.barMat.opacity = 0.05;
        u.haloMat.opacity = 0;
      }

      // 过站产品：滑入设备 → 加工中随扫描微动 → 出料滑出，循环演示
      const prod = u.cycleProd;
      if (!prod) {
        return;
      }
      prod.visible = on;
      if (!on) {
        return;
      }
      const period = u.cyclePeriod || 10;
      const tt = (t + u.cyclePhase) % period;
      const move = 1.5;
      const ease = k => k * k * (3 - 2 * k);
      if (tt < move) {
        // 进设备：从输送侧滑入表架
        const e = ease(tt / move);
        prod.position.set(prod.position.x, 0.12 + 0.62 * e, u.dz + 1.9 - 1.9 * e);
      } else if (tt > period - move) {
        // 出料：滑向下游侧
        const e = ease((period - tt) / move);
        prod.position.set(prod.position.x, 0.12 + 0.62 * e, u.dz + 1.9 - 1.9 * e);
      } else {
        // 加工中：轻微起伏，跟随扫描节奏
        prod.position.set(prod.position.x, 0.74 + 0.02 * Math.sin(t * 5 + u.phase), u.dz);
      }
    });

    // 工区边框呼吸
    state.areas.forEach((area, index) => {
      const st = area.userData.status;
      const speed = st === 'ng' ? 4.6 : st === 'slow' ? 2.2 : 1.3;
      const baseI = st === 'idle' ? 0.3 : 0.78;
      area.userData.borderMats.forEach(m => {
        m.emissiveIntensity = baseI + 0.22 * Math.sin(t * speed + index);
      });
    });

    // 在测表位滚动扫描波（约 8Hz 刷新，避免每帧上传整块实例色）
    if (state.lastCfgs.length && t - state.lastPaint > 0.12) {
      state.lastPaint = t;
      paintSlots(state.lastCfgs, t);
    }

    // 产品沿工艺路线流动
    const step = state.speed * dt * path.total / 60;
    state.products.forEach(p => {
      p.userData.dist += step;
      if (p.userData.dist > path.total) {
        p.userData.dist -= path.total;
      }
      const pt = pathPoint(p.userData.dist);
      p.position.x = pt.x;
      p.position.z = pt.z;
      p.rotation.y = Math.atan2(pt.dx, pt.dz);
      // 经过异常工区时表体转红，经过瓶颈转琥珀
      let target = C.cyan;
      for (const area of state.areas) {
        const L = AREA_LAYOUT[area.userData.code];
        if (L && pt.x >= L.x0 && pt.x <= L.x1 && pt.z >= L.z0 && pt.z <= L.z1) {
          const st = area.userData.status;
          target = st === 'ng' ? C.red : st === 'slow' ? C.amber : C.cyan;
          break;
        }
      }
      tmpColor.setHex(target);
      p.userData.bodyMat.emissive.lerp(tmpColor, 0.05);
      p.userData.ledMat.emissive.lerp(tmpColor, 0.05);
    });

    controls.update();
    if (composer) composer.render();
    else renderer.render(scene, camera);
  }

  applyViewOffset();
  camera.updateProjectionMatrix();

  applyData(opts.data || {});
  animate();

  return {
    update(data) {
      if (state.disposed) return;
      applyData(data || {});
    },
    resetView() {
      camera.position.fromArray(CAM_HOME.pos);
      controls.target.fromArray(CAM_HOME.target);
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
