#!/usr/bin/env python3
"""Test de fumée Evora : le build web chargé dans une iframe servie par une AUTRE origine.

Écrit pour le fork tazerty/pdfcraft ; bibliothèque standard Python seule, aucune action tierce.
Chrome (préinstallé sur le runner) est piloté par le protocole DevTools sur tuyaux
(--remote-debugging-pipe : commandes JSON terminées par un octet nul sur les descripteurs 3 et 4).

  origine A (moteur)  : http://127.0.0.1:<port A>/  sert le site empaqueté ;
  origine B (parente) : http://localhost:<port B>/  sert une page qui encadre A dans une iframe.

Deux origines (hôtes et ports distincts, donc deux sites : la situation du mode B d'Evora).
Deux scénarios, chacun sur un profil Chrome vierge (démarrage à froid) :
  1. « sans CSP » ;
  2. « CSP appliquée » : la CSP cible des documents moteur (ARCHITECTURE §3.6), avec les
     empreintes de csp-hashes.txt et frame-ancestors limité à l'origine B.

Succès d'un scénario : le canvas #pdfcraft existe et eframe l'a dimensionné (largeur = largeur CSS ×
devicePixelRatio, différente des 300 px par défaut), son contexte WebGL2 est vivant, et ni la page
parente ni l'iframe ne remontent d'exception, d'erreur de console ou d'erreur de journal
(chargement, CSP…). Le démarrage à froid mesuré va de la navigation de l'iframe au premier
dimensionnement du canvas (performance.now() de l'iframe).

Usage : smoke.py SITE_DIR CSP_HASHES_FILE OUT_DIR REPORT_MD
Statut 1 si un scénario échoue.
"""

import base64
import fcntl
import functools
import http.server
import json
import os
import select
import shutil
import socket
import sys
import tempfile
import threading
import time

PORT_A = 8801
PORT_B = 8802
ENGINE_ORIGIN = f"http://127.0.0.1:{PORT_A}"
PARENT_ORIGIN = f"http://localhost:{PORT_B}"
IFRAME_W, IFRAME_H = 1280, 800
# Paramètres de l'URL du moteur dans l'iframe. Avant le pont EHP natif (E4), aucun : le pont amont
# ?host=parent ne parle qu'à sa propre origine et Chrome signalerait chaque envoi refusé.
ENGINE_QUERY = os.environ.get("EVORA_SMOKE_QUERY", "")
READY_TIMEOUT = 180.0
ERROR_GRACE = 30.0
SETTLE = 4.0

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".wasm": "application/wasm",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
}


def engine_csp(hashes):
    """CSP cible des documents moteur (ARCHITECTURE §3.6), frame-ancestors = origine parente."""
    script = " ".join(["'self'", "'wasm-unsafe-eval'"] + [f"'{h}'" for h in hashes])
    return ("default-src 'self'; "
            f"script-src {script}; "
            "worker-src 'self' blob:; connect-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
            f"frame-ancestors {PARENT_ORIGIN}; object-src 'none'; base-uri 'none'")


