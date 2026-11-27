---
name: cfd-web3d
description: 把 CFD/CAE 结果（ANSYS Fluent·CFD-Post、COMSOL、ParaView、自算场）做成网页里能转的 3D。当用户说"把流线/云图/切面放到网页""做成可交互的三维图""导出 glTF/GLB""这个三维结果给汇报/内网用"时加载：三条路线怎么选、各软件的按钮与 API、坐标系与配色坑、体积预算、验收清单。
---

# CFD 结果 → 网页 3D

把"仿真里能转的那张三维图"变成浏览器里能转的东西。**最终格式一定是 glTF 2.0（.glb）**，
网页端渲染用 three.js。下列结论在 Windows + ANSYS 2025 R2 + COMSOL 6.3 + three.js r186 上逐条实测。

## 先选路线

| 路线 | 做法 | 何时用 | 代价 |
|---|---|---|---|
| **A 软件原生导** | 软件自己把绘图组导成 glTF | 只要一版能转的汇报图 | 可控性低，改一点要回软件重导 |
| **B 场数据自算**（推荐做正式交付） | 导出场数据 → 本 skill 脚本积分流线 → GLB | 配色/图例/密度可控、要批量、要嵌内网 | 多一步数据导出 |
| **C 图片/序列帧** | 软件出 PNG 或动画 | 只要看，不需要转视角 | 不是 3D |

判断口令：**要"能转"→ A 或 B；要"点哪儿读数值"→ 都不够**，得带原始场数据（vtk.js）。

## 路线 A：软件原生导 glTF

### COMSOL（6.3 实测）

- 入口：结果树 **导出 → 图像（Image）**，格式选 glTF；GUI 里也可用图形窗口的「图像快照」。
- **只有三维绘图组能导**（sdim=3 → allowgltf=on；1D/2D 一律不允许）。
- 颜色走**顶点色 COLOR_0**（不是纹理），比 VTK 系省事。
- 图例/标题**不会**随文件导出，网页端要自己画。
- 批量脚本：`scripts/comsol_export_gltf.py`

```powershell
& 'D:\program\py\python.exe' scripts/comsol_export_gltf.py --list --model "<...>.mph"
& 'D:\program\py\python.exe' scripts/comsol_export_gltf.py --model "<...>.mph" --plot pg14 --out out/scene.glb
```

**必踩的坑**：不显式 `set("allowgltf","on")` 直接设 `imagetype=gltf`，报错是
"属性值无效（格式只支持 bmp/jpeg/png/tiff/gif）"——看着像不支持 glTF，其实是"这个绘图组不是 3D"。

