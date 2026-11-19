#!/usr/bin/env bash
# 构建仓库 3D 运输看板的单文件资源
# 用法：在 sn_wsd_report 目录执行 bash build_3d.sh
set -e
cd "$(dirname "$0")"
npx --yes esbuild@0.21.5 src3d/entry.js \
  --bundle \
  --format=iife \
  --minify \
  --target=es2020 \
  --alias:three=./static/src/lib/three/three.module.js \
  --outfile=static/src/js/warehouse_3d_scene.bundle.js
echo "built: static/src/js/warehouse_3d_scene.bundle.js"