def minimal_pdf():
    """Un PDF d'une page, xref exacte : le document que la page parente ouvre par evora:open."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
    for o in offsets:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


# Coquille minimale (page parente du scénario « pont-ehp », HOST-PROTOCOL.md) : vérifie source et
# origine, répond à evora:ready par un evora:init invalide (v: 2, doit rester sans réponse) puis par
# un evora:init valide, puis ouvre un PDF par evora:open. Tout ce qui arrive est journalisé.
HOST_HARNESS = """
const ENGINE = "%(engine)s";
const A = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
let n = 0;
const ulid = () => { n += 1; return "01JZZZZZZZZZZZZZZZZZZZZZ" + A[(n >> 5) %% 32] + A[n %% 32]; };
const PDF = "%(pdf)s";
const ids = window.__evoraIds = {};
const log = window.__evoraLog = [];
const frame = document.getElementById("engine");
const send = (m, transfer) => frame.contentWindow.postMessage(m, ENGINE, transfer || []);
addEventListener("message", (e) => {
  const d = e.data;
  const fromEngine = e.source === frame.contentWindow && e.origin === ENGINE;
  const plain = d !== null && typeof d === "object" && Object.getPrototypeOf(d) === Object.prototype;
  log.push({origin: e.origin, fromEngine, plain, keys: plain ? Object.keys(d) : [], v: plain ? d.v : null,
            type: plain ? d.type : null, id: plain ? d.id : null, re: plain ? (d.re || null) : null,
            payload: plain && d.payload ? JSON.parse(JSON.stringify(d.payload,
              (k, v) => v instanceof ArrayBuffer ? {byteLength: v.byteLength} : v)) : null});
  if (!fromEngine || !plain || d.v !== 1) return;
  if (d.type === "evora:ready") {
    ids.ready = d.id;
    ids.bogus = ulid();
    send({v: 2, type: "evora:init", id: ids.bogus, re: d.id, payload: {}});
    ids.init = ulid();
    send({v: 1, type: "evora:init", id: ids.init, re: d.id, payload: {
      lang: "fr", engineLang: "fr", theme: "dark", accent: "#4F46E5", readOnly: false,
      storageNs: "ab".repeat(32), displayName: "Compte Evora", capabilities: d.payload.capabilities,
      prefs: {}, limits: {maxDocumentBytes: 1048576, maxExportBytes: 1048576}}});
  } else if (d.type === "evora:ack" && d.re === ids.init && d.payload && d.payload.ok === true) {
    const bytes = Uint8Array.from(atob(PDF), (c) => c.charCodeAt(0)).buffer;
    ids.open = ulid();
    send({v: 1, type: "evora:open", id: ids.open, payload: {docRef: ulid(), name: "evora-smoke.pdf", bytes}}, [bytes]);
  }
});
"""


def parent_page(query, host=False):
    harness = HOST_HARNESS % {"engine": ENGINE_ORIGIN, "pdf": base64.b64encode(minimal_pdf()).decode()} if host else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><link rel="icon" href="data:,"><title>Evora smoke</title></head>
<body style="margin:0;background:#fff">
<iframe id="engine" src="{ENGINE_ORIGIN}/index.html{query}" width="{IFRAME_W}" height="{IFRAME_H}"
 style="border:0;display:block" sandbox="allow-scripts allow-same-origin"></iframe>
<script>
window.__evoraMessages = [];
addEventListener("message", (e) => {{
  const d = e.data;
  window.__evoraMessages.push({{origin: e.origin, type: (d && typeof d === "object" && typeof d.type === "string") ? d.type : null}});
}});
{harness}
</script>
</body></html>
""".encode()


class Handler(http.server.SimpleHTTPRequestHandler):
    csp = None
    page = None
    served = None
    host_config = None

    def log_message(self, fmt, *args):  # journal sobre, consigné par le test
        if self.served is not None:
            self.served.append(f"{self.server.server_address[1]} {self.command} {self.path} -> {args[1] if len(args) > 1 else '?'}")

    def guess_type(self, path):
        return MIME.get(os.path.splitext(path)[1], "application/octet-stream")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.csp:
            self.send_header("Content-Security-Policy", self.csp)
        super().end_headers()

    def do_GET(self):
        if self.host_config is not None and self.path.split("?")[0] == "/evora-host.json":
            # Ce qu'écrit le provisionnement d'Evora à côté d'index.html (HOST-PROTOCOL §2.3).
            body = json.dumps(self.host_config).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.page is not None:
            if self.path.split("?")[0] in ("/", "/index.html"):
                body = self.page
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)
            return
        super().do_GET()


