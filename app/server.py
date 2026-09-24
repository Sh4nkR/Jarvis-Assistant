"""Jarvis: one local server that runs everything.

  http://127.0.0.1:8795/          the window: jaredrhod's face + the button dock
  /ws                             live link between the window and Jarvis
  /state, /config                 what the face reads (same contract as ai-visualizer)
  /api/...                        speech-to-text, status, memory notes

Only this PC can reach it (127.0.0.1), and only the Jarvis window itself may
talk to it: every live connection and every POST must come from this page.
Other websites open in your browser are refused.
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser

from aiohttp import WSMsgType, web

from common import APP, CFG, IS_WIN, MEMORY, setup_logging

log = setup_logging()

import tools                                    # noqa: E402

tools.dpi_aware()                               # before anything measures the screen
tools.STATE.hands = bool(CFG.get("hands_on_at_start", True))

import signin                                   # noqa: E402
from brain import Brain, describe               # noqa: E402
from ears import Ears                           # noqa: E402
from mouth import Mouth                         # noqa: E402

PORT = int(CFG["port"])
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ORIGINS = {f"http://{h}" for h in HOSTS}
FACE_DIR = (APP / "face").resolve()
DOCK_DIR = (APP / "dock").resolve()
FACES = ["board", "radial", "rain", "neural"]
INJECT = ('<link rel="stylesheet" href="/dock/dock.css">\n'
          '<script src="/dock/dock.js"></script>\n')


# ------------------------------------------------------------------ hub ----
class Hub:
    def __init__(self):
        self.clients: set[web.WebSocketResponse] = set()
        self.history: list[dict] = []
        self.perms: dict[str, asyncio.Future] = {}
        self.cams: dict[str, asyncio.Future] = {}
        self.state = "idle"

    async def send(self, obj: dict):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(obj)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def remember(self, who: str, text: str):
        self.history.append({"who": who, "text": text, "t": time.time()})
        del self.history[:-200]


HUB = Hub()
EARS = Ears()
MOUTH = Mouth()


def status() -> dict:
    return {"brain": BRAIN.status, "brain_error": BRAIN.error, "ears": EARS.status,
            "ears_error": EARS.error, "mouth": MOUTH.status, "hands": tools.STATE.hands,
            "screen_text": bool(tools.find_tesseract()), "name": CFG["name"],
            "call_me": CFG["call_me"], "face": CFG["face"]}


async def push_status():
    await HUB.send({"type": "status", "status": status()})


async def permission_gate(name: str, inp: dict) -> bool:
    """The brain wants to do something that needs Dr Wolf's yes."""
    if not HUB.clients:
        return False
    pid = uuid.uuid4().hex
    fut = asyncio.get_running_loop().create_future()
    HUB.perms[pid] = fut
    await HUB.send({"type": "permission", "id": pid, "tool": name, "detail": describe(name, inp)})
    audio = await MOUTH.synth("I need your permission for this one, sir. It's on screen.")
    await HUB.send({"type": "notice", "text": "Permission needed", "audio": _b64(audio)})
    try:
        return bool(await asyncio.wait_for(fut, 120))
    except asyncio.TimeoutError:
        await HUB.send({"type": "permission_closed", "id": pid})
        return False
    finally:
        HUB.perms.pop(pid, None)


async def camera_provider():
    """The brain asked for a camera picture; the window takes it."""
    if not HUB.clients:
        return None, "The Jarvis window isn't open."
    cid = uuid.uuid4().hex
    fut = asyncio.get_running_loop().create_future()
    HUB.cams[cid] = fut
    await HUB.send({"type": "camera_request", "id": cid})
    try:
        data, note = await asyncio.wait_for(fut, 20)
        return data, note
    except asyncio.TimeoutError:
        return None, "The camera didn't answer. Is it allowed in the Jarvis window?"
    finally:
        HUB.cams.pop(cid, None)


