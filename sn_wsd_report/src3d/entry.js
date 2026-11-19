/**
 * 打包入口：把 three.js + OrbitControls + Bloom + 场景代码压成单文件 IIFE，
 * 挂到 window.SnWarehouse3D，供 OWL 组件在 lazyLoad 之后调用。
 * 构建命令见 build_3d.sh
 */
import { mount } from './scene.js';

globalThis.SnWarehouse3D = { mount };
