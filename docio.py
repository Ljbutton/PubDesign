"""PubDesign backup format (.pubdesign; older .pagecraft files are the same format) (zip with document.json + pictures)."""
import json
import zipfile
import hashlib

from pubmodel import Document, Page, Item, Para, Run

FORMAT_VERSION = 1


def doc_to_dict(doc, images=None):
    """images: optional dict filled with name -> bytes (for zip storage).
    When None, images are embedded as hex (used for undo snapshots)."""
    pages = []
    for p in doc.pages:
        items = []
        for it in p.items:
            d = {
                "kind": it.kind, "x": it.x, "y": it.y, "w": it.w, "h": it.h,
                "rotation": it.rotation, "fill": it.fill, "stroke": it.stroke,
                "stroke_width": it.stroke_width, "valign": it.valign,
            }
            if it.paras:
                d["paras"] = [{"align": pa.align, "runs": [r.__dict__.copy() for r in pa.runs]} for pa in it.paras]
            if it.kind == "image":
                key = hashlib.md5(it.image).hexdigest()
                if images is not None:
                    ext = "jpg" if it.image[:2] == b"\xff\xd8" else "png"
                    name = f"pictures/{key}.{ext}"
                    images[name] = it.image
                    d["image"] = name
                else:
                    d["image_key"] = key
                d["image_name"] = it.image_name
            if it.kind == "path":
                d["path_d"] = it.path_d
                d["view"] = list(it.view)
            if it.kind == "auto":
                d["spt"] = it.spt
            items.append(d)
        pages.append({"items": items})
    return {"version": FORMAT_VERSION, "width": doc.width, "height": doc.height,
            "unit": getattr(doc, "unit", "in"), "margin": getattr(doc, "margin", 36), "pages": pages}


def dict_to_doc(d, images):
    doc = Document(width=d["width"], height=d["height"], pages=[])
    doc.unit = d.get("unit", "in")
    doc.margin = d.get("margin", 36)
    for p in d["pages"]:
        items = []
        for x in p["items"]:
            it = Item(kind=x["kind"], x=x["x"], y=x["y"], w=x["w"], h=x["h"],
                      rotation=x.get("rotation", 0),
                      fill=tuple(x["fill"]) if x.get("fill") else None,
                      stroke=tuple(x["stroke"]) if x.get("stroke") else None,
                      stroke_width=x.get("stroke_width", 1.0), valign=x.get("valign", "top"))
            for pa in x.get("paras", []):
                runs = []
                for r in pa["runs"]:
                    r = dict(r)
                    r["color"] = tuple(r.get("color", (0, 0, 0)))
                    runs.append(Run(**r))
                it.paras.append(Para(runs, pa.get("align", "left")))
            if it.kind == "image":
                it.image = images.get(x.get("image") or x.get("image_key"), b"")
                it.image_name = x.get("image_name", "picture.png")
            if it.kind == "path":
                it.path_d = x.get("path_d")
                it.view = tuple(x.get("view", (0, 0, 1, 1)))
            if it.kind == "auto":
                it.spt = x.get("spt", 1)
            items.append(it)
        doc.pages.append(Page(items=items))
    if not doc.pages:
        doc.pages.append(Page())
    return doc


def save_backup(doc, path):
    images = {}
    d = doc_to_dict(doc, images)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("document.json", json.dumps(d, indent=1))
        for name, data in images.items():
            z.writestr(name, data, compress_type=zipfile.ZIP_STORED)


def load_backup(path):
    with zipfile.ZipFile(path) as z:
        d = json.loads(z.read("document.json"))
        images = {n: z.read(n) for n in z.namelist() if n.startswith("pictures/")}
    return dict_to_doc(d, images)


class Snapshotter:
    """Cheap undo snapshots: JSON text + a shared picture pool."""

    def __init__(self):
        self.pool = {}

    def snap(self, doc):
        for p in doc.pages:
            for it in p.items:
                if it.kind == "image" and it.image:
                    self.pool[hashlib.md5(it.image).hexdigest()] = it.image
        return json.dumps(doc_to_dict(doc, None))

    def restore(self, s):
        return dict_to_doc(json.loads(s), self.pool)
