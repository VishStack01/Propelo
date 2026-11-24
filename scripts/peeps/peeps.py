"""Compose the website's people from Open Peeps (Pablo Stanley, CC0) in Propelo's colours.

Only young characters: grey-haired heads and the "Old" face are refused.

    unzip open-peeps.sketch -d /tmp/open-peeps          # the Sketch file from openpeeps.com
    python3 -I scripts/peeps/peeps.py /tmp/open-peeps cast scripts/peeps/cast.json /tmp/peeps
    node scripts/peeps/fit.js /tmp/peeps/*.svg            # crop each drawing to its edges
    npx svgo@3.3.2 --config scripts/peeps/svgo.config.js -f /tmp/peeps -o /tmp/peeps/out
    # then copy each file to the place its "used_in" names

    python3 -I scripts/peeps/peeps.py /tmp/open-peeps sheet standing|sitting|bodies|heads|faces sheet.html

A cast entry: {"name": "hero", "kind": "standing", "pose": "robot_dance-1", "head": "Long", "face": "Smile",
               "theme": {"skin": "#ae5d29", "top": "#FF85BA", ...}}
"""

import copy
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sketch2svg import Doc  # noqa: E402

ROLES = [  # (keyword in the layer name, role)
    ("Ink", "ink"), ("Skin", "skin"), ("Hair", "hair"), ("Jacket", "jacket"), ("Top", "top"), ("Clothes", "top"),
    ("Pants", "pants"), ("Shorts", "pants"), ("Shoes", "shoes"), ("Device", "device"), ("Computer", "device"),
    ("Cup", "device"), ("hijab", "headwear"), ("Turban", "headwear"), ("Hat", "headwear"),
]
SKIN_STYLE_NAMES = {"Skin"}
NOT_YOUNG_HEADS = {"Gray Bun", "Gray Medium", "Gray Short"}
NOT_YOUNG_FACES = {"Old"}

HIDE = {"403D70B2", "F7BC2926", "4F8E29BA", "71CA0A94"}
SLOTS = {"BODY": "pose", "HEAD": "head", "FACE": "face", "ACCESORIES": "acc", "FACIAL HAIR": "hair_face", "MASK": "mask"}


def rgb(hexs):
    h = hexs.lstrip("#")
    return {"_class": "color", "alpha": 1, "red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


class Peeps(Doc):
    def __init__(self, root):
        super().__init__(root)
        doc = json.load(open(os.path.join(root, "document.json")))
        self.style_names = {o["do_objectID"]: o["name"] for o in doc["layerStyles"]["objects"]}
        self.theme = {}
        self.sym_by_name = {m["name"]: m["symbolID"] for m in self.masters.values()}
        # The laptop's lid logo reads as an emoji at small sizes: leave it off.
        self._hide(self.by_name["body/Macbook"])

    def _hide(self, l):
        for c in l.get("layers") or []:
            if (c.get("do_objectID") or "")[:8] in HIDE:
                c["isVisible"] = False
            self._hide(c)

    def role(self, l):
        name = l.get("name") or ""
        for key, role in ROLES:
            if key in name:
                return role
        cat = self.style_names.get(l.get("sharedStyleID") or "", "").split("/")[0]
        return {"Skin": "skin", "Hair": "hair", "Mono": None}.get(cat)

    def style_of(self, l, ov):
        st = super().style_of(l, ov)
        if not self.theme or not st:
            return st
        r = self.role(l)
        if r and r in self.theme:
            st = copy.deepcopy(st)
            fills = [f for f in st.get("fills") or [] if f.get("isEnabled")]
            if fills:
                fills[-1]["color"] = rgb(self.theme[r])
            borders = [b for b in st.get("borders") or [] if b.get("isEnabled")]
            if borders and r == "ink":
                borders[-1]["color"] = rgb(self.theme[r])
        return st

    def compose(self, kind, theme=None, **parts):
        """Render 'a person/<kind>' with the chosen parts. Returns an <svg> string."""
        self.theme = theme or {}
        master = self.by_name[f"a person/{kind}"]
        ov = {}
        prefix = {"pose": f"pose/{kind}/" if kind != "bust" else "body/", "head": "head/", "face": "face/",
                  "acc": "accessories/", "hair_face": "facial-hair/", "mask": "mask/"}

        def walk(l):
            for c in l.get("layers") or []:
                if c.get("_class") == "symbolInstance" and c.get("name") in SLOTS:
                    want = parts.get(SLOTS[c["name"]])
                    if want:
                        full = prefix[SLOTS[c["name"]]] + want
                        if full not in self.sym_by_name:
                            raise SystemExit(f"no symbol {full}")
                        ov[f'{c["do_objectID"]}_symbolID'] = self.sym_by_name[full]
                if c.get("_class") == "group":
                    walk(c)
        walk(master)
        f = master["frame"]
        body = "".join(self.children(master, ov, 0))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {f["width"]:.0f} {f["height"]:.0f}">{body}</svg>')


def sheet(p, what, out):
    names = sorted(m["name"] for m in p.masters.values())
    cells = []
    if what in ("standing", "sitting"):
        for n in names:
            if n.startswith(f"pose/{what}/"):
                cells.append((n.split("/")[-1], p.compose(what, pose=n.split("/")[-1], head="Short 1", face="Smile")))
    elif what == "bodies":
        for n in names:
            if n.startswith("body/"):
                cells.append((n.split("/")[-1], p.compose("bust", pose=n.split("/")[-1], head="Short 1", face="Smile")))
    elif what == "heads":
        for n in names:
            if n.startswith("head/"):
                cells.append((n.split("/")[-1], p.compose("bust", head=n.split("/")[-1], face="Smile")))
    elif what == "faces":
        for n in names:
            if n.startswith("face/") and "With_Mask" not in n:
                cells.append((n.split("/")[-1], p.compose("bust", head="Short 1", face=n.split("/")[-1])))
    html = ["<!doctype html><meta charset=utf8><style>body{margin:0;font:12px sans-serif;display:grid;grid-template-columns:repeat(8,200px);gap:4px;background:#FAF3E6}",
            "figure{margin:0;background:#fff}figure svg{width:200px;height:240px}figcaption{padding:2px 4px}</style>"]
    for name, svg in cells:
        html.append(f"<figure>{svg}<figcaption>{name}</figcaption></figure>")
    open(out, "w").write("".join(html))
    print("wrote", out, len(cells))


def cast(p, spec, outdir):
    os.makedirs(outdir, exist_ok=True)
    for c in json.load(open(spec)):
        for bad, banned in (("head", NOT_YOUNG_HEADS), ("face", NOT_YOUNG_FACES)):
            if c.get(bad) in banned:
                raise SystemExit(f"{c['name']}: {c[bad]} is not a young character part")
        parts = {k: c[k] for k in ("pose", "head", "face", "acc", "hair_face") if k in c}
        svg = p.compose(c["kind"], theme=c.get("theme"), **parts)
        open(os.path.join(outdir, c["name"] + ".svg"), "w").write(svg)
        print("wrote", c["name"], len(svg))


if __name__ == "__main__":
    peeps = Peeps(sys.argv[1])
    if sys.argv[2] == "sheet":
        sheet(peeps, sys.argv[3], sys.argv[4])
    elif sys.argv[2] == "cast":
        cast(peeps, sys.argv[3], sys.argv[4])
