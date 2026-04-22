"""
╔══════════════════════════════════════════════════════════════╗
║          J.A.R.V.I.S  —  STARK INDUSTRIES  v4.0             ║
║                                                              ║
║  ► Tam ekran HUD (masaüstünü kaplar)                        ║
║  ► Gerçek CPU/RAM/Ağ verisi (psutil)                        ║
║  ► Hava durumu (wttr.in API, Toppenstedt)                   ║
║  ► Alexa cihaz paneli (placeholder — hazır altyapı)         ║
║  ► Takvim / hatırlatıcı widget                              ║
║  ► Müzik webm→mp3 dönüşüm + smooth fade                    ║
║  ► Dönen wireframe küre merkez                              ║
╚══════════════════════════════════════════════════════════════╝

EK KURULUM:
    py -m pip install psutil requests
"""

import os, sys, asyncio, datetime, threading, math, time, queue, random, json
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
API_KEY         = "AIzaSyDJwDlO0pWBrHh00AFM_KfcioOBiMUDjOE"
VOICE           = "en-GB-RyanNeural"
INTRO_FILE      = "intro.webm"
WAKE_WORD       = "wake up"
LANGUAGE        = "en-US"
MUSIC_FULL_SECS = 20
MUSIC_FADE_SECS = 3
WEATHER_CITY    = "Toppenstedt"

# ── SSH / Claude Code bridge ────────────────────────────────
SSH_HOST     = "192.168.178.22"
SSH_PORT     = 22
SSH_USER     = "Gökay"
SSH_KEY_PATH = ""
SSH_PASSWORD = "1208Gy1980"
SSH_CLAUDE   = "C:\\Users\\Gökay\\AppData\\Roaming\\npm\\claude.cmd"

# Voice prefixes that route to Claude Code instead of Gemini
# (speech recognition won't produce punctuation, so no colons)
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
            {"role":"user",  "parts":[SYSTEM_PROMPT.format(date=today)]},
            {"role":"model", "parts":["Understood, Sir. J.A.R.V.I.S. online."]}
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
_music_file = None   # path to the playable audio file

def prepare_music():
    """Convert intro.webm → WAV via ffmpeg for reliable pygame playback.
    Falls back to mp3 then raw source if ffmpeg is unavailable."""
    global _music_file
    import subprocess

    for name in [INTRO_FILE, "intro.mp3", "intro.wav", "intro.webm"]:
        if not os.path.exists(name):
            continue

        if name.endswith(".wav"):
            _music_file = name
            return

        # Prefer WAV — pygame.mixer handles it perfectly for smooth fadeout
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

        # ffmpeg failed — try mp3 fallback
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
                print("[JARVIS] Müzik mp3'e dönüştürüldü.")
                return
        except Exception:
            pass

        # Last resort: play source file directly (webm may work on some setups)
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
    """Full-volume playback → smooth pygame fadeout → Jarvis speaks."""
    print(f"[JARVIS] {MUSIC_FULL_SECS}sn müzik...")
    time.sleep(MUSIC_FULL_SECS)

    if PYGAME_OK and pygame.mixer.get_init() and pygame.mixer.music.get_busy():
        print("[JARVIS] Fade out...")
        pygame.mixer.music.fadeout(int(MUSIC_FADE_SECS * 1000))
        time.sleep(MUSIC_FADE_SECS + 0.15)   # wait for fadeout to finish
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
_weather = {"temp":"--","desc":"LOADING","icon":"◈","wind":"--","humid":"--"}

def fetch_weather():
    global _weather
    while True:
        try:
            if REQUESTS_OK:
                url = f"https://wttr.in/{WEATHER_CITY}?format=j1"
                r = requests.get(url, timeout=8)
                d = r.json()
                cur = d["current_condition"][0]
                temp   = cur["temp_C"]
                desc   = cur["weatherDesc"][0]["value"].upper()
                wind   = cur["windspeedKmph"]
                humid  = cur["humidity"]
                icons  = {
                    "SUNNY":"☀","CLEAR":"☀","CLOUD":"☁","OVERCAST":"☁",
                    "RAIN":"⛆","DRIZZLE":"⛆","SNOW":"❄","THUNDER":"⚡",
                    "FOG":"≋","MIST":"≋","HAZE":"≋"
                }
                icon = "◈"
                for k,v in icons.items():
                    if k in desc:
                        icon = v
                        break
                _weather = {"temp":f"{temp}°C","desc":desc[:18],
                            "icon":icon,"wind":f"{wind}km/h","humid":f"{humid}%"}
        except Exception:
            pass
        time.sleep(600)  # 10 dakikada bir güncelle

threading.Thread(target=fetch_weather, daemon=True).start()