tools.STATE.camera_provider = camera_provider
BRAIN = Brain(permission_gate)


def _b64(b: bytes | None):
    return base64.b64encode(b).decode() if b else None


# ---------------------------------------------------------- conversation ----
class Conversation:
    def __init__(self):
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.cut = False                            # STOP pressed: drop unspoken sentences

    async def ask(self, text: str, images: list[dict]):
        if self.task and not self.task.done():
            await self.stop(quiet=True)             # a new question cuts the old answer off
        self.task = asyncio.create_task(self._turn(text, images))

    async def stop(self, quiet: bool = False):
        self.cut = True
        await BRAIN.interrupt()
        for f in list(HUB.perms.values()):
            if not f.done():
                f.set_result(False)
        if self.task and not self.task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 15)
            except (asyncio.TimeoutError, Exception):
                self.task.cancel()
        if not quiet:
            await HUB.send({"type": "stopped"})

    async def _turn(self, text: str, images: list[dict]):
        async with self.lock:
            self.cut = False
            HUB.remember("you", text + ("  [+ picture]" if images else ""))
            await HUB.send({"type": "turn_start", "text": text, "pictures": len(images)})
            q: asyncio.Queue = asyncio.Queue()
            speaker = asyncio.create_task(self._speaker(q))
            reply: list[str] = []
            try:
                async for ev in BRAIN.ask(text, images):
                    kind = ev[0]
                    if kind == "delta":
                        reply.append(ev[1])
                        await HUB.send({"type": "delta", "text": ev[1]})
                    elif kind == "sentence":
                        q.put_nowait((ev[1], asyncio.create_task(MOUTH.synth(ev[1]))))
                    elif kind == "tool":
                        await HUB.send({"type": "tool", "name": ev[1], "detail": describe(ev[1], ev[2])})
                    elif kind == "error":
                        chunk = ("\n" if reply else "") + ev[1]
                        reply.append(chunk)
                        await HUB.send({"type": "delta", "text": chunk})
                        q.put_nowait((ev[1], asyncio.create_task(MOUTH.synth(ev[1]))))
                        await push_status()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("turn failed")
                await HUB.send({"type": "delta", "text": f"\nSomething broke: {e}"})
            finally:
                q.put_nowait(None)
                try:
                    await asyncio.wait_for(speaker, 120)
                except Exception:
                    speaker.cancel()
                HUB.remember("jarvis", "".join(reply).strip())
                await HUB.send({"type": "turn_end"})

    async def _speaker(self, q: asyncio.Queue):
        """Sends sentences to the window in order; each one's audio was made in parallel."""
        seq = 0
        while True:
            item = await q.get()
            if item is None:
                return
            text, task = item
            if self.cut:
                task.cancel()
                continue
            try:
                audio = await task
            except Exception:
                audio = None
            if self.cut:
                continue
            seq += 1
            await HUB.send({"type": "say", "seq": seq, "text": text, "audio": _b64(audio)})


CONVO = Conversation()


# ------------------------------------------------------------ websocket ----
async def ws_handler(request: web.Request):
    if request.headers.get("Origin") not in ORIGINS:
        return web.Response(status=403, text="Only the Jarvis window may connect.")
    ws = web.WebSocketResponse(max_msg_size=24 * 1024 * 1024, heartbeat=25)
    await ws.prepare(request)
    HUB.clients.add(ws)
    await ws.send_json({"type": "hello", "status": status(), "history": HUB.history[-60:]})
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except ValueError:
                continue
            try:
                await on_client(data)
            except Exception as e:
                log.exception("window message failed")
                await ws.send_json({"type": "toast", "text": f"Error: {e}"})
    finally:
        HUB.clients.discard(ws)
    return ws