class V6Server(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6


def start_server(port, host, directory=None, csp=None, page=None, served=None, host_config=None):
    handler = type("H", (Handler,), {"csp": csp, "page": page, "served": served, "host_config": host_config})
    if directory is not None:
        handler = functools.partial(handler, directory=directory)
    server_class = V6Server if ":" in host else http.server.ThreadingHTTPServer
    httpd = server_class((host, port), handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


class Chrome:
    """Chrome sans interface piloté par --remote-debugging-pipe (descripteurs 3 et 4)."""

    def __init__(self, binary, profile, log_path):
        cmd_r, self.cmd_w = os.pipe()
        self.res_r, res_w = os.pipe()
        # Descripteurs du fils déplacés au-delà de 4, pour que les dup2 vers 3 et 4 ne s'écrasent pas.
        hi_r = fcntl.fcntl(cmd_r, fcntl.F_DUPFD_CLOEXEC, 20)
        hi_w = fcntl.fcntl(res_w, fcntl.F_DUPFD_CLOEXEC, 20)
        os.close(cmd_r)
        os.close(res_w)
        self.log = open(log_path, "wb")
        args = [
            binary, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
            "--disable-background-networking", "--disable-component-update", "--disable-default-apps",
            "--mute-audio", "--no-sandbox", "--ignore-gpu-blocklist", "--enable-webgl",
            "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--window-size=1400,1000",
            "about:blank",
        ]
        actions = [
            (os.POSIX_SPAWN_OPEN, 0, "/dev/null", os.O_RDONLY, 0),
            (os.POSIX_SPAWN_DUP2, self.log.fileno(), 1),
            (os.POSIX_SPAWN_DUP2, self.log.fileno(), 2),
            (os.POSIX_SPAWN_DUP2, hi_r, 3),
            (os.POSIX_SPAWN_DUP2, hi_w, 4),
        ]
        self.pid = os.posix_spawn(binary, args, os.environ, file_actions=actions)
        os.close(hi_r)
        os.close(hi_w)
        self.buf = b""
        self.next_id = 0
        self.responses = {}
        self.events = []
        self.handlers = []

    def send(self, method, params=None, session=None):
        self.next_id += 1
        msg = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        os.write(self.cmd_w, json.dumps(msg).encode() + b"\0")
        return self.next_id

    def pump(self, timeout):
        r, _, _ = select.select([self.res_r], [], [], timeout)
        if not r:
            return
        chunk = os.read(self.res_r, 1 << 20)
        if not chunk:
            raise RuntimeError("Chrome a fermé le tuyau DevTools")
        self.buf += chunk
        while b"\0" in self.buf:
            raw, self.buf = self.buf.split(b"\0", 1)
            msg = json.loads(raw)
            if "id" in msg:
                self.responses[msg["id"]] = msg
            else:
                self.events.append(msg)
                for h in self.handlers:
                    h(msg)

    def call(self, method, params=None, session=None, timeout=30.0):
        i = self.send(method, params, session)
        end = time.monotonic() + timeout
        while i not in self.responses:
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"{method} sans réponse")
            self.pump(min(left, 0.25))
        msg = self.responses.pop(i)
        if "error" in msg:
            raise RuntimeError(f"{method} : {msg['error']}")
        return msg.get("result", {})

    def close(self):
        try:
            self.send("Browser.close")
            end = time.monotonic() + 10
            while time.monotonic() < end:
                pid, _ = os.waitpid(self.pid, os.WNOHANG)
                if pid:
                    break
                time.sleep(0.1)
            else:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, 0)
        except OSError:
            pass
        self.log.close()


def describe_remote(obj):
    if not isinstance(obj, dict):
        return str(obj)
    return str(obj.get("value", obj.get("description", obj.get("unserializableValue", obj.get("type", "")))))


