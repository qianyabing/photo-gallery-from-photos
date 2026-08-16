# -*- coding: utf-8 -*-
"""本地图片画廊 —— 纯标准库实现，无需 Flask。
Pillow 为可选依赖：安装了会自动启用缩略图缓存（更快），没装也能直接显示原图。
"""
import os, json, time, hashlib, mimetypes, urllib.parse, struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
PHOTOS = os.path.join(BASE, "photos")
CACHE = os.path.join(BASE, ".cache", "thumbs")
CACHE_INDEX = os.path.join(BASE, ".cache", "index.json")
EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}

try:
    from PIL import Image, ImageOps
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

INDEX = []
INDEX_TS = 0


def safe_rel(path):
    return os.path.relpath(path, PHOTOS).replace(os.sep, "/")


def load_cache():
    try:
        with open(CACHE_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_INDEX), exist_ok=True)
        with open(CACHE_INDEX, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def build_index():
    global INDEX, INDEX_TS
    # 复用上次扫描的缓存：以 (修改时间+大小) 为指纹，没变的图跳过读头、直接复用尺寸
    cache = load_cache()
    items = []
    n = 0
    for root, dirs, files in os.walk(PHOTOS):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in EXTS:
                continue
            full = os.path.join(root, f)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = safe_rel(full)
            sig = f"{int(st.st_mtime)}:{st.st_size}"
            entry = cache.get(rel)
            if entry and entry.get("sig") == sig:
                w, h = entry.get("w", 0), entry.get("h", 0)
            else:
                w, h = header_dims(full)   # 只读文件头，不解码像素，速度远快于 Image.open
            items.append({
                "id": hashlib.md5(rel.encode()).hexdigest()[:12],
                "name": f, "rel": rel, "folder": os.path.dirname(rel),
                "size": st.st_size, "mtime": int(st.st_mtime),
                "w": w, "h": h, "sig": sig,
            })
            n += 1
            if n % 2000 == 0:
                print(f"  已扫描 {n} 张...")
    # 只保留当前存在的图，丢弃已移动/删除的旧缓存项
    new_cache = {
        it["rel"]: {"sig": it["sig"], "name": it["name"], "folder": it["folder"],
                    "size": it["size"], "mtime": it["mtime"], "w": it["w"], "h": it["h"]}
        for it in items
    }
    save_cache(new_cache)
    print(f"  共索引 {len(items)} 张图片。")
    INDEX = items
    INDEX_TS = time.time()


def resolve(rel):
    full = os.path.normpath(os.path.join(PHOTOS, rel))
    if not full.startswith(PHOTOS) or not os.path.isfile(full):
        return None
    return full


def header_dims(path):
    """不依赖 Pillow，读取常见图片格式的宽高（用于未安装 Pillow 的降级模式）。"""
    try:
        with open(path, "rb") as f:
            sig = f.read(8)
        if sig[:4] == b"RIFF" and sig[8:12] == b"WEBP":
            return webp_dims(path)
        if sig[:3] == b"\xff\xd8\xff":
            return jpeg_dims(path)
        if sig[:8] == b"\x89PNG\r\n\x1a\n":
            with open(path, "rb") as f:
                f.seek(16)
                w, h = struct.unpack(">II", f.read(8))
            return w, h
        if sig[:6] in (b"GIF87a", b"GIF89a"):
            with open(path, "rb") as f:
                f.seek(6)
                w, h = struct.unpack("<HH", f.read(4))
            return w, h
        if sig[:2] == b"BM":
            with open(path, "rb") as f:
                f.seek(18)
                w, h = struct.unpack("<ii", f.read(8))
            return abs(w), abs(h)
    except Exception:
        pass
    return 0, 0


def webp_dims(path):
    with open(path, "rb") as f:
        f.seek(12)
        fmt = f.read(4)
        if fmt == b"VP8X":
            f.seek(24)
            w, h = struct.unpack("<II", f.read(8))
            return (w & 0xffffff) + 1, (h & 0xffffff) + 1
        if fmt == b"VP8L":
            f.seek(21)
            b = struct.unpack("<I", f.read(4))[0]
            return (b & 0x3fff) + 1, ((b >> 14) & 0x3fff) + 1
        if fmt == b"VP8 ":
            f.seek(26)
            w, h = struct.unpack("<HH", f.read(4))
            return w, h
    return 0, 0


def jpeg_dims(path):
    with open(path, "rb") as f:
        f.read(2)
        while True:
            b = f.read(1)
            if not b:
                return 0, 0
            if b != b"\xff":
                continue
            m = f.read(1)
            if not m:
                return 0, 0
            if m in (b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6",
                     b"\xc7", b"\xc9", b"\xca", b"\xcb"):
                f.read(3)
                h, w = struct.unpack(">HH", f.read(4))
                return w, h
            if m == b"\xd9" or m == b"\xd8" or 0xd0 <= m[0] <= 0xd7:
                continue
            ln = struct.unpack(">H", f.read(2))[0]
            f.read(ln - 2)


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, mimetype, nocache=False):
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mimetype)
        self.send_header("Content-Length", str(os.path.getsize(path)))
        if nocache:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                b = f.read(65536)
                if not b:
                    break
                self.wfile.write(b)
        finally:
            f.close()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        g = lambda k: (qs.get(k) or [""])[0]

        if p in ("/", "/index.html"):
            self._file(os.path.join(BASE, "templates", "index.html"),
                       "text/html; charset=utf-8")
            return

        if p.startswith("/static/"):
            fp = os.path.normpath(os.path.join(BASE, p[1:]))
            if not fp.startswith(BASE) or not os.path.isfile(fp):
                self.send_error(404)
                return
            self._file(fp, mimetypes.guess_type(fp)[0] or "application/octet-stream")
            return

        if p == "/api/folders":
            self._json({"folders": sorted({it["folder"] for it in INDEX}),
                        "total": len(INDEX)})
            return

        if p == "/api/images":
            folder = g("folder") or "__all__"
            q = (g("q") or "").strip().lower()
            sort = g("sort") or "name"
            order = g("order") or "asc"
            items = INDEX
            if folder and folder != "__all__":
                items = [i for i in items if i["folder"] == folder]
            if q:
                items = [i for i in items
                         if q in i["name"].lower() or q in i["rel"].lower()]
            rev = (order == "desc")
            if sort == "name":
                items.sort(key=lambda i: i["name"].lower(), reverse=rev)
            elif sort == "time":
                items.sort(key=lambda i: i["mtime"], reverse=rev)
            elif sort == "size":
                items.sort(key=lambda i: i["size"], reverse=rev)
            elif sort == "dim":
                items.sort(key=lambda i: i["w"] * i["h"], reverse=rev)
            out = [{
                "id": i["id"], "name": i["name"], "rel": i["rel"],
                "folder": i["folder"], "size": i["size"], "mtime": i["mtime"],
                "w": i["w"], "h": i["h"],
                "thumb": "/thumb/" + i["rel"], "full": "/img/" + i["rel"],
            } for i in items]
            self._json({"images": out, "total": len(out)})
            return

        if p == "/api/refresh":
            build_index()
            self._json({"ok": True, "total": len(INDEX)})
            return

        if p.startswith("/thumb/"):
            rel = urllib.parse.unquote(p[len("/thumb/"):])
            full = resolve(rel)
            if not full:
                self.send_error(404)
                return
            if HAVE_PIL:
                key = hashlib.md5(
                    (rel + str(os.path.getmtime(full)) + str(os.path.getsize(full)))
                    .encode()).hexdigest()
                cf = os.path.join(CACHE, key + ".jpg")
                if not os.path.exists(cf):
                    os.makedirs(CACHE, exist_ok=True)
                    try:
                        with Image.open(full) as im:
                            im = ImageOps.exif_transpose(im)
                            im.thumbnail((480, 480))
                            if im.mode in ("RGBA", "P"):
                                im = im.convert("RGB")
                            im.save(cf, "JPEG", quality=82)
                    except Exception:
                        self._file(full, mimetypes.guess_type(full)[0]
                                   or "application/octet-stream", nocache=True)
                        return
                self._file(cf, "image/jpeg", nocache=True)
                return
            self._file(full, mimetypes.guess_type(full)[0]
                       or "application/octet-stream", nocache=True)
            return

        if p.startswith("/img/"):
            rel = urllib.parse.unquote(p[len("/img/"):])
            full = resolve(rel)
            if not full:
                self.send_error(404)
                return
            self._file(full, mimetypes.guess_type(full)[0]
                       or "application/octet-stream", nocache=True)
            return

        self.send_error(404)

    def log_message(self, *a):
        pass


def run():
    import webbrowser
    port = 8000
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass
    print(f"图库已启动: http://localhost:{port}  (Ctrl+C 停止)")
    srv.serve_forever()


build_index()

if __name__ == "__main__":
    run()
