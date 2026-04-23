"""
╔══════════════════════════════════════════════════════════════╗
║          J.A.R.V.I.S  —  STARK INDUSTRIES  v4.0             ║
║                                                              ║
║  ► Tam ekran HUD  (jarvis_hud_v2.html tasarımı)             ║
║  ► Radar sweep merkez  (wireframe küre → radar)             ║
║  ► Gerçek CPU/RAM/Ağ verisi (psutil)                        ║
║  ► Hava durumu (wttr.in API, Toppenstedt)                   ║
║  ► Alexa cihaz paneli                                       ║
║  ► SSH / Claude Code bridge                                  ║
║  ► Müzik webm→WAV + pygame smooth fadeout                   ║
╚══════════════════════════════════════════════════════════════╝
"""

import os, sys, asyncio, datetime, threading, math, time, random
import tkinter as tk
import customtkinter as ctk
import speech_recognition as sr
import sounddevice as sd
import numpy as np
from scipy.io import wavfile

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

import edge_tts
import google.generativeai as genai

# ══════════════════════════════════════════════════════════════
#  AYARLAR
# ══════════════════════════════════════════════════════════════
API_KEY         = ""
VOICE           = "en-GB-RyanNeural"
INTRO_FILE      = "intro.webm"
WAKE_WORD       = "wake up"
LANGUAGE        = "en-US"
MUSIC_FULL_SECS = 20
MUSIC_FADE_SECS = 3
WEATHER_CITY    = "Toppenstedt"

# ── SSH / Claude Code bridge ────────────────────────────────
SSH_HOST     = ""          # e.g. "192.168.1.100"
SSH_PORT     = 22
SSH_USER     = ""          # e.g. "ubuntu"
SSH_KEY_PATH = ""          # path to .ssh/id_rsa, or "" for password
SSH_PASSWORD = ""
SSH_CLAUDE   = "claude"    # path to claude CLI on remote

BRIDGE_TRIGGERS = ("code ", "claude code ", "send to claude ", "hey claude ")

SYSTEM_PROMPT = """You are J.A.R.V.I.S. (Just A Rather Very Intelligent System),
the AI assistant of Tony Stark / Iron Man.
- Polite, efficient, slightly witty British butler tone
- Address the user as "Sir" or "Efendim" depending on language
- Keep responses concise (2-4 sentences) unless asked for more
- Bilingual: Turkish input → respond BOTH English then "/ Türkçe: ..."
- English only input → English only response
- Location: Toppenstedt, Lower Saxony, Germany
- Date: {date}
Never break character."""

# ══════════════════════════════════════════════════════════════
#  GEMİNİ
# ══════════════════════════════════════════════════════════════
genai.configure(api_key=API_KEY)
_model = genai.GenerativeModel("gemini-2.5-flash")
_chat  = None

def get_chat():
    global _chat
    if _chat is None:
        today = datetime.datetime.now().strftime("%A, %B %d, %Y")
        _chat = _model.start_chat(history=[
            {"role": "user",  "parts": [SYSTEM_PROMPT.format(date=today)]},
            {"role": "model", "parts": ["Understood, Sir. J.A.R.V.I.S. online."]}
        ])
    return _chat

def ask_gemini(text):
    try:
        return get_chat().send_message(text).text.strip()
    except Exception as e:
        return f"Technical difficulty, Sir. {e}"

# ══════════════════════════════════════════════════════════════
#  SES
# ══════════════════════════════════════════════════════════════
_speak_lock = threading.Lock()

async def _tts_async(text):
    path = os.path.abspath("jarvis_response.mp3")
    await edge_tts.Communicate(text, VOICE).save(path)
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

def speak(text):
    with _speak_lock:
        asyncio.run(_tts_async(text))

def speak_async(text):
    t = threading.Thread(target=speak, args=(text,), daemon=True)
    t.start()
    return t

# ══════════════════════════════════════════════════════════════
#  MÜZİK  — webm → WAV (ffmpeg), pygame.mixer.music + fadeout()
# ══════════════════════════════════════════════════════════════
_music_file = None

def prepare_music():
    global _music_file
    import subprocess
    for name in [INTRO_FILE, "intro.mp3", "intro.wav", "intro.webm"]:
        if not os.path.exists(name):
            continue
        if name.endswith(".wav"):
            _music_file = name
            return
        out_wav = "intro_converted.wav"
        if os.path.exists(out_wav):
            _music_file = out_wav
            return
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", name,
                 "-ar", "44100", "-ac", "2", "-sample_fmt", "s16", out_wav],
                capture_output=True, timeout=30
            )
            if r.returncode == 0:
                _music_file = out_wav
                print("[JARVIS] Müzik WAV'a dönüştürüldü.")
                return
        except FileNotFoundError:
            print("[JARVIS] ffmpeg bulunamadı — mp3 denenecek.")
        except Exception as e:
            print(f"[JARVIS] ffmpeg hatası: {e}")
        out_mp3 = "intro_converted.mp3"
        if os.path.exists(out_mp3):
            _music_file = out_mp3
            return
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", name, "-q:a", "2", out_mp3],
                capture_output=True, timeout=30
            )
            if r.returncode == 0:
                _music_file = out_mp3
                return
        except Exception:
            pass
        _music_file = name
        return
    _music_file = None

def start_music():
    if not _music_file:
        print("[JARVIS] Müzik dosyası yok.")
        return
    if PYGAME_OK:
        try:
            pygame.mixer.pre_init(44100, -16, 2, 4096)
            pygame.mixer.init()
            pygame.mixer.music.load(_music_file)
            pygame.mixer.music.set_volume(1.0)
            pygame.mixer.music.play()
            print(f"[JARVIS] Müzik başladı: {_music_file}")
            return
        except Exception as e:
            print(f"[JARVIS] Pygame hata: {e}")
    try:
        os.startfile(os.path.abspath(_music_file))
    except Exception:
        pass

