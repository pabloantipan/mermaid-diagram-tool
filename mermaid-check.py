#!/usr/bin/env python3
"""
Overlap checker for mermaid-generated SVG.

Reports what makes a flow chart unreadable and is easy to miss on a thumbnail:

  FAILURES (non-zero exit)
  1. an edge label sitting on top of a NODE
  2. two edge labels sitting on top of EACH OTHER
  3. an edge passing THROUGH a node it does not connect
  4. an edge label sitting on an edge that is NOT its own

  INFORMATIONAL
  5. a count of edge-vs-edge CROSSINGS (-v lists which pairs)

Crossings are reported, never failed: some are structural. Two back-edges whose
spans INTERLEAVE (a < c < b < d) cannot both be drawn on the same side without
crossing — no amount of reordering fixes that one, only changing the graph.

Use the crossing count to compare declaration orders objectively: layout follows
declaration order, so swapping the two branches of a decision often removes a
crossing. Script the search rather than eyeballing renders.

Usage:
    mermaid-check.py <file.svg> [file2.svg ...] [-v]
    mermaid2svg <input.md> --style flow --check     (runs this automatically)

Exit code 0 = clean, 1 = a FAILURE above (crossings alone do not fail).

Note this checks LABEL geometry, not edge-path geometry: a label overlapping a
line is normal and is handled by the opaque plate behind it. A label overlapping
a NODE or another LABEL is not normal.
"""

import re
import sys
import xml.etree.ElementTree as ET

SVG = "{http://www.w3.org/2000/svg}"
TRANSLATE = re.compile(r"translate\(\s*([-\d.eE]+)[ ,]+([-\d.eE]+)\s*\)")
NUMPAIR = re.compile(r"(-?[\d.]+(?:[eE]-?\d+)?)[ ,]+(-?[\d.]+(?:[eE]-?\d+)?)")

# Reported as a FRACTION of the label's own area, which is interpretable:
# "a third of this label is on top of a node" means something, "533px2" does not.
# Below WARN the label merely grazes a corner and stays legible.
WARN_FRACTION = 0.20


def translation(el):
    m = TRANSLATE.search(el.get("transform") or "")
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def classes(el):
    return (el.get("class") or "").split()


def rect_box(el, ox, oy):
    try:
        x = float(el.get("x", 0)); y = float(el.get("y", 0))
        w = float(el.get("width", 0)); h = float(el.get("height", 0))
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return (ox + x, oy + y, ox + x + w, oy + y + h)


def path_box(el, ox, oy):
    """Approximate a path's extent from its coordinate pairs. Bezier control
    points overshoot the true outline slightly, which biases toward reporting —
    the right direction for a checker."""
    pts = [(float(a), float(b)) for a, b in NUMPAIR.findall(el.get("d") or "")]
    if not pts:
        return None
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (ox + min(xs), oy + min(ys), ox + max(xs), oy + max(ys))


PATH_TOKENS = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?[\d.]+(?:[eE]-?\d+)?)")


def path_outline(d, ox, oy):
    """On-curve points only.

    Taking every number pair out of a path looks like it yields an outline, but
    a cubic segment contributes two CONTROL points before its endpoint. Feeding
    those to ray casting builds a self-intersecting polygon and the containment
    test returns nonsense — it reported labels as sitting fully inside a diamond
    they were nowhere near. Only M/L/C-endpoints trace the real shape.
    """
    toks = [(c, n) for c, n in PATH_TOKENS.findall(d or "")]
    pts, nums, cmd = [], [], None
    cur = (0.0, 0.0)

    def flush():
        nonlocal nums, cur
        if not cmd or not nums:
            nums = []
            return
        rel = cmd.islower()
        k = cmd.upper()
        i = 0
        if k in ("M", "L", "T"):
            step = 2
        elif k == "C":
            step = 6
        elif k in ("S", "Q"):
            step = 4
        elif k in ("H", "V"):
            step = 1
        elif k == "A":
            step = 7
        else:
            nums = []
            return
        while i + step <= len(nums):
            seg = nums[i:i + step]
            if k in ("H",):
                x, y = seg[0], 0.0 if rel else cur[1]
                pt = (cur[0] + x, cur[1]) if rel else (x, cur[1])
            elif k in ("V",):
                y = seg[0]
                pt = (cur[0], cur[1] + y) if rel else (cur[0], y)
            else:
                ex, ey = seg[-2], seg[-1]
                pt = (cur[0] + ex, cur[1] + ey) if rel else (ex, ey)
            pts.append(pt)
            cur = pt
            i += step
        nums = []

    for c, n in toks:
        if c:
            flush()
            cmd = c
        else:
            nums.append(float(n))
    flush()
    return [(ox + x, oy + y) for x, y in pts]


def points_box(el, ox, oy):
    pts = [(float(a), float(b)) for a, b in NUMPAIR.findall(el.get("points") or "")]
    if not pts:
        return None
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (ox + min(xs), oy + min(ys), ox + max(xs), oy + max(ys))


