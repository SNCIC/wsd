/**
 * 整机自动线看板打包入口：three.js + OrbitControls + Bloom + 场景压成单文件 IIFE，
 * 挂到 window.SnAssemblyLine3D，供 OWL 组件在 loadBundle 之后调用。
 * 构建命令见 build_line_3d.sh
 */
import { mount } from './line_scene.js';

globalThis.SnAssemblyLine3D = { mount };
