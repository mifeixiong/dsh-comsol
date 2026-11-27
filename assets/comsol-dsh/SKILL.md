---
name: comsol-dsh
description: Drive COMSOL Multiphysics models end to end - open in the desktop, read/modify parameters, rebuild mesh, tune solver, run steady or time-dependent studies with live progress, load results into the desktop plot, evaluate and export. Use when the user asks to run, modify, solve, or inspect a COMSOL (.mph) model.
---

# COMSOL Multiphysics workflow skill

## When to use this skill

The user wants anything done with a COMSOL model: open it, explain it, change a
parameter, refine the mesh, re-solve, get numbers out, or export a plot image.
The engine behind this skill is `comsol-mcp` (a stdio MCP server driving a
COMSOL Multiphysics server + visible desktop client through MPh).

> **Driving MPh / `model.java.*` directly?** Jump to
> [直驱 MPh + Java API 实战清单](#直驱-mph--java-api-实战清单comsol-63-实测2026-11-极地号-cfd-复盘)
> near the end: property-name landmines, the solver-collapse trap, mesh strategy,
> sign conventions, single-machine multi-agent gating, and a physics self-check card.

## Install into DSH

This skill ships as the **`dsh-comsol` plugin**. In the DSH left-sidebar plugin
panel, find "COMSOL" and toggle it on; new sessions then offer the `comsol-dsh`
skill automatically (toggling it off removes the skill everywhere). To install
the plugin on a fresh machine, copy the bundle folder into
`%USERPROFILE%/.dsh/plugin-sources/dsh-comsol`, add it to the profile's
`package.json` (`dependencies: {"dsh-comsol": "link:..."}` and append
`"dsh-comsol"` to `dsh.profile.bundles`), run `pnpm install` in the profile
directory, and restart DSH.

The skill body is `SKILL.md` here; the runner is `scripts/run_workflow.py`
(shipped alongside under the plugin's `assets/`). DSH has no per-conversation
MCP slot by default, so COMSOL is driven through that runner - a single
command, no resident server. (DSH does have an optional `dsh-mcp-client`
bridge that would expose `mcp__comsol__*` tools directly; it is deliberately
not mounted because `comsol-mcp` starts a JVM at import, which would then sit
resident for every DSH session.)

## Prerequisites (verify once per machine)

- COMSOL Multiphysics **6.0 - 6.3** (fully verified on **6.2**), local install +
  valid license. MPh auto-discovers it; set `COMSOL_ROOT` (the `.../Multiphysics`
  folder) only if `comsol-mcp detect` finds nothing.
- Python **3.10+** with the engine importable. The runner auto-detects, in order:
  `COMSOL_MCP_REPO` env var / `--mcp-repo`, a sibling `comsol-mcp/` checkout next
  to this skill folder, then an installed `comsol-mcp` package. It always puts
  that checkout's `src/` first on the server's `PYTHONPATH`. Plus the `mcp`
  package (`pip install mcp`) for this script itself.
- **Foreground session to SEE the window.** A COMSOL desktop started from a
  background task lives in another Windows session and is invisible to
  the user. If the user wants to watch, run in their own terminal.

## GPU acceleration (COMSOL 6.3)

COMSOL 6.3 runs on a GPU in exactly three situations: time-explicit pressure
acoustics (dG-FEM), a Hardware Acceleration node under a Time-Dependent solver
for discontinuous Galerkin, and DNN surrogate training. Every other solver -
stationary or implicit transient FEM - stays on the CPU; a GPU buys nothing
there, so do not offer acceleration for a steady electro-thermal model.

Two model-side switches, both exposed by the engine:

| Where | Switch | Property names |
|---|---|---|
| solver node, e.g. `solution/sol1/feature/t1` | HardwareAcceleration feature (tag `ha1`) | `dgacc`, `gpuresidual`, `gpusingleprecision`, `usemaxblocksize` |
| physics interface, e.g. `physics/acpr` (Pressure Acoustics, Time Explicit) | SolverSettings group | `AcceleratedFormulation`, `GPUResidual`, `GPUSinglePrecision` |

Playbook:

1. `comsol_gpu_status` - read `host.conclusion` **before** promising anything.
   COMSOL 6.3 needs compute capability 6.0-9.0 and a CUDA 12 runtime: it loads
   `cudart64_12.dll` / `cublas64_12.dll`, so a CUDA 13-only toolkit
   (`cudart64_13`) does not qualify, and RTX 50-series cards (12.0) sit outside
   the support matrix.
2. `comsol_gpu_configure(enabled=True, single_precision=False)` - creates
   `ha1` under each Time-Dependent solver node and sets the interface flag.
3. `comsol_solve(study="std1", gpu=True)` - the same switches, applied right
   before the solve; `gpu=False` turns them off again.

Hard notes: single precision is faster and less exact (COMSOL defaults to double
precision, and Compute residual on GPU stays on); multi-GPU needs a floating
network license; the switches are model-side only - on an unsupported card the
solve still runs on the CPU, so never report a speed-up that was not measured.
The one-command workflow accepts `--gpu` (and `--gpu-single-precision`).

## The one-command workflow (recommended)

```powershell
python <skill>/scripts/run_workflow.py --model "<abs path>.mph" --home "<work dir>"
```

Preflight first, without touching COMSOL:

```powershell
python <skill>/scripts/run_workflow.py --model "<abs>" --home "<dir>" --check
```

Chain: open -> describe -> parameters -> solver tweak -> mesh `hauto` one step
finer + rebuild -> background solve with progress -> evaluate -> export plot
image -> show in desktop -> clean shutdown. Sensible defaults are safe on any
model: **no parameter changes unless `--set-param NAME=VALUE` (repeatable)**,
expression auto-picked from the physics (T / solid.mises / es.normE), plot group
auto-picked by label. Other flags: `--hauto N|none`, `--no-mesh`,
`--no-solver-tweak`, `--study std1`, `--dataset dset1`, `--expression`,
`--plot-hint`, `--timeout`, `--port`, `--reuse-port`, `--no-close`,
`--gpu`, `--gpu-single-precision`, `--mcp-repo`.

Lock/port guard: `<model>.mph.lock` is deleted only when no COMSOL process is
live (`--allow-live-lock` to force); the run aborts if the port is already
listening (`--reuse-port` to attach instead). Never run two workflows against
the same port at once. On early failure the session is still ended cleanly
(snapshots cover the work).

## Transient workflow (time-varying boundary condition)

`scripts/run_transient.py` turns a steady model into a Time Dependent one:
adds an Analytic ramp function `Tbc(x)=base+delta*(1-exp(-x/tau))`, rewires a
heat boundary to `Tbc(t)`, creates a transient study, solves, exports the
per-timestep `T` series to CSV, verifies the rise, and saves a new model.

```powershell
python <skill>/scripts/run_transient.py --model "<in>.mph" --home "<dir>" `
  --save-as "<out>.mph" --allow-code `
  --base-k 293.15 --delta-k 60 --tau-s 15 --tlist "range(0,1,60)"
```

It edits model structure (functions/studies/solvers), so it runs through
`comsol_run_python` and **requires `--allow-code`** (hard rule 6). Defaults
auto-detect the boundary (a Temperature `T0`, else a HeatFlux convective
ambient `Text`); override with `--bc-feature`/`--bc-prop`. `--save-as` never
overwrites and never touches the input file.

**Like a manual COMSOL run**: while solving, COMSOL's own progress window is
shown in the desktop (`--stream-progress` keeps the console channel instead);
afterwards the transient dataset is bound to the model's temperature plot
group and rendered, so the window shows the solved result. By default the run
then **holds the session open** for inspection and cleans up automatically the
moment you close the COMSOL window (or after `--hold-max` seconds). `--close`
shuts everything down immediately instead; `--shutdown-only --port N` recovers
a session left behind by an interrupted run.

Field-tested traps on 6.2 the script already handles (do not reintroduce them
when editing by hand):
- **Analytic functions take `x`, not `s`/`t`.** A body using the wrong argument
  name fails deep inside the solve ("Variable: s ... not found"). Build in `x`,
  call as `Func(t)`.
- **Units go inside the expression** (`293.15[K]+60[K]*(...)`); `funcunit` /
  `argunit` are not valid Analytic properties and raise "Unknown".
- **A failed solve strands an empty-shell `solN`** (no features, no datasets);
  stale dataset tags then break `comsol_evaluate` ("Dataset does not exist").
  Drop empty shells before solving and re-derive dataset tags after.
- **In a GUI-owned session you cannot create numerical/plot operations**
  ("Operation cannot be created in this context"). Verify with a Data export
  node (allowed) or a headless reopen (`gui=False`), never `result().numerical()`.
- **`study.createSolver()` / `createAutoSequencesAll()` do not exist on 6.2**;
  the real call is `sol.createAutoSequences(<stepTag>)`, and even that is
  optional because `study.run()` auto-builds the sequence.
- **You cannot leave the desktop open by exiting the runner.** The COMSOL
  desktop client (`comsolmphclient`) shuts itself down when its MCP/engine
  process dies (verified: it survives neither JVM exit nor WMI-detached
  launch). To let the user inspect results, *hold the session* - poll
  `comsol_session_status` until `gui_pid` disappears (user closed the window),
  then end the session cleanly.

## Tool playbook (driving the MCP server directly)

1. `comsol_detect` - installs, desktop processes, port 2036.
2. `comsol_start_session(model_path=...)` - server + desktop open the file;
   the desktop owns the main model (`owner: gui`). Takes ~30-115 s. Normal.
3. `comsol_describe_model` - parameters/components/physics/mesh/studies/
   solutions/results. Start every "understand" request here.
4. `comsol_get_parameters` / `comsol_set_parameters({"I": "200[A]"})` -
   values are strings exactly as COMSOL expects, units included. Snapshots
   automatically first.
5. Solver probe - `comsol_node_tree(path="solution/sol1", depth=4)`, find the
   `Stationary` feature (`s1`); read with `comsol_get_property(node=...)`,
   tweak with `comsol_set_property(node=..., property_name=..., value=...)`.
   **Parameter-name trap:** the getter takes `property`, the setter takes
   `property_name`; mixing them up raises "Unknown argument". Unknown node ->
   skip the tweak, never guess.
6. Mesh - `comsol_get_property(node="component/comp1/mesh/mesh1/feature/size",
   property="hauto")`, set one step finer with
   `comsol_set_property(..., property_name="hauto", value="3")`, then
   `comsol_mesh(action="build_stats")`. If the model has no COMSOL mesh (only
   import/part-work), there is no `size` feature - skip.
7. Solve - `comsol_solve_start({})` (or `{"study": "std1"}`), poll
   `comsol_solve_status` every ~5 s (`state/progress.percent/last_line`, as
   JSON - parse it, do not grep raw text). COMSOL has no cancel API; the Stop
   button in its progress window does that. `state: done` + a solution listed
   before trusting results; `failed` carries the COMSOL error in `error`.
8. Post - `comsol_evaluate(expression="T")` (`values` inline, or `file` +
   `statistics` for large results), `comsol_export_plot_image(plot_group="pg3")`
   (read the PNG back and describe it), `comsol_show_results(plot_group="pg3")`
   so the desktop shows it. Plot group tags/labels come from
   `comsol_describe_model -> results.plot_groups`.
9. `comsol_end_session(save=False, stop_server=True, close_gui=True)` -
   snapshots cover the work; a "save changes?" dialog is answered with No.

## Hard rules (field-tested on 6.2, do not violate)

1. **Never force-kill the COMSOL window** (`taskkill /F`, End task). A killed
   desktop corrupts the server-side session; every later connection fails until
   the server restarts. Ask the user to close it from the COMSOL UI.
2. `Server is in use by another client` almost always means a modal dialog is
   open in the COMSOL window (e.g. "save changes?"). Ask the user to dismiss
   it, then retry. `run_workflow.py` sweeps stale windows via
   `comsol_focus_desktop` after mesh and after results, and once more inside
   the close handshake. The blank box over the model tree is a Chinese-IME
   `CiceroUIWndFrame` ghost: the sweep walks the whole descendant window tree
   and hides only small *floating* residue (never a docked panel, never while
   progress is fresh), best-effort, never force-killed. Dialog dismissal
   matches button labels by normalized prefix, so a Chinese "否(N)" is still
   found by "No"; a lingering "等待服务空闲" frame is answered with
   Quit/Cancel on a second pass.
3. The desktop only shows models **it** opened. To show another model, start a
   new session with that `model_path` - never load via API and claim it shows.
4. `Untitled.mph` instead of the requested model -> stale `<model>.mph.lock`
   (server stopped while the window held the model). The runner only removes it
   when no COMSOL process is running; in future close the window before
   stopping the server (`comsol_end_session(close_gui=True, stop_server=True)`
   does exactly that).
5. `comsol_save_model` **never overwrites** without explicit user confirmation
   (`allow_overwrite=True`). Saves/snapshots go to `<home>/saved|history/`.
6. `comsol_run_python` stays disabled unless the user sets
   `COMSOL_MCP_ALLOW_CODE=1` (the runners expose that as `--allow-code`;
   `run_workflow.py` does not need it, `run_transient.py` requires it and
   refuses to start without it).
7. One desktop per server port. `run_workflow.py` refuses a busy port unless
   `--reuse-port` is passed.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `start_session` times out, desktop reports `['Model1']` | stale `.mph.lock` | runner deletes it when no COMSOL runs; otherwise close the window |
| `Server is in use by another client` | port busy / modal dialog | free the port / dismiss dialog, retry |
| runner aborts "port is already listening" | another session holds 2036 | stop it, use another `--port`, or `--reuse-port` |
| runner aborts "engine does not match" | old comsol-mcp checkout | update the engine or pass `--mcp-repo` |
| `focus_desktop`: `GetClassName not found` | restricted shell blocks win32 `ctypes` | run from a normal terminal; solve is unaffected |
| Window never appears | started from a background task | re-run in the user's foreground terminal |
| `solve_status` stays `idle` | solve never started (fail-fast) | check the `solve_start` error, do not poll forever |
| evaluate/plot shows stale numbers | solve still running when you post-processed | wait for `state: done` in solve_status first |


---

## 直驱 MPh + Java API 实战清单（COMSOL 6.3 实测，2026-11 极地号 CFD 复盘）

不经过 `comsol-mcp` 的 MCP 工具、直接用 `MPh 1.4` + JPype 调 `model.java.*` 时，下面每一条都是报错后确定的写法。**先读这一节，能省掉半天。**

### A. 属性赋值：数值一律传字符串

| 对象 | 正确 | 报错写法与信息 |
|---|---|---|
| `selection` | `s.set("entitydim","2")`、`s.set("xmin","-150")` | 传 int/float → `Ambiguous overloads ... set(str,int)/set(str,double)` |
| Block | `bk.set("size",["400","46.59","140"])` | 传 list[float] 同上 |
| 全局 mesh size | `m.feature("size").set("hauto","5")` | 传 int 同上 |
| 局部 Size | `f.set("hmaxactive","on")`、`f.set("hmax","0.5")` | 全局 size 节点**没有**这些 `*active` 开关 |
| 入口速度 | `fi.set("U0in","7.716[m/s]")` | `U0` 不存在；`u0` 数组易报"期望长度为 3" |
| 壁面类型 | `w.set("BoundaryCondition","Slip")` | `WallType` / `SlipWall` 都不存在 |

### B. 对象创建签名

- 物理场：`c.physics().create("spf","TurbulentFlowSST","3")` —— 第三参必须是**字符串** `"3"`（传 int 报 `No matching overloads ... create(str,str,int)`）。
- 材料：`c.material().create("mat1","Common")` —— **只有两个参数**，带 `"3"` 报"未知模型"。
  然后 `mat.propertyGroup("def").set("density","1025")`、`.set("dynamicviscosity","1.22e-3")`。
  **没有材料 → 求解报"未定义材料属性 mu"**。
- 网格单元：`m.create("ftet1","FreeTet"); ftet.set("optlevel","high")` —— 合法值 `basic/medium/high`，`quality` 无效。

### C. 特征 tag 不能猜

- **没有默认 `wall1`**：用 API 建 `TurbulentFlowSST` 时不生成 Wall 节点，`spf.feature("wall1")` 抛"未知物理场接口特征"。
- 正确做法：自己建 `spf.create("wallShip","Wall",2)` 与 `spf.create("wallOuter","Wall",2)`，用 `selection().set([...])` 赋面号。
- **后建覆盖先建**：先建滑移壁面、最后建 NoSlip 壁面；否则后建的 Slip 会把船体覆盖成全滑移（本会话真实踩过）。
- 边界条件要显式全覆盖：`outer = set(range(1, nBnd+1)) - ship - inlet - outlet`。

### D. 无法通过 API 配置的两处（6.3）

| 想配的东西 | 现实 |
|---|---|
| `BndLayer` 的层数 / 首层厚度 | 属性表只有 `sharpcorners / trimminangle / layerdec / trimmaxangle / splitangle / ...`，**没有 `bln/blstretch/blthickness`** → 本版本无法用脚本加边界层 |
| `sol1.feature("s1")` 的 `maxiter` / `dtech` | 报"未知的求解器特性"——**手工拼出来的求解器序列没有可调的非线性迭代上限**（见 §E） |

### E. 求解器：三条铁律（本次最大教训）

1. **不要复用别人的 `.mph` 直接 `study.run()`。** 实测：加载一个已有解的模型再跑一次，会把解覆盖成"等于初始场"的假解（`max(spf.U)` 从 10.48 掉回 7.716 = 来流值，压力积分从 −443 kN 变 −30.3 MN）。同一模型两次求解差 **68 倍**就是这么来的。
2. **正确做法：几何 → 网格 → 物理 → 边界条件全部建完后，新建 study**：
   ```python
   std = j.study().create("std1"); std.create("stat","Stationary"); std.run()
   ```
   让 COMSOL **自动生成**求解器序列，一个 solver 属性都不要改。
3. **收敛证书（缺一不可）**：
   - `max(spf.U)` 必须明显偏离来流：钝体横风 1.5–2.5×，细长体顶风 1.3× 也算合格；**等于来流就是塌陷**；
   - 同一模型**连跑两次**，关键量相对差应 <1e-3（好解实测 4×10⁻⁶）；
   - 控制体**动量平衡** D 与压力积分 R_p 自洽（D ≈ R_p + 摩擦）。
   **不要用"残差降到 1e-4"当唯一判据。**

### F. 网格策略（大尺度钝体/船体）

- **别用 minQ 判好坏**：实船几何有尖边（艉封板、整流鳍、龙骨端），minQ 永远 <0.05。判据用 **meanQ ≥ 0.5 且 quality<0.25 的单元占比 <1%**。
- **单元数不由壁面尺寸控制**：`hauto 4` 下船体壁 1.0→1.8 m 只降 3.5%，因为全局默认尺寸被上千个小特征拉低（本船 1648 个面 → 默认 ~2.8 m）。要么显式压全局 `hmax`，要么接受规模。
- **局部尺寸盒才是性价比**：一条 90 m 船 `hauto5 + 船体 0.5 / 艏 0.18 / 艉 0.28 / 吊舱 0.09` → 31 万四面体、22 s、meanQ 0.688。
- **薄缝不要局部加密**：25 mm 环缝设 `hmax 0.008–0.016` 会因 `hgrad` 传播涨到 46–155 万单元且质量更差（hgrad 1.1 传播 10–20 层）。改几何（把缝堵上）比加密便宜。
- **"能不能出网格"是域尺寸 × 全局 hmax 的函数**：同一几何换个小参考域，`hauto 4` 从硬失败变成"能过但质量差"。
- 改 `hmax` 必须**重建 Mesh Sequence**（复用旧 mesh 对象改参数不重算）。

### G. 符号、单位、取数

- **面法向**：COMSOL 导入 CAD 实体后 `nx/ny/nz` 指向实体外（流入流体），与流体域外法向相反。作用在实体上的压力 = `∫p·n dA`，不是 `∫(−p)·n dA`。验证方法：看分区压力（迎风面正、背风面负）反推力的方向。
- **力矩必须含全部叉积项**：`M_x = ∫(y·F_z − z·F_y)`，漏掉 `−z·F_y` 会差 15%。参考点要写清。
- **重力**：不显式设 `grav1.g = ["0","0","0"]`，压力里会混进 `ρgh`（40 m 水柱 = 398 kPa），p_max 会从 30 kPa 跳到 600 kPa，力会大一个量级。
- **取数**：`IntSurface` 必须 `it.set("data","dset1")` 并确认 `len(it.selection().entities(2))>0`，否则 `getReal()` 返回空数组（"array index out of bounds"）。
- **Interp**：坐标矩阵用 **N×3**；报"postinterp 中有错误的搜索点的维度"就是形状反了。
- **Data 导出的平面/体数据展平顺序是 x 最快、z 最慢**；按 `(ny,nz)` 直接 reshape 会得到斜向拉丝的假图。判序技巧：用物体 NaN 洞的包围盒最小来确定。
- **GProp 体积用默认容差会欠积分**：同一实体默认 14 024 m³、显式 `eps≤1e-7` 为 14 247 m³（差 1.6%）。体积一律显式传 eps 并用第二种方法（高度场/切片）交叉验证。
- **STEP 的 PRODUCT 顺序与 shape 顺序不保证一致** → 按名字选实体不可靠，用 XCAF label 或按几何（包围盒/体积）选。

### H. 单机多智能体调度（一台机器只能跑一个 server）

15.6 GB 内存的机器，一个 `comsolmphserver` + 一次 30 万单元求解就吃掉 4–6 GB；多个代理并发会在内存和许可证上互相拖死（实测能把可用内存打到 0.7 GB，所有人卡住）。需要一把闸门：

```python
# C:\cfdrun\comsol_gate.py 的最小可用语义
# 1) 原子独占：os.open(owner, O_CREAT|O_EXCL)，谁先建谁持有
# 2) 排队：queue.json 里 (priority, 入队时间) 排序，轮到自己才 acquire
# 3) 死进程自清理：每条目带 pid，tasklist 校验，pid 死了就删
# 4) hold.txt：每行一个被 root 暂停的代理名，命中直接 PermissionError 退出
# 5) 内存门槛：可用物理内存 < 2 GB 不放行
```

- **release 会删掉队列条目** → 重新 acquire 时时间戳作废、优先级优势清零。**长任务要拿锁后一路握到交付完成**，中间用 `renew()` 续期，不要反复 release。
- 起 server 前先断言机器上 **0 个 `comsolmphserver`**；一个进程只 `mph.start()` 一次，失败就退出重排（`mph.start` 偶发 `Starting server failed: lines[-1] IndexError`，是启动竞态）。
- `client.create()` 在 server 刚起时偶发 Java NPE → `sleep 3` + 重试 2 次。

### I. 物理自检卡（每次求解后先过这张表，再解释异常）

| 检查 | 期望 | 不满足说明 |
|---|---|---|
| `max(p)` ≤ `0.5ρV²` | 水 15 kn ≈ 30.5 kPa；风 25 m/s ≈ 390 Pa | 远超 → 重力没关 / 单位错 / 入口设错 |
| 对称量 `F_z` 或 `p_nz` | ≈ 0（左右舷对称几何） | 非零 → 选择集左右不对称或漏面 |
| 入口流量 `∫u·n dA` | = `V·A` | 不等 → 入口选择或速度单位错 |
| `max(|U|)` | ≠ 来流值 | 相等 → 解塌回初始场（§E） |
| 动量平衡 D vs 压力积分 R_p | 同量级、D ≈ R_p + 摩擦 | 差很多 → 边界/选择集有问题 |
| `min(p)` 的 Cp | > −1.5 | 更负 → 尖边奇点（水线角点、艉部切口），网格问题 |

### J. 反例：这次三次错误归因，教训都是"先看守恒量，再讲故事"

| 现象 | 我的第一解释 | 真相 | 教训 |
|---|---|---|---|
| p_max 602 kPa、力 30 MN | 静水压没关 | 对，但先该算 `0.5ρV²` 上限 | 先做量纲/上限自检 |
| 壁面 ⟨|U|⟩ = 0.94×来流、摩擦≈0 | 后建 Slip 覆盖了 NoSlip | NoSlip/Slip 对照只差 0.5%，壁面设置无关 | 异常先做 A/B 对照，不要靠推理 |
| 54% 的力落在 3.5% 面积上 | 艉部斜切 → 基座分离（几何缺陷） | 进流方向反了也解释不了，最终归因"壁面分辨率不足" | 一个解释要能被两组独立对照否证 |

> 一句话：**求解器塌陷、法向反了、重力没关、展平顺序错——这四类错误都会伪装成"物理现象"。每次看到不可能的数值，先跑 I 表。**

