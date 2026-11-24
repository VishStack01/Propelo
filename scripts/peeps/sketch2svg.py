"""Render a layer from a Sketch file's JSON (unzipped) to SVG.

Handles what Open Peeps uses: groups, shape groups, shape paths, rectangles, ovals, symbol instances with
symbol-swap overrides, solid fills, borders, flips, rotation, opacity and clipping masks.

    python3 -I sketch2svg.py <unzipped dir> --list
    python3 -I sketch2svg.py <unzipped dir> "<layer name or objectID>" out.svg
"""

import json
import math
import os
import re
import sys

NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def pt(s):
    x, y = (float(v) for v in NUM.findall(s)[:2])
    return x, y


class Doc:
    def __init__(self, root):
        self.pages = [json.load(open(os.path.join(root, "pages", f))) for f in sorted(os.listdir(os.path.join(root, "pages")))]
        self.masters, self.by_name, self.by_id = {}, {}, {}
        for p in self.pages:
            for l in p.get("layers", []):
                self._index(l)
        self.clip_n = 0
        doc = json.load(open(os.path.join(root, "document.json")))
        self.styles = {}
        for o in (doc.get("layerStyles") or {}).get("objects", []):
            self.styles[o["do_objectID"]] = o["value"]
        for o in doc.get("foreignLayerStyles") or []:
            ls = o.get("localSharedStyle") or {}
            if ls.get("do_objectID"):
                self.styles[ls["do_objectID"]] = ls.get("value")
            if o.get("remoteStyleID"):
                self.styles.setdefault(o["remoteStyleID"], ls.get("value"))

    def style_of(self, l, ov):
        sid = ov.get(f'{l.get("do_objectID")}_layerStyle')
        if sid and self.styles.get(sid):
            return self.styles[sid]
        return l.get("style")

    def _index(self, l):
        self.by_id.setdefault(l.get("do_objectID"), l)
        if l.get("_class") in ("artboard", "symbolMaster"):
            self.by_name.setdefault(l.get("name"), l)
        if l.get("_class") == "symbolMaster":
            self.masters[l["symbolID"]] = l
        for c in l.get("layers", []) or []:
            if c.get("_class") in ("artboard", "symbolMaster", "group"):
                self._index(c)

    # ---------------------------------------------------------------- geometry
    @staticmethod
    def local_xform(l):
        f = l["frame"]
        x, y, w, h = f["x"], f["y"], f["width"], f["height"]
        t = [f"translate({x:.3f} {y:.3f})"]
        cx, cy = w / 2, h / 2
        rot = l.get("rotation") or 0
        fh, fv = l.get("isFlippedHorizontal"), l.get("isFlippedVertical")
        if rot or fh or fv:
            t.append(f"translate({cx:.3f} {cy:.3f})")
            if rot:
                t.append(f"rotate({-rot:.3f})")
            if fh or fv:
                t.append(f"scale({-1 if fh else 1} {-1 if fv else 1})")
            t.append(f"translate({-cx:.3f} {-cy:.3f})")
        return " ".join(t)

    @staticmethod
    def path_d(l):
        """Path data in the layer's own frame (0..w, 0..h)."""
        f = l["frame"]
        w, h = f["width"], f["height"]
        pts = l.get("points") or []
        if not pts:
            return ""
        P = lambda s: (pt(s)[0] * w, pt(s)[1] * h)
        out = []
        n = len(pts)
        p0 = P(pts[0]["point"])
        out.append(f"M{p0[0]:.2f} {p0[1]:.2f}")
        segs = n if l.get("isClosed") else n - 1
        for i in range(segs):
            a, b = pts[i], pts[(i + 1) % n]
            pa, pb = P(a["point"]), P(b["point"])
            c1 = P(a["curveFrom"]) if a.get("hasCurveFrom") else pa
            c2 = P(b["curveTo"]) if b.get("hasCurveTo") else pb
            if c1 == pa and c2 == pb:
                out.append(f"L{pb[0]:.2f} {pb[1]:.2f}")
            else:
                out.append(f"C{c1[0]:.2f} {c1[1]:.2f} {c2[0]:.2f} {c2[1]:.2f} {pb[0]:.2f} {pb[1]:.2f}")
        if l.get("isClosed"):
            out.append("Z")
        return " ".join(out)

    @staticmethod
    def paint(style):
        style = style or {}
        attrs = []
        fills = [f for f in style.get("fills") or [] if f.get("isEnabled") and f.get("fillType", 0) == 0]
        if fills:
            c = fills[-1]["color"]
            attrs.append(f'fill="{Doc.hexa(c)}"')
            if c.get("alpha", 1) < 1:
                attrs.append(f'fill-opacity="{c["alpha"]:.3f}"')
        else:
            attrs.append('fill="none"')
        borders = [b for b in style.get("borders") or [] if b.get("isEnabled")]
        if borders:
            b = borders[-1]
            attrs.append(f'stroke="{Doc.hexa(b["color"])}" stroke-width="{b.get("thickness", 1):.2f}"')
            opts = style.get("borderOptions") or {}
            cap = {0: "butt", 1: "round", 2: "square"}.get(opts.get("lineCapStyle", 0), "butt")
            join = {0: "miter", 1: "round", 2: "bevel"}.get(opts.get("lineJoinStyle", 0), "miter")
            attrs.append(f'stroke-linecap="{cap}" stroke-linejoin="{join}"')
        op = (style.get("contextSettings") or {}).get("opacity", 1)
        if op != 1:
            attrs.append(f'opacity="{op:.3f}"')
        return " ".join(attrs)

    @staticmethod
    def hexa(c):
        return "#%02x%02x%02x" % tuple(max(0, min(255, round(c.get(k, 0) * 255))) for k in ("red", "green", "blue"))

    # ---------------------------------------------------------------- rendering
    def shape_group_d(self, g):
        parts, evenodd = [], False
        for i, c in enumerate(g.get("layers") or []):
            if c.get("isVisible") is False:
                continue
            if c.get("_class") == "shapeGroup":
                d, eo = self.shape_group_d(c)
                evenodd = evenodd or eo
            else:
                d = self.path_d(c)
            if not d:
                continue
            if i and c.get("booleanOperation") in (1, 3):
                evenodd = True
            parts.append(f'<path transform="{self.local_xform(c)}" d="{d}"/>' if False else (self.local_xform(c), d))
        return parts, evenodd

    def flat_d(self, g):
        """A shape group's children as one path, each transformed into the group's frame."""
        out, eo = [], False
        for i, c in enumerate(g.get("layers") or []):
            if c.get("isVisible") is False:
                continue
            if i and c.get("booleanOperation") in (1, 3):
                eo = True
            if c.get("_class") == "shapeGroup":
                d, e2 = self.flat_d(c)
                eo = eo or e2
            else:
                d = self.path_d(c)
            if d:
                out.append(self.apply(self.matrix(c), d))
        return " ".join(out), eo

    @staticmethod
    def matrix(l):
        f = l["frame"]
        w, h = f["width"], f["height"]
        m = [1, 0, 0, 1, f["x"], f["y"]]
        rot = math.radians(-(l.get("rotation") or 0))
        sx = -1 if l.get("isFlippedHorizontal") else 1
        sy = -1 if l.get("isFlippedVertical") else 1
        if rot or sx < 0 or sy < 0:
            # translate(c) rotate scale translate(-c)
            def mul(a, b):
                return [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
                        a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]]
            cx, cy = w / 2, h / 2
            m = mul(m, [1, 0, 0, 1, cx, cy])
            m = mul(m, [math.cos(rot), math.sin(rot), -math.sin(rot), math.cos(rot), 0, 0])
            m = mul(m, [sx, 0, 0, sy, 0, 0])
            m = mul(m, [1, 0, 0, 1, -cx, -cy])
        return m

    @staticmethod
    def apply(m, d):
        toks = re.findall(r"[MLCZ]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
        out, nums, cmd = [], [], None

        def flush():
            for i in range(0, len(nums), 2):
                x, y = nums[i], nums[i + 1]
                out.append(f"{m[0] * x + m[2] * y + m[4]:.2f} {m[1] * x + m[3] * y + m[5]:.2f}")
        for t in toks:
            if t in "MLCZ":
                flush()
                nums = []
                out.append(t)
            else:
                nums.append(float(t))
        flush()
        return " ".join(out)

    def render(self, l, ov=None, depth=0):
        if depth > 40 or l.get("isVisible") is False:
            return ""
        ov = ov or {}
        cls = l.get("_class")
        if cls in ("text", "slice", "bitmap"):
            return ""
        op = (l.get("style") or {}).get("contextSettings", {}).get("opacity", 1)
        if cls == "symbolInstance":
            oid = l.get("do_objectID")
            sid = ov.get(f"{oid}_symbolID", l.get("symbolID"))
            if not sid:
                return ""
            master = self.masters.get(sid)
            if not master:
                return ""
            # overrides for inside this instance: its own, plus the parent's that target paths under it
            inner = {}
            for o in l.get("overrideValues") or []:
                inner[o["overrideName"]] = o["value"]
            pre = f"{oid}/"
            for k, v in ov.items():
                if k.startswith(pre):
                    inner[k[len(pre):]] = v
            mf, f = master["frame"], l["frame"]
            sx = f["width"] / mf["width"] if mf["width"] else 1
            sy = f["height"] / mf["height"] if mf["height"] else 1
            body = "".join(self.children(master, inner, depth))
            attrs = f' opacity="{op:.3f}"' if op != 1 else ""
            return f'<g transform="{self.local_xform(l)} scale({sx:.5f} {sy:.5f})"{attrs}>{body}</g>'
        if cls == "shapeGroup":
            kids = [c for c in l.get("layers") or [] if c.get("isVisible") is not False]
            cut = next((i for i, c in enumerate(kids) if i and c.get("booleanOperation") == 2), None)
            if cut is not None:
                # Intersect: the shapes before it, clipped by it (Sketch combines each child with those below it).
                base = dict(l, layers=kids[:cut])
                clip = dict(l, layers=kids[cut:cut + 1])
                d, eo = self.flat_d(base)
                cd, _ = self.flat_d(clip)
                self.clip_n += 1
                cid = f"clip{self.clip_n}"
                rule = ' fill-rule="evenodd"' if eo else ""
                return (f'<g transform="{self.local_xform(l)}"><clipPath id="{cid}"><path d="{cd}"/></clipPath>'
                        f'<path d="{d}" clip-path="url(#{cid})" {self.paint(self.style_of(l, ov))}{rule}/></g>')
            d, eo = self.flat_d(l)
            if not d:
                return ""
            rule = ' fill-rule="evenodd"' if eo else ""
            return f'<path transform="{self.local_xform(l)}" d="{d}" {self.paint(self.style_of(l, ov))}{rule}/>'
        if cls in ("shapePath", "rectangle", "oval", "star", "polygon", "triangle"):
            d = self.path_d(l)
            if not d:
                return ""
            return f'<path transform="{self.local_xform(l)}" d="{d}" {self.paint(self.style_of(l, ov))}/>'
        if cls in ("group", "artboard", "symbolMaster"):
            attrs = f' opacity="{op:.3f}"' if op != 1 and cls == "group" else ""
            inner = "".join(self.children(l, ov, depth))
            xf = self.local_xform(l) if cls == "group" else ""
            return f'<g transform="{xf}"{attrs}>{inner}</g>' if xf else f"<g{attrs}>{inner}</g>"
        return ""

    def children(self, l, ov, depth):
        out, mask_open = [], False
        for c in l.get("layers") or []:
            if c.get("hasClippingMask"):
                if mask_open:
                    out.append("</g>")
                self.clip_n += 1
                cid = f"clip{self.clip_n}"
                shape = self.render(c, ov, depth + 1)
                # the mask shape itself is also drawn when it has a fill
                out.append(f'<clipPath id="{cid}">{re.sub(r" (fill|stroke)[-a-z]*=\"[^\"]*\"", "", shape)}</clipPath>{shape}<g clip-path="url(#{cid})">')
                mask_open = True
                continue
            if mask_open and c.get("shouldBreakMaskChain"):
                out.append("</g>")
                mask_open = False
            out.append(self.render(c, ov, depth + 1))
        if mask_open:
            out.append("</g>")
        return out

    def svg(self, l):
        f = l["frame"]
        body = "".join(self.children(l, {}, 0)) if l["_class"] in ("artboard", "symbolMaster") else self.render(l)
        bg = ""
        if l.get("hasBackgroundColor") and l.get("backgroundColor"):
            bg = f'<rect width="{f["width"]:.0f}" height="{f["height"]:.0f}" fill="{self.hexa(l["backgroundColor"])}"/>'
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {f["width"]:.0f} {f["height"]:.0f}" '
                f'width="{f["width"]:.0f}" height="{f["height"]:.0f}">{bg}{body}</svg>')


if __name__ == "__main__":
    doc = Doc(sys.argv[1])
    if sys.argv[2] == "--list":
        for p in doc.pages:
            for l in p["layers"]:
                if l["_class"] in ("artboard",):
                    print(l["_class"], "|", l["name"], "|", l["do_objectID"], "|", int(l["frame"]["width"]), "x", int(l["frame"]["height"]))
        sys.exit()
    key = sys.argv[2]
    layer = doc.by_id.get(key) or doc.by_name.get(key)
    if not layer:
        sys.exit(f"no layer {key}")
    open(sys.argv[3], "w").write(doc.svg(layer))
    print("wrote", sys.argv[3], os.path.getsize(sys.argv[3]))
