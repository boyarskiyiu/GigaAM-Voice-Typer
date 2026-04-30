#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GigaAM Complete — Версия 7.7.8 (Финальный релиз)
(c) Боярский Игорь Юрьевич, 2026
"""

import sys, os, subprocess, tempfile, time, re, threading, queue, atexit, webbrowser, json
from collections import deque
from datetime import datetime
from ctypes import windll
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk
import numpy as np

# ----------------------------------------------------------------------
# Автоустановка пакетов
# ----------------------------------------------------------------------
def install(pkg):
    subprocess.run(
        [sys.executable, "-m", "pip", "install", pkg, "--quiet", "--no-warn-script-location"],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
    )

def ensure_packages():
    needed = {
        "onnx-asr": "onnx_asr",
        "sounddevice": "sounddevice",
        "numpy": "numpy",
        "keyboard": "keyboard",
        "pyperclip": "pyperclip",
        "requests": "requests",
        "scipy": "scipy",
    }
    for pip_name, imp_name in needed.items():
        try:
            __import__(imp_name)
        except ImportError:
            install(pip_name)

ensure_packages()

import keyboard
import pyperclip
import requests

CURRENT_VERSION = "7.7.8"
GITHUB_REPO = "boyarskiyiu/GigaAM-Voice-Typer"

# ----------------------------------------------------------------------
# Яндекс.Спеллер (таймаут 1.0 с)
# ----------------------------------------------------------------------
def spellcheck_text(text, timeout=1.0):
    try:
        url = "https://speller.yandex.net/services/spellservice.json/checkText"
        params = {"text": text, "lang": "ru"}
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 200:
            corrections = resp.json()
            if not corrections:
                return text
            result = list(text)
            for err in corrections:
                pos = err["pos"]
                length = err["len"]
                replacement = err["s"][0] if err["s"] else err["word"]
                result[pos:pos+length] = replacement
            return ''.join(result)
    except Exception:
        pass
    return text

def async_spellcheck(text, callback):
    def worker():
        corrected = spellcheck_text(text)
        callback(corrected)
    threading.Thread(target=worker, daemon=True).start()

# ----------------------------------------------------------------------
# Стоп-слова — только протяжные гласные и мычание
# ----------------------------------------------------------------------
STOP_WORDS = [
    r'а-а+', r'о-о+', r'у-у+', r'э-э+', r'и-и+',
    r'м-м+', r'мм+',
    r'(.)\1{2,}',
]
STOP_PATTERN = re.compile('|'.join(STOP_WORDS), re.IGNORECASE)

def clean_text(text):
    text = STOP_PATTERN.sub(' ', text)
    return re.sub(r'\s{2,}', ' ', text).strip()

# ----------------------------------------------------------------------
# Защита от повторного запуска
# ----------------------------------------------------------------------
LOCK_FILE = os.path.join(tempfile.gettempdir(), "gigaam_778.lock")
def check_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f: pid = int(f.read().strip())
            out = subprocess.check_output(
                f'tasklist /FI "PID eq {pid}"', shell=True, encoding='cp866',
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW
            )
            if str(pid) in out:
                return False
            else:
                os.unlink(LOCK_FILE)
        except:
            os.unlink(LOCK_FILE)
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(LOCK_FILE) and os.unlink(LOCK_FILE))
    return True

if not check_lock():
    sys.exit(0)

# ----------------------------------------------------------------------
# Интерфейс (780×680, topmost)
# ----------------------------------------------------------------------
class ToolTip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.tip_window = None
        widget.bind('<Enter>', self.schedule)
        widget.bind('<Leave>', self.hide)
    def schedule(self, event):
        self.enter_id = self.widget.after(500, self.show)
    def show(self):
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 25
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes('-topmost', True)
        tk.Label(tw, text=self.text, bg="#ffffe0", relief=tk.SOLID,
                 borderwidth=1, font=("Segoe UI", 9)).pack()
    def hide(self, event=None):
        if hasattr(self, 'enter_id'):
            self.widget.after_cancel(self.enter_id)
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

class GigaAMApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GigaAM Complete — Голосовой ввод")
        self.root.geometry("780x680")
        self.root.minsize(760, 640)
        self.root.attributes('-topmost', True)
        self.root.configure(bg="#f0f0f0")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.listening = False
        self.rate = 16000
        self.blocksize = 1024
        self.device = None
        self.last_text = ""
        self.corr_path = os.path.join(os.path.dirname(__file__), "corrections.json")

        self.running = True
        self._closing = False
        self.model = None
        self.model_ready = False

        # VAD
        self.speech_buffer = []
        self.speaking = False
        self.silence_counter = 0
        self.MAX_SILENCE_FRAMES = int(0.8 * 16000 / 1024)
        self.MIN_SPEECH_DURATION = 1.2
        self.MAX_PHRASE_DURATION = 8.0

        self.audio_queue = queue.Queue(maxsize=200)
        self.volume_history = deque(maxlen=7)

        self.create_widgets()
        self.start_keep_alive_ping()
        threading.Thread(target=self.init_model, daemon=True).start()

    def init_model(self):
        self.set_status("Загрузка GigaAM...")
        self.log("📥 Загрузка GigaAM v3 (RNNT)...")
        try:
            import onnx_asr
            self.model = onnx_asr.load_model("gigaam-v3-e2e-rnnt")
            self.model_ready = True
            self.log("✅ GigaAM готов")
            self.set_status("Готов к работе")
            self.start_stream()
            threading.Thread(target=self.recognition_worker, daemon=True).start()
            self.root.after(300, lambda: self.toggle_listening())
        except Exception as e:
            self.log(f"❌ Ошибка загрузки GigaAM: {e}")
            self.set_status("Ошибка GigaAM")

    def create_widgets(self):
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=0)  # разделитель
        self.root.grid_rowconfigure(2, weight=0)  # горячие клавиши
        self.root.grid_rowconfigure(3, weight=0)  # статус
        self.root.grid_rowconfigure(4, weight=1)  # лог
        self.root.grid_rowconfigure(5, weight=0)  # фраза
        self.root.grid_rowconfigure(6, weight=0)  # кнопки
        self.root.grid_columnconfigure(0, weight=1)

        # --- Шапка ---
        header_outer = tk.Frame(self.root, bg="#f0f0f0", highlightthickness=2, highlightbackground="#555")
        header_outer.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        header = tk.Frame(header_outer, bg="#2c3e50", height=150, relief=tk.RAISED, borderwidth=3)
        header.pack(fill=tk.X); header.pack_propagate(False)

        left = tk.Frame(header, bg="#2c3e50")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=1)

        tk.Label(left, text="🎤 GigaAM Complete", font=("Segoe UI", 14, "bold"),
                 bg="#2c3e50", fg="white").pack(anchor="w", pady=(3, 0))
        tk.Label(left, text="Голосовой ввод • Активация по голосу • Фильтр междометий",
                 font=("Segoe UI", 11), bg="#2c3e50", fg="#bdc3c7").pack(anchor="w", pady=(1, 0))
        tk.Label(left, text=f"Версия {CURRENT_VERSION} | VAD 0.8c | Буфер 8с | Таймаут сп. 1.0с",
                 font=("Segoe UI", 10, "bold"), bg="#2c3e50", fg="#bdc3c7").pack(anchor="w", pady=(1, 0))
        tk.Label(left, text="Разработчик: Боярский Игорь Юрьевич", font=("Segoe UI", 14, "bold"),
                 bg="#2c3e50", fg="#f1c40f").pack(anchor="w", pady=(3, 0))
        tk.Label(left, text="Микрофон: системный по умолчанию.", font=("Segoe UI", 11),
                 bg="#2c3e50", fg="#bdc3c7").pack(anchor="w", pady=(1, 0))
        tk.Label(left, text="🔍 Яндекс.Спеллер", font=("Segoe UI", 10, "bold"),
                 bg="#2c3e50", fg="#bdc3c7").pack(anchor="w", pady=(3, 3))

        right = tk.Frame(header, bg="#2c3e50")
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=8, pady=1)
        tk.Label(right, text="📞 +7 905 570-28-04", font=("Segoe UI", 11, "bold"),
                 bg="#2c3e50", fg="#ecf0f1").pack(anchor="e", pady=(1, 0))
        tk.Label(right, text="✉️ boyarskiyiu@yandex.ru", font=("Segoe UI", 11, "bold"),
                 bg="#2c3e50", fg="#ecf0f1").pack(anchor="e", pady=(1, 0))
        tk.Label(right, text="© 2026 Боярский И.Ю.", font=("Segoe UI", 11, "bold"),
                 bg="#2c3e50", fg="#f1c40f", justify=tk.RIGHT).pack(anchor="e", pady=(1, 3))

        # Тонкий разделитель
        separator = tk.Frame(self.root, height=1, bg="#888888")
        separator.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 0))

        # --- Горячие клавиши ---
        hotkey_frame = tk.Frame(self.root, bg="#f0f0f0")
        hotkey_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 2))
        tk.Label(hotkey_frame, text="F2 — пауза  |  F3 — исправить  |  F4 — свернуть",
                 font=("Segoe UI", 12, "bold"), bg="#f0f0f0", fg="#333").pack()

        # --- Статусная строка ---
        status_frame = tk.Frame(self.root, bg="#f0f0f0")
        status_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=2)

        self.ready_label = tk.Label(status_frame, text="✅ Готов к работе", font=("Segoe UI", 12, "bold"),
                                    bg="#f0f0f0", fg="#2e7d32")
        self.ready_label.pack(side=tk.RIGHT, padx=(8, 0))

        self.status_label = tk.Label(status_frame, text="⏳ Инициализация...",
                                     font=("Segoe UI", 11, "bold"), bg="#f0f0f0")
        self.status_label.pack(side=tk.LEFT)

        vol_frame = tk.Frame(status_frame, bg="#f0f0f0")
        vol_frame.pack(side=tk.RIGHT)
        self.volume_label = tk.Label(vol_frame, text="0%", font=("Segoe UI", 9), bg="#f0f0f0", width=4)
        self.volume_label.pack(side=tk.RIGHT, padx=(4, 0))
        self.volume_indicator = ttk.Progressbar(vol_frame, mode='determinate', length=60, maximum=100)
        self.volume_indicator.pack(side=tk.RIGHT)

        self.listening_label = tk.Label(status_frame, text="○ ПАУЗА", font=("Segoe UI", 11, "bold"),
                                        bg="#f0f0f0", fg="#c62828")
        self.listening_label.pack(side=tk.RIGHT, padx=(12, 0))

        # --- Лог ---
        log_frame = tk.LabelFrame(self.root, text="Лог работы", bg="#f0f0f0", font=("Segoe UI", 11, "bold"),
                                  relief=tk.RIDGE, borderwidth=2)
        log_frame.grid(row=4, column=0, sticky="nsew", padx=10, pady=2)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=6,
                                                   bg="#ffffff", fg="#000000", font=("Segoe UI", 11))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        # --- Поле фразы ---
        phrase_frame = tk.LabelFrame(self.root, text="Последняя распознанная фраза", bg="#f0f0f0", font=("Segoe UI", 11, "bold"),
                                     relief=tk.RIDGE, borderwidth=2)
        phrase_frame.grid(row=5, column=0, sticky="ew", padx=10, pady=2)

        self.phrase_text = tk.Text(phrase_frame, height=4, wrap=tk.WORD,
                                   bg="#ffffff", fg="#000000", font=("Segoe UI", 12),
                                   relief=tk.SUNKEN, borderwidth=2)
        self.phrase_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- Кнопки ---
        btn_frame = tk.Frame(self.root, bg="#f0f0f0")
        btn_frame.grid(row=6, column=0, sticky="ew", padx=10, pady=(4, 8))

        for i in range(5):
            btn_frame.columnconfigure(i, weight=1)

        btn_style = {
            "width": 20, "font": ("Segoe UI", 10, "bold"),
            "relief": tk.RAISED, "borderwidth": 2, "padx": 6, "pady": 2
        }

        def on_enter(btn, color_on):
            btn.config(background=color_on)
        def on_leave(btn, color_off):
            btn.config(background=color_off)

        self.btn_pause = tk.Button(btn_frame, text="⏯ Возобновить (F2)", command=self.toggle_listening,
                                   bg="#4caf50", fg="white", **btn_style)
        self.btn_pause.grid(row=0, column=0, padx=4, pady=4)
        self.btn_pause.bind("<Enter>", lambda e: on_enter(self.btn_pause, "#81c784"))
        self.btn_pause.bind("<Leave>", lambda e: on_leave(self.btn_pause, "#4caf50"))
        ToolTip(self.btn_pause, "Пауза / Возобновить")

        self.btn_fix = tk.Button(btn_frame, text="✎ Исправить (F3)", command=self.fix_last_phrase,
                                 bg="#2196f3", fg="white", **btn_style)
        self.btn_fix.grid(row=0, column=1, padx=4, pady=4)
        ToolTip(self.btn_fix, "Исправить последнюю фразу")

        self.btn_minimize = tk.Button(btn_frame, text="🗕 Свернуть (F4)", command=self.minimize_window,
                                      bg="#9e9e9e", fg="white", **btn_style)
        self.btn_minimize.grid(row=0, column=2, padx=4, pady=4)
        ToolTip(self.btn_minimize, "Свернуть окно")

        self.btn_update = tk.Button(btn_frame, text="🔄 Обновить", command=self.check_updates,
                                    bg="#4caf50", fg="white", **btn_style)
        self.btn_update.grid(row=0, column=3, padx=4, pady=4)

        self.btn_about = tk.Button(btn_frame, text="ℹ️ О программе", command=self.show_about,
                                   bg="#607d8b", fg="white", **btn_style)
        self.btn_about.grid(row=0, column=4, padx=4, pady=4)

        keyboard.add_hotkey('F2', self.toggle_listening)
        keyboard.add_hotkey('F3', self.fix_last_phrase)
        keyboard.add_hotkey('F4', self.minimize_window)

    # ==================================================================
    # VAD + РАСПОЗНАВАНИЕ
    # ==================================================================
    def recognition_worker(self):
        while self.running:
            if not self.listening:
                time.sleep(0.05)
                continue
            try:
                chunk = self.audio_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            energy = np.mean(chunk ** 2)
            is_speech = energy > 0.0008

            if is_speech and not self.speaking:
                self.speaking = True
                self.speech_buffer = [chunk]
                self.phrase_start_time = time.time()
                self.silence_counter = 0
            elif is_speech and self.speaking:
                self.speech_buffer.append(chunk)
                self.silence_counter = 0
            elif not is_speech and self.speaking:
                self.silence_counter += 1
                if self.silence_counter > self.MAX_SILENCE_FRAMES:
                    self._finalize_phrase()
                else:
                    self.speech_buffer.append(chunk)
            else:
                pass

            if self.speaking and (time.time() - self.phrase_start_time) > self.MAX_PHRASE_DURATION:
                self._finalize_phrase()

    def _finalize_phrase(self):
        if not self.speech_buffer:
            return
        audio = np.concatenate(self.speech_buffer).flatten()
        if len(audio) < self.rate * self.MIN_SPEECH_DURATION:
            self.speech_buffer = []
            self.speaking = False
            self.silence_counter = 0
            return

        threading.Thread(target=self._recognize, args=(audio,), daemon=True).start()
        self.speech_buffer = []
        self.speaking = False
        self.silence_counter = 0

    def _recognize(self, audio):
        wav_path = None
        try:
            from scipy.io.wavfile import write as write_wav
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                write_wav(f.name, self.rate, audio.astype(np.int16))
                wav_path = f.name

            result = self.model.recognize(wav_path)

            if isinstance(result, str):
                text = result.strip()
            elif hasattr(result, 'text'):
                text = result.text.strip()
            else:
                text = str(result).strip()

            if text:
                self._process_text(text)
        except Exception as e:
            self.log(f"❌ Ошибка GigaAM: {e}")
        finally:
            if wav_path and os.path.exists(wav_path):
                try:
                    os.unlink(wav_path)
                except:
                    pass

    def _process_text(self, text):
        text = clean_text(text)
        if text and text != self.last_text:
            draft = text[0].upper() + text[1:]
            self.root.after(0, lambda: self.update_phrase(draft))
            async_spellcheck(text, self._on_spellcheck_done)

    def _on_spellcheck_done(self, corrected_text):
        if corrected_text and corrected_text != self.last_text:
            final = corrected_text[0].upper() + corrected_text[1:]
            self.last_text = final
            self.root.after(0, lambda: self.update_phrase(final))
            self.root.after(0, lambda: self.paste(final))
            self.log(f"✅ {final}")

    # ==================================================================
    # ОБНОВЛЕНИЯ
    # ==================================================================
    def check_updates(self):
        self.log("🔄 Проверка обновлений...")
        def do_check():
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            try:
                resp = requests.get(url, timeout=5)
                resp.raise_for_status()
                latest = resp.json()["tag_name"].replace("v", "")
                self.log(f"   GitHub: {latest}, текущая: {CURRENT_VERSION}")
                if self._version_cmp(latest, CURRENT_VERSION) > 0:
                    if messagebox.askyesno("Доступно обновление", f"Найдена новая версия: {latest}.\nОткрыть страницу для скачивания?"):
                        webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")
                else:
                    messagebox.showinfo("Обновлений нет", "У вас последняя версия.")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось проверить обновления:\n{e}")
        threading.Thread(target=do_check, daemon=True).start()

    def _version_cmp(self, a, b):
        def normalize(v):
            return [int(x) for x in v.split('.')]
        try:
            return (normalize(a) > normalize(b)) - (normalize(a) < normalize(b))
        except:
            return 0

    # ==================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ==================================================================
    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)

    def set_status(self, text):
        self.status_label.config(text=text)

    def toggle_listening(self):
        if not self.model_ready:
            messagebox.showinfo("Модель не готова", "Дождитесь загрузки")
            return
        self.listening = not self.listening
        if self.listening:
            self.listening_label.config(text="● СЛУШАЮ", fg="#2e7d32")
            self.btn_pause.config(text="⏸ Пауза (F2)", bg="#ff9800")
            self.log("Возобновление работы")
        else:
            self.listening_label.config(text="○ ПАУЗА", fg="#c62828")
            self.btn_pause.config(text="⏯ Возобновить (F2)", bg="#4caf50")
            self.log("Пауза")

    def minimize_window(self):
        self.root.iconify()

    def fix_last_phrase(self):
        if not self.last_text:
            messagebox.showinfo("Исправление", "Нет фразы")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Исправление фразы")
        dialog.geometry("560x180")
        dialog.configure(bg="#f0f0f0")
        dialog.attributes('-topmost', True)
        dialog.focus_force()
        tk.Label(dialog, text="Неправильно:", bg="#f0f0f0", font=("Segoe UI", 11)).pack(pady=(10, 0))
        wrong = tk.Entry(dialog, width=50, font=("Segoe UI", 11))
        wrong.insert(0, self.last_text)
        wrong.config(state='readonly')
        wrong.pack(pady=5)
        tk.Label(dialog, text="Правильный текст:", bg="#f0f0f0", font=("Segoe UI", 11)).pack()
        correct = tk.Entry(dialog, width=50, font=("Segoe UI", 11))
        correct.pack(pady=5)
        def save():
            corr = correct.get().strip()
            if corr and corr != self.last_text:
                data = {}
                if os.path.exists(self.corr_path):
                    with open(self.corr_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                data[self.last_text] = corr
                with open(self.corr_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self.log(f"Исправление сохранено: '{self.last_text}' → '{corr}'")
                messagebox.showinfo("Успех", "Сохранено!")
                dialog.destroy()
        tk.Button(dialog, text="Сохранить", command=save, bg="#4caf50", fg="white",
                  font=("Segoe UI", 11, "bold")).pack(pady=10)

    def on_close(self):
        if self._closing:
            return
        self._closing = True
        self.running = False
        self.listening = False
        os._exit(0)

    def start_keep_alive_ping(self):
        def ping():
            while self.running:
                time.sleep(10)
                if hasattr(self, 'stream') and self.stream and not self.listening:
                    try:
                        empty = np.zeros((self.blocksize, 1), dtype=np.int16)
                        self.audio_callback(empty, self.blocksize, None, None)
                    except:
                        pass
        threading.Thread(target=ping, daemon=True).start()

    def start_stream(self):
        import sounddevice as sd
        self.stream = sd.InputStream(device=self.device, samplerate=self.rate,
                                     channels=1, dtype='int16', callback=self.audio_callback)
        self.stream.start()

    def update_volume_color(self, value):
        if value < 40:
            style = "green.Horizontal.TProgressbar"
        elif value < 70:
            style = "orange.Horizontal.TProgressbar"
        else:
            style = "red.Horizontal.TProgressbar"
        self.volume_indicator.configure(style=style, value=value)
        self.volume_label.config(text=f"{int(value)}%")

    def audio_callback(self, indata, frames, time_info, status):
        vol = np.max(np.abs(indata))
        norm_vol = min(100, int(np.log10(vol / 100 + 1) * 40)) if vol > 0 else 0
        self.volume_history.append(norm_vol)
        smoothed = sum(self.volume_history) / len(self.volume_history)
        self.root.after(0, lambda: self.update_volume_color(smoothed))
        if not self.listening:
            return
        try:
            self.audio_queue.put_nowait(indata.copy())
        except queue.Full:
            pass

    def update_phrase(self, text):
        self.phrase_text.delete(1.0, tk.END)
        self.phrase_text.insert(tk.END, text)

    def paste(self, text):
        text += " "
        try:
            pyperclip.copy(text)
            time.sleep(0.005)
            keyboard.press_and_release('ctrl+v')
        except:
            pass

    def show_about(self):
        messagebox.showinfo("О программе",
                            f"GigaAM Complete v{CURRENT_VERSION}\n"
                            f"(c) Боярский И.Ю.\n\n"
                            f"GigaAM v3 + Яндекс.Спеллер.\n"
                            f"Контакты: +7 905 570-28-04")

if __name__ == '__main__':
    root = tk.Tk()
    try:
        windll.dwmapi.DwmSetWindowAttribute(windll.user32.GetParent(root.winfo_id()), 33, 2, 4)
    except:
        pass
    app = GigaAMApp(root)
    root.mainloop()