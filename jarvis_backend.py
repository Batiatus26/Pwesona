"""
J.A.R.V.I.S — FastAPI / WebSocket Backend
Listens on ws://localhost:8765/ws
Launches Electron HUD as subprocess on wake word.

Usage:
    pip install fastapi uvicorn[standard] websockets
    python jarvis_backend.py
"""

# load_dotenv() must run before any other import that reads env vars
from dotenv import load_dotenv
load_dotenv()

import asyncio, os, sys, subprocess, threading, time, datetime, math, random, json
import speech_recognition as sr
import sounddevice as sd
import numpy as np
from scipy.io import wavfile

import edge_tts
from google import genai
from google.genai import types

try:
    import pygame
    PYGAME_OK = True
except ImportError:
    PYGAME_OK = False

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

try:
    from langdetect import detect as _langdetect
    LANGDETECT_OK = True
except ImportError:
    LANGDETECT_OK = False

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import agents

# ══════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════
API_KEY         = os.environ["GEMINI_API_KEY"]
VOICE_EN        = "en-GB-RyanNeural"
VOICE_TR        = "tr-TR-AhmetNeural"
VOICE           = VOICE_EN            # default; updated per-command by detect_lang()
INTRO_FILE      = "intro.webm"
WAKE_WORD       = "wake up"
LANGUAGE        = "en-US"
MUSIC_FULL_SECS = 20
MUSIC_FADE_SECS = 3
WEATHER_CITY    = os.getenv("WEATHER_CITY", "Toppenstedt")
WS_PORT         = int(os.getenv("WS_PORT", "8765"))

SSH_HOST     = os.getenv("SSH_HOST", "")
SSH_PORT     = int(os.getenv("SSH_PORT", "22"))
SSH_USER     = os.getenv("SSH_USER", "")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", "")
SSH_PASSWORD = os.getenv("SSH_PASSWORD", "")
SSH_CLAUDE   = os.getenv("SSH_CLAUDE", "claude")

SYSTEM_PROMPT = """You are J.A.R.V.I.S. (Just A Rather Very Intelligent System),
the AI assistant of Tony Stark / Iron Man.
- Polite, efficient, slightly witty British butler tone
- If the user speaks English: respond ONLY in English, address as "Sir"
- If the user speaks Turkish: respond ONLY in Turkish, address as "efendim"
- Keep responses concise (2-4 sentences) unless asked for more
- Location: Toppenstedt, Lower Saxony, Germany
- Date: {date}
Never break character."""

# ══════════════════════════════════════════════════════════════
#  GEMINI
# ══════════════════════════════════════════════════════════════
_client = genai.Client(api_key=API_KEY)
_chat  = None

def get_chat():
    global _chat
    if _chat is None:
        today = datetime.datetime.now().strftime("%A, %B %d, %Y")
        _chat = _client.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT.format(date=today),
            )
        )
    return _chat

_current_lang = "en"   # updated per-command; read by ask_gemini for language steering

def detect_lang(text: str) -> str:
    """Returns 'tr' or 'en'. Falls back to 'en' on any error."""
    if not LANGDETECT_OK or len(text.strip()) < 4:
        return "en"
    try:
        lang = _langdetect(text)
        return "tr" if lang == "tr" else "en"
    except Exception:
        return "en"

def ask_gemini(text: str) -> str:
    if _current_lang == "tr":
        text = f"[Tamamen Türkçe yanıt ver, kullanıcıya 'efendim' diye hitap et, JARVIS karakterinde kal] {text}"
    try:
        return get_chat().send_message(text).text.strip()
    except Exception as e:
        return f"Technical difficulty, Sir. {e}"

# ══════════════════════════════════════════════════════════════
#  TTS
# ══════════════════════════════════════════════════════════════
_speak_lock = threading.Lock()

async def _tts_async(text: str, voice: str = VOICE_EN):
    path = os.path.abspath("jarvis_response.mp3")
    await edge_tts.Communicate(text, voice).save(path)
    if PYGAME_OK:
        try:
            pygame.mixer.init()
            snd = pygame.mixer.Sound(path)
            snd.play()
            await asyncio.sleep(snd.get_length() + 0.4)
            return
        except Exception:
            pass
    try:
        os.startfile(path)
        await asyncio.sleep(max(2.0, len(text.split()) * 0.42))
    except Exception:
        pass