async def on_client(d: dict):
    t = d.get("type")
    if t == "ask":
        text = (d.get("text") or "").strip()
        images = [im for im in (d.get("images") or []) if isinstance(im, dict) and im.get("data")]
        if d.get("screen"):
            img, _ = await asyncio.to_thread(tools.grab_screen)
            b64, _ = await asyncio.to_thread(tools.to_jpeg_b64, img)
            images.append({"media_type": "image/jpeg", "data": b64})
            text = text or "Look at my screen. What's on it?"
        if text or images:
            await CONVO.ask(text or "What do you see in this picture?", images)
    elif t == "stop":
        await CONVO.stop()
    elif t == "hands":
        tools.STATE.hands = bool(d.get("on"))
        log.info("hands %s", "ON" if tools.STATE.hands else "OFF")
        await push_status()
    elif t == "permission_reply":
        f = HUB.perms.get(d.get("id"))
        if f and not f.done():
            f.set_result(bool(d.get("allow")))
    elif t == "camera_frame":
        f = HUB.cams.get(d.get("id"))
        if f and not f.done():
            f.set_result((d.get("data"), d.get("note") or ""))
    elif t == "signin":
        asyncio.create_task(do_signin())
    elif t == "new_session":
        await CONVO.stop(quiet=True)
        await BRAIN.restart()
        HUB.history.clear()
        await HUB.send({"type": "cleared"})
        await push_status()


async def do_signin():
    """Opens Claude's sign-in page, then waits (up to 5 minutes) for it to finish."""
    try:
        await asyncio.to_thread(signin.login, True)
    except Exception as e:
        await HUB.send({"type": "toast", "text": f"Couldn't open the sign-in: {e}"})
        return
    for _ in range(100):
        await asyncio.sleep(3)
        s = await asyncio.to_thread(signin.status)
        if s.get("loggedIn"):
            await start_brain()
            return
    await HUB.send({"type": "toast", "text": "Sign-in didn't finish. Press SIGN IN to try again."})


async def start_brain():
    BRAIN.status = "starting"
    await push_status()
    s = await asyncio.to_thread(signin.status)
    if not s.get("loggedIn"):
        BRAIN.status, BRAIN.error = "signin", s.get("error", "")
        log.info("brain needs sign-in")
        await push_status()
        return
    try:
        await BRAIN.stop()
        await BRAIN.start()
    except Exception as e:
        BRAIN.status, BRAIN.error = "error", str(e)[:300]
        log.exception("brain failed to start")
    await push_status()


async def start_ears():
    await asyncio.to_thread(EARS.load)
    await push_status()