# Évalué dans le document moteur dès la création de son contexte JavaScript : horodate, en
# performance.now() du document, la fin du chargeur Trunk (wasm instancié, main lancé) et le premier
# dimensionnement du canvas par eframe. Le relevé ne dépend donc pas de la latence du sondage.
TIMING = """(() => {
  if (window.__evoraT) return;
  const T = window.__evoraT = {};
  const mark = (k) => { if (!(k in T)) T[k] = performance.now(); };
  const watch = (c) => new MutationObserver(() => { if (c.width !== 300) mark('canvasSized'); })
    .observe(c, {attributes: true, attributeFilter: ['width']});
  const find = () => { const c = document.getElementById('pdfcraft'); if (c) { watch(c); return true; } return false; };
  if (!find()) new MutationObserver((_, o) => { if (find()) o.disconnect(); })
    .observe(document, {childList: true, subtree: true});
  addEventListener('TrunkApplicationStarted', () => mark('trunkStarted'));
})()"""

PROBE = """(() => {
  const c = document.getElementById('pdfcraft');
  if (!c) return JSON.stringify({canvas: false, t: performance.now()});
  const dpr = window.devicePixelRatio || 1;
  return JSON.stringify({canvas: true, w: c.width, h: c.height, cw: c.clientWidth, ch: c.clientHeight,
                         dpr, t: performance.now(), marks: window.__evoraT || {}});
})()"""

GL_PROBE = """(() => {
  const c = document.getElementById('pdfcraft');
  if (!c) return 'no-canvas';
  const gl = c.getContext('webgl2');
  return gl ? (gl.isContextLost() ? 'lost' : 'webgl2') : 'other';
})()"""

RESOURCES = """JSON.stringify(performance.getEntriesByType('resource').map(e => ({
  name: e.name.split('/').pop(), dur: Math.round(e.duration), size: e.transferSize || e.encodedBodySize || 0})))"""