def bare_id(i):
    """Drop the per-diagram prefix newer mmdc writes on element ids
    (my-svg-L_A_B_0, my-svg-flowchart-A-0), so edge ids match the labels'
    data-id and node keys match the edge ids' endpoints."""
    return re.sub(r"^[\w-]*?-(?=L_|flowchart-)", "", i or "")


def collect(el, ox=0.0, oy=0.0, nodes=None, labels=None, edges=None):
    if nodes is None:
        nodes, labels, edges = [], [], []
    tx, ty = translation(el)
    ox, oy = ox + tx, oy + ty
    cls = classes(el)

    if el.tag == SVG + "path" and "flowchart-link" in cls:
        pts = path_outline(el.get("d") or "", ox, oy)
        if pts:
            edges.append((bare_id(el.get("id") or el.get("data-id")), pts))
        return nodes, labels, edges

    if "node" in cls:
        # Union of every geometry child, rather than hunting one blessed class:
        # mermaid draws rects, paths and polygons depending on the shape
        # ([], {}, ([]), [[]]), and matching on class name silently missed
        # more than half the nodes.
        boxes, poly = [], []
        # Walk accumulating transforms. iter() flattens the subtree and loses
        # any <g transform> sitting BETWEEN the node and its shape, which put
        # every node outline out by a constant offset — and that offset, not
        # real collisions, was what the checker had been reporting.
        def walk(node, nx, ny):
            nonlocal poly
            dx, dy = translation(node)
            nx, ny = nx + dx, ny + dy
            b = None
            if node.tag == SVG + "rect":
                b = rect_box(node, nx, ny)
                if b and len(poly) < 4:
                    poly = [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])]
            elif node.tag == SVG + "path":
                b = path_box(node, nx, ny)
                pts = path_outline(node.get("d") or "", nx, ny)
                if len(pts) > len(poly):
                    poly = pts
            elif node.tag == SVG + "polygon":
                b = points_box(node, nx, ny)
                pts = [(nx + float(a), ny + float(c))
                       for a, c in NUMPAIR.findall(node.get("points") or "")]
                if len(pts) > len(poly):
                    poly = pts
            if b:
                boxes.append(b)
            for c in node:
                walk(c, nx, ny)

        for child in el:
            walk(child, ox, oy)
        if boxes:
            box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                   max(b[2] for b in boxes), max(b[3] for b in boxes))
            nodes.append((bare_id(el.get("id")) or "node", box, poly))
        return nodes, labels, edges

    if "edgeLabel" in cls:
        text = "".join(t.text or "" for t in el.iter(SVG + "tspan")).strip()
        edge_id = ""
        for g in el.iter(SVG + "g"):
            if g.get("data-id"):
                edge_id = bare_id(g.get("data-id"))
                break
        for child in el.iter(SVG + "rect"):
            if "background" in classes(child):
                lox, loy = ox, oy
                for g in el.iter(SVG + "g"):
                    if "label" in classes(g):
                        gx, gy = translation(g)
                        lox, loy = ox + gx, oy + gy
                        break
                box = rect_box(child, lox, loy)
                if box and text:
                    labels.append((text, box, edge_id))
                break
        return nodes, labels, edges

    for child in el:
        collect(child, ox, oy, nodes, labels, edges)
    return nodes, labels, edges


def overlap_area(a, b):
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return dx * dy if dx > 0 and dy > 0 else 0.0


def area(b):
    return max(b[2] - b[0], 0) * max(b[3] - b[1], 0)


def in_poly(x, y, poly):
    """Ray casting. Needed because a diamond's bounding box is twice the
    diamond: testing boxes alone reported a label tucked beside a decision
    node as sitting on top of it."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) / (y2 - y1) * (x2 - x1) if y2 != y1 else x1
            if x < xin:
                inside = not inside
    return inside


def poly_overlap_area(rect, poly, box):
    """Area of rect actually covered by the node outline, estimated on a grid.
    Falls back to the box intersection when no usable outline was parsed."""
    inter = overlap_area(rect, box)
    if inter <= 0:
        return 0.0
    if len(poly) < 3:
        return inter
    x0, y0 = max(rect[0], box[0]), max(rect[1], box[1])
    x1, y1 = min(rect[2], box[2]), min(rect[3], box[3])
    steps = 12
    hit = 0
    for i in range(steps):
        for j in range(steps):
            px = x0 + (x1 - x0) * (i + 0.5) / steps
            py = y0 + (y1 - y0) * (j + 0.5) / steps
            if in_poly(px, py, poly):
                hit += 1
    return inter * hit / (steps * steps)


def densify(pts, step=6.0):
    """Sample along the polyline so containment tests can't slip between
    vertices. For step/linear routing the vertices ARE the path; for basis they
    are the on-curve endpoints, which tracks the curve closely enough."""
    out = []
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        d = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        n = max(int(d / step), 1)
        for k in range(n):
            t = k / n
            out.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
    if pts:
        out.append(pts[-1])
    return out


def edge_endpoints(edge_id, node_keys):
    """Split L_<SRC>_<DST>_<n>. Node keys may themselves contain underscores
    (RAMA_A, SALE_OK), so the split is resolved against the known key set
    rather than by counting underscores."""
    m = re.match(r"L_(.+)_\d+$", edge_id or "")
    if not m:
        return set()
    body = m.group(1)
    for a in node_keys:
        if body.startswith(a + "_"):
            b = body[len(a) + 1:]
            if b in node_keys:
                return {a, b}
    return set()


def node_key(nid):
    return re.sub(r"^flowchart-", "", re.sub(r"-\d+$", "", nid or ""))


def seg_cross(p1, p2, p3, p4):
    """Proper intersection of two segments (shared endpoints don't count)."""
    def o(a, b, c):
        v = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else 2)
    o1, o2, o3, o4 = o(p1, p2, p3), o(p1, p2, p4), o(p3, p4, p1), o(p3, p4, p2)
    return o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4)