流线特征的可调项：`expr`（速度向量，如 `["u","v","w"]`）、`linetype`（line/ribbon/**tube**）、
`posmethod`+`number`（均匀布种）、`maxlen` / `maxsteps`。变量名必须**在该绘图组的数据集上可求值**：
2D 物理映射出来的 3D 数据集里取不到三维速度分量，流线会在渲染时炸（不是导出时）。

### ANSYS（2025 R2 实测）

- **CFD-Post**：会话里设 `HARDCOPY` 再 `print`，格式 `gltf`（文本）或 `glb2`（**二进制 GLB**）。
  模板见 `templates/cfdpost_hardcopy_gltf.cse`。
- CFD-Post 会**按视口导出多个 scene**（Viewport1..4），网页端默认只加载 `scenes[0]`。
- 2025 R2 的 `EXPORT` 单例里**没有 VTK/EnSight**，别按老教程找"导成 VTK 折线"。
- Fluent 的 Export 只导场数据、不导流线几何：要流线几何走 A（CFD-Post）或 B（自己积分）。

### ParaView / PyVista

```python
pl = pv.Plotter(off_screen=True)
pl.add_mesh(mesh.streamlines_from_source(src, vectors="Velocity").tube(radius=r, n_sides=8),
            scalars="Speed", cmap="viridis")
pl.export_gltf("scene.glb")
```

注意：`vtkGLTFExporter`（PyVista 底层）**即使文件名写 .glb 也可能写出文本 glTF**，
颜色靠 `baseColorTexture` + `TEXCOORD_0`。判据只有一个：首字节 `g` 才是 GLB，`{` 是 JSON。

## 路线 B：场数据自算流线（本 skill 主力）

`scripts/field_streamlines.py` 只依赖 numpy，输入两种：

1. **平面场 npz**：`X (nx,)`、`Y (ny,)`、`VX/VY`（`(ny,nx)` 或 `(nx,ny)`，脚本自动判向），
   可选 `VZ/U/P`。CFD 后处理最常见就是这种切面数据。
2. **三维结构化 .vtk**：legacy ASCII，`DIMENSIONS` + `POINTS` + `VECTORS Velocity`。

```powershell
# 平面场 + 船体（几何若是 mm，用 --hull-scale 0.001）
& 'D:\program\py\python.exe' scripts/field_streamlines.py --npz mid.npz --out scene.glb
& 'D:\program\py\python.exe' scripts/field_streamlines.py --npz mid.npz --hull tris_clean.bin --hull-scale 0.001 --seeds 40 --radius 0.2 --out scene.glb
```

输出 `scene.glb` + `scene.meta.json`（图例用：单位、范围、色标）。要点：

- 速度**先归一化再积分**（等弧长步进），否则大域要跑几十万步；
- 种子按"来流上游"自动判断，可用 `--upstream auto|lo|hi` 覆盖；
- `--hull` 把船体/障碍三角面一起塞进同一个 GLB（灰、单 primitive）；
- 平面场（nz=1）的 z 边界厚度为 0，脚本已跳过该维越界判定（不跳会一步全死）。

## 网页端

`web/viewer.html`（three.js 走 CDN，免 npm）+ `web/serve.mjs`：

```powershell
node web/serve.mjs 8787
# http://127.0.0.1:8787/viewer.html?src=/scene.glb
# http://127.0.0.1:8787/viewer.html?src=/scene.glb&meta=/scene.meta.json&axes=none
```

| 参数 | 作用 |
|---|---|
| `src` | glb/gltf 路径；不给则用 `scene.glb` |
| `meta` | 图例信息；不给会**自动**找同名 `.meta.json` |
| `axes` | `none`（默认，官方导出器已转好）/ `zup`（CFD 裸 Z-up 数据）/ `vtk`（(x,y,z)→(y,z,x) 置换） |

自带：按真实包围盒自动取景 + 随尺度调近远平面、色标图例、X 向剖切、自动旋转、导出 PNG、帧率。

## 坑（全部实测，按出现频率排）

1. **glTF 只存几何+颜色，不存数据**：图例、单位、范围、探针值都得前端另建。
2. **坐标系转两次就歪 90°**：CFD 是 Z-up、glTF 是 Y-up；官方导出器通常已在 node 矩阵里转好，
   网页里再转就错。用 `?axes=` 明确指定，别猜。
3. **线宽在 Windows/ANGLE 上恒为 1px**：要粗细就做管子网格（`--radius`），或用 `Line2`。
4. **glTF 的线图元不是 Mesh**：three.js 里 mode=1 变成 `LineSegments`，只认 `isMesh` 的加载器会报"没有网格"。
5. **单位**：几何常是 mm、场数据是 m，混用会放大 1000 倍（`--hull-scale 0.001`）。
6. **尺度**：几厘米的试件和三百米的船域在同一套相机里，必须按包围盒动态设 near/far，否则整个场景被裁掉。
7. **大域多线会糊成一团**：320 m 的域铺 600 条线远看是一块白斑。降种子数、只画贴体一段，或改"切面流线 + 色标"。
8. **命名都不直白**：COMSOL 只有 3D 绘图组能导 glTF；ANSYS 只有 `glb2` 才是二进制。

## 体积预算

| 内容 | 量级 | 说明 |
|---|---|---|
| 96 条 8 边管，14.8 万三角面 | 3.7 MiB（gzip 47%、brotli 1.16 MiB） | 一张汇报图的正常量 |
| 32k 三角面船体 + 3 万顶点管子 | 4.7 MiB | 极地号 0° 风载实算例 |
| 只要折线（float32 xyz + uint8 rgb） | 同数据约 1/20 | 但 1px 线宽，远看糊 |

首屏目标 **< 3 MiB**（压缩后）。超了先降：管子边数 8→6、种子数减半、抽稀折线。
再狠一点：Draco / meshopt（gltf-transform、gltfpack）或分块 LOD。

## 验收清单

1. 文件首字节是 `g`（GLB）还是 `{`（文本 glTF）？文本版 +33% 体积。
2. 网页里颜色与软件一致？不一致先查是不是被自建材质覆盖（顶点色/纹理都要保留）。
3. 流线相对几何体没歪 90°、没镜像？
4. 图例刻度与数据范围对得上（meta 的 `range` 用 p99 而不是 max）？
5. 手机能转吗（`devicePixelRatio` 上限 2）？
6. 首屏体积、三角面数在预算内？

## 附：脚本清单

| 文件 | 作用 |
|---|---|
| `scripts/field_streamlines.py` | 场数据 → 流线 → 管状 GLB + meta（numpy，无第三方依赖） |
| `scripts/comsol_export_gltf.py` | COMSOL 原生导出：`--list` 列绘图组 / `--plot` 导 GLB |
| `templates/cfdpost_hardcopy_gltf.cse` | CFD-Post 会话模板（`gltf` 文本 / `glb2` 二进制） |
| `web/viewer.html` | three.js 查看器（CDN，免构建） |
| `web/serve.mjs` | 带正确 MIME 的本地静态服务器 |

依赖：Python 3.10+ 且 `numpy`；Node 18+（只用来起静态服务）；three.js 走 CDN。