def run_scenario(name, site, csp, out_dir, chrome_bin, query=ENGINE_QUERY, expect=None):
    served = []
    expect = expect or {}
    host = bool(expect.get("ehp"))
    engine = start_server(PORT_A, "127.0.0.1", directory=site, csp=csp, served=served,
                          host_config={"parentOrigins": [PARENT_ORIGIN]} if host else None)
    parent = start_server(PORT_B, "127.0.0.1", page=parent_page(query, host), served=served)
    # « localhost » peut se résoudre en ::1 : la page parente écoute aussi en IPv6 quand c'est possible.
    try:
        parent6 = start_server(PORT_B, "::1", page=parent_page(query, host), served=served)
    except OSError:
        parent6 = None
    profile = tempfile.mkdtemp(prefix=f"evora-smoke-{name}-")
    chrome = Chrome(chrome_bin, profile, os.path.join(out_dir, f"chrome-{name}.log"))
    errors = []
    contexts = {}  # (session, contextId) -> origin
    sessions = {}  # sessionId -> type

    def on_event(msg):
        method, params, sess = msg.get("method"), msg.get("params", {}), msg.get("sessionId")
        where = sessions.get(sess, "navigateur")
        if method == "Target.attachedToTarget":
            child = params["sessionId"]
            sessions[child] = params.get("targetInfo", {}).get("type", "?") + " " + params.get("targetInfo", {}).get("url", "")
            for m in ("Runtime.enable", "Log.enable"):
                chrome.send(m, {}, child)
            chrome.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, child)
            chrome.send("Runtime.runIfWaitingForDebugger", {}, child)
        elif method == "Runtime.executionContextCreated":
            ctx = params["context"]
            if ctx.get("auxData", {}).get("isDefault"):
                contexts[(sess, ctx["id"])] = ctx.get("origin", "")
                if ctx.get("origin") == ENGINE_ORIGIN:
                    # Le contexte naît au premier script du document, bien avant la fin du chargement
                    # du .wasm : l'horodatage est posé à temps.
                    chrome.send("Runtime.evaluate", {"expression": TIMING, "contextId": ctx["id"]}, sess)
        elif method == "Runtime.executionContextDestroyed":
            contexts.pop((sess, params.get("executionContextId")), None)
        elif method == "Runtime.executionContextsCleared":
            for k in [k for k in contexts if k[0] == sess]:
                contexts.pop(k, None)
        elif method == "Runtime.exceptionThrown":
            d = params.get("exceptionDetails", {})
            errors.append(f"[{where}] exception : {d.get('text', '')} {describe_remote(d.get('exception', {}))} "
                          f"({d.get('url', '')}:{d.get('lineNumber', '')})")
        elif method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "assert"):
            text = " ".join(describe_remote(a) for a in params.get("args", []))
            errors.append(f"[{where}] console.{params.get('type')} : {text}")
        elif method == "Log.entryAdded":
            e = params.get("entry", {})
            if e.get("level") == "error":
                errors.append(f"[{where}] journal ({e.get('source', '')}) : {e.get('text', '')} {e.get('url', '')}")

    chrome.handlers.append(on_event)
    result = {"scenario": name, "csp": bool(csp), "query": query, "ok": False}
    try:
        version = chrome.call("Browser.getVersion")
        result["chrome"] = version.get("product", "?")
        target = chrome.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        page = chrome.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        sessions[page] = "page parente"
        for m in ("Page.enable", "Runtime.enable", "Log.enable"):
            chrome.call(m, {}, page)
        chrome.call("Emulation.setDeviceMetricsOverride",
                    {"width": IFRAME_W + 40, "height": IFRAME_H + 40, "deviceScaleFactor": 1, "mobile": False}, page)
        chrome.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, page)
        def wait_ready(t0, stale=()):
            """Attend un contexte moteur (hors `stale`) dont eframe a dimensionné le canvas."""
            probe = None
            while time.monotonic() - t0 < READY_TIMEOUT:
                chrome.pump(0.1)
                if errors and time.monotonic() - t0 > ERROR_GRACE:
                    break  # erreurs déjà relevées : inutile d'attendre la fin du délai
                engine_ctx = [k for k, o in contexts.items() if o == ENGINE_ORIGIN and k not in stale]
                if not engine_ctx:
                    continue
                sess, ctx = engine_ctx[-1]
                try:
                    r = chrome.call("Runtime.evaluate", {"expression": PROBE, "contextId": ctx, "returnByValue": True}, sess, 10)
                except (RuntimeError, TimeoutError):
                    continue
                probe = json.loads(r.get("result", {}).get("value", "{}") or "{}")
                if probe.get("canvas") and probe.get("cw", 0) > 0 and probe.get("w") != 300 \
                        and abs(probe["w"] - round(probe["cw"] * probe.get("dpr", 1))) <= 1:
                    marks = probe.get("marks", {})
                    result["trunk_started_ms"] = round(marks["trunkStarted"]) if "trunkStarted" in marks else None
                    return (time.monotonic() - t0, marks.get("canvasSized", probe["t"]), sess, ctx), probe
            return None, probe

        t0 = time.monotonic()
        chrome.call("Page.navigate", {"url": f"{PARENT_ORIGIN}/"}, page)
        ready, probe = wait_ready(t0)
        if ready is not None and expect.get("legacy_storage"):
            # E5 : un « compte précédent » a laissé ses réglages sous les clés partagées de l'amont ;
            # après rechargement, le moteur ne doit ni les appliquer (langue « ja ») ni les garder.
            _, _, sess0, ctx0 = ready
            seed = ("localStorage.setItem('pdfcraft', JSON.stringify({language: 'ja', author: 'Compte précédent'}));"
                    "localStorage.setItem('printcraft', '{}'); 'ok'")
            chrome.call("Runtime.evaluate", {"expression": seed, "contextId": ctx0, "returnByValue": True}, sess0)
            stale = set(k for k, o in contexts.items() if o == ENGINE_ORIGIN)
            chrome.send("Runtime.evaluate", {"expression": "location.reload()", "contextId": ctx0}, sess0)
            ready, probe = wait_ready(time.monotonic(), stale)
            if ready is not None:
                _, _, sess1, ctx1 = ready
                keys = chrome.call("Runtime.evaluate", {"expression": "JSON.stringify(Object.keys(localStorage))",
                                                        "contextId": ctx1, "returnByValue": True}, sess1)
                result["storage_keys"] = json.loads(keys.get("result", {}).get("value", "[]"))
                leftover = [k for k in ("pdfcraft", "printcraft") if k in result["storage_keys"]]
                if leftover:
                    errors.append(f"[test] clés partagées de l'amont encore présentes après démarrage : {leftover}")
        result["probe"] = probe
        if ready is None:
            errors.append(f"[test] canvas non dimensionné par eframe après {time.monotonic() - t0:.0f} s "
                          f"(dernier relevé : {probe})")
        else:
            wall, inner, sess, ctx = ready
            result["cold_start_ms_iframe"] = round(inner)
            result["cold_start_ms_parent"] = round(wall * 1000)
            settle_end = time.monotonic() + SETTLE
            while time.monotonic() < settle_end:
                chrome.pump(0.1)
            if host:
                check_ehp(chrome, page, result, errors)
            gl = chrome.call("Runtime.evaluate", {"expression": GL_PROBE, "contextId": ctx, "returnByValue": True}, sess)
            result["gl"] = gl.get("result", {}).get("value")
            if result["gl"] != "webgl2":
                errors.append(f"[test] contexte du canvas : {result['gl']} (attendu : webgl2)")
            if "evora-audit=1" in query:
                # E9 et E10 vérifiés au rendu : le moteur audite chaque texte dessiné (window.__evoraAudit).
                audit = chrome.call("Runtime.evaluate", {"expression": "JSON.stringify(window.__evoraAudit || null)",
                                                         "contextId": ctx, "returnByValue": True}, sess)
                a = json.loads(audit.get("result", {}).get("value", "null") or "null")
                result["audit"] = a
                if not a or not a.get("frames") or not a.get("texts") or a.get("selftest") is not True:
                    errors.append(f"[test] audit au rendu absent, sans image, sans texte ou détecteur muet : {a}")
                elif a.get("emoji") or a.get("terms"):
                    errors.append(f"[test] audit au rendu : {a.get('emoji')} émoji(s) (E10) et {a.get('terms')} terme(s) "
                                  f"sensible(s) (E9) dessinés, ex. « {a.get('sample', '')} »")
                if a and "dark" in expect and a.get("dark") is not expect["dark"]:
                    errors.append(f"[test] thème au rendu : sombre={a.get('dark')} (attendu : {expect['dark']})")
                if a and expect.get("probe") and not a.get("probe"):
                    errors.append(f"[test] texte attendu au rendu absent (sonde {expect['probe']!r}) : langue non appliquée ?")
            res = chrome.call("Runtime.evaluate", {"expression": RESOURCES, "contextId": ctx, "returnByValue": True}, sess)
            result["resources"] = json.loads(res.get("result", {}).get("value", "[]"))
            msgs = chrome.call("Runtime.evaluate", {"expression": "JSON.stringify(window.__evoraMessages || [])",
                                                    "returnByValue": True}, page)
            result["parent_messages"] = json.loads(msgs.get("result", {}).get("value", "[]"))
            shot = chrome.call("Page.captureScreenshot", {"format": "png"}, page)
            with open(os.path.join(out_dir, f"smoke-{name}.png"), "wb") as fh:
                fh.write(base64.b64decode(shot["data"]))
        result["ok"] = ready is not None and not errors
    except Exception as exc:  # noqa: BLE001 — tout incident du banc est un échec visible
        errors.append(f"[test] incident : {exc!r}")
    finally:
        chrome.close()
        for srv in (engine, parent, parent6):
            if srv is not None:
                srv.shutdown()
                srv.server_close()
        shutil.rmtree(profile, ignore_errors=True)
    result["errors"] = errors
    result["requests"] = served
    result["ok"] = result["ok"] and not errors
    return result