def speak(text: str, voice: str = VOICE_EN):
    with _speak_lock:
        asyncio.run(_tts_async(text, voice))

def speak_async(text: str, voice: str = VOICE_EN):
    t = threading.Thread(target=speak, args=(text, voice), daemon=True)
    t.start()
    return t

_TTS_CACHE = os.path.abspath("jarvis_response.mp3")

async def _tts_render_async(text: str):
    """Download TTS audio to disk without playing it."""
    await edge_tts.Communicate(text, VOICE).save(_TTS_CACHE)

def prerender_tts(text: str) -> threading.Thread:
    """Start rendering TTS in background; join() before play_prerendered()."""
    def _run():
        asyncio.run(_tts_render_async(text))
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t

def play_prerendered():
    """Play the already-rendered TTS file immediately — no network wait."""
    if PYGAME_OK:
        try:
            pygame.mixer.init()
            snd = pygame.mixer.Sound(_TTS_CACHE)
            snd.play()
            time.sleep(snd.get_length() + 0.3)
            return
        except Exception:
            pass
    try:
        os.startfile(_TTS_CACHE)
        time.sleep(max(2.0, len(open(_TTS_CACHE, "rb").read()) / 16000))
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
#  MUSIC
# ══════════════════════════════════════════════════════════════
_music_file = None

def prepare_music():
    """Convert intro.webm → intro_converted.mp3 via ffmpeg for smooth pygame fadeout.
    Skips conversion if the mp3 already exists. Falls back to the raw file if ffmpeg
    is unavailable."""
    global _music_file
    import subprocess as sp

    # Already-converted mp3 takes priority (avoids re-encoding on every run)
    OUT_MP3 = "intro_converted.mp3"
    if os.path.exists(OUT_MP3):
        _music_file = OUT_MP3
        print(f"[MUSIC] Using cached: {OUT_MP3}")
        return

    # Find the source file
    source = None
    for name in [INTRO_FILE, "intro.webm", "intro.mp3", "intro.wav"]:
        if os.path.exists(name):
            source = name
            break

    if source is None:
        print("[MUSIC] No intro file found.")
        _music_file = None
        return

    # If source is already mp3/wav, use it directly — no conversion needed
    if source.endswith((".mp3", ".wav")):
        _music_file = source
        print(f"[MUSIC] Using: {source}")
        return

    # Convert webm (or other) → mp3 with ffmpeg
    try:
        r = sp.run(
            ["ffmpeg", "-y", "-i", source, "-q:a", "2", OUT_MP3],
            capture_output=True, timeout=60,
        )
        if r.returncode == 0:
            _music_file = OUT_MP3
            print(f"[MUSIC] Converted {source} → {OUT_MP3}")
            return
        print(f"[MUSIC] ffmpeg error: {r.stderr.decode(errors='replace')[:120]}")
    except FileNotFoundError:
        print("[MUSIC] ffmpeg not found — using source file directly.")
    except Exception as e:
        print(f"[MUSIC] Conversion failed: {e}")

    # Last resort: play the source as-is (may not fade smoothly)
    _music_file = source

def start_music():
    if not _music_file:
        return
    if PYGAME_OK:
        try:
            pygame.mixer.pre_init(44100, -16, 2, 4096)
            pygame.mixer.init()
            pygame.mixer.music.load(_music_file)
            pygame.mixer.music.set_volume(1.0)
            pygame.mixer.music.play()
            print(f"[MUSIC] Playing: {_music_file}")
            return
        except Exception as e:
            print(f"[MUSIC] pygame error: {e}")
    try:
        os.startfile(os.path.abspath(_music_file))
    except Exception:
        pass

def fadeout_music():
    if PYGAME_OK and pygame.mixer.get_init():
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.fadeout(int(MUSIC_FADE_SECS * 1000))
            time.sleep(MUSIC_FADE_SECS)
        # if already stopped, no wait — caller is responsible for timing

