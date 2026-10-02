import os
import sys
import time
import math
import socket
import shutil
import threading
import subprocess
from contextlib import contextmanager
import speech_recognition as sr
import ollama

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QRectF
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QPainter, QColor, QConicalGradient, QBrush, QPen, QPainterPath, QFont, QFontMetrics

SOCKET_PATH = "/tmp/harris.sock"
MODEL_NAME = "qwen2.5:7b"

# ==================== CONFIGURATION ANIMASI & UI ====================
ANIM_SPEED = 0.065      
ROTATION_SPEED = 4.5    
BASE_THICKNESS = 3.5    
GLOW_MAX_SPREAD = 30.0  

# ==================== BUNGKAM LOG C-LEVEL ====================
@contextmanager
def suppress_stderr():
    try:
        null_fd = os.open(os.devnull, os.O_WRONLY)
        save_fd = os.dup(2)
        os.dup2(null_fd, 2)
        os.close(null_fd)
        yield
    finally:
        os.dup2(save_fd, 2)
        os.close(save_fd)

# ==================== NATIVE GLOBAL SYSTEM COMMANDS (0 DETIK) ====================
def lock_screen() -> str:
    try:
        subprocess.run(["loginctl", "lock-session"], check=True)
        return "Layar berhasil dikunci."
    except Exception:
        return "Gagal mengunci layar."

def turn_off_display() -> str:
    try:
        subprocess.run(["kscreendoctor", "output.1.disable"], check=False)
        subprocess.run(["hyprctl", "dispatch", "dpms", "off"], check=False)
        subprocess.run(["xset", "dpms", "force", "off"], check=False)
        return "Monitor dimatikan."
    except Exception:
        return "Gagal mematikan monitor."

def control_media(action: str) -> str:
    try:
        subprocess.run(["playerctl", action], check=True)
        return f"Musik di-{action}."
    except Exception:
        return "Tidak ada pemutar media aktif."

def open_application_global(app_query: str) -> str:
    clean_name = app_query.lower().strip()
    
    global_map = {
        "pengaturan": "systemsettings",
        "system settings": "systemsettings",
        "setting": "systemsettings",
        "settings": "systemsettings",
        "screenshot": "spectacle",
        "tangkap layar": "spectacle",
        "cuplikan layar": "spectacle",
        "terminal": "konsole",
        "konsole": "konsole",
        "kitty": "kitty",
        "file manager": "dolphin",
        "berkas": "dolphin",
        "dolphin": "dolphin",
        "kalkulator": "kcalc",
        "calculator": "kcalc",
        "browser": "zen-browser",
        "chrome": "google-chrome-stable",
        "firefox": "firefox",
        "vscode": "code",
        "vs code": "code",
        "code": "code",
        "spotify": "spotify",
        "discord": "discord",
        "obs": "obs",
    }
    
    executable = global_map.get(clean_name, clean_name)
    
    if shutil.which(executable) or shutil.which(clean_name):
        target = executable if shutil.which(executable) else clean_name
        try:
            subprocess.Popen([target], start_new_session=True)
            return f"Membuka {app_query}..."
        except Exception as e:
            return f"Gagal membuka {app_query}: {e}"
            
    try:
        subprocess.Popen(["gtk-launch", clean_name], start_new_session=True)
        return f"Membuka {app_query}..."
    except Exception:
        pass

    return f"Aplikasi '{app_query}' tidak ditemukan."

HARRIS_PERSONA = """
Kamu adalah Harris (bisa juga dipanggil Kiana), asisten pintar CachyOS yang sigap, cerdas, efisien, dan ramah.
Gaya bicaramu santai, to the point, lugas, dan menggunakan bahasa Indonesia sehari-hari.
PENTING: Buat jawaban singkat (1-2 kalimat), padat, tanpa simbol markdown (*).
"""
chat_history = [{'role': 'system', 'content': HARRIS_PERSONA}]

