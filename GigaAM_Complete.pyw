#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GigaAM Complete — Версия 1.7.5 (15.04.2026)
(c) Боярский Игорь Юрьевич, 2026

- Ещё увеличены шрифты, окно уже (750x720)
- Кнопки единой ширины, идеальная геометрия
- Мгновенный старт, автообновление
"""

import sys
import os
import subprocess
import tempfile
import time
import json
import re
import threading
import queue
import atexit
import shutil
import requests
import webbrowser
from collections import deque
from datetime import datetime

# ----------------------------------------------------------------------
# МАКСИМАЛЬНАЯ ОПТИМИЗАЦИЯ ONNX RUNTIME
# ----------------------------------------------------------------------
cpu_cores = os.cpu_count() or 4
os.environ["OMP_NUM_THREADS"] = str(cpu_cores)
os.environ["ORT_INTRA_OP_NUM_THREADS"] = str(cpu_cores)
os.environ["ORT_INTER_OP_NUM_THREADS"] = "1"
os.environ["ORT_ENABLE_ALL_OPTIMIZATIONS"] = "1"
os.environ["ORT_DISABLE_TENSORRT"] = "1"
os.environ["ORT_DISABLE_CUDA"] = "1"
os.environ["ORT_DISABLE_DML"] = "1"
os.environ["ORT_DISABLE_OPENVINO"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

CURRENT_VERSION = "1.7.5"
GITHUB_REPO = "boyarskiyiu/GigaAM-Voice-Typer"

# ----------------------------------------------------------------------
# АВТОУСТАНОВКА ВСЕХ ЗАВИСИМОСТЕЙ (тихая)
# ----------------------------------------------------------------------
def install_pip_packages():
    required = [
        "onnxruntime", "onnx", "onnx-asr[cpu,hub]", "sounddevice",
        "numpy", "keyboard", "scipy", "pyperclip", "librosa",
        "pyautogui", "pillow", "pyaspeller", "requests"
    ]
    missing = []
    for pkg in required:
        pkg_name = pkg.replace("[cpu,hub]", "").replace("-", "_")
        if pkg_name == "pillow":
            pkg_name = "PIL"
        if pkg_name == "pyaspeller":
            pkg_name = "pyaspeller"
        try:
            __import__(pkg_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        for pkg in missing:
            subprocess.run([sys.executable, "-m", "pip", "install", pkg, "--quiet", "--no-warn-script-location"],
                           capture_output=True, check=False)

def install_ffmpeg():
    if shutil.which("ffmpeg") is None:
        try:
            import static_ffmpeg
            static_ffmpeg.add_paths()
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", "static-ffmpeg", "--quiet", "--no-warn-script-location"],
                           capture_output=True, check=False)
            try:
                import static_ffmpeg
                static_ffmpeg.add_paths()
            except:
                pass

install_pip_packages()
install_ffmpeg()

# ----------------------------------------------------------------------
# ИМПОРТЫ (кроме tkinter)
# ----------------------------------------------------------------------
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
from scipy.io.wavfile import write as write_wav
import onnx_asr

try:
    from pyaspeller import YandexSpeller
    SPELLER_AVAILABLE = True
except ImportError:
    SPELLER_AVAILABLE = False

# ----------------------------------------------------------------------
# ФИЛЬТРЫ ТЕКСТА
# ----------------------------------------------------------------------
STOP_WORDS = [
    r'э-э+', r'ээ+', r'м-м+', r'мм+', r'ну+', r'вот+', r'как бы', r'типа',
    r'это', r'это самое', r'в общем', r'так', r'значит', r'прям', r'короче',
    r'вообще', r'как сказать', r'как его', r'нуу', r'так вот', r'вообщем',
    r'честно говоря', r'собственно', r'понимаешь', r'понимаете', r'видите ли',
    r'знаешь', r'знаете', r'ладно', r'допустим', r'скажем', r'пожалуй',
    r'наверное', r'конкретно', r'мероприятие', r'например', r'ну вот', r'так сказать',
    r'кстати', r'во-первых', r'во-вторых', r'кажется', r'типа того', r'как-то',
    r'вообще-то', r'собственно говоря', r'по сути', r'в принципе', r'естественно',
    r'безусловно', r'конечно', r'слышь', r'слышишь', r'понимаешь'
]
STOP_WORDS_PATTERN = '|'.join([rf'\b({w})\b' for w in STOP_WORDS])
STOP_WORDS_REGEX = re.compile(STOP_WORDS_PATTERN, re.IGNORECASE)

def clean_text(text):
    if not text: return ""
    text = STOP_WORDS_REGEX.sub('', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def remove_leading_punctuation(text):
    if not text: return text
    text = re.sub(r'^[^\w\s]+', '', text)
    return text.lstrip()

def normalize_punctuation(text):
    if not text: return text
    text = re.sub(r',\s*,+', ',', text)
    text = re.sub(r'^,+', '', text)
    text = re.sub(r',+$', '', text)
    text = re.sub(r',\s*\.', '.', text)
    text = re.sub(r'\.{2,}', '.', text)
    if text and text[-1] not in '.!?':
        text += '.'
    return text

# ----------------------------------------------------------------------
# МИКРОФОН (АВТОМАТИЧЕСКИЙ ВЫБОР)
# ----------------------------------------------------------------------
def get_best_mic():
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0 and "microsoft sound mapper" not in d['name'].lower():
            return i
    return None

# ----------------------------------------------------------------------
# ЗАЩИТА ОТ ПОВТОРНЫХ ЗАПУСКОВ
# ----------------------------------------------------------------------
lock_file = os.path.join(tempfile.gettempdir(), "gigaam_175.lock")
def is_process_running(pid):
    try:
        output = subprocess.check_output(f'tasklist /FI "PID eq {pid}"', shell=True, encoding='cp866')
        return str(pid) in output
    except:
        return False
if os.path.exists(lock_file):
    try:
        with open(lock_file, 'r') as f:
            old_pid = int(f.read().strip())
        if is_process_running(old_pid):
            print("⚠️ Программа уже запущена. Закройте предыдущий экземпляр.")
            sys.exit(1)
        else:
            os.unlink(lock_file)
    except:
        try:
            os.unlink(lock_file)
        except:
            pass
with open(lock_file, 'w') as f:
    f.write(str(os.getpid()))
atexit.register(lambda: os.path.exists(lock_file) and os.unlink(lock_file))

# ----------------------------------------------------------------------
# ТОЛЬКО ТЕПЕРЬ ИМПОРТИРУЕМ TKINTER
# ----------------------------------------------------------------------
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk

# ----------------------------------------------------------------------
# КЛАСС TOOLTIP
# ----------------------------------------------------------------------
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.enter_id = None
        widget.bind('<Enter>', self.schedule_show)
        widget.bind('<Leave>', self.on_leave)
        widget.bind('<Button-1>', self.on_leave)

    def schedule_show(self, event):
        self.on_leave()
        self.enter_id = self.widget.after(500, self.show_tip)

    def show_tip(self):
        if self.tip_window: return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes('-topmost', True)
        tk.Label(tw, text=self.text, justify=tk.LEFT, background="#ffffe0",
                 relief=tk.SOLID, borderwidth=1, font=("Segoe UI", 9)).pack()

    def on_leave(self, event=None):
        if self.enter_id:
            self.widget.after_cancel(self.enter_id)
            self.enter_id = None
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

# ----------------------------------------------------------------------
# ОСНОВНОЙ КЛАСС
# ----------------------------------------------------------------------
class GigaAMApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GigaAM Complete — Голосовой ввод")
        self.root.geometry("750x720")        # Уже и чуть выше
        self.root.configure(bg="#f0f0f0")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.style = ttk.Style()
        self.style.theme_use('default')
        self.style.configure("green.Horizontal.TProgressbar", background="#2e7d32", troughcolor="#e0e0e0")
        self.style.configure("orange.Horizontal.TProgressbar", background="#f57c00", troughcolor="#e0e0e0")
        self.style.configure("red.Horizontal.TProgressbar", background="#c62828", troughcolor="#e0e0e0")

        self.model = None
        self.listening = False
        self.rate = 16000
        self.blocksize = 1024
        self.silence_dur = 0.7
        self.min_speech_frames = 4
        self.threshold = 550
        self.device = None
        self.last_orig = ""
        self.last_final = ""
        self.corr_path = os.path.join(os.path.dirname(__file__), "corrections.json")

        if SPELLER_AVAILABLE:
            try:
                self.speller = YandexSpeller(lang='ru', find_repeat_words=True)
            except:
                self.speller = None
        else:
            self.speller = None

        self.silent_frames = 0
        self.recording = False
        self.current_rec = []
        self.record_start = 0
        self.speech_counter = 0
        self.end_wait_frames = 0
        self.pre_buffer = []
        self.pre_max = int(0.7 * self.rate / self.blocksize)

        self.running = True
        self.task_queue = queue.Queue(maxsize=5)
        self.start_worker()

        self.volume_indicator = None
        self.volume_label = None
        self.volume_history = deque(maxlen=7)
        self._closing = False

        self.create_widgets()
        threading.Thread(target=self.init_background, daemon=True).start()

    def start_worker(self):
        def worker():
            while self.running:
                try:
                    audio = self.task_queue.get(timeout=0.5)
                    if audio is None: continue
                    self._recognize_and_paste(audio)
                except queue.Empty:
                    continue
        threading.Thread(target=worker, daemon=True).start()

    def create_widgets(self):
        # Шапка (высота 180)
        header_frame = tk.Frame(self.root, bg="#f0f0f0", highlightthickness=2, highlightbackground="black")
        header_frame.pack(fill=tk.X, padx=5, pady=4)
        header = tk.Frame(header_frame, bg="#2c3e50", height=180, relief=tk.RAISED, borderwidth=3)
        header.pack(fill=tk.X, padx=0, pady=0)
        header.pack_propagate(False)

        left = tk.Frame(header, bg="#2c3e50")
        left.place(relx=0, rely=0, relwidth=0.68, relheight=1)
        tk.Label(left, text="🎤 GigaAM Complete", font=("Segoe UI", 17, "bold"),
                 bg="#2c3e50", fg="white").place(x=6, y=6)
        tk.Label(left, text=f"Версия {CURRENT_VERSION} (15.04.2026)", font=("Segoe UI", 10),
                 bg="#2c3e50", fg="#bdc3c7").place(x=6, y=38)
        tk.Label(left, text="Разработчик: Боярский Игорь Юрьевич", font=("Segoe UI", 13, "bold"),
                 bg="#2c3e50", fg="#f1c40f").place(x=6, y=60)

        desc_text = (
            "Голос → текст с вставкой в активное окно. Модель GigaAM-v3.\n"
            "• Автоустановка пакетов, модели, ffmpeg.\n"
            "• Яндекс.Спеллер исправляет опечатки и повторы.\n"
            "F2 — пауза, F3 — исправить, F4 — свернуть."
        )
        tk.Label(left, text=desc_text, font=("Segoe UI", 10), bg="#2c3e50", fg="#c0d0e0",
                 justify=tk.LEFT).place(x=6, y=92)

        mic_desc = "Микрофон: автоматический выбор. Автокалибровка."
        tk.Label(left, text=mic_desc, font=("Segoe UI", 10), bg="#2c3e50", fg="#bdc3c7",
                 justify=tk.LEFT).place(x=6, y=152)

        right = tk.Frame(header, bg="#2c3e50")
        right.place(relx=0.68, rely=0, relwidth=0.32, relheight=1)
        tk.Label(right, text="📞 +7 905 570-28-04", font=("Segoe UI", 11),
                 bg="#2c3e50", fg="#ecf0f1").place(relx=0.98, y=10, anchor="ne")
        tk.Label(right, text="✉️ boyarskiyiu@yandex.ru", font=("Segoe UI", 11),
                 bg="#2c3e50", fg="#ecf0f1").place(relx=0.98, y=40, anchor="ne")
        tk.Label(right, text="© 2026 Боярский И.Ю.\nВсе права защищены.",
                 font=("Segoe UI", 11), bg="#2c3e50", fg="#bdc3c7", justify=tk.RIGHT).place(relx=0.98, y=76, anchor="ne")

        # Статусная строка
        status_frame = tk.Frame(self.root, bg="#f0f0f0")
        status_frame.pack(fill=tk.X, padx=5, pady=4)
        self.status_label = tk.Label(status_frame, text="⏳ Инициализация...", font=("Segoe UI", 11, "bold"), bg="#f0f0f0")
        self.status_label.pack(side=tk.LEFT)

        vol_frame = tk.Frame(status_frame, bg="#f0f0f0")
        vol_frame.pack(side=tk.RIGHT)
        self.volume_label = tk.Label(vol_frame, text="0%", font=("Segoe UI", 10), bg="#f0f0f0", width=4)
        self.volume_label.pack(side=tk.RIGHT, padx=(4,0))
        self.volume_indicator = ttk.Progressbar(vol_frame, mode='determinate', length=80, maximum=100)
        self.volume_indicator.pack(side=tk.RIGHT)

        self.listening_label = tk.Label(status_frame, text="○ ПАУЗА", font=("Segoe UI", 11, "bold"),
                                        bg="#f0f0f0", fg="#c62828")
        self.listening_label.pack(side=tk.RIGHT, padx=(0,10))

        # Лог
        log_frame = tk.LabelFrame(self.root, text="Лог работы", bg="#f0f0f0", font=("Segoe UI", 11))
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=4)
        accent_canvas = tk.Canvas(log_frame, width=3, bg="#f1c40f", highlightthickness=0)
        accent_canvas.pack(side=tk.LEFT, fill=tk.Y)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10,
                                                   bg="#ffffff", fg="#000000", font=("Segoe UI", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Последняя фраза
        phrase_frame = tk.LabelFrame(self.root, text="Последняя распознанная фраза", bg="#f0f0f0", font=("Segoe UI", 11))
        phrase_frame.pack(fill=tk.X, padx=5, pady=4)
        self.phrase_text = tk.Text(phrase_frame, height=2, wrap=tk.WORD,
                                   bg="#ffffff", fg="#000000", font=("Segoe UI", 12),
                                   relief=tk.SUNKEN, borderwidth=2)
        self.phrase_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Кнопки – все шириной 16, одинаковые
        btn_frame = tk.Frame(self.root, bg="#f0f0f0")
        btn_frame.pack(fill=tk.X, padx=5, pady=6)

        btn_width = 16
        def on_enter(btn, color_on): btn.config(bg=color_on)
        def on_leave(btn, color_off): btn.config(bg=color_off)

        self.btn_pause = tk.Button(btn_frame, text="▶ Возобновить (F2)", command=self.toggle_listening,
                                   bg="#4caf50", fg="white", width=btn_width, font=("Segoe UI", 11, "bold"))
        self.btn_pause.pack(side=tk.LEFT, padx=2)
        self.btn_pause.bind("<Enter>", lambda e: on_enter(self.btn_pause, "#81c784"))
        self.btn_pause.bind("<Leave>", lambda e: on_leave(self.btn_pause, "#4caf50"))
        ToolTip(self.btn_pause, "Приостановить/возобновить прослушивание микрофона")

        self.btn_fix = tk.Button(btn_frame, text="✏️ Исправить (F3)", command=self.fix_last_phrase,
                                 bg="#2196f3", fg="white", width=btn_width, font=("Segoe UI", 11, "bold"))
        self.btn_fix.pack(side=tk.LEFT, padx=2)
        self.btn_fix.bind("<Enter>", lambda e: on_enter(self.btn_fix, "#64b5f6"))
        self.btn_fix.bind("<Leave>", lambda e: on_leave(self.btn_fix, "#2196f3"))
        ToolTip(self.btn_fix, "Открыть окно для исправления последней фразы")

        self.btn_minimize = tk.Button(btn_frame, text="🗕 Свернуть (F4)", command=self.minimize_window,
                                      bg="#9e9e9e", fg="white", width=btn_width, font=("Segoe UI", 11, "bold"))
        self.btn_minimize.pack(side=tk.LEFT, padx=2)
        self.btn_minimize.bind("<Enter>", lambda e: on_enter(self.btn_minimize, "#bdbdbd"))
        self.btn_minimize.bind("<Leave>", lambda e: on_leave(self.btn_minimize, "#9e9e9e"))
        ToolTip(self.btn_minimize, "Свернуть окно в панель задач")

        self.btn_update = tk.Button(btn_frame, text="⚡ Обновить", command=self.check_updates,
                                    bg="#2196f3", fg="white", width=btn_width, font=("Segoe UI", 11, "bold"))
        self.btn_update.pack(side=tk.LEFT, padx=2)
        self.btn_update.bind("<Enter>", lambda e: on_enter(self.btn_update, "#64b5f6"))
        self.btn_update.bind("<Leave>", lambda e: on_leave(self.btn_update, "#2196f3"))
        ToolTip(self.btn_update, "Проверить и установить обновления")

        self.btn_about = tk.Button(btn_frame, text="ℹ️ О программе", command=self.show_about,
                                   bg="#607d8b", fg="white", width=btn_width, font=("Segoe UI", 11, "bold"))
        self.btn_about.pack(side=tk.LEFT, padx=2)
        self.btn_about.bind("<Enter>", lambda e: on_enter(self.btn_about, "#90a4ae"))
        self.btn_about.bind("<Leave>", lambda e: on_leave(self.btn_about, "#607d8b"))
        ToolTip(self.btn_about, "Информация о программе")

        self.btn_exit = tk.Button(btn_frame, text="✖ Выход", command=self.on_close,
                                  bg="#f44336", fg="white", width=btn_width, font=("Segoe UI", 11, "bold"))
        self.btn_exit.pack(side=tk.RIGHT, padx=2)
        self.btn_exit.bind("<Enter>", lambda e: on_enter(self.btn_exit, "#ef5350"))
        self.btn_exit.bind("<Leave>", lambda e: on_leave(self.btn_exit, "#f44336"))
        ToolTip(self.btn_exit, "Завершить работу программы")

        keyboard.add_hotkey('F2', self.toggle_listening)
        keyboard.add_hotkey('F3', self.fix_last_phrase)
        keyboard.add_hotkey('F4', self.minimize_window)

    # ------------------------------------------------------------------
    # Вспомогательные методы (аналогичны 1.7.4, только шрифты в диалогах тоже увеличены)
    # ------------------------------------------------------------------
    def compare_versions(self, v1, v2):
        def normalize(v):
            return [int(x) for x in v.split('.')]
        try:
            v1_parts = normalize(v1)
            v2_parts = normalize(v2)
        except:
            return 0
        for p1, p2 in zip(v1_parts, v2_parts):
            if p1 > p2: return 1
            if p1 < p2: return -1
        return 0

    def download_and_install_update(self, download_url):
        try:
            self.log("⬇️ Скачивание обновления...")
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pyw") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)
                tmp_path = tmp_file.name
            self.log(f"✅ Загружено: {os.path.basename(tmp_path)}")
            if not messagebox.askyesno("Установка обновления",
                                       "Новая версия загружена. Установить и перезапустить программу сейчас?"):
                os.unlink(tmp_path)
                return
            current_path = os.path.abspath(sys.argv[0])
            backup_path = current_path + ".backup"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(current_path, backup_path)
            shutil.copy2(tmp_path, current_path)
            os.unlink(tmp_path)
            self.log("✅ Обновление установлено. Перезапуск...")
            self.running = False
            if hasattr(self, 'stream') and self.stream:
                self.stream.stop()
                self.stream.close()
            self.root.quit()
            subprocess.Popen([sys.executable, current_path], creationflags=subprocess.CREATE_NO_WINDOW)
            sys.exit(0)
        except Exception as e:
            self.log(f"❌ Ошибка установки обновления: {e}")
            messagebox.showerror("Ошибка", f"Не удалось установить обновление:\n{e}")

    def check_updates(self):
        self.log("🔄 Проверка обновлений...")
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                latest_release = response.json()
                latest_version = latest_release["tag_name"].replace("v", "")
                self.log(f"   GitHub: {latest_version}, текущая: {CURRENT_VERSION}")
                if self.compare_versions(latest_version, CURRENT_VERSION) > 0:
                    assets = latest_release.get("assets", [])
                    download_url = None
                    for asset in assets:
                        if asset["name"].endswith(".pyw"):
                            download_url = asset["browser_download_url"]
                            break
                    if not download_url:
                        if messagebox.askyesno("Доступно обновление",
                                               f"Найдена новая версия: {latest_version}.\n"
                                               "Автоматическая установка невозможна (нет .pyw файла в релизе).\n"
                                               "Открыть страницу для ручного скачивания?"):
                            webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")
                        return
                    if messagebox.askyesno("Доступно обновление",
                                           f"Найдена новая версия: {latest_version}.\n"
                                           "Скачать и установить автоматически?"):
                        self.download_and_install_update(download_url)
                else:
                    messagebox.showinfo("Обновлений нет", "У вас установлена последняя версия.")
                return
            except requests.exceptions.ConnectionError:
                if attempt == max_retries:
                    messagebox.showerror("Ошибка сети", "Не удалось подключиться к серверу обновлений.")
                else:
                    time.sleep(2)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось проверить обновления:\n{e}")
                return

    def show_about(self):
        about_text = (
            f"GigaAM Complete v{CURRENT_VERSION}\n\n"
            "Разработчик: Боярский Игорь Юрьевич\n"
            "© 2026 Все права защищены.\n\n"
            "• Распознавание GigaAM-v3\n"
            "• Яндекс.Спеллер\n"
            "• Автоустановка зависимостей\n"
            "• Автоматическое обновление\n\n"
            "Репозиторий:\n"
            f"https://github.com/{GITHUB_REPO}"
        )
        messagebox.showinfo("О программе", about_text)

    def log(self, msg, append=False):
        ts = datetime.now().strftime("%H:%M:%S")
        if not append:
            self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        else:
            self.log_text.insert(tk.END, f"{msg}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def set_status(self, text, color="#555"):
        self.status_label.config(text=text, fg=color)

    def toggle_listening(self):
        self.listening = not self.listening
        if self.listening:
            self.listening_label.config(text="● СЛУШАЮ", fg="#2e7d32")
            self.btn_pause.config(text="⏸ Пауза (F2)", bg="#ff9800")
            self.log("Возобновление работы")
        else:
            self.listening_label.config(text="○ ПАУЗА", fg="#c62828")
            self.btn_pause.config(text="▶ Возобновить (F2)", bg="#4caf50")
            self.log("Пауза")

    def minimize_window(self):
        self.root.iconify()

    def fix_last_phrase(self):
        if not self.last_orig:
            messagebox.showinfo("Исправление", "Нет фразы для исправления.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Исправление фразы")
        dialog.geometry("520x170")
        dialog.configure(bg="#f0f0f0")
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(dialog, text="Неправильно:", bg="#f0f0f0", font=("Segoe UI", 12)).pack(pady=(10,0))
        wrong_entry = tk.Entry(dialog, width=55, font=("Segoe UI", 12))
        wrong_entry.insert(0, self.last_orig)
        wrong_entry.config(state='readonly')
        wrong_entry.pack(pady=5)
        tk.Label(dialog, text="Правильный текст:", bg="#f0f0f0", font=("Segoe UI", 12)).pack()
        correct_entry = tk.Entry(dialog, width=55, font=("Segoe UI", 12))
        correct_entry.pack(pady=5)
        btn_save = tk.Button(dialog, text="Сохранить", command=lambda: self._save_fix(dialog, correct_entry.get().strip()),
                             bg="#4caf50", fg="white", width=14, font=("Segoe UI", 11, "bold"))
        btn_save.pack(pady=10)

    def _save_fix(self, dialog, corr):
        if corr and corr != self.last_orig:
            data = {}
            if os.path.exists(self.corr_path):
                with open(self.corr_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            data[self.last_orig] = corr
            with open(self.corr_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log(f"Исправление сохранено: '{self.last_orig}' → '{corr}'")
            messagebox.showinfo("Успех", "Сохранено!")
            dialog.destroy()
        else:
            messagebox.showwarning("Ошибка", "Введите корректный текст")

    def on_close(self):
        if self._closing: return
        self._closing = True
        self.btn_exit.config(state=tk.DISABLED)
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        try:
            if messagebox.askyesno("Выход", "Завершить программу?"):
                self.running = False
                if hasattr(self, 'stream') and self.stream:
                    self.stream.stop()
                    self.stream.close()
                self.root.quit()
                self.root.destroy()
                sys.exit(0)
        finally:
            if self.root.winfo_exists():
                self.btn_exit.config(state=tk.NORMAL)
                self.root.after(100, lambda: self.root.protocol("WM_DELETE_WINDOW", self.on_close))
            self._closing = False

    def init_background(self):
        self.log("="*50)
        self.log(f"GigaAM Complete v{CURRENT_VERSION}")
        self.log(f"Ядер CPU: {cpu_cores}")
        self.log("(c) Боярский Игорь Юрьевич, 2026")
        self.log("="*50)

        self.set_status("Загрузка модели GigaAM-v3...")
        self.log("📥 Загрузка модели (может занять время при первом запуске)...")
        try:
            self.model = onnx_asr.load_model("gigaam-v3-e2e-rnnt")
            self.log("✅ Модель загружена")
        except Exception as e:
            self.log(f"❌ Ошибка модели: {e}")
            self.root.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось загрузить модель:\n{e}"))
            sys.exit(1)

        self.set_status("Поиск микрофона...")
        self.device = get_best_mic()
        if self.device is None:
            self.log("❌ Микрофон не найден")
            self.root.after(0, lambda: messagebox.showerror("Ошибка", "Микрофон не найден"))
            sys.exit(1)
        self.log(f"🎙️ Микрофон: {sd.query_devices(self.device)['name']}")

        self.set_status("Калибровка шума...")
        self.threshold = self.calibrate_threshold()
        self.log(f"🔊 Порог шума: {self.threshold}")

        if not os.path.exists(self.corr_path):
            with open(self.corr_path, 'w') as f:
                json.dump({}, f)
            self.log("✅ corrections.json создан")

        self.set_status("Готов к работе", "#2e7d32")
        self.log("✅ Говорите.")
        self.start_stream()
        self.root.after(0, lambda: self.toggle_listening())

    def calibrate_threshold(self):
        try:
            rec = sd.rec(int(2 * self.rate), samplerate=self.rate, channels=1, dtype='int16', device=self.device)
            sd.wait()
            noise = np.max(np.abs(rec))
            threshold = max(noise + 20, 160)
            return min(threshold, 800)
        except:
            return 300

    def start_stream(self):
        self.stream = sd.InputStream(device=self.device, samplerate=self.rate, channels=1,
                                     dtype='int16', blocksize=self.blocksize, callback=self.audio_callback)
        self.stream.start()
        self.log("🎙️ Аудиопоток запущен")

    def update_volume_color(self, value):
        if value < 40:
            self.volume_indicator.configure(style="green.Horizontal.TProgressbar")
        elif value < 70:
            self.volume_indicator.configure(style="orange.Horizontal.TProgressbar")
        else:
            self.volume_indicator.configure(style="red.Horizontal.TProgressbar")
        self.volume_indicator.configure(value=value)
        self.volume_label.config(text=f"{int(value)}%")

    def audio_callback(self, indata, frames, time_info, status):
        vol = np.max(np.abs(indata))
        if vol <= 0:
            norm_vol = 0
        else:
            norm_vol = min(100, int(np.log10(vol / 100 + 1) * 40))
        self.volume_history.append(norm_vol)
        smoothed_vol = sum(self.volume_history) / len(self.volume_history)
        self.root.after(0, lambda: self.update_volume_color(smoothed_vol))

        if not self.listening or self.model is None:
            self.silent_frames = 0
            self.recording = False
            self.current_rec = []
            self.speech_counter = 0
            self.end_wait_frames = 0
            self.pre_buffer = []
            return
        self.pre_buffer.append(indata.copy())
        if len(self.pre_buffer) > self.pre_max:
            self.pre_buffer.pop(0)

        frames_per_sec = self.rate / self.blocksize
        silence_needed = int(self.silence_dur * frames_per_sec)
        end_wait_needed = int(0.4 * frames_per_sec)

        if vol > self.threshold:
            self.silent_frames = 0
            self.end_wait_frames = 0
            self.speech_counter += 1
            if not self.recording and self.speech_counter >= self.min_speech_frames:
                self.recording = True
                self.current_rec = list(self.pre_buffer)
                self.record_start = time.time()
                self.log("🎙️ Начало речи", append=True)
            elif self.recording:
                self.current_rec.append(indata.copy())
        else:
            if self.recording:
                self.silent_frames += 1
                if self.silent_frames <= silence_needed + end_wait_needed:
                    self.current_rec.append(indata.copy())
                if self.silent_frames > silence_needed:
                    self.end_wait_frames += 1
                    if self.end_wait_frames >= end_wait_needed:
                        self.recording = False
                        if self.current_rec:
                            dur = time.time() - self.record_start
                            if dur >= 0.5 and self.speech_counter >= self.min_speech_frames:
                                self.log("⏹️ Отправка фрагмента...")
                                self.root.after(0, lambda: self.set_status("⏳ Распознаю...", "#e67e22"))
                                audio = np.concatenate(self.current_rec, axis=0)
                                try:
                                    self.task_queue.put(audio, block=False)
                                except queue.Full:
                                    self.log("⚠️ Очередь переполнена")
                            else:
                                self.log("⏹️ Шум (отброшено)", append=True)
                        self.current_rec = []
                        self.silent_frames = 0
                        self.end_wait_frames = 0
                        self.speech_counter = 0
            else:
                if self.speech_counter > 0:
                    self.speech_counter -= 1
                self.silent_frames = 0

    def _recognize_and_paste(self, audio):
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                write_wav(f.name, self.rate, audio.astype(np.int16))
                f.flush()
                raw = self.model.recognize(f.name).strip()
                for _ in range(3):
                    try:
                        os.unlink(f.name)
                        break
                    except:
                        time.sleep(0.2)
            if raw:
                self.log(f"📝 Распознано: '{raw}'")
                orig = raw.strip()
                self.last_orig = orig
                text = orig
                if os.path.exists(self.corr_path):
                    with open(self.corr_path, 'r', encoding='utf-8') as cf:
                        corr = json.load(cf)
                    for wrong, right in corr.items():
                        text = text.replace(wrong, right)
                text = clean_text(text)
                text = remove_leading_punctuation(text)
                text = re.sub(r'\s+', ' ', text).strip()
                text = normalize_punctuation(text)
                if text:
                    text = text[0].upper() + text[1:]
                if self.speller and text and len(text) > 3:
                    try:
                        text = self.speller.spelled(text)
                        self.log(f"🪄 После спеллера: '{text}'")
                    except:
                        pass
                if text and text != self.last_final and len(text) > 1:
                    elapsed = time.time() - self.record_start
                    self.log(f"✅ {elapsed:.1f} сек: {text}")
                    self.paste(text)
                    self.last_final = text
                    self.root.after(0, lambda: self.update_phrase(text))
                else:
                    self.log("⚠️ Повтор или пусто")
            else:
                self.log("⚠️ Не распознано")
        except Exception as e:
            self.log(f"❌ Ошибка: {e}")
        finally:
            self.root.after(0, lambda: self.set_status("Готов к работе", "#2e7d32"))

    def update_phrase(self, text):
        self.phrase_text.delete(1.0, tk.END)
        self.phrase_text.insert(tk.END, text)

    def paste(self, text):
        text += " "
        try:
            pyperclip.copy(text)
            time.sleep(0.05)
            keyboard.press_and_release('ctrl+v')
            self.log("   [Вставка Ctrl+V]")
        except:
            try:
                import pyautogui
                pyautogui.write(text, interval=0.02)
                self.log("   [Вставка pyautogui]")
            except:
                self.log("   ❌ Не удалось вставить")

# ----------------------------------------------------------------------
# ТОЧКА ВХОДА
# ----------------------------------------------------------------------
def main():
    root = tk.Tk()
    app = GigaAMApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()