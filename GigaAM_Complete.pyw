#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GigaAM Complete — Версия 3.0.0 (23.04.2026)
(c) Боярский Игорь Юрьевич, 2026

- Гибридное распознавание: VOSK (непрерывный поток) + GigaAM (финальная точность).
- Автоматическая загрузка модели VOSK при первом запуске.
- Современный интерфейс на ttkbootstrap.
- Полная автономность и защита от зависаний.
"""

import sys, os, subprocess, tempfile, time, json, re, threading, queue, atexit, shutil, requests, webbrowser, zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from ctypes import windll

# ----------------------------------------------------------------------
# НАДЕЖНАЯ БЛОКИРОВКА ПОВТОРНОГО ЗАПУСКА (Lock-файл + Windows Mutex)
# ----------------------------------------------------------------------
LOCK_FILE = os.path.join(tempfile.gettempdir(), "gigaam_300.lock")
MUTEX_NAME = "Global\\GigaAMCompleteVoiceTyperMutex_300"

def is_process_running(pid):
    try:
        output = subprocess.check_output(f'tasklist /FI "PID eq {pid}"', shell=True, encoding='cp866', stderr=subprocess.DEVNULL)
        return str(pid) in output
    except Exception: return False

def check_and_set_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f: old_pid = int(f.read().strip())
            if is_process_running(old_pid):
                print(f"⚠️ Программа уже запущена (PID: {old_pid}). Закрываем текущий экземпляр.")
                return False
            else: os.unlink(LOCK_FILE)
        except: os.unlink(LOCK_FILE)
    with open(LOCK_FILE, 'w') as f: f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(LOCK_FILE) and os.unlink(LOCK_FILE))
    return True

def check_mutex():
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.restype = wintypes.DWORD
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if kernel32.GetLastError() == 183:
            if mutex: kernel32.CloseHandle(mutex)
            print("⚠️ Программа уже запущена (проверка Mutex). Закрываем текущий экземпляр.")
            return False
        return True
    except Exception as e:
        print(f"⚠️ Не удалось проверить мьютекс: {e}. Пропускаем.")
        return True

if not check_and_set_lock() or not check_mutex(): sys.exit(0)

# ----------------------------------------------------------------------
# ОПТИМИЗАЦИЯ ONNX RUNTIME
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

CURRENT_VERSION = "3.0.0"
GITHUB_REPO = "boyarskiyiu/GigaAM-Voice-Typer"

# ----------------------------------------------------------------------
# АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ (включая ttkbootstrap, vosk, pyspellchecker)
# ----------------------------------------------------------------------
def install_pip_packages():
    required = [
        "onnxruntime", "onnx", "onnx-asr[cpu,hub]", "sounddevice", "numpy",
        "keyboard", "scipy", "pyperclip", "librosa", "pyautogui", "pillow",
        "pyspellchecker", "requests", "vosk", "ttkbootstrap"
    ]
    missing = []
    for pkg in required:
        pkg_name = pkg.replace("[cpu,hub]", "").replace("-", "_")
        if pkg_name == "pillow": pkg_name = "PIL"
        if pkg_name == "pyspellchecker": pkg_name = "spellchecker"
        if pkg_name == "vosk": pkg_name = "vosk"
        if pkg_name == "ttkbootstrap": pkg_name = "ttkbootstrap"
        try: __import__(pkg_name)
        except ImportError: missing.append(pkg)
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
            except: pass

install_pip_packages()
install_ffmpeg()

# ----------------------------------------------------------------------
# ИМПОРТЫ ПОСЛЕ УСТАНОВКИ
# ----------------------------------------------------------------------
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
from scipy.io.wavfile import write as write_wav
import onnx_asr
np.seterr(all='ignore')

from spellchecker import SpellChecker
SPELLER_AVAILABLE = True

import vosk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
from tkinter import scrolledtext, messagebox, filedialog

# ----------------------------------------------------------------------
# АВТОМАТИЧЕСКАЯ ЗАГРУЗКА МОДЕЛИ VOSK
# ----------------------------------------------------------------------
VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
VOSK_MODEL_DIR = os.path.join(os.path.dirname(__file__), "vosk-model-small-ru-0.22")

def ensure_vosk_model(callback=None):
    """Проверяет наличие модели VOSK и при необходимости скачивает её."""
    if os.path.exists(VOSK_MODEL_DIR) and os.path.isdir(VOSK_MODEL_DIR):
        if callback: callback("✅ Модель VOSK найдена")
        return True

    if callback: callback("📥 Скачивание модели VOSK (~40 МБ). Подождите...")
    try:
        # Создаём временный файл для скачивания
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp_zip.close()

        response = requests.get(VOSK_MODEL_URL, stream=True, timeout=60)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(temp_zip.name, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if callback and total_size > 0:
                    percent = int(100 * downloaded / total_size)
                    callback(f"📥 Скачивание VOSK: {percent}%")

        if callback: callback("📦 Распаковка модели VOSK...")
        with zipfile.ZipFile(temp_zip.name, 'r') as zip_ref:
            zip_ref.extractall(os.path.dirname(__file__))

        os.unlink(temp_zip.name)
        if callback: callback("✅ Модель VOSK готова")
        return True

    except Exception as e:
        if callback: callback(f"❌ Ошибка загрузки модели VOSK: {e}")
        return False

# ----------------------------------------------------------------------
# ФИЛЬТРЫ ТЕКСТА
# ----------------------------------------------------------------------
STOP_WORDS = [r'э-э+', r'ээ+', r'м-м+', r'мм+', r'ну+', r'вот+', r'короче', r'так сказать',
              r'как бы', r'типа', r'это самое', r'в общем', r'нуу', r'честно говоря',
              r'собственно', r'понимаешь', r'понимаете', r'видите ли', r'знаешь', r'знаете',
              r'ладно', r'допустим', r'скажем', r'пожалуй', r'наверное', r'конкретно',
              r'например', r'кстати', r'во-первых', r'во-вторых', r'кажется', r'типа того',
              r'как-то', r'вообще-то', r'собственно говоря', r'по сути', r'в принципе',
              r'естественно', r'безусловно', r'конечно', r'слышь', r'слышишь']
STOP_WORDS_PATTERN = '|'.join([rf'\b({w})\b' for w in STOP_WORDS])
STOP_WORDS_REGEX = re.compile(STOP_WORDS_PATTERN, re.IGNORECASE)

def clean_text(text):
    if not text: return ""
    text = STOP_WORDS_REGEX.sub('', text)
    return re.sub(r'\s+', ' ', text).strip()

def remove_leading_punctuation(text):
    if not text: return text
    return re.sub(r'^[^\w\s]+', '', text).lstrip()

def normalize_punctuation(text):
    if not text: return text
    text = re.sub(r',\s*,+', ',', text)
    text = re.sub(r'^,+', '', text)
    text = re.sub(r',+$', '', text)
    text = re.sub(r',\s*\.', '.', text)
    text = re.sub(r'\.{2,}', '.', text)
    if text and text[-1] not in '.!?': text += '.'
    return text

# ----------------------------------------------------------------------
# МИКРОФОН (системный по умолчанию)
# ----------------------------------------------------------------------
def get_best_mic(): return None

# ----------------------------------------------------------------------
# ОСНОВНОЙ КЛАСС
# ----------------------------------------------------------------------
class GigaAMApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GigaAM Complete — Голосовой ввод")
        self.root.geometry("740x750")
        self.root.minsize(740, 720)

        # Установка темы Flatly (светлая, современная)
        self.style = ttk.Style(theme="flatly")

        self.root.configure(bg=self.style.colors.bg)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.model = None           # GigaAM
        self.vosk_model = None      # VOSK
        self.vosk_recognizer = None
        self.listening = False
        self.rate = 16000
        self.blocksize = 1024
        self.silence_dur = 0.4
        self.min_speech_frames = 3
        self.threshold = 120
        self.device = get_best_mic()
        self.last_orig = ""
        self.last_final = ""
        self.corr_path = os.path.join(os.path.dirname(__file__), "corrections.json")

        self.speller = None
        try:
            self.speller = SpellChecker(language='ru')
        except Exception:
            self.speller = None

        self.silent_frames = 0
        self.recording = False
        self.current_rec = []
        self.record_start = 0
        self.speech_counter = 0
        self.end_wait_frames = 0
        self.pre_buffer = []
        self.pre_max = int(1.5 * self.rate / self.blocksize)

        self.running = True
        self.task_queue = queue.Queue(maxsize=10)
        self.start_worker()

        self.volume_history = deque(maxlen=7)
        self._closing = False

        self.create_widgets()
        self.start_keep_alive_ping()
        self.start_hotkey_refresher()

        # Сначала загружаем VOSK, потом GigaAM
        threading.Thread(target=self.init_background, daemon=True).start()
        self.root.after(100, self.lift_and_focus)

    def lift_and_focus(self):
        try:
            self.root.lift()
            self.root.focus_force()
        except Exception: pass

    def start_hotkey_refresher(self):
        def refresher():
            while self.running:
                time.sleep(30)
                try:
                    keyboard.unhook_all_hotkeys()
                    with keyboard._pressed_events_lock: keyboard._pressed_events.clear()
                    keyboard._listener.active_modifiers.clear()
                    keyboard._logically_pressed_keys.clear()
                    keyboard.add_hotkey('F2', self.toggle_listening)
                    keyboard.add_hotkey('F3', self.fix_last_phrase)
                    keyboard.add_hotkey('F4', self.minimize_window)
                except: pass
        threading.Thread(target=refresher, daemon=True).start()

    def start_keep_alive_ping(self):
        def ping():
            while self.running:
                time.sleep(10)
                if hasattr(self, 'stream') and self.stream and not self.listening:
                    try:
                        empty_buffer = np.zeros((self.blocksize, 1), dtype=np.int16)
                        self.audio_callback(empty_buffer, self.blocksize, None, None)
                    except: pass
        threading.Thread(target=ping, daemon=True).start()

    def start_worker(self):
        def worker():
            while self.running:
                try:
                    audio = self.task_queue.get(timeout=0.5)
                    if audio is None: continue
                    self._recognize_and_paste(audio)
                except queue.Empty: continue
        threading.Thread(target=worker, daemon=True).start()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=BOTH, expand=YES)

        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=0)
        main_frame.grid_columnconfigure(0, weight=1)

        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        top_frame.grid_rowconfigure(3, weight=1)
        top_frame.grid_columnconfigure(0, weight=1)

        # Шапка
        header_frame = ttk.LabelFrame(top_frame, text="Информация", padding=10)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))

        ttk.Label(header_frame, text="🎤 GigaAM Complete", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(header_frame, text=f"Версия {CURRENT_VERSION} (23.04.2026)").pack(anchor="w", pady=(2,5))
        ttk.Label(header_frame, text="Разработчик: Боярский Игорь Юрьевич", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0,5))
        ttk.Label(header_frame, text="Гибридное распознавание: VOSK (непрерывный поток) + GigaAM (точность)",
                  wraplength=700).pack(anchor="w", pady=(0,5))
        ttk.Label(header_frame, text="F2 — пауза/продолжить, F3 — исправить, F4 — свернуть").pack(anchor="w")

        # Контактная информация (справа в шапке)
        contact_frame = ttk.Frame(header_frame)
        contact_frame.pack(side=RIGHT, anchor="e")
        ttk.Label(contact_frame, text="📞 +7 905 570-28-04").pack(anchor="e")
        ttk.Label(contact_frame, text="✉️ boyarskiyiu@yandex.ru").pack(anchor="e", pady=(5,10))
        ttk.Label(contact_frame, text="© 2026 Боярский И.Ю.", font=("Segoe UI", 9, "bold")).pack(anchor="e")

        # Статусная строка
        status_frame = ttk.Frame(top_frame)
        status_frame.grid(row=1, column=0, sticky="ew", pady=5)

        self.ready_label = ttk.Label(status_frame, text="✅ Готов к работе", font=("Segoe UI", 12, "bold"))
        self.ready_label.pack(side=RIGHT, padx=(10,0))

        self.status_label = ttk.Label(status_frame, text="⏳ Инициализация...", font=("Segoe UI", 10, "bold"))
        self.status_label.pack(side=LEFT)

        # Индикатор громкости
        vol_frame = ttk.Frame(status_frame)
        vol_frame.pack(side=RIGHT)
        self.volume_label = ttk.Label(vol_frame, text="0%", width=4)
        self.volume_label.pack(side=RIGHT, padx=(5,0))
        self.volume_indicator = ttk.Progressbar(vol_frame, mode=DETERMINATE, length=70, maximum=100)
        self.volume_indicator.pack(side=RIGHT)

        self.listening_label = ttk.Label(status_frame, text="○ ПАУЗА", font=("Segoe UI", 10, "bold"))
        self.listening_label.pack(side=RIGHT, padx=(15,0))

        # Лог
        log_frame = ttk.LabelFrame(top_frame, text="Лог работы", padding=5)
        log_frame.grid(row=2, column=0, sticky="nsew", pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=8,
                                                   bg="white", fg="#222222", font=("Segoe UI", 10))
        self.log_text.pack(fill=BOTH, expand=YES)

        # Последняя фраза
        phrase_frame = ttk.LabelFrame(top_frame, text="Последняя распознанная фраза", padding=5)
        phrase_frame.grid(row=3, column=0, sticky="ew", pady=5)

        self.phrase_text = tk.Text(phrase_frame, height=5, wrap=tk.WORD,
                                   bg="white", fg="#222222", font=("Segoe UI", 11),
                                   relief=tk.FLAT, borderwidth=2)
        self.phrase_text.pack(fill=BOTH, expand=YES, padx=2, pady=2)

        # Кнопки
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=1, column=0, sticky="ew", pady=(5,0))
        for i in range(5): btn_frame.columnconfigure(i, weight=1)

        self.btn_pause = ttk.Button(btn_frame, text="⏯ Возобновить (F2)", command=self.toggle_listening, style="success.TButton")
        self.btn_pause.grid(row=0, column=0, padx=4, pady=5, sticky="ew")
        ToolTip(self.btn_pause, "Приостановить/возобновить прослушивание")

        self.btn_fix = ttk.Button(btn_frame, text="✎ Исправить (F3)", command=self.fix_last_phrase, style="info.TButton")
        self.btn_fix.grid(row=0, column=1, padx=4, pady=5, sticky="ew")
        ToolTip(self.btn_fix, "Открыть окно для исправления последней фразы")

        self.btn_minimize = ttk.Button(btn_frame, text="🗕 Свернуть (F4)", command=self.minimize_window, style="secondary.TButton")
        self.btn_minimize.grid(row=0, column=2, padx=4, pady=5, sticky="ew")
        ToolTip(self.btn_minimize, "Свернуть окно в панель задач")

        self.btn_update = ttk.Button(btn_frame, text="🔄 Обновить", command=self.check_updates, style="success.TButton")
        self.btn_update.grid(row=0, column=3, padx=4, pady=5, sticky="ew")
        ToolTip(self.btn_update, "Проверить и установить обновления")

        self.btn_about = ttk.Button(btn_frame, text="ℹ️ О программе", command=self.show_about, style="secondary.TButton")
        self.btn_about.grid(row=0, column=4, padx=4, pady=5, sticky="ew")
        ToolTip(self.btn_about, "Информация о программе")

        keyboard.add_hotkey('F2', self.toggle_listening)
        keyboard.add_hotkey('F3', self.fix_last_phrase)
        keyboard.add_hotkey('F4', self.minimize_window)

    # ------------------------------------------------------------------
    # Методы
    # ------------------------------------------------------------------
    def compare_versions(self, v1, v2):
        def normalize(v): return [int(x) for x in v.split('.')]
        try: return (normalize(v1) > normalize(v2)) - (normalize(v1) < normalize(v2))
        except: return 0

    def download_and_install_update(self, download_url):
        try:
            self.log("⬇️ Скачивание обновления...")
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pyw") as tmp_file:
                for chunk in response.iter_content(chunk_size=8192): tmp_file.write(chunk)
                tmp_path = tmp_file.name
            self.log(f"✅ Загружено: {os.path.basename(tmp_path)}")
            if not messagebox.askyesno("Установка обновления", "Новая версия загружена. Установить и перезапустить программу сейчас?"):
                os.unlink(tmp_path); return
            current_path = os.path.abspath(sys.argv[0])
            backup_path = current_path + ".backup"
            if os.path.exists(backup_path): os.remove(backup_path)
            os.rename(current_path, backup_path)
            shutil.copy2(tmp_path, current_path)
            os.unlink(tmp_path)
            self.log("✅ Обновление установлено. Перезапуск...")
            self.running = False
            if hasattr(self, 'stream') and self.stream: self.stream.stop(); self.stream.close()
            self.root.quit()
            subprocess.Popen([sys.executable, current_path], creationflags=subprocess.CREATE_NO_WINDOW)
            sys.exit(0)
        except Exception as e:
            self.log(f"❌ Ошибка установки обновления: {e}")
            messagebox.showerror("Ошибка", f"Не удалось установить обновление:\n{e}")

    def check_updates(self):
        self.log("🔄 Проверка обновлений...")
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
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
                    if asset["name"].endswith(".pyw") or ".pyw" in asset["name"]:
                        download_url = asset["browser_download_url"]; break
                if not download_url:
                    if messagebox.askyesno("Доступно обновление", f"Найдена новая версия: {latest_version}.\nАвтоматическая установка невозможна (нет .pyw файла в релизе).\nОткрыть страницу для ручного скачивания?"):
                        webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")
                    return
                if messagebox.askyesno("Доступно обновление", f"Найдена новая версия: {latest_version}.\nСкачать и установить автоматически?"):
                    self.download_and_install_update(download_url)
            else:
                messagebox.showinfo("Обновлений нет", "У вас установлена последняя версия.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось проверить обновления:\n{e}")

    def show_about(self):
        about_text = (
            f"GigaAM Complete v{CURRENT_VERSION}\n\n"
            "Разработчик: Боярский Игорь Юрьевич\n© 2026 Все права защищены.\n\n"
            "• Гибридное распознавание: VOSK (поток) + GigaAM (точность)\n"
            "• Офлайн-спеллер (pyspellchecker)\n"
            "• Автоустановка зависимостей и моделей\n"
            "• Автоматическое обновление\n\n"
            "Контакты:\n📞 +7 905 570-28-04\n✉️ boyarskiyiu@yandex.ru\n\n"
            f"Репозиторий:\nhttps://github.com/{GITHUB_REPO}"
        )
        messagebox.showinfo("О программе", about_text)

    def log(self, msg, append=False):
        ts = datetime.now().strftime("%H:%M:%S")
        if not append: self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        else: self.log_text.insert(tk.END, f"{msg}\n")
        self.log_text.see(tk.END); self.root.update_idletasks()

    def set_status(self, text, color=None):
        self.status_label.config(text=text)
        if text == "Готов к работе":
            self.ready_label.config(text="✅ Готов к работе")
        else:
            self.ready_label.config(text="")

    def toggle_listening(self):
        self.listening = not self.listening
        if self.listening:
            self.listening_label.config(text="● СЛУШАЮ")
            self.btn_pause.config(text="⏸ Пауза (F2)")
            self.log("Возобновление работы")
            self.ready_label.config(text="")
        else:
            self.listening_label.config(text="○ ПАУЗА")
            self.btn_pause.config(text="⏯ Возобновить (F2)")
            self.log("Пауза")
            self.ready_label.config(text="✅ Готов к работе")

    def minimize_window(self): self.root.iconify()

    def fix_last_phrase(self):
        if not self.last_orig: messagebox.showinfo("Исправление", "Нет фразы для исправления."); return
        dialog = tk.Toplevel(self.root)
        dialog.title("Исправление фразы")
        dialog.geometry("560x180")
        dialog.configure(bg=self.style.colors.bg)
        dialog.transient(self.root)
        x = self.root.winfo_x() + (self.root.winfo_width() - 560) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 180) // 2
        dialog.geometry(f"+{x}+{y}")
        ttk.Label(dialog, text="Неправильно:").pack(pady=(10,0))
        wrong_entry = ttk.Entry(dialog, width=50, font=("Segoe UI", 11))
        wrong_entry.insert(0, self.last_orig)
        wrong_entry.config(state='readonly')
        wrong_entry.pack(pady=5)
        ttk.Label(dialog, text="Правильный текст:").pack()
        correct_entry = ttk.Entry(dialog, width=50, font=("Segoe UI", 11))
        correct_entry.pack(pady=5)
        btn_save = ttk.Button(dialog, text="Сохранить", command=lambda: self._save_fix(dialog, correct_entry.get().strip()))
        btn_save.pack(pady=10)

    def _save_fix(self, dialog, corr):
        if corr and corr != self.last_orig:
            data = {}
            if os.path.exists(self.corr_path):
                with open(self.corr_path, 'r', encoding='utf-8') as f: data = json.load(f)
            data[self.last_orig] = corr
            with open(self.corr_path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)
            self.log(f"Исправление сохранено: '{self.last_orig}' → '{corr}'")
            messagebox.showinfo("Успех", "Сохранено!"); dialog.destroy()
        else: messagebox.showwarning("Ошибка", "Введите корректный текст")

    def on_close(self):
        if self._closing: return
        self._closing = True
        try:
            if messagebox.askyesno("Выход", "Завершить программу?"):
                self.running = False
                if hasattr(self, 'stream') and self.stream: self.stream.stop(); self.stream.close()
                self.root.quit()
                self.root.destroy()
        except Exception: pass

    def init_background(self):
        # 1. Загрузка модели VOSK
        self.set_status("Загрузка модели VOSK...")
        if not ensure_vosk_model(self.log):
            self.log("❌ Не удалось загрузить модель VOSK. Потоковый ввод отключён.")
        else:
            try:
                self.vosk_model = vosk.Model(VOSK_MODEL_DIR)
                self.vosk_recognizer = vosk.KaldiRecognizer(self.vosk_model, self.rate)
                self.vosk_recognizer.SetWords(True)
                self.log("✅ Модель VOSK загружена")
            except Exception as e:
                self.log(f"❌ Ошибка загрузки VOSK: {e}")

        # 2. Загрузка модели GigaAM
        self.set_status("Загрузка модели GigaAM-v3...")
        self.log("📥 Загрузка модели GigaAM (может занять время при первом запуске)...")
        try:
            self.model = onnx_asr.load_model("gigaam-v3-e2e-rnnt")
            self.log("✅ Модель GigaAM загружена")
        except Exception as e:
            self.log(f"❌ Ошибка модели GigaAM: {e}")
            self.root.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось загрузить модель GigaAM:\n{e}"))
            self.set_status("Ошибка загрузки модели", "red")
            return

        # 3. Остальная инициализация
        self.set_status("Поиск микрофона...")
        self.log("🎙️ Используется системный микрофон по умолчанию")
        self.log(f"🔊 Порог шума: {self.threshold}")

        if not os.path.exists(self.corr_path):
            with open(self.corr_path, 'w') as f: json.dump({}, f)
            self.log("✅ corrections.json создан")

        self.set_status("Готов к работе")
        self.log("✅ Говорите.")
        self.start_stream()
        self.root.after(0, lambda: self.toggle_listening())

    def start_stream(self):
        self.stream = sd.InputStream(device=self.device, samplerate=self.rate, channels=1,
                                     dtype='int16', blocksize=self.blocksize, callback=self.audio_callback)
        self.stream.start()
        self.log("🎙️ Аудиопоток запущен")

    def update_volume_color(self, value):
        if value < 40: self.volume_indicator.configure(style="success.Horizontal.TProgressbar")
        elif value < 70: self.volume_indicator.configure(style="warning.Horizontal.TProgressbar")
        else: self.volume_indicator.configure(style="danger.Horizontal.TProgressbar")
        self.volume_indicator.configure(value=value)
        self.volume_label.config(text=f"{int(value)}%")

    def audio_callback(self, indata, frames, time_info, status):
        vol = np.max(np.abs(indata))
        if vol <= 0: norm_vol = 0
        else: norm_vol = min(100, int(np.log10(vol / 100 + 1) * 40))
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

        # Потоковое распознавание через VOSK
        if self.vosk_recognizer is not None:
            if self.vosk_recognizer.AcceptWaveform(indata.tobytes()):
                result = json.loads(self.vosk_recognizer.Result())
                text = result.get('text', '').strip()
                if text:
                    self.root.after(0, lambda: self.update_phrase(text))
            else:
                partial = json.loads(self.vosk_recognizer.PartialResult())
                text = partial.get('partial', '').strip()
                if text:
                    self.root.after(0, lambda: self.update_phrase(text))

        # Основной механизм записи для GigaAM
        self.pre_buffer.append(indata.copy())
        if len(self.pre_buffer) > self.pre_max: self.pre_buffer.pop(0)

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
                            if dur >= 0.8 and self.speech_counter >= self.min_speech_frames:
                                self.log("⏹️ Отправка фрагмента на GigaAM...")
                                self.root.after(0, lambda: self.set_status("⏳ Распознаю..."))
                                audio = np.concatenate(self.current_rec, axis=0)
                                try: self.task_queue.put(audio, block=False)
                                except queue.Full: self.log("⚠️ Очередь переполнена")
                            else:
                                self.log("⏹️ Шум (отброшено)", append=True)
                        self.current_rec = []
                        self.silent_frames = 0
                        self.end_wait_frames = 0
                        self.speech_counter = 0
            else:
                if self.speech_counter > 0: self.speech_counter -= 1
                self.silent_frames = 0

    def _recognize_and_paste(self, audio):
        if self.model is None:
            self.log("⚠️ Модель GigaAM не загружена")
            self.root.after(0, lambda: self.set_status("Ошибка модели"))
            return
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                write_wav(f.name, self.rate, audio.astype(np.int16))
                f.flush()
                raw = self.model.recognize(f.name).strip()
                try: os.unlink(f.name)
                except: pass
            if raw:
                self.log(f"📝 GigaAM: '{raw}'")
                orig = raw.strip()
                self.last_orig = orig
                text = orig
                if os.path.exists(self.corr_path):
                    with open(self.corr_path, 'r', encoding='utf-8') as cf:
                        corr = json.load(cf)
                    for wrong, right in corr.items(): text = text.replace(wrong, right)
                text = clean_text(text)
                text = remove_leading_punctuation(text)
                text = re.sub(r'\s+', ' ', text).strip()
                text = normalize_punctuation(text)
                if text: text = text[0].upper() + text[1:]

                # Офлайн-спеллер
                if self.speller and len(text) > 3:
                    try:
                        words = text.split()
                        corrected_words = []
                        for word in words:
                            if re.search(r'[0-9]', word) or not word.isalpha():
                                corrected_words.append(word); continue
                            if word.lower() in self.speller:
                                corrected_words.append(word)
                            else:
                                correction = self.speller.correction(word.lower())
                                if correction:
                                    if word[0].isupper(): correction = correction[0].upper() + correction[1:]
                                    corrected_words.append(correction)
                                else: corrected_words.append(word)
                        text = ' '.join(corrected_words)
                        self.log(f"🪄 После спеллера: '{text}'")
                    except Exception as e:
                        self.log(f"⚠️ Ошибка спеллера: {e}")

                if text and text != self.last_final and len(text) > 1:
                    elapsed = time.time() - self.record_start
                    self.log(f"✅ {elapsed:.1f} сек: {text}")
                    self.paste(text)
                    self.last_final = text
                    self.root.after(0, lambda: self.update_phrase(text))
                else:
                    self.log("⚠️ Повтор или пусто")
            else:
                self.log("⚠️ GigaAM не распознал")
        except Exception as e:
            self.log(f"❌ Ошибка: {e}")
        finally:
            self.root.after(0, lambda: self.set_status("Готов к работе"))

    def update_phrase(self, text):
        self.phrase_text.delete(1.0, tk.END)
        self.phrase_text.insert(tk.END, text)

    def paste(self, text):
        text += " "
        try:
            pyperclip.copy(text)
            time.sleep(0.01)
            keyboard.press_and_release('ctrl+v')
            self.log("   [Вставка Ctrl+V]")
        except:
            try:
                import pyautogui
                pyautogui.write(text, interval=0.01)
                self.log("   [Вставка pyautogui]")
            except:
                self.log("   ❌ Не удалось вставить")

# ----------------------------------------------------------------------
# ТОЧКА ВХОДА
# ----------------------------------------------------------------------
def main():
    root = ttk.Window(themename="flatly")
    try:
        from ctypes import windll
        windll.dwmapi.DwmSetWindowAttribute(windll.user32.GetParent(root.winfo_id()), 33, 2, 4)
    except: pass
    app = GigaAMApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()