# ==================== FLOATING TEXT & RGB OVERLAY ====================
class HarrisGlowOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        
        self.state = "idle"
        self.phase = 0.0
        self.message_text = ""
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(16)
        
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(lambda: self.set_state("idle"))
        
        self.hide()

    def set_state(self, new_state):
        self.state = new_state
        if new_state in ["listening", "speaking", "thinking"]:
            self.hide_timer.stop()
            self.phase = 0.0
            self.show()
            self.raise_()
        else:
            self.hide()

    def set_message(self, text):
        self.message_text = text
        self.update()

    def auto_hide_after(self, ms=3000):
        self.hide_timer.start(ms)

    def update_animation(self):
        if self.state != "idle":
            self.phase += ANIM_SPEED
            self.update()

    def _build_left_branch(self, w, h, m, progress):
        path = QPainterPath()
        path.moveTo(w / 2.0, h - m)
        s1, s2, s3 = (w / 2.0) - m, h - (2 * m), (w / 2.0) - m
        rem = progress * (s1 + s2 + s3)
        if rem <= s1:
            path.lineTo(w / 2.0 - rem, h - m)
            return path
        path.lineTo(m, h - m)
        rem -= s1
        if rem <= s2:
            path.lineTo(m, h - m - rem)
            return path
        path.lineTo(m, m)
        rem -= s2
        path.lineTo(m + rem, m)
        return path

    def _build_right_branch(self, w, h, m, progress):
        path = QPainterPath()
        path.moveTo(w / 2.0, h - m)
        s1, s2, s3 = (w / 2.0) - m, h - (2 * m), (w / 2.0) - m
        rem = progress * (s1 + s2 + s3)
        if rem <= s1:
            path.lineTo(w / 2.0 + rem, h - m)
            return path
        path.lineTo(w - m, h - m)
        rem -= s1
        if rem <= s2:
            path.lineTo(w - m, h - m - rem)
            return path
        path.lineTo(w - m, m)
        rem -= s2
        path.lineTo(w - m - rem, m)
        return path

    def paintEvent(self, event):
        if self.state == "idle":
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2.0, h / 2.0
        
        eased_progress = 1.0 - math.pow(1.0 - min(1.0, self.phase), 3)
        path_l = self._build_left_branch(w, h, 1.5, eased_progress)
        path_r = self._build_right_branch(w, h, 1.5, eased_progress)
        
        gradient = QConicalGradient(cx, cy, (self.phase * ROTATION_SPEED * 10) % 360)
        
        if self.state == "listening":
            gradient.setColorAt(0.0, QColor(0, 255, 170, 240))
            gradient.setColorAt(0.5, QColor(0, 210, 255, 240))
            gradient.setColorAt(1.0, QColor(0, 255, 170, 240))
        elif self.state == "thinking":
            gradient.setColorAt(0.0, QColor(255, 200, 0, 240))
            gradient.setColorAt(0.5, QColor(255, 100, 0, 240))
            gradient.setColorAt(1.0, QColor(255, 200, 0, 240))
        else: # speaking
            gradient.setColorAt(0.0, QColor(0, 180, 255, 240))
            gradient.setColorAt(0.5, QColor(140, 80, 255, 240))
            gradient.setColorAt(1.0, QColor(0, 180, 255, 240))

        pulse = math.sin(self.phase * 3.5) * 0.5
        for spread, alpha in [(GLOW_MAX_SPREAD, 0.04), (GLOW_MAX_SPREAD * 0.5, 0.12)]:
            pen = QPen(QBrush(gradient), BASE_THICKNESS + spread + pulse)
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setOpacity(alpha)
            painter.setPen(pen)
            painter.drawPath(path_l)
            painter.drawPath(path_r)

        core_pen = QPen(QBrush(gradient), BASE_THICKNESS + pulse)
        core_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        core_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setOpacity(0.95)
        painter.setPen(core_pen)
        painter.drawPath(path_l)
        painter.drawPath(path_r)

        if self.message_text:
            painter.setOpacity(1.0)
            font = QFont("Sans Serif", 12, QFont.Weight.Bold)
            painter.setFont(font)
            
            fm = QFontMetrics(font)
            text_width = max(220.0, fm.horizontalAdvance(self.message_text) + 40.0)
            text_height = 44.0
            
            rect_x = (w - text_width) / 2.0
            rect_y = h - 90.0
            rect = QRectF(rect_x, rect_y, text_width, text_height)
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(12, 16, 24, 220))
            painter.drawRoundedRect(rect, 14, 14)
            
            painter.setPen(QPen(QColor(0, 210, 255, 180), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 14, 14)
            
            painter.setPen(QColor(245, 245, 250))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.message_text)

