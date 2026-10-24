# TG Tools

Готовый инструмент для работы с Telegram **только через официальный API** (MTProto, библиотека [Telethon](https://docs.telethon.dev/)). Никакой автоматизации окна Telegram Desktop, кликов и скриншотов: приложение общается с серверами Telegram напрямую.

Telegram Desktop может быть открыт параллельно — он нужен только для того, чтобы удобно получить код входа. Все действия выполняются от вашего личного аккаунта (или бота) и сохраняются в обычной сессии.

## Что умеет

- читать сообщения, историю, искать по тексту;
- отправлять текст, файлы и альбомы;
- скачивать фото/видео/документы/голосовые/стикеры — по одному или массово из чата;
- пересылать, редактировать, удалять, закреплять сообщения;
- показывать список чатов, информацию о чате, участников;
- вступать/выходить из каналов и групп, создавать группы;
- экспортировать историю в JSONL;
- слушать новые сообщения в реальном времени (`watch`);
- использовать всё это из Python как обычные асинхронные функции.

## Быстрый старт (Windows)

Откройте PowerShell или cmd в папке проекта:

```powershell
cd "C:\Users\Максим\Desktop\TG Tools"
.\tg.bat setup
```

`tg.bat` сам создаст `.venv` и установит зависимости при первом запуске. Дальше можно работать коротко:

```powershell
.\tg.bat chats
.\tg.bat read @durov --limit 10
```

### 1. Получите api_id и api_hash

1. Откройте <https://my.telegram.org> и войдите по номеру телефона.
2. Перейдите в **API development tools**.
3. Создайте приложение (название и платформа — любые).
4. Скопируйте `api_id` (число) и `api_hash` (32 символа).

Это официальные данные приложения Telegram, а не токен бота. Они нужны Telethon для подключения.

### 2. Введите данные

Мастер `setup` спросит:

- `TG_API_ID` — число;
- `TG_API_HASH` — 32 символа;
- телефон в формате `+79991234567`;
- режим: `user` (личный аккаунт) или `bot`;
- папку для скачивания.

Настройки сохраняются в `.env`. Файл сессии появится в `data/telegram.session` после входа.

### 3. Войдите

Код придёт в Telegram — в том числе в открытое Desktop-приложение. Введите его в терминале. Если включена двухэтапная аутентификация, попросит пароль 2FA.

```powershell
.\tg.bat login
```

Готово. Проверка:

```powershell
.\tg.bat me
```

> В этом окружении команда `python` может быть заглушкой Microsoft Store. Используйте `tg.bat` или `py`. Внутри `tg.bat` уже прописан путь к `.venv`.

## Команды

Полная справка: `.\tg.bat --help` и `.\tg.bat <команда> --help`.

| Команда | Что делает |
|---|---|
| `setup` | Настроить api_id/api_hash и войти |
| `login` | Войти в аккаунт |
| `me` | Показать текущий аккаунт |
| `chats` | Список чатов (личные, группы, каналы) |
| `read <чат>` | Прочитать сообщения |
| `search <чат> <текст>` | Поиск сообщений в чате |
| `send <чат> <текст>` | Отправить сообщение |
| `send-file <чат> <файлы...>` | Отправить файл или альбом |
| `download <ссылка>` | Скачать медиа по ссылке на сообщение |
| `download-message <чат> <id>` | Скачать медиа по id сообщения |
| `download-chat <чат>` | Массово скачать медиа из чата |
| `info <чат>` | Информация о чате/канале/пользователе |
| `participants <чат>` | Участники группы/канала |
| `forward <откуда> <куда> <id...>` | Переслать сообщения |
| `delete <чат> <id...>` | Удалить сообщения |
| `edit <чат> <id> <текст>` | Изменить текст |
| `mark-read <чат>` | Отметить прочитанным |
| `pin` / `unpin` | Закрепить/открепить сообщение |
| `join <ссылка>` | Вступить в канал/группу |
| `leave <чат>` | Выйти из группы/канала |
| `create-group <название> <участники...>` | Создать группу |
| `export <чат>` | Экспортировать историю в JSONL |
| `watch [чаты...]` | Слушать новые сообщения |

### Примеры

```powershell
# Последние 20 сообщений из канала
.\tg.bat read @durov --limit 20

# Только сообщения с медиа за последние 7 дней
.\tg.bat read @channel --media-only --since 7d

# Отправить сообщение (Markdown поддерживается)
.\tg.bat send @username "**Привет!** Как дела?"

# Обычный текст без разметки
.\tg.bat send @username "Текст *со звёздочками*" --plain

# Ответить на сообщение
.\tg.bat send @username "Согласен" --reply-to 12345

# Отправить файл или несколько файлов (альбом до 10 штук)
.\tg.bat send-file @username photo.jpg
.\tg.bat send-file @username photo1.jpg photo2.jpg --caption "Смотри"

# Скачать файл по ссылке на сообщение
.\tg.bat download "https://t.me/channel/123" -o downloads

# Скачать все фото и видео из чата (до 500 штук)
.\tg.bat download-chat @channel --type photo,video --limit 500

# История в JSONL
.\tg.bat export @channel -o channel.jsonl

# Слушать новые сообщения и выводить JSON-строками
.\tg.bat watch @channel --json

# Удалить сообщения у всех
.\tg.bat delete @channel 101 102 103

# Сначала посмотреть, что будет удалено
.\tg.bat delete @channel 101 102 --dry-run
```

### Даты

Параметры `--since` / `--until` понимают:

- `2026-10-25`, `25.10.2026`, `2026-10-25 18:30`;
- относительные интервалы: `30m`, `2h`, `7d`, `1w`;
- `today`, `yesterday` (и русские варианты);
- Unix timestamp.

### Машиночитаемый вывод

У любой команды есть `--json` (можно ставить до или после команды):

```powershell
.\tg.bat read @channel --limit 5 --json
$messages = .\tg.bat read @channel --limit 5 --json | ConvertFrom-Json
```

Служебные сообщения пишутся в stderr, JSON — в stdout, поэтому его можно безопасно передавать в пайплайны.

## Python API

```python
import asyncio
from tgtools import TelegramAPI

async def main():
    # Настройки берутся из .env, сессия — из data/telegram.session
    async with TelegramAPI() as tg:
        me = await tg.get_me()
        print(me["title"])

        chats = await tg.list_chats(limit=10)
        messages = await tg.read_messages("@durov", limit=20)
        for message in messages:
            print(message["date"], message["sender_name"], message["text"])

        await tg.send_message("@username", "Привет из Python")
        await tg.send_file("@username", "photo.jpg", caption="Файл")

        await tg.download_by_link(
            "https://t.me/channel/123",
            "downloads",
        )
        await tg.download_chat_media(
            "@channel",
            limit=100,
            media_types={"photo", "video"},
            dest="downloads/channel",
        )

asyncio.run(main())
```

Запуск примера из папки проекта:

```powershell
.\.venv\Scripts\python.exe examples\read_and_export.py
```

### Основные методы

```python
# Чаты
await tg.list_chats(limit=50, archived=False, folder=None)
await tg.get_chat_info("@username", full=True)
await tg.get_participants("@group", limit=200, search="")
await tg.join_chat("https://t.me/+invite")
await tg.leave_chat("@group")
await tg.create_group("Название", ["@user1", "@user2"])

# Сообщения
await tg.read_messages(chat, limit=20, search=None, since=None, until=None,
                       reverse=False, from_user=None, media_only=False)
await tg.search_messages(chat, "текст", limit=50)
await tg.get_message(chat, 123)
await tg.send_message(chat, "текст", reply_to=None, silent=False,
                      parse_mode="md", link_preview=True)
await tg.send_file(chat, ["a.jpg", "b.jpg"], caption="Альбом")
await tg.edit_message(chat, 123, "новый текст")
await tg.delete_messages(chat, [123, 124], revoke=True)
await tg.forward_messages(from_chat, [123], to_chat)
await tg.mark_read(chat)
await tg.pin_message(chat, 123)
await tg.unpin_message(chat)

# Файлы
await tg.download_media(chat, 123, dest=None, skip_existing=True)
await tg.download_by_link("https://t.me/channel/123", "downloads")
await tg.download_chat_media(chat, limit=100, media_types=None,
                             dest=None, since=None, until=None)

# Экспорт и события
await tg.export_messages(chat, "out.jsonl", limit=0)
async for message in tg.iter_new_messages(["@channel"], incoming=True):
    print(message["text"])
```

Полный список — в `tgtools/api.py`, у методов есть docstring'и и понятные параметры.

### Формат сообщения

`read_messages` и другие методы возвращают словари:

```json
{
  "id": 123,
  "date": "2026-10-25T10:30:00+00:00",
  "edit_date": null,
  "chat_id": -100123456789,
  "chat_title": "Канал",
  "chat_username": "channel",
  "sender_id": 42,
  "sender_name": "Иван",
  "sender_username": "ivan",
  "text": "Привет",
  "out": false,
  "post": true,
  "reply_to": null,
  "topic_id": null,
  "views": 100,
  "forwards": 2,
  "grouped_id": null,
  "pinned": false,
  "has_media": true,
  "media": {
    "type": "photo",
    "file_name": null,
    "size": 123456,
    "mime_type": "image/jpeg",
    "ext": ".jpg"
  },
  "link": "https://t.me/channel/123"
}
```

### Свой конфиг

```python
from tgtools import Settings, TelegramAPI

settings = Settings.from_env("C:/path/to/.env")
settings.download_dir = settings.download_dir / "project"

async with TelegramAPI(settings) as tg:
    ...
```

### Автоответчик

Смотрите `examples/auto_reply.py`: он слушает выбранные чаты, проверяет ключевые слова и отвечает не чаще раза в минуту. Не используйте такие скрипты для спама.

## Как это работает

- Telethon подключается к серверам Telegram по MTProto и хранит авторизацию в `data/telegram.session`.
- Desktop-приложение и этот инструмент — две независимые сессии. Desktop можно не закрывать.
- Первый вход интерактивный: номер → код из Telegram → пароль 2FA (если есть). Дальше сессия переиспользуется.
- Все команды при запуске автоматически подключаются к API. Если `.env` ещё нет, первая интерактивная команда запустит мастер настройки; если нет сессии — предложит войти.
- Для ботов: `TG_MODE=bot` и `TG_BOT_TOKEN`; но у ботов свои ограничения (они не читают произвольные чаты). Для личных сообщений нужен режим `user`.

## Безопасность

- `.env`, `*.session`, `data/`, `downloads/`, `exports/` уже в `.gitignore`.
- **Файл `.session` — это полный доступ к аккаунту.** Не отправляйте его никому и не публикуйте.
- Не публикуйте `api_hash` и токен бота. При утечке перевыпустите приложение/токен.
- `TG_PASSWORD` (пароль 2FA) хранится в открытом виде, если вы его укажете. Лучше оставить пустым и вводить при входе.
- Если сессия скомпрометирована: Telegram → Настройки → Устройства → завершить сессию, затем удалить `data/telegram.session` и войти заново.
- Соблюдайте правила Telegram: массовые рассылки, спам и автоматизация с большим числом действий могут привести к ограничениям аккаунта. Инструмент сам по себе не обходит лимиты Telegram — при `FloodWaitError` он попросит подождать.

## Ограничения

- Секретные чаты (end-to-end encryption) недоступны через API — их нельзя прочитать этим инструментом.
- Бот не видит историю произвольных чатов и сообщения, которые ему не адресованы.
- Для приватного канала/чата нужен доступ: состоят в нём или есть ссылка-приглашение (сначала `join`).
- Скачивание ограничено правами аккаунта и настройками чата (запрет сохранения контента и т.п.).
- Историю можно читать только там, где она доступна вашему аккаунту.

## Если что-то не работает

**`python` открывает Microsoft Store / ничего не делает.** Используйте `.\tg.bat` или `py`.

**`TG_API_ID` / `TG_API_HASH` не заданы.** Запустите `.\tg.bat setup` или создайте `.env` по образцу `.env.example`.

**`api_hash` должен состоять из 32 символов.** Скопируйте значение с my.telegram.org целиком, без пробелов.

**Код не приходит.** Проверьте Telegram Desktop, SMS и раздел «Активные сеансы». Не запрашивайте код много раз: Telegram может временно заблокировать вход (`FloodWait`).

**`AuthKeyUnregisteredError` / сессия недействительна.** Сессию завершили в настройках Telegram. Удалите `data/telegram.session` и выполните `.\tg.bat login`.

**`database is locked`.** Уже запущен другой процесс `tg`. Закройте его и повторите.

**`ChatNotFoundError`.** Укажите точный `@username`, ссылку `t.me/...` или числовой id. Для приватного чата сначала вступите: `.\tg.bat join <ссылка>`.

**`FloodWaitError`.** Telegram просит подождать N секунд. Подождите указанное время, не запускайте команду в цикле.

**Нужно без интерактивных запросов.** Используйте `--no-input`; при отсутствии сессии команда завершится ошибкой, а не зависнет.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Тесты проверяют разбор ссылок и дат, имена файлов, конфигурацию, преобразование сообщений и CLI-обработчики на фейковом API. Для живого входа нужны ваши `api_id`/`api_hash` и код из Telegram.

## Структура

```
tg.py                  # точка входа CLI
tg.bat                 # запуск в Windows (сам создаёт .venv)
tgtools/
  api.py               # TelegramAPI — все функции
  cli.py               # команды и вывод
  config.py            # .env, пути, сессия
  models.py            # сообщения/чаты -> словари
  utils.py             # ссылки, даты, файлы
  errors.py            # понятные исключения
examples/              # примеры автоматизации
tests/                 # unit-тесты
.env.example           # образец конфигурации
```
