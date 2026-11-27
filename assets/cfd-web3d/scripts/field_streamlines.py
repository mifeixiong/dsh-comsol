# -*- coding: utf-8 -*-
"""
field_streamlines.py —— 流场 -> 流线 -> 管状网格 -> glTF(.glb) + meta.json

支持两种输入：
  1) 平面 npz（CFD 后处理最常见的产物）：
       X (nx,), Y (ny,), VX/VY (ny,nx) 或 (nx,ny)（自动判方向），可选 VZ / U / P
  2) 三维结构化 .vtk（legacy ASCII，POINTS + VECTORS Velocity）

输出：
  <out>.glb        管状流线（顶点色，按速度着色）
  <out>.meta.json  图例所需信息（单位、范围、色标）

用法：
  python field_streamlines.py --npz mid.npz --out scene.glb
  python field_streamlines.py --npz mid.npz --out scene.glb --hull tris_clean.bin --hull-scale 0.001
  python field_streamlines.py --vtk field.vtk --out scene.glb --seeds 80

只依赖 numpy。
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

VIRIDIS = np.array([
    [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142],
    [38, 130, 142], [31, 158, 137], [53, 183, 121], [109, 205, 89],
    [180, 222, 44], [253, 231, 37]], dtype=np.float64) / 255.0


def colormap(t):
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0) * (len(VIRIDIS) - 1)
    i = np.floor(t).astype(int)
    i1 = np.clip(i + 1, 0, len(VIRIDIS) - 1)
    f = (t - i)[..., None]
    c = VIRIDIS[i] * (1 - f) + VIRIDIS[i1] * f
    return np.clip(c * 255.0, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- 场
class Field:
    """等距结构化场（nz 可以为 1，即单平面）。采样越界返回 0。"""

    def __init__(self, dims, origin, spacing, vel, speed):
        self.dims = np.asarray(dims, dtype=int)
        self.lo = np.asarray(origin, dtype=float)
        self.sp = np.asarray(spacing, dtype=float)
        self.vel = np.asarray(vel, dtype=float)
        self.speed = np.asarray(speed, dtype=float)
        mag = np.linalg.norm(self.vel, axis=-1)
        self.dir = np.zeros_like(self.vel)
        nz = mag > 1e-9
        self.dir[nz] = self.vel[nz] / mag[nz][:, None]

    def _idx(self, p):
        g = (p - self.lo) / self.sp
        i = np.floor(g)
        ok = (np.all(g[..., :2] >= -0.5, axis=-1) &
              np.all(g[..., :2] <= (self.dims[:2] - 0.5), axis=-1))
        if self.dims[2] > 1:
            ok &= (g[..., 2] >= -0.5) & (g[..., 2] <= self.dims[2] - 0.5)
        ii = np.stack([np.clip(i[..., 0], 0, self.dims[0] - 1),
                       np.clip(i[..., 1], 0, self.dims[1] - 1),
                       np.clip(i[..., 2], 0, self.dims[2] - 1)], axis=-1).astype(np.int64)
        return ii, ok

    def sample(self, p, which="dir"):
        ii, ok = self._idx(np.asarray(p, dtype=float))
        arr = self.dir if which == "dir" else self.speed
        out = np.asarray(arr[ii[..., 0], ii[..., 1], ii[..., 2]], dtype=float)
        return out * (ok[..., None] if out.ndim == ok.ndim + 1 else ok)


def load_npz(path, level=None):
    d = np.load(path, allow_pickle=True)
    X = np.asarray(d["X"], float); Y = np.asarray(d["Y"], float)
    VX = np.asarray(d["VX"], float); VY = np.asarray(d["VY"], float)
    VZ = np.asarray(d["VZ"], float) if "VZ" in d.files else np.zeros_like(VX)
    U = np.asarray(d["U"], float) if "U" in d.files else None
    # npz 常见是 (ny, nx)，按坐标长度自动转
    if VX.shape == (Y.size, X.size) and Y.size != X.size:
        VX, VY, VZ = VX.T, VY.T, VZ.T
        if U is not None:
            U = U.T
    mask = ~np.isfinite(VX) | ~np.isfinite(VY)
    VX = np.where(mask, 0.0, VX); VY = np.where(mask, 0.0, VY)
    VZ = np.nan_to_num(np.where(mask, 0.0, VZ))
    speed = np.sqrt(VX ** 2 + VY ** 2 + VZ ** 2) if U is None else np.where(mask, 0.0, U)
    z = 0.0 if level is None else float(level)
    vel = np.stack([VX, VY, VZ], axis=-1)[:, :, None, :]      # (nx,ny,1,3)
    spd = speed[:, :, None]                                   # (nx,ny,1)
    return Field((X.size, Y.size, 1), (X[0], Y[0], z),
                 (X[1] - X[0], Y[1] - Y[0], 1.0), vel, spd), dict(
                     x=(float(X[0]), float(X[-1])), y=(float(Y[0]), float(Y[-1])),
                     solid_frac=float(mask.mean()))


def load_vtk(path):
    txt = Path(path).read_text(encoding="utf-8", errors="replace").split("\n")
    dims = None; npts = None; pts = None; vec = None
    def nums(start, count):
        vals = []
        for line in txt[start:]:
            toks = line.split()
            if not toks:
                continue
            try:
                float(toks[0])
            except ValueError:
                break
            vals.extend(float(t) for t in toks)
            if len(vals) >= count:
                break
        return np.array(vals[:count], dtype=float)
    for i, ln in enumerate(txt):
        u = ln.strip().upper()
        if u.startswith("DIMENSIONS"):
            dims = np.array([int(v) for v in ln.split()[1:4]])
        elif u.startswith("POINTS"):
            npts = int(ln.split()[1]); pts = nums(i + 1, npts * 3).reshape(npts, 3)
        elif u.startswith("VECTORS"):
            vec = nums(i + 1, npts * 3).reshape(npts, 3)
    if dims is None or vec is None:
        raise SystemExit("只支持 DIMENSIONS + VECTORS 的 legacy ASCII .vtk")
    nx, ny, nz = dims
    origin = pts[0]
    sp = np.array([(pts[1] - pts[0])[0], (pts[nx] - pts[0])[1], (pts[nx * ny] - pts[0])[2]])
    vel = vec.reshape(tuple(dims) + (3,), order="F")
    spd = np.linalg.norm(vel, axis=-1)
    return Field(dims, origin, sp, vel, spd), dict(dims=tuple(int(v) for v in dims))


# ---------------------------------------------------------------- 积分
def seeds_for(field, n, upstream="auto"):
    """在流动上游布一排种子（沿最长的两条轴），自动判断来流方向。"""
    lo = field.lo
    hi = lo + (field.dims - 1) * field.sp
    span = hi - lo
    ax_main = int(np.argmax(span[:2]))
    ax_seed = 1 - ax_main
    # 上游端：比较该端的速度是否"朝内"
    def probe(frac):
        p = lo[None, :] + (hi - lo)[None, :] * np.array([0.5, 0.5, 0.5])
        p[0, ax_main] = lo[ax_main] + frac * span[ax_main]
        v = field.vel[int(np.clip((p[0, 0] - lo[0]) / field.sp[0], 0, field.dims[0] - 1)),
                      int(np.clip((p[0, 1] - lo[1]) / field.sp[1], 0, field.dims[1] - 1)),
                      0]
        return v
    v_lo, v_hi = probe(0.02), probe(0.98)
    if upstream == "auto":
        upstream = "lo" if (v_lo[ax_main] > 0 and abs(v_lo[ax_main]) >= abs(v_hi[ax_main])) else "hi"
    frac = 0.02 if upstream == "lo" else 0.98
    main = lo[ax_main] + frac * span[ax_main]
    other = np.linspace(lo[ax_seed] + 0.02 * span[ax_seed], hi[ax_seed] - 0.02 * span[ax_seed], n)
    seeds = np.zeros((n, 3))
    seeds[:, ax_main] = main
    seeds[:, ax_seed] = other
    seeds[:, 2] = lo[2] if field.dims[2] == 1 else lo[2] + 0.5 * span[2]
    if field.dims[2] > 1:
        # 三维时再叠一层：在第三个轴上也铺开
        layers = max(2, n // 6)
        out = []
        for zz in np.linspace(lo[2] + 0.05 * span[2], hi[2] - 0.05 * span[2], layers):
            s = seeds.copy(); s[:, 2] = zz; out.append(s)
        seeds = np.vstack(out)
    return seeds


def integrate(field, seeds, h, steps):
    pos = seeds.astype(float).copy()
    out = np.zeros((steps + 1,) + pos.shape)
    out[0] = pos
    alive = np.ones(len(pos), bool)
    lo = field.lo
    hi = lo + (field.dims - 1) * field.sp
    for s in range(steps):
        v1 = field.sample(pos); v2 = field.sample(pos + 0.5 * h * v1)
        v3 = field.sample(pos + 0.5 * h * v2); v4 = field.sample(pos + h * v3)
        step = (h / 6.0) * (v1 + 2 * v2 + 2 * v3 + v4)
        newp = pos + step
        alive &= np.linalg.norm(step, axis=-1) > 1e-3 * h
        # 平面场（nz=1）的 z 边界厚度为 0，跳过该维的越界判定
        kmax = 2 if field.dims[2] > 1 else 2
        for k in range(3):
            if k == 2 and field.dims[2] == 1:
                continue
            alive &= (newp[:, k] > lo[k]) & (newp[:, k] < hi[k])
        if not alive.any():
            return out[: s + 2], s + 1
        pos = np.where(alive[:, None], newp, pos)
        out[s + 1] = pos
    return out, steps


def polylines(paths, field, max_pts=260):
    lines = []
    for k in range(paths.shape[1]):
        p = paths[:, k, :]
        d = np.linalg.norm(np.diff(p, axis=0), axis=1)
        ok = np.where(d > 1e-9)[0]
        if ok.size < 10:
            continue
        p = p[: ok[-1] + 2]
        idx = np.linspace(0, len(p) - 1, min(max_pts, len(p))).astype(int)
        p = p[idx]
        lines.append((p, field.sample(p, "speed")))
    return lines


# ---------------------------------------------------------------- 管 + GLB
def tube(lines, radius, sides, vmin, vmax):
    P, N, C, I, base = [], [], [], [], 0
    th = np.linspace(0, 2 * np.pi, sides, endpoint=False)
    ct, st = np.cos(th), np.sin(th)
    for pts, spd in lines:
        n = len(pts)
        t = np.zeros_like(pts)
        t[1:-1] = pts[2:] - pts[:-2]; t[0] = pts[1] - pts[0]; t[-1] = pts[-1] - pts[-2]
        t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-12
        ref = np.array([0.0, 1.0, 0.0]) if abs(t[0][1]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = np.zeros_like(pts); v = np.zeros_like(pts)
        u[0] = np.cross(ref, t[0]); u[0] /= np.linalg.norm(u[0]) + 1e-12
        v[0] = np.cross(t[0], u[0])
        for i in range(1, n):
            ax = np.cross(t[i - 1], t[i]); s = np.linalg.norm(ax); c = float(np.dot(t[i - 1], t[i]))
            if s < 1e-9:
                u[i] = u[i - 1]
            else:
                k = ax / s; ang = np.arctan2(s, c)
                u[i] = (u[i - 1] * np.cos(ang) + np.cross(k, u[i - 1]) * np.sin(ang)
                        + k * np.dot(k, u[i - 1]) * (1 - np.cos(ang)))
                u[i] /= np.linalg.norm(u[i]) + 1e-12
            v[i] = np.cross(t[i], u[i])
        ring = pts[:, None, :] + radius * (ct[None, :, None] * u[:, None, :] + st[None, :, None] * v[:, None, :])
        nrm = ct[None, :, None] * u[:, None, :] + st[None, :, None] * v[:, None, :]
        col = colormap((spd - vmin) / max(vmax - vmin, 1e-9))
        colv = np.repeat(col[:, None, :], sides, axis=1)
        rgba = np.concatenate([colv, np.full(colv.shape[:2] + (1,), 255, np.uint8)], axis=-1)
        P.append(ring.reshape(-1, 3)); N.append(nrm.reshape(-1, 3)); C.append(rgba.reshape(-1, 4))
        s_idx = np.arange(sides)[None, :]; i_idx = np.arange(n - 1)[:, None]
        a = base + i_idx * sides + s_idx
        b = base + i_idx * sides + (s_idx + 1) % sides
        c1 = base + (i_idx + 1) * sides + s_idx
        d1 = base + (i_idx + 1) * sides + (s_idx + 1) % sides
        tri = np.stack([np.stack([a, c1, b], -1), np.stack([b, c1, d1], -1)], axis=2).reshape(-1, 3)
        I.append(tri); base += n * sides
    return (np.concatenate(P).astype(np.float32), np.concatenate(N).astype(np.float32),
            np.concatenate(C), np.concatenate(I).reshape(-1))


def load_hull(path, scale, color=(150, 160, 175, 255)):
    tri = np.fromfile(path, dtype="<f4").reshape(-1, 3, 3).astype(np.float64) * scale
    verts = tri.reshape(-1, 3)
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nrm /= (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12)
    return (verts.astype(np.float32), np.repeat(nrm, 3, axis=0).astype(np.float32),
            np.tile(np.array(color, np.uint8), (len(verts), 1)),
            np.arange(len(verts), dtype=np.uint32))


def write_glb(path, prims):
    blobs, views, accs, off, na = [], [], [], 0, 0
    for P, N, C, I in prims:
        for b in (P.tobytes(), N.tobytes(), C.tobytes(), I.astype(np.uint32).tobytes()):
            pad = b + b"\x00" * ((4 - len(b) % 4) % 4)
            blobs.append(pad); views.append((off, len(b))); off += len(pad)
        accs += [
            {"bufferView": na, "componentType": 5126, "count": int(len(P)), "type": "VEC3",
             "min": [float(P[:, k].min()) for k in range(3)],
             "max": [float(P[:, k].max()) for k in range(3)]},
            {"bufferView": na + 1, "componentType": 5126, "count": int(len(N)), "type": "VEC3"},
            {"bufferView": na + 2, "componentType": 5121, "normalized": True, "count": int(len(C)), "type": "VEC4"},
            {"bufferView": na + 3, "componentType": 5125, "count": int(len(I)), "type": "SCALAR"},
        ]
        na += 4
    bin_data = b"".join(blobs)
    gltf = {
        "asset": {"version": "2.0", "generator": "cfd-web3d / field_streamlines.py"},
        "scene": 0, "scenes": [{"nodes": list(range(len(prims)))}],
        "nodes": [{"mesh": i, "name": ("streamlines" if i == 0 else "hull%d" % i)} for i in range(len(prims))],
        "meshes": [{"primitives": [{"attributes": {"POSITION": i * 4, "NORMAL": i * 4 + 1, "COLOR_0": i * 4 + 2},
                                   "indices": i * 4 + 3, "material": i, "mode": 4}]} for i in range(len(prims))],
        "materials": [{"name": "streamtube" if i == 0 else "solid%d" % i,
                       "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1],
                                                "metallicFactor": 0.0, "roughnessFactor": 0.55},
                       "doubleSided": True} for i in range(len(prims))],
        "accessors": accs,
        "bufferViews": [{"buffer": 0, "byteOffset": o, "byteLength": l,
                         "target": 34963 if i % 4 == 3 else 34962} for i, (o, l) in enumerate(views)],
        "buffers": [{"byteLength": len(bin_data)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_data)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack("<II", len(bin_data), 0x004E4942)); f.write(bin_data)
    return pathlib_len(path)


def pathlib_len(p):
    from pathlib import Path
    return Path(p).stat().st_size


def main():
    ap = argparse.ArgumentParser(description="流场 -> 流线 -> GLB")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--npz", help="平面场 npz（X,Y,VX,VY[,VZ][,U]）")
    src.add_argument("--vtk", help="三维结构化 legacy ASCII .vtk")
    ap.add_argument("--out", default="scene.glb")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--radius", type=float, default=None, help="管半径（米），默认按域尺度取 0.3%%")
    ap.add_argument("--sides", type=int, default=6)
    ap.add_argument("--step", type=float, default=None, help="积分步长（米），默认按域尺度取 0.25%%")
    ap.add_argument("--max-steps", type=int, default=1600)
    ap.add_argument("--upstream", choices=["auto", "lo", "hi"], default="auto")
    ap.add_argument("--hull", help="船体/障碍三角面 bin（float32，每三角 9 个浮点）")
    ap.add_argument("--hull-scale", type=float, default=1.0, help="bin 单位换算，mm->m 用 0.001")
    ap.add_argument("--label", default="Velocity Magnitude")
    a = ap.parse_args()

    if a.npz:
        field, info = load_npz(a.npz)
    else:
        field, info = load_vtk(a.vtk)

    lo = field.lo
    hi = lo + (field.dims - 1) * field.sp
    diag = float(np.linalg.norm(hi - lo))
    h = a.step if a.step else max(diag * 0.0025, 1e-6)
    radius = a.radius if a.radius else max(diag * 0.003, 1e-6)

    seeds = seeds_for(field, a.seeds, a.upstream)
    paths, nst = integrate(field, seeds, h, a.max_steps)
    lines = polylines(paths, field)
    if not lines:
        raise SystemExit("没有生成长度足够的流线：检查 --upstream / 场是否全零")
    spd = np.concatenate([s for _, s in lines])
    vmin, vmax = 0.0, float(np.percentile(spd, 99.0))
    prims = [tube(lines, radius, a.sides, vmin, vmax)]
    if a.hull:
        prims.append(load_hull(a.hull, a.hull_scale))
    size = write_glb(a.out, prims)

    meta = {
        "units": {"length": "m", "velocity": "m/s"},
        "scalar": a.label,
        "range": [round(vmin, 3), round(vmax, 3)],
        "colormap": "viridis",
        "colormap_stops": (VIRIDIS * 255).astype(int).tolist(),
        "n_streamlines": len(lines),
        "n_vertices": int(sum(len(p[0]) for p in prims)),
        "glb_bytes": size,
        "source": (a.npz or a.vtk),
        "info": info,
    }
    meta_path = str(Path(a.out).with_suffix("")) + ".meta.json"
    Path(meta_path).write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("streamlines %d | verts %d | %.2f MB -> %s" % (
        len(lines), meta["n_vertices"], size / 1e6, a.out))
    print("legend     %s  (%.2f .. %.2f)" % (meta_path, vmin, vmax))


if __name__ == "__main__":
    main()