LOG_EXPR = "JSON.stringify({log: window.__evoraLog || [], ids: window.__evoraIds || {}})"


def check_ehp(chrome, page, result, errors):
    """E4 : poignée de main EHP v1 vue de la page parente (HOST-PROTOCOL.md §3, §4, §5)."""
    end = time.monotonic() + 30
    state = {}
    while time.monotonic() < end:
        chrome.pump(0.2)
        r = chrome.call("Runtime.evaluate", {"expression": LOG_EXPR, "returnByValue": True}, page)
        state = json.loads(r.get("result", {}).get("value", "{}") or "{}")
        ids = state.get("ids", {})
        if ids.get("open") and any(m.get("re") == ids["open"] for m in state.get("log", [])):
            break
    log, ids = state.get("log", []), state.get("ids", {})
    result["ehp"] = {"messages": [{k: m.get(k) for k in ("type", "re", "payload")} for m in log], "ids": ids}
    for m in log:
        if not (m.get("fromEngine") and m.get("plain") and m.get("v") == 1):
            errors.append(f"[ehp] message hors norme ou d'une autre source : {m}")
        elif not set(m.get("keys", [])) <= {"v", "type", "id", "re", "payload"}:
            errors.append(f"[ehp] enveloppe avec un champ inconnu : {m.get('keys')}")
    ready = [m for m in log if m.get("type") == "evora:ready"]
    if len(ready) != 1:
        errors.append(f"[ehp] evora:ready reçu {len(ready)} fois (attendu : 1)")
    else:
        p = ready[0].get("payload") or {}
        caps = set(p.get("capabilities") or [])
        if p.get("app") != "colophon-atelier" or p.get("ehp") != "1.0" or not {"doc.open", "doc.save"} <= caps:
            errors.append(f"[ehp] evora:ready inattendu : {p}")
    def ack(re):
        return [m for m in log if m.get("type") == "evora:ack" and m.get("re") == re]
    if [m for m in log if ids.get("bogus") and m.get("re") == ids["bogus"]]:
        errors.append("[ehp] le moteur a répondu à un evora:init de version 2 (doit l'ignorer)")
    for step in ("init", "open"):
        got = ack(ids.get(step)) if ids.get(step) else []
        if len(got) != 1 or (got[0].get("payload") or {}).get("ok") is not True:
            errors.append(f"[ehp] accusé de evora:{step} absent ou négatif : {got}")