# ----------------------------------------------------------------- http ----
@web.middleware
async def guard(request: web.Request, handler):
    if request.host not in HOSTS:                       # blocks DNS-rebinding tricks
        return web.Response(status=403, text="forbidden")
    if request.method != "GET" and request.headers.get("Origin") not in ORIGINS:
        return web.Response(status=403, text="Only the Jarvis window may do that.")
    resp = await handler(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _safe(base, tail: str):
    p = (base / tail).resolve()
    if p != base and base not in p.parents:
        raise web.HTTPNotFound()
    if p.is_dir():
        p = p / "index.html"
    if not p.is_file():
        raise web.HTTPNotFound()
    return p


async def root(request):
    face = CFG["face"] if CFG["face"] in FACES else "board"
    raise web.HTTPFound(f"/face/faces/{face}/index.html")


async def face_file(request):
    p = _safe(FACE_DIR, request.match_info["tail"])
    if p.name == "index.html" and p.parent.parent.name == "faces":
        html = p.read_text(encoding="utf-8").replace("<head>", "<head>\n" + INJECT, 1)
        return web.Response(text=html, content_type="text/html")
    return web.FileResponse(p)


async def dock_file(request):
    return web.FileResponse(_safe(DOCK_DIR, request.match_info["tail"]))


async def face_state(request):
    return web.json_response({"state": HUB.state, "level": 0, "samples": None,
                              "alert": False, "loading": False})


async def face_config(request):
    faces = []
    for f in FACES:
        meta = {"id": f, "title": f.title(), "tagline": ""}
        try:
            meta.update(json.loads((FACE_DIR / "faces" / f / "face.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        faces.append(meta)
    return web.json_response({"name": CFG["name"], "badge": "", "face": CFG["face"],
                              "thinking_sound": True, "faces": faces})


async def api_ping(request):
    return web.json_response({"jarvis": True, "name": CFG["name"]})


async def api_status(request):
    return web.json_response(status())


async def api_listen(request):
    audio = await request.read()
    if len(audio) < 1500:
        return web.json_response({"text": "", "note": "too short"})
    try:
        text = await asyncio.to_thread(EARS.transcribe, audio)
    except Exception as e:
        return web.json_response({"text": "", "note": str(e)}, status=503)
    log.info("heard: %s", text)
    return web.json_response({"text": text})


async def api_face(request):
    d = await request.json()
    face = d.get("face")
    if face not in FACES:
        raise web.HTTPBadRequest()
    CFG["face"] = face
    try:
        path = APP / "jarvis.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["face"] = face
        path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        pass
    return web.json_response({"face": face})


async def api_memory(request):
    out = []
    for p in sorted(MEMORY.rglob("*.md")):
        rel = p.relative_to(MEMORY).as_posix()
        if rel.startswith("."):
            continue
        st = p.stat()
        out.append({"path": rel, "size": st.st_size, "modified": st.st_mtime})
    out.sort(key=lambda n: -n["modified"])
    return web.json_response(out)


async def api_note(request):
    p = _safe(MEMORY.resolve(), request.query.get("path", ""))
    if p.suffix.lower() != ".md":
        raise web.HTTPNotFound()
    return web.json_response({"path": p.relative_to(MEMORY.resolve()).as_posix(),
                              "text": p.read_text(encoding="utf-8", errors="replace")})


def build_app() -> web.Application:
    app = web.Application(middlewares=[guard], client_max_size=32 * 1024 * 1024)
    app.router.add_get("/", root)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/state", face_state)
    app.router.add_get("/config", face_config)
    app.router.add_get("/face/{tail:.*}", face_file)
    app.router.add_get("/dock/{tail:.*}", dock_file)
    app.router.add_get("/api/ping", api_ping)
    app.router.add_get("/api/status", api_status)
    app.router.add_post("/api/listen", api_listen)
    app.router.add_post("/api/face", api_face)
    app.router.add_get("/api/memory", api_memory)
    app.router.add_get("/api/memory/note", api_note)
    return app


# ----------------------------------------------------------------- main ----
URL = f"http://127.0.0.1:{PORT}/"


def open_window():
    if not CFG.get("open_window", True):
        return
    if IS_WIN:
        for exe in (shutil.which("msedge"),
                    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                    os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")):
            if exe and os.path.exists(exe):
                subprocess.Popen([exe, f"--app={URL}", "--start-maximized"])
                return
    webbrowser.open(URL)


def already_running() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/ping", timeout=2) as r:
            return json.loads(r.read()).get("jarvis") is True
    except Exception:
        return False


async def serve():
    runner = web.AppRunner(build_app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    print()
    print(f"  {CFG['name']} is running at {URL}")
    print("  Keep this window open. Closing it switches Jarvis off.")
    print()
    open_window()
    bg = [asyncio.create_task(start_ears()), asyncio.create_task(start_brain())]
    try:
        await asyncio.Event().wait()
    finally:
        for t in bg:
            t.cancel()
        await BRAIN.stop()
        await runner.cleanup()


def main():
    if already_running():
        print("  Jarvis is already running. Opening its window.")
        open_window()
        return
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
    except OSError as e:
        print(f"\n  Jarvis couldn't start: port {PORT} is in use by another program ({e}).")
        print("  Change \"port\" in app\\jarvis.json, or restart the PC.")
        sys.exit(1)


if __name__ == "__main__":
    main()