# ══════════════════════════════════════════════════════════════
#  WEATHER
# ══════════════════════════════════════════════════════════════
_weather = {"temp": "--", "desc": "LOADING", "icon": "◈", "wind": "--", "humid": "--"}

def _fetch_weather_loop():
    global _weather
    while True:
        try:
            if REQUESTS_OK:
                url = f"https://wttr.in/{WEATHER_CITY}?format=j1"
                r   = requests.get(url, timeout=8)
                d   = r.json()
                cur = d["current_condition"][0]
                desc = cur["weatherDesc"][0]["value"].upper()
                icons = {
                    "SUNNY":"☀","CLEAR":"☀","CLOUD":"☁","OVERCAST":"☁",
                    "RAIN":"⛆","DRIZZLE":"⛆","SNOW":"❄","THUNDER":"⚡",
                    "FOG":"≋","MIST":"≋","HAZE":"≋",
                }
                icon = next((v for k, v in icons.items() if k in desc), "◈")
                _weather = {
                    "temp":  f"{cur['temp_C']}°C",
                    "desc":  desc[:18],
                    "icon":  icon,
                    "wind":  f"{cur['windspeedKmph']}km/h",
                    "humid": f"{cur['humidity']}%",
                }
        except Exception:
            pass
        time.sleep(600)

threading.Thread(target=_fetch_weather_loop, daemon=True).start()

# ══════════════════════════════════════════════════════════════
#  SYSTEM METRICS
# ══════════════════════════════════════════════════════════════
_sys_metrics = {"cpu": 0, "mem": 0, "disk": 0, "net_up": 0, "net_down": 0}
_net_old     = None

def _fetch_metrics_loop():
    global _sys_metrics, _net_old
    while True:
        try:
            if PSUTIL_OK:
                cpu  = psutil.cpu_percent(interval=1)
                mem  = psutil.virtual_memory().percent
                disk = psutil.disk_usage('/').percent
                net  = psutil.net_io_counters()
                up   = (net.bytes_sent - _net_old.bytes_sent) / 1024 if _net_old else 0.0
                down = (net.bytes_recv - _net_old.bytes_recv) / 1024 if _net_old else 0.0
                _net_old = net
                _sys_metrics = {
                    "cpu":      round(cpu,  1),
                    "mem":      round(mem,  1),
                    "disk":     round(disk, 1),
                    "net_up":   round(up,   1),
                    "net_down": round(down, 1),
                }
        except Exception:
            pass
        time.sleep(2)

threading.Thread(target=_fetch_metrics_loop, daemon=True).start()

# ══════════════════════════════════════════════════════════════
#  ALEXA (placeholder)
# ══════════════════════════════════════════════════════════════
_alexa_devices = [
    {"name": "LIVING ROOM", "type": "LIGHT",  "state": "ON",  "val": "80%"},
    {"name": "BEDROOM",     "type": "LIGHT",  "state": "OFF", "val": "--"},
    {"name": "THERMOSTAT",  "type": "THERMO", "state": "ON",  "val": "21°C"},
    {"name": "TV",          "type": "SWITCH", "state": "OFF", "val": "--"},
    {"name": "SPEAKER",     "type": "AUDIO",  "state": "ON",  "val": "VOL 40"},
]

# ══════════════════════════════════════════════════════════════
#  REMINDERS
# ══════════════════════════════════════════════════════════════
_reminders = [
    {"time": "09:00", "text": "Morning briefing"},
    {"time": "14:30", "text": "System backup check"},
    {"time": "18:00", "text": "Network scan"},
    {"time": "22:00", "text": "Shutdown sequence"},
]

