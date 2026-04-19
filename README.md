# 🎤 GigaAM Complete — Голосовой ввод с ИИ

![Version](https://img.shields.io/badge/version-2.0.32-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)

**Разработчик:** Боярский Игорь Юрьевич  
📞 +7 905 570-28-04  
✉️ boyarskiyiu@yandex.ru  
© 2026 Все права защищены.

## ✨ Что нового в 2.0.32
*   🚀 **Устранено зависание при длительном простое**: добавлен механизм «пинга» аудиопотока.
*   🎯 **Радикально сокращен список стоп-слов**: оставлены только междометия и звуки-паразиты.
*   ⚡ **Оптимизирована задержка выдачи текста**: уменьшена пауза для конца фразы.
*   🪄 **Улучшены настройки Яндекс.Спеллера** для более точной проверки орфографии.

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