# ══════════════════════════════════════════════════════════════
#  GERÇEK SİSTEM METRİKLERİ (psutil)
# ══════════════════════════════════════════════════════════════
_sys_metrics = {"cpu":0,"mem":0,"disk":0,"net_up":0,"net_down":0}
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
                if _net_old:
                    up   = (net.bytes_sent - _net_old.bytes_sent) / 1024
                    down = (net.bytes_recv - _net_old.bytes_recv) / 1024
                else:
                    up = down = 0.0
                _net_old = net

                _sys_metrics = {
                    "cpu":  round(cpu, 1),
                    "mem":  round(mem, 1),
                    "disk": round(disk, 1),
                    "net_up":   round(up, 1),
                    "net_down": round(down, 1),
                }
        except Exception:
            pass
        time.sleep(2)

threading.Thread(target=fetch_sys_metrics, daemon=True).start()

# ══════════════════════════════════════════════════════════════
#  ALEXA CİHAZ DURUMU (placeholder — gerçek API altyapısı)
# ══════════════════════════════════════════════════════════════
_alexa_devices = [
    {"name":"LIVING ROOM", "type":"LIGHT",  "state":"ON",  "val":"80%"},
    {"name":"BEDROOM",     "type":"LIGHT",  "state":"OFF", "val":"--"},
    {"name":"THERMOSTAT",  "type":"THERMO", "state":"ON",  "val":"21°C"},
    {"name":"TV",          "type":"SWITCH", "state":"OFF", "val":"--"},
    {"name":"SPEAKER",     "type":"AUDIO",  "state":"ON",  "val":"VOL 40"},
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
        """Send a coding task to Claude Code on the remote machine.
        Returns (success: bool, output: str)."""
        with self._lock:
            if not SSH_HOST or not SSH_USER:
                return False, "SSH not configured — set SSH_HOST and SSH_USER."
            if self._client is None:
                ok, msg = self._connect()
                if not ok:
                    return False, f"SSH connection failed: {msg}"
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
#  TAKVİM / HATIRLATICI
# ══════════════════════════════════════════════════════════════
_reminders = [
    {"time":"09:00","text":"Morning briefing"},
    {"time":"14:30","text":"System backup check"},
    {"time":"18:00","text":"Network scan"},
    {"time":"22:00","text":"Shutdown sequence"},
]

# ══════════════════════════════════════════════════════════════
#  MİKROFON
# ══════════════════════════════════════════════════════════════
class MicrophoneEngine:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self.fs = 44100
        self.rec_seconds = 5
        self.active = False
        self._stop  = False

    def listen_once(self):
        try:
            rec = sd.rec(int(self.rec_seconds*self.fs),
                         samplerate=self.fs,channels=1,dtype='int16')
            sd.wait()
            wavfile.write("_tmp_rec.wav",self.fs,rec)
            with sr.AudioFile("_tmp_rec.wav") as src:
                audio = self.recognizer.record(src)
            return self.recognizer.recognize_google(audio,language=LANGUAGE).lower().strip()
        except sr.UnknownValueError:
            return ""
        except Exception as e:
            print(f"[MIC] {e}"); return ""

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

    def stop(self): self._stop = True

# ══════════════════════════════════════════════════════════════
#  JARVIS HUD v4  —  TAM EKRAN PREMİUM
# ══════════════════════════════════════════════════════════════
class JarvisHUD(ctk.CTk):

    C_BG     = "#000608"
    C_PANEL  = "#00080c"
    C_CYAN   = "#00e8ff"
    C_CYAN2  = "#00a0b8"
    C_CYAN3  = "#003d50"
    C_CYAN4  = "#001e28"
    C_ORANGE = "#ff8c00"
    C_RED    = "#ff2244"
    C_GREEN  = "#00ff99"
    C_YELLOW = "#ffcc00"
    C_GRID   = "#001214"
    C_BORDER = "#002535"

    def __init__(self, mic):
        super().__init__()
        self.mic = mic

        # ── TAM EKRAN
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
        self.overrideredirect(True)        # Pencere çerçevesi yok
        self.configure(fg_color=self.C_BG)
        self.attributes("-topmost", True)

        # ESC ile çıkış
        self.bind("<Escape>", lambda e: self._exit())
        self.bind("<F4>",     lambda e: self._exit())

        # State
        self.angle      = 0.0
        self.status_text= "INITIALIZING"
        self.log_lines  = []
        self._speaking  = False
        self._wave_phase= 0.0
        self._cw = sw - 600   # canvas genişliği (tahmin)
        self._ch = sh - 104

        self._build_ui(sw, sh)
        self._start_clock()
        self._update_panels()
        self._animate()

        # Ensure the borderless window receives keyboard events immediately
        self.focus_force()

        threading.Thread(target=self._boot_sequence, daemon=True).start()

    def _exit(self):
        self.mic.stop()
        _bridge.disconnect()
        self.destroy()
        sys.exit(0)

    # ──────────────────────────────────────────────────────────
    #  ANA LAYOUT  (top + mid + bot)
    # ──────────────────────────────────────────────────────────
    def _build_ui(self, sw, sh):
        # TOP BAR — 52px
        self._top = tk.Frame(self, bg="#000c12", height=52)
        self._top.pack(fill="x", side="top")
        self._top.pack_propagate(False)
        self._build_topbar()

        # MID ROW — expands
        mid = tk.Frame(self, bg=self.C_BG)
        mid.pack(fill="both", expand=True)

        # Sol panel 300px
        self._lp = tk.Frame(mid, bg=self.C_PANEL, width=300)
        self._lp.pack(side="left", fill="y", padx=(6,2), pady=2)
        self._lp.pack_propagate(False)
        self._build_left()

        # Orta canvas — expands
        self._canvas = tk.Canvas(mid, bg=self.C_BG, highlightthickness=0)
        self._canvas.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        self._canvas.bind("<Configure>", lambda e: self._on_resize(e))

        # Sağ panel 300px
        self._rp = tk.Frame(mid, bg=self.C_PANEL, width=300)
        self._rp.pack(side="right", fill="y", padx=(2,6), pady=2)
        self._rp.pack_propagate(False)
        self._build_right()

        # BOT BAR — 52px
        self._bot = tk.Frame(self, bg="#000c12", height=52)
        self._bot.pack(fill="x", side="bottom")
        self._bot.pack_propagate(False)
        self._build_botbar()

    # ── TOP BAR
    def _build_topbar(self):
        p = self._top
        tk.Label(p, text="  J·A·R·V·I·S", bg="#000c12", fg=self.C_CYAN,
                 font=("Courier New",22,"bold")).pack(side="left")
        self._vline(p)
        tk.Label(p, text="STARK INDUSTRIES  ·  MARK 42  ·  NEURAL INTERFACE v4",
                 bg="#000c12", fg=self.C_CYAN3,
                 font=("Courier New",10)).pack(side="left", padx=14)
        self._vline(p)
        self._date_lbl = tk.Label(p, text="", bg="#000c12", fg=self.C_CYAN2,
                 font=("Courier New",10))
        self._date_lbl.pack(side="left", padx=14)

        # Sağ taraf
        self._top_status = tk.Label(p, text="●  SYSTEM ONLINE  ",
                 bg="#000c12", fg=self.C_GREEN,
                 font=("Courier New",11,"bold"))
        self._top_status.pack(side="right")
        self._vline(p, side="right")
        # ESC hint
        tk.Label(p, text="ESC: EXIT  ", bg="#000c12", fg=self.C_CYAN3,
                 font=("Courier New",8)).pack(side="right", padx=8)

    # ── BOT BAR
    def _build_botbar(self):
        p = self._bot
        self._clock_lbl = tk.Label(p, text="00:00:00",
                 bg="#000c12", fg=self.C_CYAN,
                 font=("Courier New",20,"bold"))
        self._clock_lbl.pack(side="left", padx=20, pady=6)
        self._vline(p)
        self._speech_lbl = tk.Label(p, text="J.A.R.V.I.S — INITIALIZING",
                 bg="#000c12", fg=self.C_CYAN,
                 font=("Courier New",12), anchor="w")
        self._speech_lbl.pack(side="left", padx=14, fill="x", expand=True)
        self._vline(p, side="right")
        self._net_lbl = tk.Label(p, text="↑ -- KB/s  ↓ -- KB/s",
                 bg="#000c12", fg=self.C_CYAN2,
                 font=("Courier New",9))
        self._net_lbl.pack(side="right", padx=14)

    def _vline(self, parent, side="left"):
        tk.Canvas(parent, width=1, height=34, bg=self.C_BORDER,
                  highlightthickness=0).pack(side=side, pady=9, padx=2)

    # ── SOL PANEL
    def _build_left(self):
        p = self._lp

        # SISTEM METRİKLERİ
        self._sec(p, "SYSTEM METRICS")
        self._bars = {}
        metrics_def = [
            ("cpu",  "CPU     "),
            ("mem",  "MEMORY  "),
            ("disk", "DISK    "),
        ]
        for key, lbl in metrics_def:
            row = tk.Frame(p, bg=self.C_PANEL)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=lbl, bg=self.C_PANEL, fg=self.C_CYAN3,
                     font=("Courier New",9), width=9, anchor="w").pack(side="left")
            val = tk.Label(row, text="--%", bg=self.C_PANEL, fg=self.C_CYAN,
                           font=("Courier New",9,"bold"), width=5)
            val.pack(side="right")
            track = tk.Frame(row, bg=self.C_CYAN4, height=7)
            track.pack(side="left", fill="x", expand=True, padx=(4,4))
            fill = tk.Frame(track, bg=self.C_CYAN, height=7)
            fill.place(x=0,y=0,relheight=1,relwidth=0.0)
            self._bars[key] = (fill, val)

        # HAVA DURUMU
        self._sec(p, "WEATHER  —  TOPPENSTEDT")
        wf = tk.Frame(p, bg=self.C_PANEL)
        wf.pack(fill="x", padx=12, pady=4)
        self._w_icon = tk.Label(wf, text="◈", bg=self.C_PANEL, fg=self.C_CYAN,
                                font=("Courier New",28))
        self._w_icon.pack(side="left", padx=(0,10))
        wr = tk.Frame(wf, bg=self.C_PANEL)
        wr.pack(side="left")
        self._w_temp = tk.Label(wr, text="--°C", bg=self.C_PANEL, fg=self.C_CYAN,
                                font=("Courier New",20,"bold"))
        self._w_temp.pack(anchor="w")
        self._w_desc = tk.Label(wr, text="LOADING...", bg=self.C_PANEL,
                                fg=self.C_CYAN3, font=("Courier New",8))
        self._w_desc.pack(anchor="w")

        wf2 = tk.Frame(p, bg=self.C_PANEL)
        wf2.pack(fill="x", padx=12, pady=2)
        self._w_wind = tk.Label(wf2, text="WIND  --", bg=self.C_PANEL,
                                fg=self.C_CYAN2, font=("Courier New",8))
        self._w_wind.pack(side="left")
        self._w_humid = tk.Label(wf2, text="  HUMID  --", bg=self.C_PANEL,
                                 fg=self.C_CYAN2, font=("Courier New",8))
        self._w_humid.pack(side="left")

        # ALEXA CİHAZLARI
        self._sec(p, "SMART HOME  —  ALEXA")
        self._alexa_lbls = []
        for dev in _alexa_devices:
            row = tk.Frame(p, bg=self.C_PANEL)
            row.pack(fill="x", padx=12, pady=2)
            icons = {"LIGHT":"⬡","THERMO":"◎","SWITCH":"◉","AUDIO":"♪"}
            icon = icons.get(dev["type"], "◈")
            state_clr = self.C_GREEN if dev["state"]=="ON" else self.C_CYAN3
            dot_clr   = self.C_GREEN if dev["state"]=="ON" else "#333333"
            tk.Label(row, text=f"{icon}", bg=self.C_PANEL, fg=self.C_CYAN2,
                     font=("Courier New",10)).pack(side="left")
            tk.Label(row, text=f" {dev['name']:<14}", bg=self.C_PANEL,
                     fg=self.C_CYAN3, font=("Courier New",8)).pack(side="left")
            state_lbl = tk.Label(row, text=dev["state"], bg=self.C_PANEL,
                                 fg=state_clr, font=("Courier New",8,"bold"))
            state_lbl.pack(side="right")
            val_lbl = tk.Label(row, text=dev["val"], bg=self.C_PANEL,
                               fg=self.C_CYAN2, font=("Courier New",8))
            val_lbl.pack(side="right", padx=6)
            self._alexa_lbls.append((dev, state_lbl, val_lbl))

        # LOG
        self._sec(p, "ACTIVITY LOG")
        self._log_frame = tk.Frame(p, bg=self.C_PANEL)
        self._log_frame.pack(fill="both", expand=True, padx=8, pady=(2,8))

    # ── SAĞ PANEL
    def _build_right(self):
        p = self._rp

        # KONUŞMA
        self._sec(p, "CONVERSATION")
        self._conv_frame = tk.Frame(p, bg=self.C_PANEL)
        self._conv_frame.pack(fill="both", expand=True, padx=8, pady=(2,4))

        # SES DALGASI
        self._sec(p, "AUDIO SIGNAL")
        self._wc = tk.Canvas(p, bg=self.C_PANEL, height=60, highlightthickness=0)
        self._wc.pack(fill="x", padx=10, pady=(2,6))
        self._draw_wave()

        # TAKVİM
        self._sec(p, "SCHEDULE  —  TODAY")
        self._cal_frame = tk.Frame(p, bg=self.C_PANEL)
        self._cal_frame.pack(fill="x", padx=8, pady=2)
        self._build_calendar()

        # ORTAM
        self._sec(p, "ENVIRONMENT")
        env_data = [
            ("LOCATION",  "TOPPENSTEDT, DE"),
            ("TIMEZONE",  "CET +1"),
            ("THREAT",    "LOW"),
            ("LANGUAGE",  "EN / TR"),
            ("AI ENGINE", "GEMINI 2.5"),
            ("VOICE",     "EN-GB RYAN"),
            ("AGENTS",    "6 / 6 ONLINE"),
        ]
        for k,v in env_data:
            row = tk.Frame(p, bg=self.C_PANEL)
            row.pack(fill="x", padx=12, pady=2)
            tk.Label(row, text=f"{k:<12}", bg=self.C_PANEL, fg=self.C_CYAN3,
                     font=("Courier New",8)).pack(side="left")
            tk.Label(row, text=v, bg=self.C_PANEL, fg=self.C_CYAN,
                     font=("Courier New",8,"bold")).pack(side="right")

        # CLAUDE CODE BRIDGE
        self._build_bridge_panel(p)

    def _build_bridge_panel(self, parent):
        self._sec(parent, "CLAUDE CODE  —  SSH BRIDGE")
        rows = [
            ("STATUS", "—"),
            ("HOST",   SSH_HOST or "not configured"),
            ("LAST",   "—"),
        ]
        self._bridge_lbls = {}
        for k, v in rows:
            row = tk.Frame(parent, bg=self.C_PANEL)
            row.pack(fill="x", padx=12, pady=2)
            tk.Label(row, text=f"{k:<8}", bg=self.C_PANEL, fg=self.C_CYAN3,
                     font=("Courier New",8)).pack(side="left")
            lbl = tk.Label(row, text=v, bg=self.C_PANEL, fg=self.C_CYAN,
                           font=("Courier New",8,"bold"))
            lbl.pack(side="right")
            self._bridge_lbls[k] = lbl
        self._refresh_bridge_panel()

    def _refresh_bridge_panel(self):
        st  = _bridge.status
        clr = {
            "ONLINE":         self.C_GREEN,
            "OFFLINE":        self.C_CYAN3,
            "DISCONNECTED":   self.C_ORANGE,
            "ERROR":          self.C_RED,
            "NOT CONFIGURED": self.C_ORANGE,
            "NO PARAMIKO":    self.C_RED,
        }.get(st, self.C_CYAN2)
        try:
            self._bridge_lbls["STATUS"].configure(text=st, fg=clr)
            self._bridge_lbls["LAST"].configure(text=_bridge.last_task[:22])
        except Exception:
            pass
        self.after(3000, self._refresh_bridge_panel)

    def _handle_bridge_command(self, task):
        """Run Claude Code task over SSH in a background thread."""
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
                summary = first_line[:150] if first_line else "Task completed, Sir."
                speak_text = f"Claude Code has responded, Sir. {summary}"
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

    def _build_calendar(self):
        now = datetime.datetime.now()
        for reminder in _reminders:
            h,m = map(int, reminder["time"].split(":"))
            rem_dt = now.replace(hour=h,minute=m,second=0,microsecond=0)
            is_past = rem_dt < now
            row = tk.Frame(self._cal_frame, bg=self.C_PANEL)
            row.pack(fill="x", pady=2)
            clr_time = self.C_CYAN3 if is_past else self.C_ORANGE
            clr_text = self.C_CYAN3 if is_past else self.C_CYAN2
            prefix = "✓" if is_past else "▸"
            tk.Label(row, text=f"{prefix} {reminder['time']}",
                     bg=self.C_PANEL, fg=clr_time,
                     font=("Courier New",9,"bold"), width=9, anchor="w").pack(side="left")
            tk.Label(row, text=reminder["text"],
                     bg=self.C_PANEL, fg=clr_text,
                     font=("Courier New",8), anchor="w").pack(side="left")

    def _sec(self, parent, title):
        f = tk.Frame(parent, bg=self.C_PANEL)
        f.pack(fill="x", padx=8, pady=(8,2))
        tk.Canvas(f, height=1, bg=self.C_BORDER,
                  highlightthickness=0).pack(fill="x", pady=(0,3))
        tk.Label(f, text=f"  {title}",
                 bg=self.C_PANEL, fg=self.C_CYAN2,
                 font=("Courier New",8,"bold")).pack(anchor="w")

    # ──────────────────────────────────────────────────────────
    #  PANEL GÜNCELLEME (weather, metrics, net)
    # ──────────────────────────────────────────────────────────
    def _update_panels(self):
        # Hava durumu
        try:
            self._w_temp.configure(text=_weather["temp"])
            self._w_desc.configure(text=_weather["desc"])
            self._w_icon.configure(text=_weather["icon"])
            self._w_wind.configure(text=f"WIND  {_weather['wind']}")
            self._w_humid.configure(text=f"  HUMID  {_weather['humid']}")
        except Exception: pass

        # Sistem metrikleri
        if PSUTIL_OK:
            for key in ["cpu","mem","disk"]:
                v = _sys_metrics.get(key, 0)
                fill, val = self._bars[key]
                pct = max(0.01, min(0.99, v/100))
                fill.place_configure(relwidth=pct)
                if key == "disk":
                    clr = self.C_RED if v>90 else (self.C_ORANGE if v>75 else self.C_CYAN)
                else:
                    clr = self.C_RED if v>88 else (self.C_ORANGE if v>70 else self.C_CYAN)
                fill.configure(bg=clr)
                val.configure(text=f"{v}%", fg=clr)
        else:
            # Simüle
            for key,(fill,val) in self._bars.items():
                v = random.uniform(20,75)
                fill.place_configure(relwidth=v/100)
                val.configure(text=f"{int(v)}%")

        # Ağ hızı (bot bar)
        try:
            up   = _sys_metrics.get("net_up", 0)
            down = _sys_metrics.get("net_down", 0)
            self._net_lbl.configure(
                text=f"↑ {up:.1f} KB/s   ↓ {down:.1f} KB/s")
        except Exception: pass

        self.after(2000, self._update_panels)

    # ──────────────────────────────────────────────────────────
    #  SAAT
    # ──────────────────────────────────────────────────────────
    def _start_clock(self):
        self._tick()

    def _tick(self):
        now = datetime.datetime.now()
        self._clock_lbl.configure(text=now.strftime("%H:%M:%S"))
        days   = ["MON","TUE","WED","THU","FRI","SAT","SUN"]
        months = ["JAN","FEB","MAR","APR","MAY","JUN",
                  "JUL","AUG","SEP","OCT","NOV","DEC"]
        self._date_lbl.configure(
            text=f"{days[now.weekday()]}  {now.day:02d} {months[now.month-1]} {now.year}")
        self.after(1000, self._tick)

    # ──────────────────────────────────────────────────────────
    #  CANVAS ANİMASYON
    # ──────────────────────────────────────────────────────────
    def _on_resize(self, e):
        self._cw, self._ch = e.width, e.height

    def _animate(self):
        try: self._draw_hud()
        except Exception: pass
        self.after(33, self._animate)

    def _draw_hud(self):
        c = self._canvas
        c.delete("all")
        cw, ch = self._cw, self._ch
        cx, cy = cw//2, ch//2
        R  = min(cx, cy) - 40
        t  = time.time()

        # Grid
        for i in range(0, cw, 55):
            c.create_line(i,0,i,ch, fill=self.C_GRID, width=1)
        for i in range(0, ch, 55):
            c.create_line(0,i,cw,i, fill=self.C_GRID, width=1)

        # Tarama çizgisi
        sy = int(ch*((t%5)/5))
        c.create_line(0,sy,cw,sy, fill=self.C_CYAN, width=1, stipple="gray12")

        # Köşe braketleri (4 köşe, çift kat)
        self._draw_corners(c, cw, ch)

        # ── Dış halkalar
        for r_off, clr, w in [
            (0,   "#001a20", 1),
            (20,  "#002535", 1),
            (36,  self.C_BORDER, 2),
        ]:
            r = R - r_off
            c.create_oval(cx-r,cy-r,cx+r,cy+r, outline=clr, width=w)

        # ── 90 tick mark (daha ince, premium)
        r_tick = R - 42
        for i in range(90):
            ang   = (i/90)*2*math.pi - math.pi/2
            major = i%9==0
            mid_t = i%3==0
            r1    = r_tick
            r2    = r_tick - (16 if major else (8 if mid_t else 4))
            x1,y1 = cx+r1*math.cos(ang), cy+r1*math.sin(ang)
            x2,y2 = cx+r2*math.cos(ang), cy+r2*math.sin(ang)
            clr = self.C_CYAN2 if major else (self.C_CYAN3 if mid_t else self.C_CYAN4)
            w   = 2 if major else 1
            c.create_line(x1,y1,x2,y2, fill=clr, width=w)
            # Major tick dışına sayı/derece
            if major:
                deg = i*4
                tx = cx+(r_tick+10)*math.cos(ang)
                ty = cy+(r_tick+10)*math.sin(ang)
                c.create_text(tx,ty, text=str(deg),
                              fill=self.C_CYAN3, font=("Courier New",6),
                              anchor="center")

        # ── 8 arc segmenti
        r_arc = R - 58
        seg_c = [self.C_CYAN,"#005566",self.C_ORANGE,
                 self.C_CYAN,"#005566",self.C_CYAN,self.C_RED,self.C_CYAN]
        for i in range(8):
            a1 = math.degrees(-math.pi/2 + (i/8)*2*math.pi) + 2.5
            a2 = math.degrees(-math.pi/2 + ((i+1)/8)*2*math.pi) - 2.5
            bx,by = cx-r_arc,cy-r_arc
            ex,ey = cx+r_arc,cy+r_arc
            w = 4 if i in (2,6) else 2
            c.create_arc(bx,by,ex,ey, start=a1, extent=a2-a1,
                         style="arc", outline=seg_c[i], width=w)

        # ── Dönen CW halkası (gradient nokta zinciri)
        self.angle += 0.007
        r_rot = R - 90
        n = 20
        for i in range(n):
            ang = self.angle + (i/n)*2*math.pi
            px  = cx + r_rot*math.cos(ang)
            py  = cy + r_rot*math.sin(ang)
            frac = i/n
            sz = 2 + int(4*frac)
            clr = self.C_CYAN if frac > 0.7 else (self.C_CYAN2 if frac > 0.3 else self.C_CYAN4)
            c.create_oval(px-sz,py-sz,px+sz,py+sz, fill=clr, outline="")

        # ── CCW yavaş halka
        r_ccw = R - 118
        for i in range(12):
            ang = -self.angle*0.5 + (i/12)*2*math.pi
            px  = cx + r_ccw*math.cos(ang)
            py  = cy + r_ccw*math.sin(ang)
            c.create_oval(px-2,py-2,px+2,py+2, fill=self.C_CYAN3, outline="")

        # ── İç halka
        r_in = R - 148
        c.create_oval(cx-r_in,cy-r_in,cx+r_in,cy+r_in,
                      outline=self.C_CYAN2, width=2)

        # Crosshair
        for ang in [0,math.pi/2,math.pi,3*math.pi/2]:
            xe = cx+r_in*math.cos(ang)
            ye = cy+r_in*math.sin(ang)
            c.create_line(cx,cy,xe,ye, fill=self.C_CYAN4, width=1)

        # ── DÖNEN KÜRE
        self._draw_sphere(c, cx, cy, r_in-18, t)

        # ── Arc reaktör çekirdeği
        pulse = 1.0 + 0.08*math.sin(t*3.2)
        for r_c, clr, w in [
            (int(30*pulse),"#001e28",2),
            (int(20*pulse),"#003d50",2),
            (int(12*pulse),"#00a0b8",3),
            (int(6*pulse), "#00e8ff",0),
        ]:
            if w==0:
                c.create_oval(cx-r_c,cy-r_c,cx+r_c,cy+r_c,
                              fill="#00e8ff", outline="")
            else:
                c.create_oval(cx-r_c,cy-r_c,cx+r_c,cy+r_c,
                              outline=clr, width=w)

        # ── Durum metni
        c.create_text(cx, cy-r_in-18, text=self.status_text,
                      fill=self.C_CYAN, font=("Courier New",13,"bold"),
                      anchor="center")

        # ── Saat çevresinde küçük bilgi nokta
        self._draw_info_ring(c, cx, cy, R-22, t)

    def _draw_sphere(self, c, cx, cy, r, t):
        rot_y = t * 0.35
        rot_x = 0.28
        cy_r, sy_r = math.cos(rot_y), math.sin(rot_y)
        cx_r, sx_r = math.cos(rot_x), math.sin(rot_x)
        sr = r * 0.56

        def proj(x3,y3,z3):
            x2 =  x3*cy_r + z3*sy_r
            z2 = -x3*sy_r + z3*cy_r
            y2 =  y3*cx_r - z2*sx_r
            z3b=  y3*sx_r + z2*cx_r
            fov = 2.4
            sc  = fov/(fov + z3b*0.4)
            return cx+x2*sr*sc, cy+y2*sr*sc, z3b

        # Enlem (yatay)
        for li in range(11):
            lat  = -math.pi/2 + li*math.pi/10
            pts  = []
            for j in range(37):
                lon = j*2*math.pi/36
                x3 = math.cos(lat)*math.cos(lon)
                y3 = math.sin(lat)
                z3 = math.cos(lat)*math.sin(lon)
                pts.append(proj(x3,y3,z3))
            for j in range(len(pts)-1):
                z_avg = (pts[j][2]+pts[j+1][2])/2
                clr   = self._sph_clr(z_avg)
                if clr:
                    c.create_line(pts[j][0],pts[j][1],
                                  pts[j+1][0],pts[j+1][1],
                                  fill=clr, width=1)

        # Boylam (dikey)
        for li in range(16):
            lon  = li*2*math.pi/16
            pts  = []
            for j in range(19):
                lat = -math.pi/2 + j*math.pi/18
                x3 = math.cos(lat)*math.cos(lon)
                y3 = math.sin(lat)
                z3 = math.cos(lat)*math.sin(lon)
                pts.append(proj(x3,y3,z3))
            for j in range(len(pts)-1):
                z_avg = (pts[j][2]+pts[j+1][2])/2
                clr   = self._sph_clr(z_avg)
                if clr:
                    c.create_line(pts[j][0],pts[j][1],
                                  pts[j+1][0],pts[j+1][1],
                                  fill=clr, width=1)

        # Merkez nokta
        c.create_oval(cx-5,cy-5,cx+5,cy+5, fill=self.C_CYAN, outline="")

    def _sph_clr(self, z):
        a = max(0.0, (z+1)/2)
        if a < 0.12: return ""
        g = int(160*a); b = int(200*a+40)
        return f"#00{min(255,g):02x}{min(255,b):02x}"

    def _draw_info_ring(self, c, cx, cy, r, t):
        """Dış halka etrafına küçük bilgi etiketleri."""
        now = datetime.datetime.now()
        infos = [
            (0,   f"CPU {_sys_metrics.get('cpu',0):.0f}%"),
            (45,  f"MEM {_sys_metrics.get('mem',0):.0f}%"),
            (90,  f"{_weather['temp']}"),
            (135, f"{_weather['icon']} {_weather['desc'][:8]}"),
            (180, now.strftime("%H:%M")),
            (225, f"NET↓{_sys_metrics.get('net_down',0):.0f}KB"),
            (270, f"DISK {_sys_metrics.get('disk',0):.0f}%"),
            (315, f"{_weather['wind']}"),
        ]
        for deg, txt in infos:
            ang = math.radians(deg - 90)
            tx  = cx + (r+28)*math.cos(ang)
            ty  = cy + (r+28)*math.sin(ang)
            c.create_text(tx,ty, text=txt,
                          fill=self.C_CYAN3, font=("Courier New",7),
                          anchor="center")

    def _draw_corners(self, c, cw, ch):
        sz, gap = 24, 6
        clr1, clr2 = self.C_CYAN2, self.C_CYAN3
        for bx,by,dx,dy in [(gap,gap,1,1),(cw-gap,gap,-1,1),
                             (gap,ch-gap,1,-1),(cw-gap,ch-gap,-1,-1)]:
            c.create_line(bx,by,bx+dx*sz,by, fill=clr1, width=2)
            c.create_line(bx,by,bx,by+dy*sz, fill=clr1, width=2)
            c.create_line(bx+dx*5,by+dy*5,bx+dx*12,by+dy*5,
                          fill=clr2, width=1)
            c.create_line(bx+dx*5,by+dy*5,bx+dx*5,by+dy*12,
                          fill=clr2, width=1)

    # ──────────────────────────────────────────────────────────
    #  SES DALGASI
    # ──────────────────────────────────────────────────────────
    def _draw_wave(self):
        c = self._wc
        c.delete("all")
        w = c.winfo_width() or 280
        h = 60
        mid = h//2
        self._wave_phase += 0.14
        amp = 18 if self._speaking else 6
        pts = []
        for i in range(0, w+1, 3):
            y = (mid
                 + math.sin(i*0.065 + self._wave_phase)*amp
                 + math.sin(i*0.13  + self._wave_phase*1.4)*(amp*0.35)
                 + random.uniform(-0.5,0.5)*(amp*0.1))
            pts.extend([i, int(y)])
        if len(pts) >= 4:
            c.create_line(pts, fill=self.C_CYAN2, width=2, smooth=True)
        c.create_line(0,mid,w,mid, fill=self.C_CYAN4, width=1)
        self.after(50, self._draw_wave)

    # ──────────────────────────────────────────────────────────
    #  LOG & KONUŞMA
    # ──────────────────────────────────────────────────────────
    def add_log(self, msg, level="info"):
        clr = {"info":self.C_CYAN3,"ok":self.C_GREEN,"warn":self.C_ORANGE,
               "alert":self.C_RED,"cmd":self.C_ORANGE,"reply":self.C_CYAN
               }.get(level, self.C_CYAN3)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.after(0, self._ins_log, f"[{ts}] {msg}", clr)

    def _ins_log(self, txt, fg):
        lbl = tk.Label(self._log_frame, text=txt, bg=self.C_PANEL,
                       fg=fg, font=("Courier New",7), anchor="w", wraplength=260)
        lbl.pack(fill="x", anchor="w")
        self.log_lines.append(lbl)
        if len(self.log_lines) > 15:
            self.log_lines[0].destroy()
            self.log_lines.pop(0)

    def add_conversation(self, role, text):
        clr = self.C_ORANGE if role=="SIR" else self.C_CYAN
        pfx = "▸" if role=="SIR" else "◂"
        self.after(0, self._ins_conv, f"{pfx} {role}: {text[:70]}", clr)

    def _ins_conv(self, txt, fg):
        lbl = tk.Label(self._conv_frame, text=txt, bg=self.C_PANEL,
                       fg=fg, font=("Courier New",7), anchor="w", wraplength=260)
        lbl.pack(fill="x", anchor="w")
        kids = self._conv_frame.winfo_children()
        if len(kids) > 16: kids[0].destroy()

    def set_speech(self, txt):
        self.after(0, self._speech_lbl.configure, {"text": txt[:160]})

    def set_status(self, txt):
        self.status_text = txt.upper()

    # ──────────────────────────────────────────────────────────
    #  BOOT
    # ──────────────────────────────────────────────────────────
    def _boot_sequence(self):
        time.sleep(0.6)
        self.set_status("BOOTING")
        self.set_speech("J.A.R.V.I.S — INITIALIZING ALL SYSTEMS...")

        start_music()

        boot_msgs = [
            ("Neural link established",       "ok",  0.3),
            ("Arc reactor nominal",           "ok",  0.5),
            ("Gemini 1.5 Flash online",       "ok",  0.7),
            ("Voice engine EN/TR ready",      "ok",  1.0),
            ("6 agents synchronized",         "ok",  1.3),
            ("Weather feed connected",        "ok",  1.6),
            ("Smart home bridge loaded",      "ok",  2.0),
            ("Network monitoring active",     "ok",  2.3),
            ("All systems nominal",           "ok",  2.8),
        ]
        for msg,lvl,delay in boot_msgs:
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

        threading.Thread(
            target=fadeout_music_and_speak,
            args=(self, report),
            daemon=True
        ).start()

    def _on_command(self, text):
        lower = text.lower().strip()

        # Route to Claude Code bridge if text starts with a trigger prefix
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

        t = speak_async(reply)
        t.join()

        self._speaking = False
        self.set_status("LISTENING")
        self.set_speech("Awaiting your command, Sir.")

# ══════════════════════════════════════════════════════════════
#  ANA PROGRAM
# ══════════════════════════════════════════════════════════════
def main():
    print("="*58)
    print("   J.A.R.V.I.S  —  STARK INDUSTRIES  v4.0")
    print("="*58)
    print("   ESC veya F4 ile çıkış")
    print("="*58)

    prepare_music()   # webm → mp3 dönüşüm (ffmpeg varsa)

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
