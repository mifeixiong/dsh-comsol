# -*- coding: utf-8 -*-
r"""
comsol_export_gltf.py —— COMSOL Multiphysics 6.3：把三维绘图组导出成 glTF/GLB

用法：
    python py\comsol_export_gltf.py --model "<绝对路径>.mph" --plot pg14 --out out\comsol.glb
    python py\comsol_export_gltf.py --list "<绝对路径>.mph"        # 先看有哪些 3D 绘图组

已在本机实测（COMSOL 6.3 build 290）：
  * 只有 sdim=3 的绘图组允许 glTF（allowgltf=on）；2D/1D 一律 off
  * 必须显式 set("allowgltf","on") 才能把 imagetype 设成 gltf
  * 产物是二进制 GLB，asset.generator = "COMSOL"，颜色走顶点色 COLOR_0
  * gltfincludelines=on 时会把线（流线/边）一起导出，mode=1 的图元
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import pathlib

import mph


def summarize(path):
    raw = pathlib.Path(path).read_bytes()
    if raw[:4] == b"glTF":
        jlen = struct.unpack("<I", raw[12:16])[0]
        js = json.loads(raw[20:20 + jlen].decode("utf-8"))
    else:
        js = json.loads(raw.decode("utf-8"))
    per = {}
    for m in js.get("meshes", []):
        for pr in m["primitives"]:
            acc = js["accessors"][pr["attributes"]["POSITION"]]
            idx = js["accessors"][pr["indices"]] if "indices" in pr else None
            mode = pr.get("mode", 4)
            per.setdefault(mode, [0, 0])
            per[mode][0] += acc["count"]
            per[mode][1] += idx["count"] if idx else acc["count"]
    names = {1: "LINES", 4: "TRIANGLES"}
    return {
        "generator": js.get("asset", {}).get("generator"),
        "meshes": len(js.get("meshes", [])),
        "materials": len(js.get("materials", [])),
        "primitives": {names.get(k, k): {"verts": v[0], "indices": v[1]} for k, v in per.items()},
        "attrs": sorted({a for m in js.get("meshes", []) for pr in m["primitives"] for a in pr["attributes"]}),
    }


def list_plot_groups(j):
    out = []
    for tag in j.result().tags():
        tag = str(tag)
        if not tag.startswith("pg"):
            continue
        pg = j.result(tag)
        subs = [str(pg.feature(ft).getType()) for ft in pg.feature().tags()]
        etag = "probe_" + tag
        try:
            j.result().export().create(etag, "Image")
            e = j.result().export(etag)
            e.set("sourcetype", "plotgroup")
            e.set("sourceobject", tag)
            sdim = str(e.getString("sdim"))
            allow = str(e.getString("allowgltf"))
        except Exception:
            sdim, allow = "?", "?"
        finally:
            try:
                j.result().export().remove(etag)
            except Exception:
                pass
        out.append((tag, str(pg.label()), sdim, allow, subs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--plot", default=None, help="绘图组 tag，如 pg14")
    ap.add_argument("--out", default="out/comsol.glb")
    ap.add_argument("--list", action="store_true", help="只列出绘图组，不导出")
    ap.add_argument("--no-lines", action="store_true", help="不导出线图元")
    ap.add_argument("--cores", type=int, default=2)
    a = ap.parse_args()

    client = mph.start(cores=a.cores)
    model = client.load(a.model)
    j = model.java
    groups = list_plot_groups(j)

    if a.list or not a.plot:
        print("tag   sdim gltf  label                       features")
        for tag, label, sdim, allow, subs in groups:
            print("%-5s %-4s %-5s %-27s %s" % (tag, sdim, allow, label[:27], subs))
        if not a.plot:
            print("\n用 --plot <tag> 指定要导出的 3D 绘图组（sdim=3 且 gltf=on 的才行）")
            return

    # COMSOL 服务端的当前目录与 Python 进程不同，文件名必须绝对化，否则文件会落到别处
    out = pathlib.Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    j.result().export().create("glb1", "Image")
    e = j.result().export("glb1")
    e.set("sourcetype", "plotgroup")
    e.set("sourceobject", a.plot)
    e.set("allowgltf", "on")          # 关键：不显式打开，imagetype 不接受 gltf
    e.set("imagetype", "gltf")
    e.set("gltffilename", str(out))
    e.set("gltfincludelines", "off" if a.no_lines else "on")
    e.set("target", "file")
    e.run()

    info = summarize(out)
    print("wrote %s  %.2f MB" % (out, out.stat().st_size / 1e6))
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()