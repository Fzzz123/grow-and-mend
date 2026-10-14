"""Tiny receiving server: serves the site and stores submissions in ./submissions.
Run:  python server.py   ->  http://localhost:8000
No third-party packages needed.
"""
import base64, io, json, os, re, threading, time, urllib.request, uuid, zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
SUB = os.environ.get("DATA_DIR", os.path.join(ROOT, "submissions"))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_KEY", "")
BUCKET = "designs"
NOTIFY_URL = os.environ.get("NOTIFY_URL", "")
NOTIFY_SECRET = os.environ.get("NOTIFY_SECRET", "")
os.makedirs(SUB, exist_ok=True)
MAX_BYTES = 3_000_000
PREFIX = "data:image/png;base64,"


def sb(method, path, body=None, ctype="application/json"):
    """Call Supabase REST/Storage with the server-side secret key."""
    h = {"apikey": SB_KEY, "Content-Type": ctype}
    if SB_KEY.startswith("eyJ"):
        h["Authorization"] = "Bearer " + SB_KEY
    req = urllib.request.Request(SB_URL + path, data=body, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def list_items():
    if SB_URL:
        rows = json.loads(sb("GET", "/rest/v1/submissions?select=*&order=time.desc&limit=300"))
        for r in rows:
            r["url"] = f"{SB_URL}/storage/v1/object/public/{BUCKET}/{r['file']}"
        return rows
    items = []
    for f in os.listdir(SUB):
        if f.endswith(".json"):
            with open(os.path.join(SUB, f), encoding="utf-8") as fh:
                m = json.load(fh)
            m["url"] = "/submissions/" + m["file"]
            items.append(m)
    items.sort(key=lambda m: m["time"], reverse=True)
    return items


def store(sid, png, meta):
    if SB_URL:
        sb("POST", f"/storage/v1/object/{BUCKET}/{sid}.png", png, "image/png")
        sb("POST", "/rest/v1/submissions", json.dumps(meta).encode())
        return
    with open(os.path.join(SUB, sid + ".png"), "wb") as fh:
        fh.write(png)
    with open(os.path.join(SUB, sid + ".json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)


def notify(meta, png):
    """Forward a submission to the Google Apps Script (email + Drive + Sheet). Best effort."""
    try:
        body = json.dumps({**meta, "secret": NOTIFY_SECRET,
                           "image_b64": base64.b64encode(png).decode()}).encode()
        req = urllib.request.Request(NOTIFY_URL, data=body, method="POST",
                                     headers={"Content-Type": "text/plain"})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        print("notify failed:", e)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sub(self):
        name = os.path.basename(self.path.split("?")[0])
        fp = os.path.join(SUB, name)
        if not name.endswith(".png") or not os.path.isfile(fp):
            return self.send_error(404)
        data = open(fp, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/submissions/"):
            return super().do_GET() if os.path.dirname(SUB) == ROOT else self._serve_sub()
        if self.path == "/api/submissions":
            try:
                return self._json(200, list_items())
            except Exception:
                return self._json(502, {"error": "storage unavailable"})
        if self.path.startswith("/api/export"):
            if not ADMIN_KEY or self.path != "/api/export?key=" + ADMIN_KEY:
                return self.send_error(403)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for m in list_items():
                    z.writestr(m["file"].replace(".png", ".json"), json.dumps(m, ensure_ascii=False))
                    if SB_URL:
                        z.writestr(m["file"], urllib.request.urlopen(m["url"], timeout=20).read())
                    else:
                        z.write(os.path.join(SUB, m["file"]), m["file"])
            body = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", "attachment; filename=submissions.zip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.split("?")[0].startswith(("/server.py", "/render.yaml", "/apps_script.gs", "/supabase_setup.sql", "/.")):
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/submit":
            return self.send_error(404)
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0 or n > MAX_BYTES:
            return self._json(413, {"error": "too large"})
        try:
            d = json.loads(self.rfile.read(n))
            img = d["image"]
            assert img.startswith(PREFIX)
            png = base64.b64decode(img[len(PREFIX):], validate=True)
            assert png[:8] == b"\x89PNG\r\n\x1a\n"
        except Exception:
            return self._json(400, {"error": "bad request"})
        sid = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
        meta = {
            "file": sid + ".png",
            "time": time.time(),
            "mode": "fashion" if d.get("mode") == "fashion" else "green",
            "name": re.sub(r"[\r\n]", " ", str(d.get("name", "")))[:40],
            "note": re.sub(r"[\r\n]", " ", str(d.get("note", "")))[:300],
        }
        try:
            store(sid, png, meta)
        except Exception:
            return self._json(502, {"error": "storage unavailable"})
        if NOTIFY_URL:
            threading.Thread(target=notify, args=(meta, png), daemon=True).start()
        self._json(200, {"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Serving on http://localhost:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