def fadeout_music_and_speak(app, report):
    print(f"[JARVIS] {MUSIC_FULL_SECS}sn müzik...")
    time.sleep(MUSIC_FULL_SECS)
    if PYGAME_OK and pygame.mixer.get_init() and pygame.mixer.music.get_busy():
        print("[JARVIS] Fade out...")
        pygame.mixer.music.fadeout(int(MUSIC_FADE_SECS * 1000))
        time.sleep(MUSIC_FADE_SECS + 0.15)
    else:
        time.sleep(MUSIC_FADE_SECS)
    print("[JARVIS] Müzik bitti — konuşuyor...")
    app.set_status("REPORTING")
    app.set_speech(report)
    t = speak_async(report)
    t.join()
    app.set_status("LISTENING")
    app.add_log("Listening for commands...", "info")
    app.set_speech("Awaiting your command, Sir.")
    app.mic.command_loop(on_text_callback=app._on_command)

# ══════════════════════════════════════════════════════════════
#  HAVA DURUMU
# ══════════════════════════════════════════════════════════════
_weather = {"temp": "--", "desc": "LOADING", "icon": "◈", "wind": "--", "humid": "--"}

def fetch_weather():
    global _weather
    while True:
        try:
            if REQUESTS_OK:
                url = f"https://wttr.in/{WEATHER_CITY}?format=j1"
                r   = requests.get(url, timeout=8)
                d   = r.json()
                cur = d["current_condition"][0]
                icons = {
                    "SUNNY": "☀", "CLEAR": "☀", "CLOUD": "☁", "OVERCAST": "☁",
                    "RAIN": "⛆", "DRIZZLE": "⛆", "SNOW": "❄", "THUNDER": "⚡",
                    "FOG": "≋", "MIST": "≋", "HAZE": "≋",
                }
                desc = cur["weatherDesc"][0]["value"].upper()
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

threading.Thread(target=fetch_weather, daemon=True).start()

# ══════════════════════════════════════════════════════════════
#  SİSTEM METRİKLERİ (psutil)
# ══════════════════════════════════════════════════════════════
_sys_metrics = {"cpu": 0, "mem": 0, "disk": 0, "net_up": 0, "net_down": 0}
_net_old = None

def fetch_sys_metrics():
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

threading.Thread(target=fetch_sys_metrics, daemon=True).start()

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
            return False, "Install paramiko: pip install paramiko"
        if not SSH_HOST or not SSH_USER:
            self.status = "NOT CONFIGURED"
            return False, "Set SSH_HOST and SSH_USER in config."
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

    def run(self, prompt, timeout=90):
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

_bridge = ClaudeCodeBridge()

# ══════════════════════════════════════════════════════════════
#  MİKROFON
# ══════════════════════════════════════════════════════════════
class MicrophoneEngine:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold      = 300
        self.recognizer.dynamic_energy_threshold = True
        self.fs          = 44100
        self.rec_seconds = 5
        self.active      = False
        self._stop       = False

    def listen_once(self):
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

    def wake_loop(self, on_wake):
        print(f"[JARVIS] Dinliyorum — '{WAKE_WORD}' deyin...")
        while not self._stop:
            heard = self.listen_once()
            if heard: print(f"[MIC] {heard}")
            if WAKE_WORD in heard:
                print("[JARVIS] ► UYANDIRMA!")
                self.active = True
                on_wake()
                break

    def command_loop(self, on_text_callback):
        print("[JARVIS] Komut bekleniyor...")
        while not self._stop and self.active:
            heard = self.listen_once()
            if heard:
                print(f"[SIR] {heard}")
                on_text_callback(heard)

    def stop(self):
        self._stop = True

