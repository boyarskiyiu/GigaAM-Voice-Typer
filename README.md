# 🎤 GigaAM Complete — Голосовой ввод с ИИ

![Version](https://img.shields.io/badge/version-2.0.26-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)

**GigaAM Complete** — программа для распознавания русской речи в реальном времени с автоматической вставкой текста в любое активное окно. Использует модель **GigaAM-v3** от Сбера (точность ~3.3% WER) и **Яндекс.Спеллер** для исправления опечаток.

## ✨ Возможности

- 🎯 Высочайшая точность распознавания русского языка
- 🔄 Автоматическая вставка текста в активное приложение (Word, блокнот, браузер)
- 📚 Сохранение исправлений для повторяющихся ошибок
- 🪄 Яндекс.Спеллер исправляет опечатки и повторы
- ⚡ Горячие клавиши: **F2** — пауза/продолжить, **F3** — исправить последнюю фразу, **F4** — свернуть
- 🌐 Окно всегда поверх других (можно отключить)
- 🔄 Автообновление с GitHub
- 📦 Автоустановка зависимостей и модели при первом запуске (только для `GigaAM_Complete.pyw`)

## 📥 Установка и запуск

### 🚀 Способ 1: Быстрый запуск (рекомендуется)

1. Скачайте `GigaAM_Complete.pyw` из [Releases](https://github.com/boyarskiyiu/GigaAM-Voice-Typer/releases/latest).
2. Запустите двойным щелчком. При первом запуске установятся все библиотеки и модель GigaAM (~500 МБ).

> 💡 Если появляется консоль, создайте ярлык:  
> `"путь\к\pythonw.exe" "путь\к\GigaAM_Complete.pyw"`

### 🛠 Способ 2: Для разработчиков

```bash
git clone https://github.com/boyarskiyiu/GigaAM-Voice-Typer
cd GigaAM-Voice-Typer
pip install -r requirements.txt
pythonw GigaAM_Source.py