# ══════════════════════════════════════════════════════════════
#  SSH / CLAUDE CODE BRIDGE
# ══════════════════════════════════════════════════════════════
class ClaudeCodeBridge:
    def __init__(self):
        self._client   = None
        self._lock     = threading.Lock()
        self.status    = "OFFLINE"
        self.last_task = "—"

    def _connect(self):
        try:
            import paramiko
        except ImportError:
            self.status = "NO PARAMIKO"
            return False, "pip install paramiko"
        if not SSH_HOST or not SSH_USER:
            self.status = "NOT CONFIGURED"
            return False, "Set SSH_HOST and SSH_USER."
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kwargs = dict(hostname=SSH_HOST, port=SSH_PORT,
                          username=SSH_USER, timeout=12)
            if SSH_KEY_PATH:
                kwargs["key_filename"] = SSH_KEY_PATH
            elif SSH_PASSWORD:
                kwargs["password"] = SSH_PASSWORD
            client.connect(**kwargs)
            self._client = client
            self.status  = "ONLINE"
            return True, "Connected"
        except Exception as e:
            self.status = "ERROR"
            return False, str(e)

    def run(self, prompt: str, timeout=90):
        with self._lock:
            if not SSH_HOST or not SSH_USER:
                return False, "SSH not configured."
            if self._client is None:
                ok, msg = self._connect()
                if not ok:
                    return False, f"SSH failed: {msg}"
            try:
                safe = prompt.replace("\\", "\\\\").replace("'", "'\\''")
                cmd  = f"{SSH_CLAUDE} --print '{safe}'"
                _, stdout, stderr = self._client.exec_command(cmd, timeout=timeout)
                out = stdout.read().decode("utf-8", errors="replace").strip()
                err = stderr.read().decode("utf-8", errors="replace").strip()
                self.last_task = prompt[:40]
                if not out and err:
                    return False, err[:600]
                return True, out or "(no output)"
            except Exception as e:
                self._client = None
                self.status  = "DISCONNECTED"
                return False, str(e)

    def disconnect(self):
        if self._client:
            try: self._client.close()
            except Exception: pass
            self._client = None
        self.status = "OFFLINE"

_bridge       = ClaudeCodeBridge()
_forced_agent: str = ""   # empty = auto-route; set by set_active_agent action

# ── Boot agents ───────────────────────────────────────────────
agents.init(ask_gemini, _bridge, _reminders, _alexa_devices)
_router = agents.AgentRouter()

# ══════════════════════════════════════════════════════════════
#  MICROPHONE
# ══════════════════════════════════════════════════════════════
class MicrophoneEngine:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold       = 300
        self.recognizer.dynamic_energy_threshold = True
        self.fs          = 44100
        self.rec_seconds = 5
        self.active      = False
        self._stop       = False

    def listen_once(self) -> str:
        try:
            rec = sd.rec(int(self.rec_seconds * self.fs),
                         samplerate=self.fs, channels=1, dtype='int16')
            sd.wait()
            wavfile.write("_tmp_rec.wav", self.fs, rec)
            with sr.AudioFile("_tmp_rec.wav") as src:
                audio = self.recognizer.record(src)
            return self.recognizer.recognize_google(audio, language=LANGUAGE).lower().strip()
        except sr.UnknownValueError:
            return ""
        except Exception as e:
            print(f"[MIC] {e}")
            return ""

    def stop(self):
        self._stop = True

_mic = MicrophoneEngine()