def main(argv):
    if len(argv) != 5:
        print(__doc__)
        return 2
    site, hashes_file, out_dir, report_path = argv[1:]
    os.makedirs(out_dir, exist_ok=True)
    chrome_bin = (os.environ.get("EVORA_CHROME") or shutil.which("google-chrome") or shutil.which("google-chrome-stable")
                  or shutil.which("chromium"))
    if not chrome_bin:
        print("::error::Chrome introuvable sur le runner")
        return 1
    with open(hashes_file, encoding="utf-8") as fh:
        hashes = [line.strip() for line in fh if line.strip().startswith("sha256-")]
    audit = "evora-audit=1" in ENGINE_QUERY
    sep = "&" if "?" in ENGINE_QUERY else "?"
    en = f"{ENGINE_QUERY}{sep}evora-probe=Welcome" if audit else ENGINE_QUERY
    fr = f"{ENGINE_QUERY}{sep}lang=fr&theme=dark&evora-probe=Bienvenue"
    results = [run_scenario("sans-csp", site, None, out_dir, chrome_bin, en,
                            {"probe": "Welcome", "dark": False} if audit else None),
               run_scenario("csp", site, engine_csp(hashes), out_dir, chrome_bin, en,
                            {"probe": "Welcome", "dark": False} if audit else None)]
    if audit:
        # E3 : langue et thème imposés par l'URL du moteur, vérifiés au rendu.
        results.append(run_scenario("fr-sombre", site, engine_csp(hashes), out_dir, chrome_bin, fr,
                                    {"probe": "Bienvenue", "dark": True}))
        # E4 : pont EHP natif, origine parente admise par evora-host.json ; evora:init impose le
        # thème sombre, evora:open ouvre « evora-smoke.pdf » (son onglet doit être dessiné).
        results.append(run_scenario("pont-ehp", site, engine_csp(hashes), out_dir, chrome_bin,
                                    f"?host=evora&evora-audit=1&evora-probe=evora-smoke",
                                    {"probe": "evora-smoke", "dark": True, "ehp": True}))
        # E5 : les réglages laissés par un autre compte sous les clés partagées ne s'appliquent pas
        # (la langue « ja » semée ne doit pas apparaître : « Welcome » reste dessiné) et sont purgés.
        results.append(run_scenario("stockage", site, engine_csp(hashes), out_dir, chrome_bin, en,
                                    {"probe": "Welcome", "dark": False, "legacy_storage": True}))
    with open(os.path.join(out_dir, "smoke.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    with open(report_path, "a", encoding="utf-8") as report:
        def log(line=""):
            print(line)
            report.write(line + "\n")
        log("### Test de fumée Chrome sans interface, origine croisée (bloquant)")
        log()
        log(f"Moteur servi par {ENGINE_ORIGIN}, encadré par une page de {PARENT_ORIGIN} ; profil vierge par scénario. "
            "URL de l'iframe : " + " ; ".join(f"{r['scenario']} index.html{r['query']}" for r in results))
        log(f"Navigateur : {results[0].get('chrome', '?')}")
        log()
        log("| Scénario | Résultat | Démarrage à froid : canvas dimensionné (iframe) | dont chargeur Trunk terminé | "
            "Depuis la navigation parente (sondage) | WebGL2 | Erreurs |")
        log("|---|---|---|---|---|---|---|")
        for r in results:
            log(f"| {r['scenario']} | {'VERT' if r['ok'] else 'ROUGE'} | {r.get('cold_start_ms_iframe', 'n/d')} ms | "
                f"{r.get('trunk_started_ms', 'n/d')} ms | {r.get('cold_start_ms_parent', 'n/d')} ms | {r.get('gl', 'n/d')} | "
                f"{len(r['errors'])} |")
        log()
        for r in results:
            wasm = [x for x in r.get("resources", []) if x["name"].endswith(".wasm")]
            if wasm:
                log(f"- {r['scenario']} : .wasm chargé en {wasm[0]['dur']} ms ({wasm[0]['size']} octets transférés, sans compression HTTP)")
            log(f"- {r['scenario']} : messages reçus par la page parente : {r.get('parent_messages', [])}")
            if "ehp" in r:
                log(f"- {r['scenario']} : échanges EHP vus de la page parente : "
                    + " ; ".join(f"{m['type']}" + (f" (re {m['re'][-4:]})" if m.get('re') else "")
                                 + (f" {json.dumps(m['payload'], ensure_ascii=False)[:160]}" if m.get('payload') else "")
                                 for m in r["ehp"]["messages"]))
            if "storage_keys" in r:
                log(f"- {r['scenario']} : clés localStorage de l'origine moteur après rechargement : {r['storage_keys']}")
            if "audit" in r:
                log(f"- {r['scenario']} : audit au rendu E9/E10 (window.__evoraAudit) : {r['audit']}")
            for e in r["errors"]:
                log(f"  - {e}")
        log()
        if any(r.get("csp") for r in results):
            log(f"CSP appliquée au scénario « csp » : `{engine_csp(hashes)}`")
            log()
    for r in results:
        print(f"::notice::fumée {r['scenario']} : {'VERT' if r['ok'] else 'ROUGE'}, démarrage à froid "
              f"{r.get('cold_start_ms_iframe', 'n/d')} ms (iframe), {r.get('cold_start_ms_parent', 'n/d')} ms (parent)")
        for e in r["errors"]:
            print(f"::error::fumée {r['scenario']} : {e[:900]}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