# ==================== WORKER THREAD ====================
class HarrisWorker(QThread):
    state_changed = pyqtSignal(str)
    message_signal = pyqtSignal(str)
    hide_signal = pyqtSignal(int)
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.manual_trigger_flag = False

    def run(self):
        self.log_signal.emit("\n==============================================")
        self.log_signal.emit(f"[System]: Assistant AI ({MODEL_NAME}) - Ready (Harris/Kiana)")
        self.log_signal.emit("==============================================\n")
        threading.Thread(target=self.start_socket_listener, daemon=True).start()
        self.start_listener()

    def start_socket_listener(self):
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        server.listen(1)
        while True:
            conn, _ = server.accept()
            conn.close()
            self.manual_trigger_flag = True

    def check_fast_command(self, text):
        txt = text.lower().strip()
        
        # PERINTAH TUTUP / OFF AI
        if any(w in txt for w in ["matikan harris", "tutup harris", "keluar harris", "stop harris", "matikan kiana", "tutup kiana", "matikan ai", "keluar"]):
            self.log_signal.emit("[System]: AI dimatikan atas perintah pengguna. Menghemat baterai...")
            self.state_changed.emit("speaking")
            self.message_signal.emit("Siap, AI dimatikan.")
            time.sleep(1.2)
            os._exit(0)
            
        # PERINTAH SYSTEM POWER
        if any(w in txt for w in ["matikan pc", "matikan komputer", "shutdown"]):
            subprocess.run(["systemctl", "poweroff"])
            return "Mematikan komputer..."
        if any(w in txt for w in ["restart pc", "reboot", "restart komputer"]):
            subprocess.run(["systemctl", "reboot"])
            return "Mulai ulang komputer..."

        # KONTROL PERANGKAT FAST
        if any(w in txt for w in ["kunci layar", "kunci laptop", "lock screen"]):
            return lock_screen()
            
        if any(w in txt for w in ["matikan layar", "matikan monitor", "turn off display"]):
            return turn_off_display()
            
        if any(w in txt for w in ["pause", "hentikan musik", "stop lagu"]):
            return control_media("pause")
        if any(w in txt for w in ["play", "lanjutkan musik", "putar musik"]):
            return control_media("play")
        if any(w in txt for w in ["next", "lagu selanjutnya"]):
            return control_media("next")
        if any(w in txt for w in ["prev", "lagu sebelumnya"]):
            return control_media("previous")
            
        # MEMBUKA APLIKASI GLOBAL
        for prefix in ["buka ", "bukain ", "open ", "jalankan "]:
            if txt.startswith(prefix):
                app_name = txt.replace(prefix, "").strip()
                return open_application_global(app_name)
                
        if txt in ["pengaturan", "system settings", "screenshot", "tangkap layar", "terminal", "konsole", "file manager", "berkas", "kalkulator"]:
            return open_application_global(txt)
                
        return None

    def process_and_respond(self, user_input):
        global chat_history
        
        fast_reply = self.check_fast_command(user_input)
        if fast_reply:
            self.log_signal.emit(f"[Fast Execution]: {fast_reply}")
            self.state_changed.emit("speaking")
            self.message_signal.emit(fast_reply)
            self.hide_signal.emit(2500)
            return

        self.state_changed.emit("thinking")
        self.message_signal.emit("Berpikir...")
        
        chat_history.append({'role': 'user', 'content': user_input})
        try:
            stream = ollama.chat(
                model=MODEL_NAME,
                messages=chat_history,
                stream=True,
                options={'num_predict': 50, 'num_ctx': 2048, 'temperature': 0.7}
            )
            
            full_reply = ""
            self.state_changed.emit("speaking")
            
            for chunk in stream:
                content = chunk.get('message', {}).get('content', '')
                if content:
                    full_reply += content
                    self.message_signal.emit(full_reply.strip())
            
            if full_reply.strip():
                self.log_signal.emit(f"[AI Stream]: {full_reply.strip()}")
                chat_history.append({'role': 'assistant', 'content': full_reply.strip()})
                self.hide_signal.emit(3500)
            else:
                self.state_changed.emit("idle")

            if len(chat_history) > 10:
                chat_history = [chat_history[0]] + chat_history[-8:]
        except Exception as e:
            self.log_signal.emit(f"\n[Error Ollama]: {e}")
            self.message_signal.emit("Koneksi ke Ollama terputus.")
            self.hide_signal.emit(2000)

    def calibrate_noise(self, recognizer, mic):
        self.log_signal.emit("[Noise Check]: Kalibrasi mikrofon...")
        with suppress_stderr():
            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
        recognizer.energy_threshold = 130.0
        recognizer.dynamic_energy_threshold = False

    def listen_user_command(self, recognizer, mic):
        self.log_signal.emit("[Listening...] Silakan bicara...")
        try:
            with suppress_stderr():
                with mic as source:
                    recognizer.pause_threshold = 0.6
                    audio = recognizer.listen(source, timeout=6, phrase_time_limit=8)
            text = recognizer.recognize_google(audio, language="id-ID")
            self.log_signal.emit(f"[User Heard]: {text}")
            return text
        except Exception:
            return None

    def is_valid_wake_word(self, text):
        """Mendukung Panggilan Harris Maupun Kiana"""
        txt = text.lower().strip()
        words = txt.split()
        
        if not words:
            return False
            
        valid_prefixes = [
            "harris", "haris", "aris", "hey harris", "hai harris", "hei harris", "halo harris",
            "kiana", "kiara", "keyana", "qiana", "keana", "yana", "kana", "iana", "hey kiana", "hai kiana", "hei kiana", "halo kiana"
        ]
        
        first_word = words[0]
        first_two = " ".join(words[:2]) if len(words) >= 2 else ""
        
        if first_word in valid_prefixes or first_two in valid_prefixes or txt in valid_prefixes:
            return True
            
        return False

    def start_listener(self):
        recognizer = sr.Recognizer()
        with suppress_stderr():
            mic = sr.Microphone()
        self.calibrate_noise(recognizer, mic)
        self.log_signal.emit("\n[System]: Siap! Panggil 'Harris' atau 'Kiana'...")
        
        while True:
            try:
                if self.manual_trigger_flag:
                    self.manual_trigger_flag = False
                    
                    self.state_changed.emit("listening")
                    self.message_signal.emit("Ya? Ada apa?")
                    
                    user_cmd = self.listen_user_command(recognizer, mic)
                    if user_cmd:
                        self.process_and_respond(user_cmd)
                    else:
                        self.state_changed.emit("idle")
                    self.log_signal.emit("\n[System]: Kembali siaga...")
                    continue

                with suppress_stderr():
                    with mic as source:
                        recognizer.pause_threshold = 0.5
                        audio = recognizer.listen(source, timeout=2, phrase_time_limit=3)
                try:
                    text = recognizer.recognize_google(audio, language="id-ID").lower()
                    self.log_signal.emit(f"[Mic Hear]: {text}")
                    
                    if self.is_valid_wake_word(text):
                        self.log_signal.emit(f"\n[Triggered]: Wake word terdeteksi! ({text})")
                        
                        self.state_changed.emit("listening")
                        self.message_signal.emit("Ya? Ada apa?")
                        
                        user_cmd = self.listen_user_command(recognizer, mic)
                        if user_cmd:
                            self.process_and_respond(user_cmd)
                        else:
                            self.state_changed.emit("idle")
                        self.log_signal.emit("\n[System]: Kembali siaga...")
                except sr.UnknownValueError:
                    pass
                except sr.RequestError:
                    pass
            except sr.WaitTimeoutError:
                pass
            except Exception:
                time.sleep(0.1)

# ==================== MAIN ====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    overlay = HarrisGlowOverlay()
    
    worker = HarrisWorker()
    worker.state_changed.connect(overlay.set_state)
    worker.message_signal.connect(overlay.set_message)
    worker.hide_signal.connect(overlay.auto_hide_after)
    worker.log_signal.connect(print)
    worker.start()
    
    sys.exit(app.exec())
