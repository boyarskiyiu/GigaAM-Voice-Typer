#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GigaAM Complete – ФИНАЛ (кнопка F2 корректно обновляется)
(c) Боярский Игорь Юрьевич, 2026
"""

import sys
import os
import traceback
import threading
import time
import subprocess
import importlib
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, filedialog

# ========== ЛОГ ==========
SCRIPT_DIR = os.path.dirname(__file__)
LOG_FILE = os.path.join(SCRIPT_DIR, "gigaam_log.txt")
SESSIONS_DIR = os.path.join(SCRIPT_DIR, "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)

def log_to_file(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")
    except:
        pass

def save_unique_text(text, prefix="live"):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{prefix}_{timestamp}.txt"
        filepath = os.path.join(SESSIONS_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text)
        log_to_file(f"💾 Сессия: {filepath}")
        return filepath
    except Exception as e:
        log_to_file(f"❌ Ошибка сессии: {e}")
        return None

log_to_file("=" * 60)
log_to_file("GigaAM vFINAL_BTN – КНОПКА F2 ОБНОВЛЯЕТСЯ")
log_to_file("=" * 60)

# ========== ПРОВЕРКА БИБЛИОТЕК ==========
REQUIRED_LIBRARIES = [
    "numpy", "sounddevice", "keyboard", "pyperclip", "scipy",
    "onnxruntime", "onnx", "onnx_asr", "huggingface_hub",
    "requests", "transformers", "torch",
]

def check_and_install_libraries():
    log_to_file("🔍 Проверка библиотек...")
    missing = []
    for lib in REQUIRED_LIBRARIES:
        try:
            if lib == "onnx_asr":
                importlib.import_module("onnx_asr")
            else:
                importlib.import_module(lib)
        except ImportError:
            missing.append(lib)
    if missing:
        log_to_file(f"❌ Отсутствуют: {missing}")
        try:
            root = tk.Tk(); root.withdraw()
            answer = messagebox.askyesno("Установка библиотек",
                f"Отсутствуют:\n\n{', '.join(missing)}\n\nУстановить автоматически?")
            root.destroy()
        except:
            answer = False
        if answer:
            for lib in missing:
                pip_name = "onnx-asr[cpu,hub]" if lib == "onnx_asr" else lib
                subprocess.run([sys.executable, "-m", "pip", "install", pip_name],
                               capture_output=True, text=True, timeout=120)
            messagebox.showinfo("Успех", "Библиотеки установлены. Перезапустите программу.")
            sys.exit(0)
        else:
            sys.exit(1)
    else:
        log_to_file("✅ Все библиотеки найдены")

check_and_install_libraries()

# ========== ИМПОРТЫ ==========
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
from scipy.io.wavfile import write as write_wav, read as read_wav
import onnx_asr
import onnxruntime as ort
import json
import re
import queue
import atexit
import tempfile
from collections import deque
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

log_to_file("✅ Импорты OK")
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

# ========== КОНСТАНТЫ ==========
VERSION = "FINAL_BTN"
APP_NAME = "GigaAM"
RATE = 16000
BLOCKSIZE = 1024
SILENCE_SEC = 1.5
MIN_SPEECH_FRAMES = 5
THRESHOLD_DEFAULT = 150
END_WAIT_SEC = 0.6
PRE_BUFFER_SEC = 2.0
MIN_PHRASE_LEN = 2
AUTO_RESUME_SEC = 4.0
SPELLER_TIMEOUT = 3.0
CHUNK_SECONDS = 20

# ========== КЭШ ТОКСИЧНОСТИ ==========
_toxicity_cache = {}

# ========== БЕЗОПАСНЫЕ СЛОВА ==========
SAFE_WORDS = {
    "ящик", "ящика", "ящику", "ящиком", "ящике", "ящики", "ящиков",
    "ладно", "окей", "ок", "хорошо", "нормально", "понятно", "ясно",
    "человек", "люди", "мужчина", "женщина", "ребёнок", "ребенок",
    "дети", "работа", "деньги", "время", "место", "дело", "жизнь",
    "мир", "стол", "стул", "окно", "дверь", "книга", "машина",
    "дом", "город", "страна", "школа", "улица", "река", "море",
    "небо", "солнце", "луна", "звезда", "трава", "дерево", "цветок",
    "кошка", "собака", "птица", "рыба", "вода", "земля", "огонь",
    "хлеб", "молоко", "мясо", "овощ", "фрукт", "яблоко", "груша",
    "привет", "пока", "спасибо", "пожалуйста", "здравствуйте",
    "муж", "жена", "сын", "дочь", "мама", "папа", "брат", "сестра",
    "день", "ночь", "утро", "вечер", "год", "месяц", "неделя",
    "да", "нет", "может", "надо", "нужно", "хочу", "буду", "есть",
}

# ========== НЕЙРОСЕТЬ ТОКСИЧНОСТИ ==========
_model_tox = None
_tokenizer_tox = None
_model_loaded = False
_model_loading = False

def load_toxicity_model():
    global _model_tox, _tokenizer_tox, _model_loaded, _model_loading
    if _model_loaded or _model_loading:
        return
    _model_loading = True
    log_to_file("🔄 Загрузка модели токсичности...")
    try:
        _tokenizer_tox = AutoTokenizer.from_pretrained("khvatov/ru_toxicity_detector")
        _model_tox = AutoModelForSequenceClassification.from_pretrained("khvatov/ru_toxicity_detector")
        _model_tox.eval()
        _model_loaded = True
        log_to_file("✅ Модель токсичности загружена")
    except Exception as e:
        log_to_file(f"❌ Ошибка модели токсичности: {e}")
    finally:
        _model_loading = False

threading.Thread(target=load_toxicity_model, daemon=True).start()

def is_word_toxic(word):
    if not word or len(word) < 2:
        return False
    word_lower = word.lower()
    if word_lower in SAFE_WORDS:
        return False
    if word_lower in _toxicity_cache:
        return _toxicity_cache[word_lower]
    if not _model_loaded:
        _toxicity_cache[word_lower] = False
        return False
    try:
        inputs = _tokenizer_tox(word, return_tensors="pt", truncation=True, max_length=128)
        with torch.no_grad():
            outputs = _model_tox(**inputs)
        logits = outputs.logits
        probs = torch.softmax(logits, dim=-1)[0]
        toxicity_score = probs[1].item()
        result = toxicity_score > 0.9
        _toxicity_cache[word_lower] = result
        return result
    except Exception as e:
        log_to_file(f"⚠️ is_word_toxic '{word}': {e}")
        _toxicity_cache[word_lower] = False
        return False

def censor_text(text):
    if not text:
        return text
    tokens = re.findall(r'\w+|[^\w\s]', text, re.UNICODE)
    new_tokens = []
    removed = []
    for token in tokens:
        if re.match(r'^\w+$', token, re.UNICODE):
            if is_word_toxic(token):
                removed.append(token)
                continue
        new_tokens.append(token)
    result = ' '.join(new_tokens)
    result = re.sub(r'\s+([,.;:!?])', r'\1', result)
    result = re.sub(r'\s+', ' ', result).strip()
    result = re.sub(r'^[,.;:!?]\s*', '', result)
    result = re.sub(r'^-\s*', '', result)
    result = re.sub(r'\s*[,.;:!?]$', '', result)
    if removed:
        log_to_file(f"🛡️ Удалены: {', '.join(removed)}")
    return result

# ========== КОНВЕРТАЦИЯ ==========
def convert_audio_to_wav_ffmpeg(input_path, output_path):
    cmd = ['ffmpeg', '-i', input_path, '-ar', str(RATE), '-ac', '1', '-y', output_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        if result.returncode != 0:
            raise Exception(f"Ошибка ffmpeg ({result.returncode})")
        return True
    except subprocess.TimeoutExpired:
        raise Exception("Таймаут ffmpeg")
    except FileNotFoundError:
        raise Exception("ffmpeg не найден.")

def check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True, timeout=5)
        return True
    except:
        return False

def load_audio_as_wav_16k_mono(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.wav':
        sample_rate, audio_data = read_wav(file_path)
        if sample_rate != RATE:
            from scipy.signal import resample
            num_samples = int(len(audio_data) * RATE / sample_rate)
            audio_data = resample(audio_data, num_samples)
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)
        return audio_data.astype(np.int16)
    else:
        if not check_ffmpeg():
            raise Exception("Для MP3/OGG/FLAC нужен ffmpeg.exe")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_wav = f.name
        try:
            convert_audio_to_wav_ffmpeg(file_path, temp_wav)
            sample_rate, audio_data = read_wav(temp_wav)
            if audio_data.ndim > 1:
                audio_data = audio_data.mean(axis=1)
            return audio_data.astype(np.int16)
        finally:
            if os.path.exists(temp_wav):
                os.unlink(temp_wav)

def recognize_audio_file(file_path, model_asr):
    log_to_file(f"🔍 Файл: {file_path}")
    audio_data = load_audio_as_wav_16k_mono(file_path)
    total_seconds = len(audio_data) / RATE
    log_to_file(f"📊 Длительность: {total_seconds:.1f} сек")

    chunk_size = CHUNK_SECONDS * RATE
    chunks = []
    for i in range(0, len(audio_data), chunk_size):
        chunk = audio_data[i:i+chunk_size]
        if len(chunk) >= RATE * 0.5:
            chunks.append(chunk)

    log_to_file(f"✂️ Разбито на {len(chunks)} кусков")

    results = []
    for i, chunk in enumerate(chunks):
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                write_wav(f.name, RATE, chunk)
                temp_path = f.name
            try:
                text = model_asr.recognize(temp_path).strip()
                log_to_file(f"  ✅ Кусок {i+1}/{len(chunks)}: '{text}'")
                if text:
                    results.append(text)
            finally:
                os.unlink(temp_path)
        except Exception as e:
            log_to_file(f"  ⚠️ Кусок {i+1}: {e}")
            continue

    full_text = " ".join(results).strip()
    log_to_file(f"📝 Итог: '{full_text}'")
    return full_text

# ========== ОСТАЛЬНОЕ ==========
STOP_WORDS = ['э-э', 'ээ', 'м-м', 'мм', 'ага', 'угу', 'ого', 'ой', 'ай', 'ох', 'ух', 'гм', 'хм', 'эм']
STOP_PATTERN = '|'.join([rf'\b{re.escape(w)}\b' for w in STOP_WORDS])
STOP_REGEX = re.compile(STOP_PATTERN, re.IGNORECASE)

def clean_text(text):
    if not text:
        return ""
    text = STOP_REGEX.sub('', text)
    text = re.sub(r'\b[а-яa-z]\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def normalize_punctuation(text):
    if not text:
        return text
    text = re.sub(r'^[,;:]+', '', text)
    text = re.sub(r'[,;:]+$', '', text)
    text = re.sub(r',\s*,+', ',', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r',\s*\.', '.', text)
    text = re.sub(r'\.+$', '.', text)
    if text and text[-1] not in '.!?':
        text += '.'
    return text

def is_garbage(text):
    if not text or len(text) < MIN_PHRASE_LEN:
        return True
    if len(re.sub(r'[^а-яё]', '', text.lower())) < 2:
        return True
    if re.fullmatch(r'[а-яa-z\s]+', text.lower()) and len(set(text.lower())) == 1:
        return True
    return False

executor = ThreadPoolExecutor(max_workers=2)

def correct_text_with_speller(text):
    if not text or len(text) < 3:
        return text, []
    url = "https://speller.yandex.net/services/spellservice.json/checkText"
    params = {"text": text, "lang": "ru", "options": 4}
    try:
        future = executor.submit(requests.get, url, params=params, timeout=5)
        try:
            response = future.result(timeout=SPELLER_TIMEOUT)
            if response.status_code != 200:
                return text, []
            errors = response.json()
            if not errors:
                return text, []
            corrected_text = list(text)
            corrections = []
            for error in reversed(errors):
                if error['s']:
                    start = error['pos']
                    end = start + error['len']
                    old_word = text[start:end]
                    new_word = error['s'][0]
                    corrections.append(f"'{old_word}' → '{new_word}'")
                    corrected_text[start:end] = new_word
            return "".join(corrected_text), corrections
        except FuturesTimeoutError:
            return text, []
    except Exception as e:
        log_to_file(f"⚠️ Спеллер: {e}")
        return text, []

def get_best_mic():
    try:
        devices = sd.query_devices()
        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            name = devices[default_input]['name'].lower()
            if ("microsoft sound mapper" not in name and
                "переназначение" not in name and
                "virtual" not in name and
                "reassignment" not in name and
                devices[default_input]['max_input_channels'] > 0):
                return default_input, devices[default_input]['name']
        for i, d in enumerate(devices):
            if d['max_input_channels'] > 0:
                name = d['name'].lower()
                if ("microsoft sound mapper" not in name and
                    "переназначение" not in name and
                    "virtual" not in name and
                    "reassignment" not in name):
                    return i, d['name']
        return None, "Не найден"
    except Exception as e:
        log_to_file(f"❌ Микрофон: {e}")
        return None, f"Ошибка: {e}"

lock_file = os.path.join(tempfile.gettempdir(), "gigaam_final.lock")
def is_process_running(pid):
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(1, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except:
        return False

if os.path.exists(lock_file):
    try:
        with open(lock_file, 'r') as f:
            old_pid = int(f.read().strip())
        if is_process_running(old_pid):
            sys.exit(0)
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

# ========== ГЛАВНОЕ ОКНО ==========
class GigaAMApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"GigaAM {VERSION}")
        self.root.geometry("600x760")
        self.root.minsize(600, 760)
        self.root.configure(bg="#f0f0f0")
        self.root.attributes('-topmost', True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.model_asr = None
        self.listening = False
        self.device = None
        self.mic_name = "Не определён"
        self.last_orig = ""
        self.last_final = ""
        self.corr_path = os.path.join(SCRIPT_DIR, "corrections.json")
        self.threshold = THRESHOLD_DEFAULT
        self.running = True
        self._closing = False

        self.noise_history = deque(maxlen=100)
        self.silent_frames = 0
        self.recording = False
        self.current_rec = []
        self.record_start = 0
        self.speech_counter = 0
        self.end_wait_frames = 0
        self.pre_buffer = []
        self.pre_max = int(PRE_BUFFER_SEC * RATE / BLOCKSIZE)
        self.last_activity_time = time.time()

        self.task_queue = queue.Queue(maxsize=3)
        self.hotkey_queue = queue.Queue()
        self.volume_history = deque(maxlen=5)

        self.create_widgets()
        self.start_worker()
        self.start_hotkey_poller()

        threading.Thread(target=self.init_background, daemon=True).start()
        threading.Thread(target=self.hotkey_thread, daemon=True).start()

    def create_widgets(self):
        main = tk.Frame(self.root, bg="#f0f0f0")
        main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        header = tk.Frame(main, bg="#2c3e50", relief=tk.RAISED, borderwidth=2, height=150)
        header.pack(fill=tk.X, pady=(0, 4))
        header.pack_propagate(False)

        left = tk.Frame(header, bg="#2c3e50")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)

        tk.Label(left, text="🎤 GigaAM Complete", font=("Segoe UI", 16, "bold"),
                 bg="#2c3e50", fg="white", anchor="w").pack(fill=tk.X)
        tk.Label(left, text=f"v{VERSION} – кнопка F2 корректно обновляется", font=("Segoe UI", 10),
                 bg="#2c3e50", fg="#bdc3c7", anchor="w").pack(fill=tk.X)
        tk.Label(left, text="Разработчик: Боярский Игорь Юрьевич", font=("Segoe UI", 11, "bold"),
                 bg="#2c3e50", fg="#f1c40f", anchor="w").pack(fill=tk.X)

        desc = "Голос → текст. F2 — пауза, F3 — исправить, F4 — свернуть."
        tk.Label(left, text=desc, font=("Segoe UI", 9), bg="#2c3e50", fg="#c0d0e0",
                 justify=tk.LEFT, anchor="w").pack(fill=tk.X)

        self.mic_label = tk.Label(left, text="🎙️ Микрофон: поиск...", font=("Segoe UI", 9, "bold"),
                                  bg="#2c3e50", fg="#2ecc71", anchor="w")
        self.mic_label.pack(fill=tk.X, pady=(2, 0))

        right = tk.Frame(header, bg="#2c3e50", width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=5)
        right.pack_propagate(False)

        tk.Label(right, text="📞 +7 905 570-28-04", font=("Segoe UI", 10, "bold"),
                 bg="#2c3e50", fg="#ecf0f1", anchor="e").pack(fill=tk.X)
        tk.Label(right, text="✉️ boyarskiyiu@yandex.ru", font=("Segoe UI", 10),
                 bg="#2c3e50", fg="#ecf0f1", anchor="e").pack(fill=tk.X, pady=(2, 2))
        tk.Label(right, text="GitHub: boyarskiyiu/GigaAM", font=("Segoe UI", 9),
                 bg="#2c3e50", fg="#3498db", anchor="e").pack(fill=tk.X)
        tk.Label(right, text="© 2026 Боярский И.Ю.", font=("Segoe UI", 9, "bold"),
                 bg="#2c3e50", fg="#f1c40f", anchor="e").pack(fill=tk.X)

        status = tk.Frame(main, bg="#f0f0f0", relief=tk.SUNKEN, borderwidth=1)
        status.pack(fill=tk.X, pady=(0, 4))

        self.status_label = tk.Label(status, text="⏳ Инициализация...", font=("Segoe UI", 10, "bold"),
                                     bg="#f0f0f0")
        self.status_label.pack(side=tk.LEFT, padx=4)

        vol_frame = tk.Frame(status, bg="#f0f0f0")
        vol_frame.pack(side=tk.RIGHT, padx=4)
        self.volume_label = tk.Label(vol_frame, text="0%", font=("Segoe UI", 9),
                                     bg="#f0f0f0", width=3)
        self.volume_label.pack(side=tk.RIGHT, padx=(3, 0))
        self.volume_indicator = ttk.Progressbar(vol_frame, mode='determinate', length=60, maximum=100)
        self.volume_indicator.pack(side=tk.RIGHT)

        self.listening_label = tk.Label(status, text="○ ПАУЗА", font=("Segoe UI", 9, "bold"),
                                        bg="#f0f0f0", fg="#c62828")
        self.listening_label.pack(side=tk.RIGHT, padx=(10, 0))

        log_frame = tk.LabelFrame(main, text="Лог работы", bg="#f0f0f0",
                                  font=("Segoe UI", 9, "bold"), relief=tk.RIDGE, borderwidth=2)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=8,
                                                  bg="#ffffff", fg="#000000", font=("Consolas", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        phrase_frame = tk.LabelFrame(main, text="Последняя распознанная фраза", bg="#f0f0f0",
                                     font=("Segoe UI", 9, "bold"), relief=tk.RIDGE, borderwidth=2)
        phrase_frame.pack(fill=tk.X, pady=(0, 4))

        self.phrase_text = tk.Text(phrase_frame, height=3, wrap=tk.WORD,
                                   bg="#ffffff", fg="#000000", font=("Segoe UI", 11),
                                   relief=tk.SUNKEN, borderwidth=2)
        self.phrase_text.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        btn_frame = tk.Frame(main, bg="#f0f0f0")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=4)

        for i in range(3):
            btn_frame.columnconfigure(i, weight=1)

        style = {"relief": tk.RAISED, "borderwidth": 2, "padx": 2, "pady": 6, "font": ("Segoe UI", 8)}

        # ---- ВАЖНО: сохраняем кнопку в self, чтобы её можно было менять ----
        self.btn_pause = tk.Button(btn_frame, text="⏸ Пауза (F2)", command=self.toggle_listening,
                                   bg="#4caf50", fg="white", **style)
        self.btn_pause.grid(row=0, column=0, padx=2, pady=2, sticky="ew")

        tk.Button(btn_frame, text="✏️ Исправить (F3)", command=self.fix_last_phrase,
                  bg="#2196f3", fg="white", **style).grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        tk.Button(btn_frame, text="📂 Распознать файл", command=self.recognize_audio_file,
                  bg="#ff9800", fg="white", **style).grid(row=0, column=2, padx=2, pady=2, sticky="ew")
        tk.Button(btn_frame, text="🗕 Свернуть (F4)", command=self.minimize_window,
                  bg="#9e9e9e", fg="white", **style).grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        tk.Button(btn_frame, text="🔄 Обновить", command=self.check_updates,
                  bg="#4caf50", fg="white", **style).grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        tk.Button(btn_frame, text="ℹ️ О прогр.", command=self.show_about,
                  bg="#607d8b", fg="white", **style).grid(row=1, column=2, padx=2, pady=2, sticky="ew")

    def log(self, msg, append=False):
        ts = datetime.now().strftime("%H:%M:%S")
        full_msg = msg if append else f"[{ts}] {msg}"
        try:
            self.log_text.insert(tk.END, full_msg + "\n")
            self.log_text.see(tk.END)
            self.root.update_idletasks()
        except:
            pass
        log_to_file(full_msg)

    def set_status(self, text, color="#555"):
        try:
            self.status_label.config(text=text, fg=color)
        except:
            pass

    def start_worker(self):
        def worker():
            while self.running:
                try:
                    audio = self.task_queue.get(timeout=0.5)
                    if audio is None:
                        continue
                    self._recognize_and_paste(audio, source="live")
                except queue.Empty:
                    continue
                except Exception as e:
                    log_to_file(f"Worker error: {e}\n{traceback.format_exc()}")
        threading.Thread(target=worker, daemon=True).start()

    def start_hotkey_poller(self):
        """Опрос очереди горячих клавиш — вызов GUI строго через root.after"""
        def poller():
            while self.running:
                try:
                    key = self.hotkey_queue.get(timeout=0.3)
                    if key == "F2":
                        self.root.after(0, self.toggle_listening)
                    elif key == "F3":
                        self.root.after(0, self.fix_last_phrase)
                    elif key == "F4":
                        self.root.after(0, self.minimize_window)
                except queue.Empty:
                    continue
                except Exception as e:
                    log_to_file(f"Hotkey poller error: {e}")
        threading.Thread(target=poller, daemon=True).start()
        log_to_file("✅ Hotkey poller запущен")

    def hotkey_thread(self):
        time.sleep(1)
        try:
            keyboard.unhook_all_hotkeys()
        except:
            pass
        try:
            keyboard.add_hotkey('F2', lambda: self.hotkey_queue.put("F2"), suppress=True)
            keyboard.add_hotkey('F3', lambda: self.hotkey_queue.put("F3"), suppress=True)
            keyboard.add_hotkey('F4', lambda: self.hotkey_queue.put("F4"), suppress=True)
            self.log("✅ Горячие клавиши зарегистрированы")
        except Exception as e:
            self.log(f"⚠️ Ошибка регистрации горячих клавиш: {e}")

    def toggle_listening(self):
        if self.model_asr is None:
            self.log("⚠️ Модель распознавания ещё не загружена")
            return
        self.listening = not self.listening
        if self.listening:
            # Обновляем и индикатор, и кнопку
            self.listening_label.config(text="● СЛУШАЮ", fg="#2e7d32")
            self.btn_pause.config(text="⏸ Пауза (F2)", bg="#ff9800")
            self.log("▶ Возобновление работы")
            self.set_status("Слушаю...", "#2e7d32")
            self._reset_vad_state()
        else:
            self.listening_label.config(text="○ ПАУЗА", fg="#c62828")
            self.btn_pause.config(text="▶ Возобновить (F2)", bg="#4caf50")
            self.log("⏸ Пауза")
            self.set_status("Пауза", "#c62828")

    def _reset_vad_state(self):
        self.silent_frames = 0
        self.recording = False
        self.current_rec = []
        self.speech_counter = 0
        self.end_wait_frames = 0
        self.pre_buffer = []
        self.last_activity_time = time.time()

    def minimize_window(self):
        self.root.iconify()
        log_to_file("🗕 Окно свёрнуто")

    def fix_last_phrase(self):
        if not self.last_orig:
            messagebox.showinfo("Исправление", "Нет фразы для исправления.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Исправление фразы")
        dialog.geometry("600x380")
        dialog.configure(bg="#f0f0f0")
        dialog.transient(self.root)
        dialog.attributes('-topmost', True)
        x = self.root.winfo_x() + (self.root.winfo_width() - 600) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 380) // 2
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text="Неправильно:", bg="#f0f0f0", font=("Segoe UI", 10, "bold")).pack(pady=(6,0))
        wrong_text = tk.Text(dialog, height=3, wrap=tk.WORD, font=("Segoe UI", 9))
        wrong_text.insert(1.0, self.last_orig)
        wrong_text.config(state='disabled')
        wrong_text.pack(pady=3, padx=8, fill=tk.X)

        tk.Label(dialog, text="Правильный текст:", bg="#f0f0f0", font=("Segoe UI", 10, "bold")).pack()
        correct_text = tk.Text(dialog, height=5, wrap=tk.WORD, font=("Segoe UI", 9))
        correct_text.pack(pady=3, padx=8, fill=tk.BOTH, expand=True)

        def save():
            corr = correct_text.get("1.0", tk.END).strip()
            if corr and corr != self.last_orig:
                data = {}
                if os.path.exists(self.corr_path):
                    with open(self.corr_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                data[self.last_orig] = corr
                with open(self.corr_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self.log(f"💾 Исправление: '{self.last_orig}' → '{corr}'")
                messagebox.showinfo("Успех", "Сохранено!")
                dialog.destroy()
        tk.Button(dialog, text="Сохранить", command=save, bg="#4caf50", fg="white",
                  width=14, font=("Segoe UI", 9, "bold")).pack(pady=8)

    def recognize_audio_file(self):
        if self.model_asr is None:
            messagebox.showerror("Ошибка", "Модель распознавания не загружена.")
            return
        file_path = filedialog.askopenfilename(
            title="Выберите аудиофайл",
            filetypes=[("Аудио файлы", "*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.wma"),
                       ("Все файлы", "*.*")]
        )
        if not file_path:
            return
        self.log(f"🔄 Распознавание: {os.path.basename(file_path)}")
        self.set_status("Распознаю файл...", "#e67e22")
        threading.Thread(target=self._recognize_file_thread, args=(file_path,), daemon=True).start()

    def _recognize_file_thread(self, file_path):
        try:
            raw = recognize_audio_file(file_path, self.model_asr)
            if raw:
                self.root.after(0, lambda: self._on_file_recognized(raw, file_path))
            else:
                self.root.after(0, lambda: self._on_file_error("Пустой результат"))
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self._on_file_error(error_msg))

    def _on_file_recognized(self, raw, source_file_path):
        self.log(f"📝 Текст: '{raw}'")
        text = self.process_recognized_text(raw, source="file")
        if text:
            self.log(f"✅ Результат: {text}")
            self.update_phrase(text)
            self.save_text_with_dialog(text, source_file_path)
        else:
            self.log("⚠️ Результат пустой")
        self.set_status("Готов к работе", "#2e7d32")

    def _on_file_error(self, error_msg):
        self.log(f"❌ Ошибка: {error_msg}")
        messagebox.showerror("Ошибка", f"Ошибка распознавания:\n{error_msg}")
        self.set_status("Готов к работе", "#2e7d32")

    def save_text_with_dialog(self, text, source_file_path=None):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default_filename = f"recognized_{timestamp}.txt"
        initial_dir = os.path.dirname(source_file_path) if source_file_path else SESSIONS_DIR
        file_path = filedialog.asksaveasfilename(
            title="Сохранить распознанный текст",
            defaultextension=".txt",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
            initialfile=default_filename,
            initialdir=initial_dir
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.log(f"💾 Сохранено в {file_path}")
                messagebox.showinfo("Успех", f"Текст сохранён в:\n{file_path}")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}")

    def process_recognized_text(self, raw, source="live"):
        if not raw:
            return None
        self.last_orig = raw
        text = raw

        if os.path.exists(self.corr_path):
            with open(self.corr_path, 'r', encoding='utf-8') as cf:
                corr = json.load(cf)
            for wrong, right in corr.items():
                text = text.replace(wrong, right)

        corrected_text, corrections = correct_text_with_speller(text)
        if corrections:
            self.log(f"🔧 Спеллер: {', '.join(corrections)}")
        text = corrected_text

        text = clean_text(text)
        text = re.sub(r'\s+', ' ', text).strip()
        text = normalize_punctuation(text)
        if text:
            text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()

        if is_garbage(text):
            self.log(f"🚫 Мусор: '{text}'")
            return None

        self.log("🧠 Проверка на токсичность...", append=True)
        censored = censor_text(text)
        text = censored
        return text

    def on_close(self):
        if self._closing:
            return
        self._closing = True
        if messagebox.askyesno("Выход", "Завершить программу?"):
            self.running = False
            while not self.task_queue.empty():
                try:
                    self.task_queue.get_nowait()
                except:
                    break
            if hasattr(self, 'stream') and self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except:
                    pass
            self.root.quit()
            self.root.destroy()
            sys.exit(0)
        else:
            self._closing = False

    def check_updates(self):
        self.log("🔄 Проверка обновлений...")
        try:
            import webbrowser
            resp = requests.get(
                "https://api.github.com/repos/boyarskiyiu/GigaAM-Voice-Typer/releases/latest",
                timeout=5
            )
            if resp.status_code == 200:
                latest = resp.json().get("tag_name", "").replace("v", "")
                if latest and latest != VERSION:
                    if messagebox.askyesno("Обновление", f"Доступна версия {latest}. Открыть?"):
                        webbrowser.open("https://github.com/boyarskiyiu/GigaAM-Voice-Typer/releases/latest")
                else:
                    messagebox.showinfo("Актуально", "У вас последняя версия.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось проверить:\n{e}")

    def show_about(self):
        messagebox.showinfo("О программе",
            f"GigaAM Complete v{VERSION}\n\n"
            "Разработчик: Боярский Игорь Юрьевич\n"
            "© 2026 Все права защищены.\n\n"
            "🔊 Модель: GigaAM-v3-e2e-rnnt\n"
            f"✂️ Разбивка аудио на куски по {CHUNK_SECONDS} сек\n"
            "🧠 Модель токсичности: khvatov/ru_toxicity_detector\n"
            "🎚️ VAD: 5 фреймов, пауза 1.5 сек\n"
            "📁 Форматы: WAV, MP3, OGG, FLAC\n"
            "💾 Сохранение сессий в папку sessions/\n\n"
            "Репозиторий: github.com/boyarskiyiu/GigaAM-Voice-Typer")

    def init_background(self):
        try:
            self.log("=" * 55)
            self.log("GigaAM Complete – запуск")

            mic_id, mic_name = get_best_mic()
            if mic_id is None:
                self.log("❌ Микрофон не найден.")
                self.set_status("Ошибка микрофона", "#c62828")
                return
            self.device = mic_id
            self.mic_name = mic_name
            self.mic_label.config(text=f"🎙️ Микрофон: {mic_name}")
            self.log(f"🎤 Микрофон: {mic_name}")

            self.log("📥 Загрузка модели распознавания...")
            self.set_status("⏳ Загрузка модели...", "#e67e22")
            try:
                providers = ['CPUExecutionProvider']
                if 'CUDAExecutionProvider' in ort.get_available_providers():
                    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                self.model_asr = onnx_asr.load_model("gigaam-v3-e2e-rnnt", providers=providers)
                self.log("✅ Модель распознавания загружена")
            except Exception as e:
                self.log(f"❌ Ошибка загрузки модели: {e}")
                self.set_status("Ошибка модели", "#c62828")
                log_to_file(f"Ошибка модели: {e}\n{traceback.format_exc()}")
                return

            self.log("🔊 Калибровка шума (3 сек)...")
            try:
                rec = sd.rec(int(3 * RATE), samplerate=RATE, channels=1, dtype='int16', device=self.device)
                sd.wait()
                noise_avg = np.mean(np.abs(rec))
                noise_max = np.max(np.abs(rec))
                self.threshold = max(noise_avg * 4 + 50, noise_max * 0.6, 120)
                self.threshold = min(self.threshold, 400)
                self.log(f"🔊 Порог: {int(self.threshold)}")
            except Exception as e:
                self.threshold = THRESHOLD_DEFAULT
                self.log(f"⚠️ Калибровка не удалась: {self.threshold}")

            if not os.path.exists(self.corr_path):
                with open(self.corr_path, 'w') as f:
                    json.dump({}, f)

            try:
                self.stream = sd.InputStream(device=self.device, samplerate=RATE, channels=1,
                                             dtype='int16', blocksize=BLOCKSIZE, callback=self.audio_callback)
                self.stream.start()
                self.log("🎙️ Аудиопоток запущен")
            except Exception as e:
                self.log(f"❌ Ошибка аудиопотока: {e}")
                return

            self.set_status("Готов к работе", "#2e7d32")
            self.log("✅ Готов к работе.")
            self.root.after(500, self.toggle_listening)
        except Exception as e:
            self.log(f"❌ Критическая ошибка: {e}")
            log_to_file(f"Критическая ошибка: {e}\n{traceback.format_exc()}")

    def update_volume(self, value):
        try:
            current = self.volume_indicator['value']
            if abs(current - value) > 2:
                self.volume_indicator.configure(value=value)
                self.volume_label.config(text=f"{int(value)}%")
        except:
            pass

    def audio_callback(self, indata, frames, time_info, status):
        try:
            vol = np.max(np.abs(indata))
            norm_vol = min(100, int(np.log10(vol / 100 + 1) * 20)) if vol > 0 else 0
            self.volume_history.append(norm_vol)
            smoothed = sum(self.volume_history) / len(self.volume_history)
            self.root.after(0, lambda: self.update_volume(smoothed))

            if not self.listening or self.model_asr is None:
                self._reset_vad_state()
                return

            if vol > 10:
                self.last_activity_time = time.time()

            if time.time() - self.last_activity_time > AUTO_RESUME_SEC:
                if self.recording:
                    self._reset_vad_state()
                return

            self.pre_buffer.append(indata.copy())
            if len(self.pre_buffer) > self.pre_max:
                self.pre_buffer.pop(0)

            is_speech = vol > self.threshold

            if is_speech:
                self.silent_frames = 0
                self.end_wait_frames = 0
                self.speech_counter += 1
                if not self.recording and self.speech_counter >= MIN_SPEECH_FRAMES:
                    self.recording = True
                    self.current_rec = list(self.pre_buffer)
                    self.record_start = time.time()
                    self.log("🎙️ Начало речи", append=True)
                    self.set_status("Слушаю...", "#2e7d32")
                elif self.recording:
                    self.current_rec.append(indata.copy())
            else:
                if self.recording:
                    self.silent_frames += 1
                    frames_per_sec = RATE / BLOCKSIZE
                    silence_needed = int(SILENCE_SEC * frames_per_sec)
                    end_wait_needed = int(END_WAIT_SEC * frames_per_sec)
                    if self.silent_frames <= silence_needed + end_wait_needed:
                        self.current_rec.append(indata.copy())
                    if self.silent_frames > silence_needed:
                        self.end_wait_frames += 1
                        if self.end_wait_frames >= end_wait_needed:
                            self.recording = False
                            if self.current_rec:
                                dur = time.time() - self.record_start
                                if dur >= 0.5 and self.speech_counter >= MIN_SPEECH_FRAMES:
                                    self.log("⏹️ Отправка на распознавание...", append=True)
                                    self.set_status("Распознаю...", "#e67e22")
                                    audio = np.concatenate(self.current_rec, axis=0).flatten()
                                    try:
                                        self.task_queue.put(audio, block=False)
                                    except queue.Full:
                                        pass
                            self.current_rec = []
                            self.silent_frames = 0
                            self.end_wait_frames = 0
                            self.speech_counter = 0
                else:
                    if self.speech_counter > 0:
                        self.speech_counter -= 1
                    self.silent_frames = 0
        except Exception as e:
            log_to_file(f"⚠️ audio_callback: {e}")

    def _recognize_and_paste(self, audio, source="live"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                write_wav(f.name, RATE, audio.astype(np.int16))
                f.flush()
                temp_path = f.name
            try:
                raw = self.model_asr.recognize(temp_path).strip()
            finally:
                try:
                    os.unlink(temp_path)
                except:
                    pass

            if not raw:
                self.log("⚠️ Не распознано")
                return

            self.log(f"📝 Исходный текст: '{raw}'")
            text = self.process_recognized_text(raw, source=source)
            if text is None:
                return

            save_unique_text(text, prefix="live")
            self.update_phrase(text)
            self.paste(text)
            self.last_final = text
            self.log(f"✅ {text}")
        except Exception as e:
            self.log(f"❌ Ошибка распознавания: {e}")
            log_to_file(f"Ошибка распознавания: {e}\n{traceback.format_exc()}")
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
        except:
            try:
                import pyautogui
                pyautogui.write(text, interval=0.03)
            except Exception as e:
                self.log(f"   ❌ Не удалось вставить: {e}")

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    root = tk.Tk()
    app = GigaAMApp(root)
    root.mainloop()