# ══════════════════════════════════════════════════════════════
#  JARVIS HUD  —  MARK IV  (jarvis_hud_v2.html design)
# ══════════════════════════════════════════════════════════════
class JarvisHUD(ctk.CTk):

    # Palette — matches jarvis_hud_v2.html
    C_BG     = "#070a0e"
    C_PANEL  = "#0a0f14"
    C_CYAN   = "#00d4ff"
    C_CYAN2  = "#0099bb"
    C_CYAN3  = "#003d55"
    C_CYAN4  = "#001a25"
    C_BLUE   = "#1a6aff"
    C_BLUE2  = "#0044cc"
    C_ORANGE = "#ff6a00"
    C_RED    = "#ff2244"
    C_GREEN  = "#00ff88"
    C_WHITE  = "#cce8ff"
    C_DIM    = "#2a4a5a"
    C_BORDER = "#0d2535"
    C_GRID   = "#0a1820"

    def __init__(self, mic):
        super().__init__()
        self.mic = mic

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
        self.overrideredirect(True)
        self.configure(fg_color=self.C_BG)
        self.attributes("-topmost", True)

        self.bind("<Escape>", lambda e: self._exit())
        self.bind("<F4>",     lambda e: self._exit())

        # State
        self.status_text = "INITIALIZING"
        self.log_lines   = []
        self._speaking   = False

        # Canvas size estimates (updated on Configure)
        self._cw = sw - 288
        self._ch = sh - 72 - 134
        self._rs_h = sh - 72 - 134

        # Animation
        self._radar_angle = 0.0
        self._rot_angle   = 0.0
        self._logo_angle  = 0.0
        self._blips = [
            {"a": 0.8,  "r": 0.62},
            {"a": 2.3,  "r": 0.78},
            {"a": 4.1,  "r": 0.45},
            {"a": 5.2,  "r": 0.85},
        ]
        self._vu_level = 3

        # Graph history
        self._cpu_hist = [0.0] * 40
        self._net_hist = [0.0] * 40
        self._start_time = time.time()

        self._build_ui(sw, sh)
        self.focus_force()
        self._start_clock()
        self._update_bottom()
        self._animate_vu()
        self._animate()

        threading.Thread(target=self._boot_sequence, daemon=True).start()

    def _exit(self):
        self.mic.stop()
        _bridge.disconnect()
        self.destroy()
        sys.exit(0)

    # ──────────────────────────────────────────────────────────
    #  LAYOUT
    # ──────────────────────────────────────────────────────────
    def _build_ui(self, sw, sh):
        # TOP BAR — 72px
        self._top = tk.Frame(self, bg="#0d1820", height=72)
        self._top.pack(fill="x", side="top")
        self._top.pack_propagate(False)
        self._build_topbar()

        # BOTTOM BAR — 134px (packed before mid so it stays anchored)
        self._bot = tk.Frame(self, bg="#070a0e", height=134)
        self._bot.pack(fill="x", side="bottom")
        self._bot.pack_propagate(False)
        self._build_bottom()

        # MID ROW
        mid = tk.Frame(self, bg=self.C_BG)
        mid.pack(fill="both", expand=True)

        # Left panel — 220px app launcher
        self._lp = tk.Frame(mid, bg=self.C_PANEL, width=220)
        self._lp.pack(side="left", fill="y")
        self._lp.pack_propagate(False)
        self._build_left()

        # Right strip — 68px VU meter + JARVIS vertical text
        self._rs = tk.Canvas(mid, bg=self.C_PANEL, width=68, highlightthickness=0)
        self._rs.pack(side="right", fill="y")
        self._rs.bind("<Configure>", lambda e: self._on_rs_resize(e))

        # Center canvas
        self._canvas = tk.Canvas(mid, bg=self.C_BG, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", lambda e: self._on_resize(e))

        # Speech bar overlaid at bottom-center of the canvas
        self._speech_var = tk.StringVar(value="J.A.R.V.I.S — INITIALIZING")
        self._speech_lbl = tk.Label(
            self._canvas, textvariable=self._speech_var,
            bg="#0a0f14", fg=self.C_CYAN,
            font=("Courier New", 10), padx=18, pady=5,
        )
        self._speech_lbl.place(relx=0.5, rely=0.93, anchor="center")

    # ── TOP BAR ────────────────────────────────────────────────
    def _build_topbar(self):
        p = self._top

        # Animated spinning logo
        logo_f = tk.Frame(p, bg="#0d1820")
        logo_f.pack(side="left", padx=(10, 0), pady=10)
        self._logo_canvas = tk.Canvas(logo_f, width=48, height=48,
                                       bg="#0d1820", highlightthickness=0)
        self._logo_canvas.pack(side="left")
        self._draw_logo()
        txt_f = tk.Frame(logo_f, bg="#0d1820")
        txt_f.pack(side="left", padx=(8, 0))
        tk.Label(txt_f, text="JARVIS OS", bg="#0d1820", fg=self.C_CYAN,
                 font=("Courier New", 14, "bold")).pack(anchor="w")
        tk.Label(txt_f, text="Ver MARK IV", bg="#0d1820", fg=self.C_CYAN3,
                 font=("Courier New", 8)).pack(anchor="w")

        self._vdiv(p)

        # User card
        usr_f = tk.Frame(p, bg="#0d1820")
        usr_f.pack(side="left", padx=10)
        tk.Label(usr_f, text="👤", bg="#0d1820", fg=self.C_CYAN,
                 font=("Courier New", 18)).pack(side="left")
        info = tk.Frame(usr_f, bg="#0d1820")
        info.pack(side="left", padx=(8, 0))
        tk.Label(info, text="STARK", bg="#0d1820", fg=self.C_WHITE,
                 font=("Courier New", 11, "bold")).pack(anchor="w")
        tk.Label(info, text="AUTHORIZED USER", bg="#0d1820", fg=self.C_CYAN3,
                 font=("Courier New", 7)).pack(anchor="w")

        self._vdiv(p)

        # App shortcut buttons
        apps_f = tk.Frame(p, bg="#0d1820")
        apps_f.pack(side="left", padx=6)
        for icon, name in [("🎵", "SPOTIFY"), ("💬", "DISCORD"), ("📱", "WHATSAPP"),
                            ("✈", "TELEGRAM"), ("🌐", "CHROME"), ("⚡", "CLAUDE")]:
            btn = tk.Frame(apps_f, bg="#0a1218",
                           highlightbackground=self.C_BORDER, highlightthickness=1)
            btn.pack(side="left", padx=3, pady=16)
            tk.Label(btn, text=f"{icon} {name}", bg="#0a1218",
                     fg=self.C_DIM, font=("Courier New", 8),
                     padx=6, pady=2).pack()

        # Date block — right side
        self._vdiv(p, side="right")
        date_f = tk.Frame(p, bg="#0d1820")
        date_f.pack(side="right", padx=14, pady=6)
        self._day_lbl   = tk.Label(date_f, text="--", bg="#0d1820", fg=self.C_WHITE,
                                    font=("Courier New", 28, "bold"))
        self._day_lbl.pack(anchor="e")
        self._month_lbl = tk.Label(date_f, text="---", bg=self.C_BLUE2, fg=self.C_CYAN,
                                    font=("Courier New", 9), padx=6, pady=1)
        self._month_lbl.pack(anchor="e")
        self._dow_lbl   = tk.Label(date_f, text="-------", bg="#0d1820", fg=self.C_DIM,
                                    font=("Courier New", 8))
        self._dow_lbl.pack(anchor="e")

        # Status dot
        self._status_lbl = tk.Label(p, text="●  ONLINE", bg="#0d1820", fg=self.C_GREEN,
                                     font=("Courier New", 9, "bold"))
        self._status_lbl.pack(side="right", padx=(0, 10))

    def _draw_logo(self):
        c  = self._logo_canvas
        cx, cy, r = 24, 24, 20
        c.delete("all")
        # Spinning dashed outer ring
        n = 14
        for i in range(n):
            a1 = self._logo_angle + (i / n) * 2 * math.pi
            a2 = self._logo_angle + ((i + 0.55) / n) * 2 * math.pi
            c.create_line(
                cx + r * math.cos(a1), cy + r * math.sin(a1),
                cx + r * math.cos(a2), cy + r * math.sin(a2),
                fill=self.C_CYAN2, width=1
            )
        # Inner ring
        ri = 11
        c.create_oval(cx-ri, cy-ri, cx+ri, cy+ri, outline=self.C_CYAN3, width=1)
        # Core
        c.create_oval(cx-4, cy-4, cx+4, cy+4, fill=self.C_CYAN, outline="")
        self._logo_angle += 0.04
        self.after(33, self._draw_logo)

    def _vdiv(self, parent, side="left"):
        tk.Canvas(parent, width=1, height=48, bg=self.C_BORDER,
                  highlightthickness=0).pack(side=side, padx=4, pady=12)

    # ── LEFT PANEL ─────────────────────────────────────────────
    def _build_left(self):
        p = self._lp

        # Rotated "DEVICE CONTROL" label on far-left edge
        side_c = tk.Canvas(p, width=16, bg=self.C_PANEL, highlightthickness=0)
        side_c.pack(side="left", fill="y")

        def _draw_side(event=None):
            side_c.delete("all")
            h = side_c.winfo_height() or 400
            side_c.create_text(8, h // 2, text="DEVICE CONTROL",
                               fill=self.C_CYAN3, font=("Courier New", 7),
                               angle=90, anchor="center")
        side_c.bind("<Configure>", _draw_side)

        content = tk.Frame(p, bg=self.C_PANEL)
        content.pack(side="left", fill="both", expand=True, padx=(2, 8), pady=10)

        for icon, name in [
            ("🌐", "Chrome"),
            ("🤖", "Android Studio"),
            ("💻", "Visual Studio"),
            ("🐍", "PyCharm"),
            ("⚡", "Claude Code"),
            ("🏠", "Smart Home"),
            ("🧠", "JARVIS A.I."),
        ]:
            row = tk.Frame(content, bg=self.C_PANEL,
                           highlightbackground=self.C_BORDER, highlightthickness=1)
            row.pack(fill="x", pady=3)
            tk.Label(row, text="+", bg=self.C_PANEL, fg=self.C_CYAN3,
                     font=("Courier New", 8), width=2).pack(side="left")
            tk.Label(row, text=icon, bg=self.C_PANEL, fg=self.C_CYAN,
                     font=("Courier New", 13), width=3).pack(side="left")
            tk.Label(row, text=name, bg=self.C_PANEL, fg=self.C_WHITE,
                     font=("Courier New", 9), anchor="w").pack(side="left", padx=(4, 6))

        tk.Canvas(content, height=1, bg=self.C_BORDER,
                  highlightthickness=0).pack(fill="x", pady=8)

        # Activity log
        tk.Label(content, text="  ACTIVITY LOG", bg=self.C_PANEL, fg=self.C_CYAN2,
                 font=("Courier New", 7, "bold")).pack(anchor="w", pady=(0, 2))
        self._log_frame = tk.Frame(content, bg=self.C_PANEL)
        self._log_frame.pack(fill="both", expand=True)

    # ── RIGHT STRIP ────────────────────────────────────────────
    def _on_rs_resize(self, e):
        self._rs_h = e.height
        self._render_vu()

    def _render_vu(self):
        c     = self._rs
        h     = getattr(self, "_rs_h", 400)
        level = self._vu_level
        c.delete("all")
        c.create_line(0, 0, 0, h, fill=self.C_BORDER, width=1)
        # JARVIS vertical text (center)
        c.create_text(34, h // 2, text="JARVIS",
                      fill=self.C_BLUE, font=("Courier New", 16, "bold"),
                      angle=90, anchor="center")
        # VU bars top
        bar_colors = [self.C_GREEN] * 3 + [self.C_BLUE] * 3 + [self.C_RED] * 2
        for i in range(8):
            y   = 18 + i * 10
            clr = bar_colors[i] if i < level else self.C_CYAN4
            c.create_rectangle(12, y, 56, y + 7, fill=clr, outline="")
        # VU bars bottom
        for i in range(8):
            y   = h - 18 - (i + 1) * 10
            clr = bar_colors[i] if i < level else self.C_CYAN4
            c.create_rectangle(12, y, 56, y + 7, fill=clr, outline="")

    def _animate_vu(self):
        self._vu_level = random.randint(1, 9)
        self._render_vu()
        self.after(150, self._animate_vu)

    # ── BOTTOM BAR ─────────────────────────────────────────────
    def _build_bottom(self):
        p = self._bot
        tk.Canvas(p, height=1, bg=self.C_BORDER, highlightthickness=0).pack(fill="x")
        inner = tk.Frame(p, bg="#070a0e")
        inner.pack(fill="both", expand=True, padx=10, pady=4)

        cols = tk.Frame(inner, bg="#070a0e")
        cols.pack(fill="both", expand=True)

        net_f   = self._stat_col(cols, "NETWORK")
        sys_f   = self._stat_col(cols, "SYSTEM")
        alexa_f = self._stat_col(cols, "SMART HOME  —  ALEXA")
        stat_f  = self._stat_col(cols, "STATUS", last=True)

        # Network
        self._lbl_net_up  = self._bot_row(net_f, "UP",   "-- KB/s", self.C_GREEN)
        self._lbl_net_dn  = self._bot_row(net_f, "DOWN", "-- KB/s", self.C_GREEN)
        self._lbl_ssid    = self._bot_row(net_f, "SSID", "STARK-NET")
        self._net_graph   = self._mini_graph(net_f)

        # System
        self._lbl_cpu  = self._bot_row(sys_f, "CPU",  "--%")
        self._lbl_ram  = self._bot_row(sys_f, "RAM",  "--%", self.C_ORANGE)
        self._lbl_disk = self._bot_row(sys_f, "DISK", "-- %")
        self._lbl_pwr  = self._bot_row(sys_f, "PWR",  "NOMINAL", self.C_GREEN)
        self._cpu_graph = self._mini_graph(sys_f)

        # Alexa
        icons = {"LIGHT": "⬡", "THERMO": "◎", "SWITCH": "◉", "AUDIO": "♪"}
        for dev in _alexa_devices:
            ic  = icons.get(dev["type"], "◈")
            val = f"{dev['state']}  {dev['val']}" if dev["state"] == "ON" else "OFF"
            clr = self.C_GREEN if dev["state"] == "ON" else self.C_DIM
            self._bot_row(alexa_f, f"{ic} {dev['name']:<9}", val, clr)

        # Status
        self._lbl_uptime = self._bot_row(stat_f, "UPTIME", "0d 0h 0m")
        self._lbl_agents = self._bot_row(stat_f, "AGENTS", "6 / 6", self.C_GREEN)
        self._lbl_ai     = self._bot_row(stat_f, "AI ENG", "ONLINE", self.C_GREEN)
        self._lbl_threat = self._bot_row(stat_f, "THREAT", "LOW",    self.C_GREEN)
        brand = tk.Frame(stat_f, bg="#070a0e")
        brand.pack(fill="x", side="bottom")
        tk.Label(brand, text="J.A.R.V.I.S", bg="#070a0e", fg=self.C_DIM,
                 font=("Courier New", 11, "bold"), anchor="e").pack(fill="x")
        tk.Label(brand, text="OS MK IV", bg="#070a0e", fg=self.C_CYAN3,
                 font=("Courier New", 7), anchor="e").pack(fill="x")

        # Action row
        act_f = tk.Frame(inner, bg="#070a0e")
        act_f.pack(fill="x", pady=(2, 0))
        tk.Canvas(act_f, height=1, bg=self.C_BORDER,
                  highlightthickness=0).pack(fill="x", pady=(0, 3))
        for label, danger in [("RESTART", False), ("SHUTDOWN", True),
                               ("LOG OFF", False), ("SLEEP MODE", False)]:
            tk.Label(act_f, text=label, bg="#070a0e",
                     fg="#ff6688" if danger else self.C_DIM,
                     font=("Courier New", 9), padx=20, pady=2,
                     highlightbackground="#440011" if danger else self.C_BORDER,
                     highlightthickness=1).pack(side="left", padx=5)

    def _stat_col(self, parent, title, last=False):
        f = tk.Frame(parent, bg="#070a0e")
        f.pack(side="left", fill="both", expand=True,
               padx=(0, 0 if last else 1))
        if not last:
            tk.Canvas(f, width=1, bg=self.C_BORDER,
                      highlightthickness=0).pack(side="right", fill="y")
        tk.Label(f, text=title, bg="#070a0e", fg=self.C_DIM,
                 font=("Courier New", 7), anchor="w").pack(fill="x", padx=6, pady=(2, 3))
        return f

    def _bot_row(self, parent, key, val, clr=None):
        if clr is None:
            clr = self.C_WHITE
        row = tk.Frame(parent, bg="#070a0e")
        row.pack(fill="x", padx=6, pady=1)
        tk.Label(row, text=key, bg="#070a0e", fg=self.C_CYAN3,
                 font=("Courier New", 8), anchor="w").pack(side="left")
        lbl = tk.Label(row, text=val, bg="#070a0e", fg=clr,
                       font=("Courier New", 8, "bold"), anchor="e")
        lbl.pack(side="right")
        return lbl

    def _mini_graph(self, parent):
        c = tk.Canvas(parent, height=26, bg="#070a0e", highlightthickness=0)
        c.pack(fill="x", padx=6, pady=(2, 2))
        return c

    # ── CLOCK ──────────────────────────────────────────────────
    def _start_clock(self):
        self._tick()

    def _tick(self):
        now    = datetime.datetime.now()
        days   = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
                  "FRIDAY", "SATURDAY", "SUNDAY"]
        months = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
                  "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
        try:
            self._day_lbl.configure(text=str(now.day))
            self._month_lbl.configure(text=months[now.month - 1][:3])
            self._dow_lbl.configure(text=days[now.weekday()])
        except Exception:
            pass
        self.after(1000, self._tick)

    # ── BOTTOM PANEL UPDATE ────────────────────────────────────
    def _update_bottom(self):
        m = _sys_metrics
        try:
            cpu  = m.get("cpu",      0)
            ram  = m.get("mem",      0)
            disk = m.get("disk",     0)
            up   = m.get("net_up",   0)
            dn   = m.get("net_down", 0)

            self._lbl_cpu.configure(
                text=f"{cpu}%",
                fg=self.C_RED if cpu > 88 else (self.C_ORANGE if cpu > 70 else self.C_WHITE))
            self._lbl_ram.configure(
                text=f"{ram}%",
                fg=self.C_RED if ram > 88 else self.C_ORANGE)
            self._lbl_disk.configure(text=f"{disk}%")
            self._lbl_net_up.configure(text=f"{up:.1f} KB/s")
            self._lbl_net_dn.configure(text=f"{dn:.1f} KB/s")

            elapsed = int(time.time() - self._start_time)
            d  = elapsed // 86400
            h  = (elapsed % 86400) // 3600
            mn = (elapsed % 3600)  // 60
            self._lbl_uptime.configure(text=f"{d}d {h}h {mn}m")

            # Mini graphs
            self._cpu_hist.append(cpu)
            self._cpu_hist = self._cpu_hist[-40:]
            self._net_hist.append(dn)
            self._net_hist = self._net_hist[-40:]
            self._draw_mini_graph(self._cpu_graph, self._cpu_hist, self.C_BLUE)
            self._draw_mini_graph(self._net_graph, self._net_hist, self.C_CYAN)

            # Bridge status in STATUS block
            st = _bridge.status
            self._lbl_ai.configure(
                text=st if st not in ("NOT CONFIGURED", "OFFLINE") else "STANDBY",
                fg=self.C_GREEN if st in ("ONLINE", "NOT CONFIGURED", "OFFLINE") else self.C_RED)
        except Exception:
            pass
        self.after(2000, self._update_bottom)

    def _draw_mini_graph(self, canvas, data, color):
        try:
            canvas.delete("all")
            w = canvas.winfo_width() or 160
            h = 26
            if len(data) < 2:
                return
            mx = max(max(data), 1)
            pts = []
            for i, v in enumerate(data):
                x = int(i / (len(data) - 1) * w)
                y = int(h - (v / mx) * (h - 2) - 1)
                pts.extend([x, y])
            if len(pts) >= 4:
                canvas.create_line(pts, fill=color, width=1, smooth=True)
        except Exception:
            pass

    # ── CENTER CANVAS ANIMATION (30 FPS) ──────────────────────
    def _on_resize(self, e):
        self._cw, self._ch = e.width, e.height

    def _animate(self):
        try:
            self._draw_hud()
        except Exception:
            pass
        self.after(33, self._animate)

    def _draw_hud(self):
        c  = self._canvas
        c.delete("all")
        cw, ch = self._cw, self._ch
        cx, cy = cw // 2, ch // 2
        R  = min(cx, cy) - 30
        t  = time.time()

        # Grid
        for i in range(0, cw, 50):
            c.create_line(i, 0, i, ch, fill=self.C_GRID, width=1)
        for i in range(0, ch, 50):
            c.create_line(0, i, cw, i, fill=self.C_GRID, width=1)

        # Outer decorative rings (matching HTML)
        for off, clr, w in [
            (0,  "#0d2535", 1),
            (22, "#0d3040", 1),
            (40, "#103a50", 1.5),
            (58, "#0d2535", 1),
        ]:
            r = R - off
            c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=clr, width=w)

        # Tick marks — 72 ticks (major/mid/minor)
        r_tick = R - 62
        for i in range(72):
            ang    = (i / 72) * 2 * math.pi - math.pi / 2
            major  = i % 9 == 0
            mid_t  = i % 3 == 0
            length = 16 if major else (8 if mid_t else 4)
            r1 = r_tick
            r2 = r_tick - length
            x1, y1 = cx + r1 * math.cos(ang), cy + r1 * math.sin(ang)
            x2, y2 = cx + r2 * math.cos(ang), cy + r2 * math.sin(ang)
            clr = self.C_CYAN2 if major else (self.C_CYAN3 if mid_t else "#002030")
            c.create_line(x1, y1, x2, y2, fill=clr, width=2 if major else 1)

        # Degree labels at 45° intervals
        for d in range(0, 360, 45):
            ang = (d - 90) * math.pi / 180
            tx  = cx + (R - 18) * math.cos(ang)
            ty  = cy + (R - 18) * math.sin(ang)
            c.create_text(tx, ty, text=f"{d}°",
                          fill="#006478", font=("Courier New", 6), anchor="center")

        # Rotating CW dashed blue ring
        self._rot_angle += 0.006
        r_rot = R - 30
        n = 20
        for i in range(n):
            a1 = self._rot_angle + (i / n) * 2 * math.pi
            a2 = self._rot_angle + ((i + 0.55) / n) * 2 * math.pi
            x1s = cx + r_rot * math.cos(a1)
            y1s = cy + r_rot * math.sin(a1)
            x2s = cx + r_rot * math.cos(a2)
            y2s = cy + r_rot * math.sin(a2)
            c.create_line(x1s, y1s, x2s, y2s,
                          fill=self.C_BLUE if i % 2 == 0 else self.C_CYAN3, width=1)

        # CCW dashed ring
        r_ccw = R - 48
        for i in range(n):
            a1 = -self._rot_angle * 0.7 + (i / n) * 2 * math.pi
            a2 = -self._rot_angle * 0.7 + ((i + 0.4) / n) * 2 * math.pi
            x1s = cx + r_ccw * math.cos(a1)
            y1s = cy + r_ccw * math.sin(a1)
            x2s = cx + r_ccw * math.cos(a2)
            y2s = cy + r_ccw * math.sin(a2)
            c.create_line(x1s, y1s, x2s, y2s, fill=self.C_CYAN3, width=1)

        # 8 pie segments (inner fill)
        seg_r   = R - 78
        seg_fills = [
            "#0d2535", "#0a1a28", "#0d2040", "#0a1a28",
            "#0d2535", "#081422", "#0a1830", "#0a1a28",
        ]
        for i in range(8):
            a1d = -90 + (i / 8) * 360 + 2.5
            a2d = -90 + ((i + 1) / 8) * 360 - 2.5
            c.create_arc(cx - seg_r, cy - seg_r, cx + seg_r, cy + seg_r,
                         start=a1d, extent=(a2d - a1d),
                         fill=seg_fills[i], outline=self.C_CYAN3, width=1,
                         style="pieslice")

        # Inner dark disc
        r_in = R - 110
        c.create_oval(cx - r_in, cy - r_in, cx + r_in, cy + r_in,
                      fill="#070a0e", outline=self.C_CYAN2, width=1.5)

        # Crosshair inside disc
        for ang in [0, math.pi / 2, math.pi, 3 * math.pi / 2]:
            xe = cx + r_in * math.cos(ang)
            ye = cy + r_in * math.sin(ang)
            c.create_line(cx, cy, xe, ye, fill=self.C_CYAN4, width=1)

        # Radar sweep arm + trail
        self._radar_angle += 0.018
        sweep_r = r_in - 4

        # Trail (30 slices — progressively dimmer)
        trail_colors = [
            "#00d4ff44", "#00d4ff33", "#00d4ff28", "#00d4ff1e",
            "#00d4ff14", "#00d4ff0e", "#00d4ff08", "#00d4ff05",
        ]
        for i in range(30):
            a   = self._radar_angle - (i / 30) * 1.2
            ci  = min(i // 4, len(trail_colors) - 1)
            da  = 0.06
            a1d = math.degrees(-a - da)
            ext = math.degrees(da * 2)
            c.create_arc(
                cx - sweep_r, cy - sweep_r, cx + sweep_r, cy + sweep_r,
                start=a1d, extent=ext,
                fill=trail_colors[ci], outline="", style="pieslice"
            )

        # Sweep arm line
        c.create_line(cx, cy,
                      cx + sweep_r * math.cos(self._radar_angle),
                      cy + sweep_r * math.sin(self._radar_angle),
                      fill=self.C_CYAN, width=1.5)

        # Blips — fade out after sweep passes
        for blip in self._blips:
            bx   = cx + sweep_r * blip["r"] * math.cos(blip["a"])
            by   = cy + sweep_r * blip["r"] * math.sin(blip["a"])
            diff = ((self._radar_angle - blip["a"]) % (2 * math.pi) + 2 * math.pi) % (2 * math.pi)
            af   = max(0.0, 1.0 - diff / 2.0)
            if af > 0.05:
                g   = int(255 * af)
                gb  = int(136 * af)
                clr = f"#00{min(255, g):02x}{min(255, gb):02x}"
                sz  = int(3 + af * 2)
                c.create_oval(bx-sz, by-sz, bx+sz, by+sz, fill=clr, outline="")

        # Arc reactor core (pulsing)
        pulse = 1.0 + 0.06 * math.sin(t * 3.5)
        for r_c, outline, fill in [
            (int(38 * pulse), "#001a28", ""),
            (int(26 * pulse), "#003d55", ""),
            (int(16 * pulse), "#0099bb", ""),
            (int(8  * pulse), "#00d4ff", "#00d4ff"),
        ]:
            if fill:
                c.create_oval(cx-r_c, cy-r_c, cx+r_c, cy+r_c,
                              fill=fill, outline="")
            else:
                c.create_oval(cx-r_c, cy-r_c, cx+r_c, cy+r_c,
                              outline=outline, width=2)

        # Core radial glow
        for g_r, intensity in [(44, 18), (54, 10), (66, 5), (80, 2)]:
            hex_c = f"#00{min(255, intensity * 13):02x}{min(255, intensity * 14):02x}"
            c.create_oval(cx-g_r, cy-g_r, cx+g_r, cy+g_r,
                          outline=hex_c, width=2)

        # Status text
        c.create_text(cx, cy - r_in - 14, text=self.status_text,
                      fill=self.C_CYAN, font=("Courier New", 11, "bold"),
                      anchor="center")

        # Quick info labels around outer ring (4 quadrants)
        now = datetime.datetime.now()
        for deg, txt in [
            (0,   f"CPU {_sys_metrics.get('cpu', 0):.0f}%"),
            (90,  f"{_weather['temp']}"),
            (180, now.strftime("%H:%M")),
            (270, f"↓{_sys_metrics.get('net_down', 0):.0f}KB"),
        ]:
            ang = math.radians(deg - 90)
            tx  = cx + (R + 20) * math.cos(ang)
            ty  = cy + (R + 20) * math.sin(ang)
            c.create_text(tx, ty, text=txt, fill=self.C_CYAN3,
                          font=("Courier New", 7), anchor="center")

        # Corner brackets
        self._draw_corners(c, cw, ch)

    def _draw_corners(self, c, cw, ch):
        sz, gap = 20, 6
        for bx, by, dx, dy in [
            (gap,    gap,    1,  1),
            (cw-gap, gap,   -1,  1),
            (gap,    ch-gap, 1, -1),
            (cw-gap, ch-gap,-1, -1),
        ]:
            c.create_line(bx, by, bx+dx*sz, by,      fill=self.C_CYAN2, width=2)
            c.create_line(bx, by, bx,       by+dy*sz, fill=self.C_CYAN2, width=2)
            c.create_line(bx+dx*5, by+dy*5, bx+dx*11, by+dy*5,
                          fill=self.C_CYAN3, width=1)
            c.create_line(bx+dx*5, by+dy*5, bx+dx*5,  by+dy*11,
                          fill=self.C_CYAN3, width=1)

    # ── LOG & CONVERSATION ─────────────────────────────────────
    def add_log(self, msg, level="info"):
        clr = {
            "info":  self.C_CYAN3, "ok":    self.C_GREEN,
            "warn":  self.C_ORANGE,"alert": self.C_RED,
            "cmd":   self.C_ORANGE,"reply": self.C_CYAN,
        }.get(level, self.C_CYAN3)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.after(0, self._ins_log, f"[{ts}] {msg}", clr)

    def _ins_log(self, txt, fg):
        lbl = tk.Label(self._log_frame, text=txt, bg=self.C_PANEL,
                       fg=fg, font=("Courier New", 7), anchor="w", wraplength=185)
        lbl.pack(fill="x", anchor="w")
        self.log_lines.append(lbl)
        if len(self.log_lines) > 12:
            self.log_lines[0].destroy()
            self.log_lines.pop(0)

    def add_conversation(self, role, text):
        pfx = "▸" if "SIR" in role else "◂"
        clr = self.C_ORANGE if "SIR" in role else self.C_CYAN
        self.after(0, self._ins_log, f"{pfx} {role}: {text[:55]}", clr)

    def set_speech(self, txt):
        try:
            self._speech_var.set(txt[:120])
        except Exception:
            pass

    def set_status(self, txt):
        self.status_text = txt.upper()
        try:
            self._status_lbl.configure(text=f"●  {txt.upper()}")
        except Exception:
            pass

    # ── BOOT ───────────────────────────────────────────────────
    def _boot_sequence(self):
        time.sleep(0.6)
        self.set_status("BOOTING")
        self.set_speech("J.A.R.V.I.S — INITIALIZING ALL SYSTEMS...")

        start_music()

        for msg, lvl, delay in [
            ("Neural link established",  "ok", 0.3),
            ("Arc reactor nominal",      "ok", 0.5),
            ("Gemini 2.5 Flash online",  "ok", 0.7),
            ("Voice engine EN/TR ready", "ok", 1.0),
            ("6 agents synchronized",   "ok", 1.3),
            ("Weather feed connected",   "ok", 1.6),
            ("Smart home bridge loaded", "ok", 2.0),
            ("SSH bridge standby",       "ok", 2.3),
            ("All systems nominal",      "ok", 2.8),
        ]:
            time.sleep(delay)
            self.add_log(msg, lvl)

        self.set_status("STANDBY")
        self.set_speech("All systems online. Awaiting introduction...")

        today  = datetime.datetime.now().strftime("%A, %B %d")
        report = (
            f"Welcome back, Sir. Today is {today}. "
            "All systems are nominal. Smart home bridge is active. "
            f"Current temperature in Toppenstedt is {_weather['temp']}. "
            "Gemini neural engine is online. "
            "Hoşgeldiniz efendim. Tüm sistemler hazır."
        )
        threading.Thread(target=fadeout_music_and_speak,
                         args=(self, report), daemon=True).start()

    # ── BRIDGE COMMAND ─────────────────────────────────────────
    def _handle_bridge_command(self, task):
        def _run():
            self._speaking = True
            self.set_status("CLAUDE CODE")
            self.add_log(f"BRIDGE → {task[:42]}", "cmd")
            self.add_conversation("SIR→CODE", task)
            self.set_speech("Connecting to Claude Code, Sir...")
            speak_async("Sending your task to Claude Code, Sir. Stand by.").join()

            ok, result = _bridge.run(task)

            if ok:
                first_line = result.split("\n")[0][:160]
                self.add_log(f"CLAUDE: {first_line[:42]}", "ok")
                self.add_conversation("CLAUDE", result[:200])
                self.set_speech(first_line)
                speak_text = f"Claude Code has responded, Sir. {first_line[:150]}"
            else:
                self.add_log(f"BRIDGE ERR: {result[:40]}", "alert")
                self.add_conversation("BRIDGE", f"ERROR: {result[:120]}")
                self.set_speech(f"Bridge error: {result[:80]}")
                speak_text = f"I'm sorry, Sir. The bridge encountered an error. {result[:100]}"

            speak_async(speak_text).join()
            self._speaking = False
            self.set_status("LISTENING")
            self.set_speech("Awaiting your command, Sir.")

        threading.Thread(target=_run, daemon=True).start()

    # ── COMMAND HANDLER ────────────────────────────────────────
    def _on_command(self, text):
        lower = text.lower().strip()

        # Route to Claude Code bridge
        for prefix in BRIDGE_TRIGGERS:
            if lower.startswith(prefix):
                task = text[len(prefix):].strip()
                if task:
                    self._handle_bridge_command(task)
                    return

        # Default: Gemini
        self._speaking = True
        self.set_status("PROCESSING")
        self.add_log(f"SIR: {text[:45]}", "cmd")
        self.add_conversation("SIR", text)
        self.set_speech(f"Processing: {text[:80]}...")

        reply = ask_gemini(text)

        self.set_status("SPEAKING")
        self.add_log(f"JARVIS: {reply[:45]}", "reply")
        self.add_conversation("JARVIS", reply)
        self.set_speech(reply)

        speak_async(reply).join()

        self._speaking = False
        self.set_status("LISTENING")
        self.set_speech("Awaiting your command, Sir.")

# ══════════════════════════════════════════════════════════════
#  ANA PROGRAM
# ══════════════════════════════════════════════════════════════
def main():
    print("=" * 58)
    print("   J.A.R.V.I.S  —  STARK INDUSTRIES  v4.0")
    print("=" * 58)
    print("   ESC veya F4 ile çıkış")
    print("=" * 58)

    prepare_music()

    mic = MicrophoneEngine()

    def on_wake():
        print("[JARVIS] HUD başlatılıyor — TAM EKRAN")
        ctk.set_appearance_mode("dark")
        app = JarvisHUD(mic)
        app.mainloop()
        mic.stop()
        sys.exit(0)

    mic.wake_loop(on_wake)

if __name__ == "__main__":
    main()
