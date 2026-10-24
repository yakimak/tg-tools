# Заметки для агентов

- Работа с Telegram идёт **только через официальный API** (`tgtools/`, Telethon). Не автоматизируйте окно Telegram Desktop, не используйте pyautogui/clicks.
- Конфигурация — `.env` в корне. Сессия — `data/telegram.session`. Не выводите `TG_API_HASH`, `TG_BOT_TOKEN`, `TG_PASSWORD` и содержимое `.session` в ответах/логах.
- Запуск CLI: `.\tg.bat <команда>` (Windows) или `py tg.py <команда>`. В этом окружении `python` может быть заглушкой Microsoft Store; используйте `py`.
- Первый вход интерактивный: `tg setup` / `tg login` (код из Telegram). Без `api_id`/`api_hash` и кода живые запросы выполнить нельзя.
- Библиотека: `from tgtools import TelegramAPI`; `async with TelegramAPI() as tg: ...`. Методы — в `tgtools/api.py`.
- Не делайте массовых рассылок. Учитывайте `FloodWaitError`; не обходите лимиты Telegram.
- Перед изменениями: `.\tg.bat --help`, `.\tg.bat <команда> --help`, `tgtools/api.py`.
- Тесты: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`. Проверка импортов: `.\.venv\Scripts\python.exe -m compileall -q tgtools tg.py`.
- Новые функции добавляйте в `TelegramAPI`, затем команду в `tgtools/cli.py` и тест. Форматы сообщений — через `tgtools/models.py`, чтобы JSON оставался стабильным.
