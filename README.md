# 🎤 GigaAM Complete — Голосовой ввод с ИИ

![Version](https://img.shields.io/badge/version-2.0.41-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)

**Разработчик:** Боярский Игорь Юрьевич  
📞 +7 905 570-28-04  
✉️ boyarskiyiu@yandex.ru  
© 2026 Все права защищены.

## ✨ Что нового в 2.0.41
*   🪄 **Окно больше не висит поверх всех**: убран режим `-topmost`, теперь программа ведёт себя как обычное приложение, но при активации поднимается на передний план.
*   🚀 **Полная защита от повторного запуска**: благодаря связке `lock-файл` + `Windows Mutex` запустить вторую копию программы невозможно.
*   🌐 **Асинхронный Яндекс.Спеллер с таймаутом**: программа больше не «зависает» при медленном интернете. Если сервер не отвечает за 2 секунды, текст вставляется без проверки орфографии.
*   ⚡ **Общая оптимизация**: фоновые потоки для загрузки модели и распознавания речи исключают любые подвисания интерфейса.

## 📥 Установка

### 🚀 Быстрый запуск
1. Скачайте `GigaAM_Complete.pyw` из [Releases](https://github.com/boyarskiyiu/GigaAM-Voice-Typer/releases/latest).
2. Запустите двойным щелчком.

### 🛠 Для разработчиков
```bash
git clone https://github.com/boyarskiyiu/GigaAM-Voice-Typer
cd GigaAM-Voice-Typer
pip install -r requirements.txt
pythonw GigaAM_Source.py