# ══════════════════════════════════════════════════════════════
#  WEBSOCKET CONNECTION MANAGER
# ══════════════════════════════════════════════════════════════
class ConnectionManager:
    def __init__(self):
        self._clients: list = []
        self._loop = None

    def set_loop(self, loop):
        self._loop = loop

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)
        print(f"[WS] Client connected. Total: {len(self._clients)}")

    def disconnect(self, ws: WebSocket):
        if ws in self._clients:
            self._clients.remove(ws)
        print(f"[WS] Client disconnected. Total: {len(self._clients)}")

    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = []
        for ws in self._clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_sync(self, data: dict):
        """Thread-safe broadcast from non-async context."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(data), self._loop)

mgr = ConnectionManager()

# ══════════════════════════════════════════════════════════════
#  JARVIS STATE
# ══════════════════════════════════════════════════════════════
_jarvis_status  = "OFFLINE"
_jarvis_speech  = "J.A.R.V.I.S — OFFLINE"
_start_time     = time.time()
_active         = False


def _set_status(text: str):
    global _jarvis_status
    _jarvis_status = text.upper()
    mgr.broadcast_sync({"type": "status", "text": _jarvis_status})


def _set_speech(text: str):
    global _jarvis_speech
    _jarvis_speech = text
    mgr.broadcast_sync({"type": "speech", "text": text})


def _add_log(msg: str, level: str = "info"):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    mgr.broadcast_sync({"type": "log", "msg": f"[{ts}] {msg}", "level": level})


def _add_conv(role: str, text: str):
    mgr.broadcast_sync({"type": "conv", "role": role, "text": text[:200]})


# ══════════════════════════════════════════════════════════════
#  BOOT SEQUENCE
# ══════════════════════════════════════════════════════════════
def _boot_sequence():
    global _active
    time.sleep(0.8)
    _set_status("BOOTING")
    _set_speech("J.A.R.V.I.S — INITIALIZING ALL SYSTEMS...")

    start_music()

    for msg, lvl, delay in [
        ("Neural link established",  "ok", 0.3),
        ("Arc reactor nominal",      "ok", 0.5),
        ("Gemini 2.5 Flash online",  "ok", 0.7),
        ("Voice engine EN/TR ready", "ok", 1.0),
        ("Agent system online",      "ok", 1.3),
        ("Weather feed connected",   "ok", 1.6),
        ("Smart home bridge loaded", "ok", 2.0),
        ("SSH bridge standby",       "ok", 2.3),
        ("All systems nominal",      "ok", 2.8),
    ]:
        time.sleep(delay)
        _add_log(msg, lvl)

    _set_status("STANDBY")
    _set_speech("All systems online. Awaiting introduction...")

    today  = datetime.datetime.now().strftime("%A, %B %d")
    report = (
        f"Welcome back, Sir. Today is {today}. "
        "All systems are nominal. "
        f"Temperature in {WEATHER_CITY} is {_weather['temp']}. "
        "Five-agent system and Gemini neural engine are online. "
        "Hoşgeldiniz efendim."
    )

    # Pre-render TTS while music is still playing so there is zero gap after fadeout
    print("[JARVIS] Pre-rendering welcome speech...")
    render_thread = prerender_tts(report)

    print(f"[JARVIS] Music playing for {MUSIC_FULL_SECS}s...")
    time.sleep(MUSIC_FULL_SECS)

    # Ensure audio is ready before we start the fade
    render_thread.join()

    print("[JARVIS] Fading out music...")
    fadeout_music()  # smooth 3-second fade; blocks until complete

    # Audio already on disk — play immediately, no network wait
    _set_status("SPEAKING")
    _set_speech(report)
    play_prerendered()

    _active = True
    _set_status("LISTENING")
    _set_speech("Awaiting your command, Sir.")
    _add_log("Listening for commands...", "info")

    _command_loop()


def _command_loop():
    print("[JARVIS] Command loop active.")
    while not _mic._stop and _active:
        heard = _mic.listen_once()
        if heard:
            print(f"[SIR] {heard}")
            _handle_command(heard)


def _handle_command(text: str):
    global _current_lang
    _set_status("PROCESSING")
    _add_log(f"SIR: {text[:45]}", "cmd")
    _add_conv("SIR", text)
    _set_speech(f"Processing: {text[:80]}...")
    mgr.broadcast_sync({"type": "user_text", "text": text})

    # Detect language; steer Gemini and TTS accordingly
    _current_lang = detect_lang(text)
    voice = VOICE_TR if _current_lang == "tr" else VOICE_EN
    mgr.broadcast_sync({"type": "lang", "lang": _current_lang.upper()})

    # Route: forced agent takes priority over auto-routing
    if _forced_agent:
        agent_name, reply, agent_icon = None, None, "◈"
        for ag in _router.agents:
            if ag.name == _forced_agent:
                try:
                    reply = ag.handle(text)
                except Exception as e:
                    reply = f"Agent error, Sir: {e}"
                agent_name, agent_icon = ag.name, ag.icon
                break
        if agent_name is None:
            agent_name, reply, agent_icon = _router.route(text)
    else:
        agent_name, reply, agent_icon = _router.route(text)

    _set_status("SPEAKING")
    _add_log(f"{agent_name}: {reply[:45]}", "reply")
    _add_conv(agent_name, reply)
    _set_speech(reply)
    mgr.broadcast_sync({"type": "agent", "agent": agent_name, "icon": agent_icon})

    speak_async(reply, voice).join()

    _set_status("LISTENING")
    _set_speech("Awaiting your command, Sir.")


# ══════════════════════════════════════════════════════════════
#  FASTAPI APP
# ══════════════════════════════════════════════════════════════
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await mgr.connect(ws)

    # Send current state immediately on connect
    await ws.send_text(json.dumps({
        "type":    "init",
        "status":  _jarvis_status,
        "speech":  _jarvis_speech,
        "weather": _weather,
        "metrics": _sys_metrics,
        "alexa":   _alexa_devices,
        "reminders": _reminders,
    }))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            await _handle_ws_message(msg)
    except WebSocketDisconnect:
        mgr.disconnect(ws)
    except Exception as e:
        print(f"[WS] Error: {e}")
        mgr.disconnect(ws)


async def _handle_ws_message(msg: dict):
    t = msg.get("type")
    if t == "command":
        text = msg.get("text", "").strip()
        if text:
            threading.Thread(target=_handle_command, args=(text,), daemon=True).start()
    elif t == "action":
        await _handle_action(msg)
    elif t == "ping":
        await mgr.broadcast({"type": "pong"})


# ── App name → Windows launch command ────────────────────────
_APP_LAUNCH: dict = {
    "chrome":          ["start", "", "chrome"],
    "spotify":         ["start", "", "spotify"],
    "discord":         ["start", "", "discord"],
    "whatsapp":        ["start", "", "WhatsApp"],
    "telegram":        ["start", "", "telegram"],
    "claude":          ["start", "", "claude"],
    "android_studio":  ["start", "", "studio64"],
    "visual_studio":   ["start", "", "devenv"],
    "pycharm":         ["start", "", "pycharm"],
}

# Friendly display names
_APP_NAMES: dict = {
    "chrome":         "Chrome",
    "spotify":        "Spotify",
    "discord":        "Discord",
    "whatsapp":       "WhatsApp",
    "telegram":       "Telegram",
    "claude":         "Claude Code",
    "android_studio": "Android Studio",
    "visual_studio":  "Visual Studio",
    "pycharm":        "PyCharm",
}

def _launch_app(app: str) -> tuple:
    if app not in _APP_LAUNCH:
        return False, f"Unknown application: {app}"
    name = _APP_NAMES.get(app, app.replace("_", " ").title())
    try:
        subprocess.Popen(
            _APP_LAUNCH[app],
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return True, f"Launching {name}, Sir."
    except Exception as e:
        return False, f"Could not launch {name}: {str(e)[:80]}"


_SYSTEM_CMDS: dict = {
    "restart":  "shutdown /r /t 10",
    "shutdown": "shutdown /s /t 10",
    "logoff":   "shutdown /l",
    "sleep":    "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
}

def _run_system_cmd(cmd: str):
    if cmd not in _SYSTEM_CMDS:
        return
    verb = cmd.title()
    msg  = f"Initiating {verb}, Sir. You have 10 seconds." if cmd in ("restart", "shutdown") \
           else f"{verb} sequence initiated, Sir."
    _add_log(f"SYSTEM: {cmd.upper()}", "warn")
    _set_speech(msg)
    speak_async(msg)
    subprocess.Popen(_SYSTEM_CMDS[cmd], shell=True)


async def _handle_action(msg: dict):
    action = msg.get("action", "")

    if action == "launch_app":
        app      = msg.get("app", "")
        ok, text = _launch_app(app)
        _add_log(text, "ok" if ok else "warn")
        await mgr.broadcast({
            "type":   "action_result",
            "ok":     ok,
            "msg":    text,
            "speech": text if ok else None,
        })
        if ok:
            speak_async(text)

    elif action == "system":
        cmd = msg.get("cmd", "")
        if cmd in _SYSTEM_CMDS:
            threading.Thread(target=_run_system_cmd, args=(cmd,), daemon=True).start()
            await mgr.broadcast({
                "type": "action_result",
                "ok":   True,
                "msg":  f"SYSTEM: {cmd.upper()} initiated",
            })

    elif action == "claude_task":
        prompt = msg.get("prompt", "").strip()
        if prompt:
            def _run_claude_task():
                _add_log(f"Claude task: {prompt[:45]}", "cmd")
                mgr.broadcast_sync({"type": "claude_status", "status": "RUNNING — SSH BRIDGE..."})
                ok, result = _bridge.run(prompt)
                mgr.broadcast_sync({
                    "type":   "claude_response",
                    "ok":     ok,
                    "output": result,
                    "prompt": prompt[:80],
                })
                _add_log(f"Claude: {'OK' if ok else 'ERR'} — {result[:45]}", "ok" if ok else "warn")
            threading.Thread(target=_run_claude_task, daemon=True).start()

    elif action == "set_active_agent":
        global _forced_agent
        _forced_agent = msg.get("agent", "").strip()
        label = _forced_agent or "AUTO-ROUTE"
        _add_log(f"Agent routing: {label}", "ok")
        await mgr.broadcast({"type": "agent_locked", "agent": _forced_agent})

    elif action == "agent_task":
        agent_name = msg.get("agent", "").strip()
        task       = msg.get("task",  "").strip()
        if agent_name and task:
            def _run_agent_task(name=agent_name, text=task):
                for ag in _router.agents:
                    if ag.name == name:
                        _add_log(f"{name} task: {text[:40]}", "cmd")
                        _set_status("PROCESSING")
                        try:
                            reply = ag.handle(text)
                        except Exception as e:
                            reply = f"Agent error: {e}"
                        _set_speech(reply)
                        _add_log(f"{name}: {reply[:45]}", "reply")
                        mgr.broadcast_sync({"type": "agent", "agent": name, "icon": ag.icon})
                        voice = VOICE_TR if _current_lang == "tr" else VOICE_EN
                        speak_async(reply, voice).join()
                        _set_status("LISTENING")
                        return
            threading.Thread(target=_run_agent_task, daemon=True).start()


# Background task: push metrics + weather every 2 seconds
async def _push_metrics():
    while True:
        await asyncio.sleep(2)
        elapsed = int(time.time() - _start_time)
        await mgr.broadcast({
            "type":    "metrics",
            "metrics": _sys_metrics,
            "weather": _weather,
            "uptime":  f"{elapsed//86400}d {(elapsed%86400)//3600}h {(elapsed%3600)//60}m",
            "bridge":  _bridge.status,
        })


@app.on_event("startup")
async def _startup():
    loop = asyncio.get_event_loop()
    mgr.set_loop(loop)
    asyncio.create_task(_push_metrics())

    # Run wake-word + boot in background thread
    def _run():
        prepare_music()
        print(f"[JARVIS] Listening for wake word: '{WAKE_WORD}'")
        _set_status("WAITING")
        _set_speech(f"Say '{WAKE_WORD}' to activate...")
        while not _mic._stop:
            heard = _mic.listen_once()
            if heard:
                print(f"[MIC] {heard}")
            if WAKE_WORD in heard:
                print("[JARVIS] Wake word detected!")
                _boot_sequence()
                break

    threading.Thread(target=_run, daemon=True).start()


# ══════════════════════════════════════════════════════════════
#  ELECTRON LAUNCHER
# ══════════════════════════════════════════════════════════════
def _launch_electron():
    electron_dir = os.path.join(os.path.dirname(__file__), "electron")
    if not os.path.exists(electron_dir):
        print("[ELECTRON] electron/ directory not found — run: npm install inside it")
        return
    node_modules = os.path.join(electron_dir, "node_modules", ".bin", "electron.cmd")
    if os.path.exists(node_modules):
        cmd = [node_modules, "."]
    else:
        cmd = ["npx", "electron", "."]
    try:
        subprocess.Popen(cmd, cwd=electron_dir,
                         creationflags=subprocess.CREATE_NEW_CONSOLE
                         if sys.platform == "win32" else 0)
        print("[ELECTRON] HUD launched.")
    except Exception as e:
        print(f"[ELECTRON] Failed to launch: {e}")


if __name__ == "__main__":
    print("=" * 58)
    print("   J.A.R.V.I.S  —  BACKEND  v4.0")
    print(f"   WebSocket: ws://localhost:{WS_PORT}/ws")
    print("=" * 58)
    _launch_electron()
    uvicorn.run(app, host="0.0.0.0", port=WS_PORT, log_level="warning")
