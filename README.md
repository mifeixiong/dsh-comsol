# dsh-comsol

DSH plugin: drive **COMSOL Multiphysics** models end to end from any chat -
open a model in the visible desktop, read/modify parameters, rebuild the mesh,
tune the solver, run steady **or time-dependent** studies with live progress,
load results into the desktop plot, evaluate numbers and export images.

Toggling the plugin in the DSH plugin panel enables/disables **both** skills for
every workspace; the plugin carries everything they need.

| Skill | What it does | Assets |
|---|---|---|
| `comsol-dsh` | drive COMSOL end to end (open, edit, mesh, solve, post-process) | `assets/comsol-dsh/` + `assets/engine/` |
| `cfd-web3d` | turn CFD results into web 3D - native glTF/GLB export, streamline tubes, three.js viewer | `assets/cfd-web3d/` |

`cfd-web3d` is optional in practice: it only loads when the user asks to put a
3D result on a web page, make an interactive view, or export glTF. It needs
nothing but **Python 3.10+ with numpy** and **Node 18+** (for the static
server); three.js comes from a CDN. It also covers the ANSYS side (CFD-Post
`HARDCOPY ... glb2`) and generic `.npz`/`.vtk` fields, so it is useful
without COMSOL installed.

## Install (any DSH user)

In the DSH plugin panel, install from:

```
github:Twofruitsgrape/dsh-comsol
```

(or the repository URL). DSH fetches the bundle with pnpm, mounts it through
`cordis.patch.yml`, and the skill appears in new sessions. Restart DSH after
installing.

Requirements on the machine:

- **COMSOL Multiphysics 6.0 - 6.3** with a valid license (fully verified on 6.2)
- **Python 3.10+** with the `mcp` package: `pip install mcp`
  (plus `MPh>=1.4` and `tomlkit` if you prefer `pip install -e assets/engine`)
- Windows desktop session (the COMSOL window is shown live; headless works too)

## What ships inside

```
index.js                 skill provider; name/description parsed from the
                         SKILL.md frontmatter (single source of truth)
cordis.patch.yml         plugin mount + the panel toggle target
assets/comsol-dsh/       the skill: SKILL.md playbook, run_workflow.py (steady),
                         run_transient.py (time-varying BC -> transient solve),
                         offline tests
assets/engine/           the comsol-mcp MCP server (Python), vendored: no
                         external checkout or pip install needed
```

`index.js` imports only `node:` builtins and declares no dependencies, so DSH
upgrades can never break plugin loading through version resolution.

## Quick start

```powershell
# offline preflight (starts nothing)
python assets/comsol-dsh/scripts/run_workflow.py --model "<abs>.mph" --home "<dir>" --check
# steady workflow: params -> mesh -> solve -> plot -> save
python assets/comsol-dsh/scripts/run_workflow.py --model "<abs>.mph" --home "<dir>" --set-param I=200[A] --save-as "<out>.mph"
# transient workflow: time-varying BC -> Time Dependent study -> solve -> results on screen
python assets/comsol-dsh/scripts/run_transient.py --model "<abs>.mph" --home "<dir>" --save-as "<out>.mph" --allow-code
```

Full playbook, hard rules and field-tested COMSOL 6.2 traps:
[assets/comsol-dsh/SKILL.md](assets/comsol-dsh/SKILL.md).

## Verified

COMSOL 6.2 + MPh 1.4 + Python 3.12 on the busbar electro-thermal case:
steady solve `T` 337.7-349.8 K; transient ramp `Tbc(t)=293.15+60(1-e^(-t/15))`
on the convective ambient, 61 time steps, maxT 293.15 -> 307.90 K; zero
leftover locks/processes; 35 skill + 58 engine offline tests green.

## License

MIT - see [LICENSE](LICENSE). COMSOL is a trademark of COMSOL AB; this project
is not affiliated with or endorsed by COMSOL AB.