def count_crossings(edges, nodes):
    """Edges that visually cross. Pairs sharing a node are skipped: they are
    expected to meet, and near a shared node the polyline approximation makes
    a spurious hit likely."""
    keys = {node_key(n[0]) for n in nodes}
    out = 0
    pairs = []
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            ida, ptsa = edges[i]
            idb, ptsb = edges[j]
            if edge_endpoints(ida, keys) & edge_endpoints(idb, keys):
                continue
            hit = False
            for a in range(len(ptsa) - 1):
                for b in range(len(ptsb) - 1):
                    if seg_cross(ptsa[a], ptsa[a + 1], ptsb[b], ptsb[b + 1]):
                        hit = True
                        break
                if hit:
                    break
            if hit:
                out += 1
                pairs.append((ida, idb))
    return out, pairs


def check(path):
    root = ET.parse(path).getroot()
    nodes, labels, edges = collect(root)
    problems = []
    keys = {node_key(n[0]) for n in nodes}

    # 3. An edge passing straight THROUGH a node it does not connect. This is
    #    what makes a line look like it starts somewhere it doesn't.
    for eid, pts in edges:
        ends = edge_endpoints(eid, keys)
        samples = densify(pts)
        for nid, nbox, npoly in nodes:
            k = node_key(nid)
            if k in ends or len(npoly) < 3:
                continue
            inside = sum(1 for (px, py) in samples
                         if nbox[0] <= px <= nbox[2] and nbox[1] <= py <= nbox[3]
                         and in_poly(px, py, npoly))
            if inside >= 3:
                nice = re.sub(r"^L_|_\d+$", "", eid).replace("_", " to ", 1)
                problems.append(f'edge [{nice}] passes through node [{k}]')

    # 4. A label sitting on an edge that is NOT its own — the reader attributes
    #    it to the wrong transition.
    for text, lbox, own in labels:
        for eid, pts in edges:
            if not eid or eid == own:
                continue
            hits = sum(1 for (px, py) in densify(pts)
                       if lbox[0] <= px <= lbox[2] and lbox[1] <= py <= lbox[3])
            if hits >= 2:
                nice = re.sub(r"^L_|_\d+$", "", eid).replace("_", " to ", 1)
                problems.append(f'label "{text}" sits on foreign edge [{nice}]')
                break

    for text, lbox, _own in labels:
        for nid, nbox, npoly in nodes:
            a = poly_overlap_area(lbox, npoly, nbox)
            frac = a / max(area(lbox), 1.0)
            if frac >= WARN_FRACTION:
                nid = nid.replace("flowchart-", "").rsplit("-", 1)[0]
                problems.append(f'label "{text}" is {frac:.0%} on top of node [{nid}]')

    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            a = overlap_area(labels[i][1], labels[j][1])
            frac = a / max(min(area(labels[i][1]), area(labels[j][1])), 1.0)
            if frac >= WARN_FRACTION:
                problems.append(
                    f'label "{labels[i][0]}" is {frac:.0%} on top of label "{labels[j][0]}"')

    return nodes, labels, problems, count_crossings(edges, nodes)


def main(argv):
    verbose = "-v" in argv
    argv = [a for a in argv if a != "-v"]
    if not argv:
        print(__doc__.strip())
        return 2
    failed = False
    for path in argv:
        try:
            nodes, labels, problems, (ncross, cpairs) = check(path)
        except (ET.ParseError, OSError) as e:
            print(f"{path}: cannot read ({e})")
            failed = True
            continue
        name = path.rsplit("/", 1)[-1]
        xinfo = f", {ncross} crossings" if ncross else ", no crossings"
        if problems:
            failed = True
            print(f"✗ {name}  ({len(nodes)} nodes, {len(labels)} labels{xinfo})")
            for p in problems:
                print(f"    {p}")
        else:
            print(f"✓ {name}  ({len(nodes)} nodes, {len(labels)} labels{xinfo})")
        if ncross and verbose:
            for a, b in cpairs:
                clean = lambda e: re.sub(r"^L_|_\d+$", "", e).replace("_", "→", 1)
                print(f"    ~ crosses: {clean(a)}  x  {clean(b)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
