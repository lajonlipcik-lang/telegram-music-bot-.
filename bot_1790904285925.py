"""Telegram bot for music search, download, and recognition.

Required Replit Secrets:
    TELEGRAM_BOT_TOKEN
    AUDD_API_KEY
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import random
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlencode, urlsplit

import requests
import yt_dlp
from yt_dlp.utils import DownloadError


CHANNEL_USERNAME = "@Musiccommomru"
CHANNEL_URL = "https://t.me/Musiccommomru"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUDD_API_KEY = os.getenv("AUDD_API_KEY")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
AUDD_ENDPOINT = "https://api.audd.io/"

MAX_TELEGRAM_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_TELEGRAM_UPLOAD_BYTES = 45 * 1024 * 1024
MAX_TELEGRAM_THUMBNAIL_BYTES = 200_000
MAX_TRACK_DURATION_SECONDS = 60 * 60
MAX_SEARCH_RESULTS = 10
MAX_CONCURRENT_UPDATES = 4
MAX_QUEUED_UPDATES = 12
MAX_CONCURRENT_MEDIA_JOBS = 2
MIN_MEDIA_REQUEST_INTERVAL_SECONDS = 2.0
MEDIA_BUSY_NOTICE_INTERVAL_SECONDS = 5.0
MAX_MEDIA_REQUEST_STATE_USERS = 10_000
MAX_PLAYLIST_PAGE_SIZE = 20
MAX_PLAYLIST_SHUFFLE_TRACKS = 20
MAX_SENT_AUDIO_REFERENCES = 20_000
PLAYLIST_DB_PATH = Path(
    os.getenv(
        "MUSIC_BOT_DB_PATH",
        str(Path(__file__).with_name("music_bot.sqlite3")),
    )
)
SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}
SUPPORTED_VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}
LANGUAGE_PREFERENCES: dict[int, str] = {}
LANGUAGE_LABELS = {
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "uk": "🇺🇦 Українська",
}
TRANSLATIONS = {
    "en": {
        "language_prompt": "Choose the interface language:",
        "language_selected": "Interface language set to {language}.",
        "language_button": "🌐 Language",
        "unknown_title": "Unknown title",
        "unknown_artist": "Unknown artist",
        "start": (
            "Hi! I can find full tracks or identify a song from audio or video.\n\n"
            "Send a song title or artist to search. You can also send an audio file, "
            "voice message, or video; I'll recognize it with AudD and show full-track options.\n\n"
            "Use /language or the button below to change the interface language."
        ),
        "searching": "Searching the internet for your song…",
        "search_failed": "Search failed. Please try again later.",
        "no_results": "No results found. Try including both the song title and artist.",
        "results_header": "YouTube results for “{query}” ({count}). Choose a number:",
        "audd_header": "AudD recognized: {artist} - {title}.",
        "album": "Album: {album}.",
        "audd_options": "Matching full-track options:",
        "file_too_large": "That file is too large. The recognition limit is 20 MB.",
        "extracting_video": "Extracting audio from the video…",
        "recognizing_audio": "Listening to the audio and checking for a match…",
        "no_match": "I couldn't identify that song. Try a clearer audio or video clip.",
        "recognition_unavailable": "The recognition service is temporarily unavailable. Please try again later.",
        "recognition_failed": "I couldn't process that file. Please try a different audio or video file.",
        "unsupported_media": (
            "Please send an audio or video file. Supported formats include MP3, M4A, WAV, "
            "FLAC, OGG, MP4, MOV, and MKV."
        ),
        "query_too_long": "Search queries must be 200 characters or fewer.",
        "choose_track": "This button has expired. Send your search again to get a new list.",
        "invalid_choice": "I couldn't select that track. Please search again.",
        "downloading": "Downloading “{title}” — {artist}…",
        "download_started": "Starting download: {title}…",
        "link_downloading": "Downloading audio from the video link…",
        "downloaded": "Sent: {title} — {artist}.",
        "download_failed": "I couldn't download or send that track. It may be unavailable or too large for Telegram.",
        "language_error": "That language selection is no longer available. Open /language to choose again.",
        "playlist_button": "🎧 My playlist",
        "search_button": "🔎 Search a song",
        "search_prompt": "Send a song title or artist to search.",
        "language_button_hint": "Change the interface language:",
        "playlist_empty": (
            "Your personal playlist\n"
            "Your favorite tracks will be kept here so you can listen any time without searching again.\n\n"
            "Your list is empty\n\n"
            "To add a song, find it and tap “Add to playlist” under the track."
        ),
        "playlist_list": (
            "Your personal playlist\nTracks: {count}\n"
            "Choose a song below to play it:"
        ),
        "playlist_saved": "✅ Track saved to “My playlist”!",
        "playlist_duplicate": "⚠️ This track is already in your playlist.",
        "playlist_removed": "Track removed from your playlist.",
        "playlist_cleared": "Your playlist has been cleared.",
        "playlist_clear_confirm": "Clear your entire playlist? This cannot be undone.",
        "playlist_clear_yes": "🗑 Clear playlist",
        "playlist_cancel": "Cancel",
        "playlist_shuffle": "🔀 Play shuffled",
        "playlist_shuffle_started": "Sending {count} tracks in shuffled order.",
        "playlist_shuffle_limited": (
            "Sending {count} shuffled tracks. To avoid flooding the chat, "
            "a maximum of 20 tracks is sent per request (your playlist has {total})."
        ),
        "playlist_empty_shuffle": "Your playlist is empty.",
        "playlist_track_missing": "This track is no longer in your playlist.",
        "playlist_track_ref_missing": "This audio can no longer be added. Search or play it again.",
        "playlist_error": "Could not open the playlist right now.",
        "playlist_next": "Next ▶️",
        "playlist_previous": "◀️ Previous",
        "track_remove_button": "🗑 Remove from playlist",
        "track_back_button": "📜 Back to playlist",
        "playlist_busy": "The bot is processing many requests. Please try again shortly.",
        "playlist_send_failed": "Could not send the saved track.",
        "track_add_button": "❤️ Add to playlist",
        "track_share_button": "🔗 Share",
    },
    "ru": {
        "language_prompt": "Выберите язык интерфейса:",
        "language_selected": "Язык интерфейса: {language}.",
        "language_button": "🌐 Язык",
        "unknown_title": "Без названия",
        "unknown_artist": "Исполнитель неизвестен",
        "start": (
            "Привет! Я найду полный трек или попробую определить песню по аудио или видео.\n\n"
            "Отправьте название песни или исполнителя для поиска. Также можно прислать "
            "аудио, голосовое сообщение или видео — я распознаю композицию через AudD "
            "и покажу варианты полного трека.\n\n"
            "Чтобы сменить язык интерфейса, введите /language или нажмите кнопку ниже."
        ),
        "searching": "Ищу песню на просторах интернета…",
        "search_failed": "Не получилось выполнить поиск. Попробуйте ещё раз позже.",
        "no_results": "Ничего не нашёл. Попробуйте указать название и исполнителя.",
        "results_header": "Результаты YouTube по запросу «{query}» ({count}). Выберите номер:",
        "audd_header": "AudD распознал: {artist} - {title}.",
        "album": "Альбом: {album}.",
        "audd_options": "Подходящие варианты полной версии:",
        "file_too_large": "Файл слишком большой. Максимальный размер для распознавания — 20 МБ.",
        "extracting_video": "Извлекаю аудио из видео…",
        "recognizing_audio": "Слушаю аудио и ищу совпадение…",
        "no_match": "Не удалось распознать песню. Пришлите фрагмент с более чётким звуком.",
        "recognition_unavailable": "Сервис распознавания временно недоступен. Попробуйте позже.",
        "recognition_failed": "Не получилось обработать файл. Попробуйте отправить другое аудио или видео.",
        "unsupported_media": (
            "Пришлите аудио или видеофайл. Поддерживаются MP3, M4A, WAV, FLAC, "
            "OGG, MP4, MOV, MKV и другие распространённые форматы."
        ),
        "query_too_long": "Запрос слишком длинный. Укажите не более 200 символов.",
        "choose_track": "Этот список устарел. Отправьте запрос ещё раз, чтобы получить новый список.",
        "invalid_choice": "Не удалось выбрать трек. Выполните поиск ещё раз.",
        "downloading": "Скачиваю «{title}» — {artist}…",
        "download_started": "Начинаю скачивание: {title}…",
        "link_downloading": "Скачиваю аудио по видеоссылке…",
        "downloaded": "Отправил: {title} — {artist}.",
        "download_failed": "Не удалось скачать или отправить трек. Возможно, он недоступен или файл слишком большой для Telegram.",
        "language_error": "Этот выбор языка устарел. Откройте /language и выберите язык снова.",
        "playlist_button": "🎧 Мой плейлист",
        "search_button": "🔎 Поиск песни",
        "search_prompt": "Отправьте название песни или исполнителя для поиска.",
        "language_button_hint": "Язык интерфейса:",
        "playlist_empty": (
            "Ваш персональный плейлист\n"
            "Здесь будут храниться ваши любимые треки, чтобы вы могли послушать их "
            "в любой момент без повторного поиска!\n\n"
            "Ваш список пока пуст\n\n"
            "Чтобы добавить песню, просто найдите её и нажмите кнопку "
            "«Добавить в плейлист» под файлом с треком."
        ),
        "playlist_list": (
            "Ваш персональный плейлист\nВсего треков: {count}\n"
            "Выберите песню из списка ниже, чтобы включить её:"
        ),
        "playlist_saved": "✅ Трек сохранен в «Мой плейлист»!",
        "playlist_duplicate": "⚠️ Этот трек уже находится в вашем плейлисте.",
        "playlist_removed": "Трек удален из плейлиста.",
        "playlist_cleared": "Плейлист очищен.",
        "playlist_clear_confirm": "Очистить весь плейлист? Это действие нельзя отменить.",
        "playlist_clear_yes": "🗑 Очистить плейлист",
        "playlist_cancel": "Отмена",
        "playlist_shuffle": "🔀 Слушать перемешано",
        "playlist_shuffle_started": "Отправляю {count} треков в случайном порядке.",
        "playlist_shuffle_limited": (
            "Отправляю {count} треков в случайном порядке. Чтобы не перегружать чат, "
            "за один запуск отправляется не более 20 треков (в плейлисте {total})."
        ),
        "playlist_empty_shuffle": "Ваш плейлист пока пуст.",
        "playlist_track_missing": "Этого трека больше нет в вашем плейлисте.",
        "playlist_track_ref_missing": "Не удалось добавить этот аудиофайл. Найдите или включите его ещё раз.",
        "playlist_error": "Не удалось открыть плейлист. Попробуйте позже.",
        "playlist_next": "Далее ▶️",
        "playlist_previous": "◀️ Назад",
        "track_remove_button": "🗑 Удалить из плейлиста",
        "track_back_button": "📜 Назад в плейлист",
        "playlist_busy": "Бот обрабатывает много запросов. Попробуйте ещё раз чуть позже.",
        "playlist_send_failed": "Не удалось отправить сохранённый трек.",
        "track_add_button": "❤️ Добавить в плейлист",
        "track_share_button": "🔗 Поделиться",
    },
    "uk": {
        "language_prompt": "Виберіть мову інтерфейсу:",
        "language_selected": "Мову інтерфейсу змінено на: {language}.",
        "language_button": "🌐 Мова",
        "unknown_title": "Без назви",
        "unknown_artist": "Невідомий виконавець",
        "start": (
            "Вітаю! Я допоможу знайти повний трек або розпізнати пісню за аудіо чи відео.\n\n"
            "Надішліть назву пісні або виконавця для пошуку. Також можна надіслати "
            "аудіо, голосове повідомлення або відео — я розпізнаю композицію через AudD "
            "і покажу варіанти повного треку.\n\n"
            "Щоб змінити мову інтерфейсу, введіть /language або натисніть кнопку нижче."
        ),
        "searching": "Шукаю вашу пісню в інтернеті…",
        "search_failed": "Не вдалося виконати пошук. Спробуйте ще раз пізніше.",
        "no_results": "Нічого не знайдено. Спробуйте вказати назву та виконавця.",
        "results_header": "Результати YouTube за запитом «{query}» ({count}). Виберіть номер:",
        "audd_header": "AudD розпізнав: {artist} - {title}.",
        "album": "Альбом: {album}.",
        "audd_options": "Відповідні варіанти повної версії:",
        "file_too_large": "Файл завеликий. Максимальний розмір для розпізнавання — 20 МБ.",
        "extracting_video": "Витягую аудіо з відео…",
        "recognizing_audio": "Слухаю аудіо та шукаю збіг…",
        "no_match": "Не вдалося розпізнати пісню. Надішліть фрагмент із чистішим звуком.",
        "recognition_unavailable": "Сервіс розпізнавання тимчасово недоступний. Спробуйте пізніше.",
        "recognition_failed": "Не вдалося обробити файл. Спробуйте надіслати інше аудіо чи відео.",
        "unsupported_media": (
            "Надішліть аудіо- або відеофайл. Підтримуються MP3, M4A, WAV, FLAC, "
            "OGG, MP4, MOV, MKV та інші поширені формати."
        ),
        "query_too_long": "Запит задовгий. Вкажіть не більше 200 символів.",
        "choose_track": "Цей список застарів. Надішліть запит ще раз, щоб отримати новий список.",
        "invalid_choice": "Не вдалося вибрати трек. Виконайте пошук ще раз.",
        "downloading": "Завантажую «{title}» — {artist}…",
        "download_started": "Починаю завантаження: {title}…",
        "link_downloading": "Завантажую аудіо за відеопосиланням…",
        "downloaded": "Надіслав: {title} — {artist}.",
        "download_failed": "Не вдалося завантажити чи надіслати трек. Можливо, він недоступний або завеликий для Telegram.",
        "language_error": "Цей вибір мови застарів. Відкрийте /language та виберіть мову знову.",
        "playlist_button": "🎧 Мій плейлист",
        "search_button": "🔎 Пошук пісні",
        "search_prompt": "Надішліть назву пісні або виконавця для пошуку.",
        "language_button_hint": "Мова інтерфейсу:",
        "playlist_empty": (
            "Ваш персональний плейлист\n"
            "Тут зберігатимуться ваші улюблені треки, щоб ви могли слухати їх будь-коли "
            "без повторного пошуку!\n\n"
            "Ваш список поки порожній\n\n"
            "Щоб додати пісню, знайдіть її та натисніть «Додати до плейлиста» "
            "під аудіофайлом."
        ),
        "playlist_list": (
            "Ваш персональний плейлист\nУсього треків: {count}\n"
            "Виберіть пісню зі списку нижче, щоб увімкнути її:"
        ),
        "playlist_saved": "✅ Трек збережено в «Мій плейлист»!",
        "playlist_duplicate": "⚠️ Цей трек уже є у вашому плейлисті.",
        "playlist_removed": "Трек видалено з плейлиста.",
        "playlist_cleared": "Плейлист очищено.",
        "playlist_clear_confirm": "Очистити весь плейлист? Цю дію не можна скасувати.",
        "playlist_clear_yes": "🗑 Очистити плейлист",
        "playlist_cancel": "Скасувати",
        "playlist_shuffle": "🔀 Слухати у випадковому порядку",
        "playlist_shuffle_started": "Надсилаю {count} треків у випадковому порядку.",
        "playlist_shuffle_limited": (
            "Надсилаю {count} треків у випадковому порядку. Щоб не перевантажувати чат, "
            "за один запуск надсилається не більше 20 треків (у плейлисті {total})."
        ),
        "playlist_empty_shuffle": "Ваш плейлист поки порожній.",
        "playlist_track_missing": "Цього треку більше немає у вашому плейлисті.",
        "playlist_track_ref_missing": "Не вдалося додати це аудіо. Знайдіть або відтворіть його ще раз.",
        "playlist_error": "Не вдалося відкрити плейлист. Спробуйте пізніше.",
        "playlist_next": "Далі ▶️",
        "playlist_previous": "◀️ Назад",
        "track_remove_button": "🗑 Видалити з плейлиста",
        "track_back_button": "📜 Назад до плейлиста",
        "playlist_busy": "Бот обробляє багато запитів. Спробуйте ще раз трохи пізніше.",
        "playlist_send_failed": "Не вдалося надіслати збережений трек.",
        "track_add_button": "❤️ Додати до плейлиста",
        "track_share_button": "🔗 Поділитися",
    },
}

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("music_bot")

# Only the most recent search/recognition per chat and user is kept in memory.
SEARCH_STATE: dict[str, dict[str, Any]] = {}
PENDING_SUBSCRIPTION_ACTIONS: dict[str, dict[str, Any]] = {}
MEDIA_JOB_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_MEDIA_JOBS)
MEDIA_REQUEST_STATE_LOCK = threading.Lock()
MEDIA_REQUEST_STATE: dict[int, tuple[float, float]] = {}
PLAYLIST_SHUFFLE_LOCK = threading.Lock()
ACTIVE_PLAYLIST_SHUFFLES: set[int] = set()


class TelegramAPIError(RuntimeError):
    """Raised when Telegram's Bot API returns an error response."""


def safe_error_summary(error: Exception) -> str:
    if isinstance(error, TelegramAPIError):
        return str(error)
    if isinstance(error, requests.RequestException):
        return f"{type(error).__name__} while calling an external service"
    return type(error).__name__


@contextmanager
def playlist_database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(str(PLAYLIST_DB_PATH), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_playlist_database() -> None:
    PLAYLIST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with playlist_database() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, file_id)
            )
            """
        )
        columns = {
            str(row["name"]): row
            for row in connection.execute("PRAGMA table_info(user_playlists)")
        }
        required_columns = {"user_id", "file_id", "title"}
        if not required_columns.issubset(columns):
            missing = ", ".join(sorted(required_columns - set(columns)))
            raise sqlite3.DatabaseError(
                f"user_playlists is missing required columns: {missing}"
            )

        id_column = columns.get("id")
        needs_migration = (
            id_column is None
            or not id_column["pk"]
            or "created_at" not in columns
        )
        if needs_migration:
            connection.execute("DROP TABLE IF EXISTS _user_playlists_migrating")
            connection.execute(
                """
                CREATE TABLE _user_playlists_migrating (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    file_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, file_id)
                )
                """
            )
            created_at_value = (
                "COALESCE(created_at, CURRENT_TIMESTAMP)"
                if "created_at" in columns
                else "CURRENT_TIMESTAMP"
            )
            connection.execute(
                f"""
                INSERT OR IGNORE INTO _user_playlists_migrating
                    (user_id, file_id, title, created_at)
                SELECT user_id, file_id, title, {created_at_value}
                FROM user_playlists
                WHERE user_id IS NOT NULL
                  AND file_id IS NOT NULL
                  AND title IS NOT NULL
                """
            )
            connection.execute("DROP TABLE user_playlists")
            connection.execute(
                "ALTER TABLE _user_playlists_migrating RENAME TO user_playlists"
            )

        has_unique_user_file_index = False
        for index in connection.execute("PRAGMA index_list(user_playlists)"):
            if not index["unique"] or (
                "partial" in index.keys() and index["partial"]
            ):
                continue
            index_name = str(index["name"]).replace('"', '""')
            index_columns = [
                str(row["name"])
                for row in connection.execute(
                    f'PRAGMA index_info("{index_name}")'
                )
            ]
            if len(index_columns) == 2 and set(index_columns) == {
                "user_id",
                "file_id",
            }:
                has_unique_user_file_index = True
                break

        if not has_unique_user_file_index:
            connection.execute(
                """
                DELETE FROM user_playlists
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM user_playlists
                    GROUP BY user_id, file_id
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_user_playlists_user_file_unique
                ON user_playlists (user_id, file_id)
                """
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_playlists_user_id
            ON user_playlists (user_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_audio_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                title TEXT NOT NULL,
                source_url TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def register_sent_audio(
    file_id: str,
    title: str,
    source_url: str | None = None,
) -> int:
    with playlist_database() as connection:
        cursor = connection.execute(
            "INSERT INTO sent_audio_refs (file_id, title, source_url) VALUES (?, ?, ?)",
            (file_id, title, source_url),
        )
        reference_id = int(cursor.lastrowid)
        connection.execute(
            """
            DELETE FROM sent_audio_refs
            WHERE id NOT IN (
                SELECT id FROM sent_audio_refs ORDER BY id DESC LIMIT ?
            )
            """,
            (MAX_SENT_AUDIO_REFERENCES,),
        )
    return reference_id


def get_sent_audio(reference_id: int) -> dict[str, Any] | None:
    with playlist_database() as connection:
        row = connection.execute(
            "SELECT id, file_id, title, source_url FROM sent_audio_refs WHERE id = ?",
            (reference_id,),
        ).fetchone()
    return dict(row) if row else None


def add_playlist_track(user_id: int, file_id: str, title: str) -> bool:
    with playlist_database() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO user_playlists (user_id, file_id, title)
            VALUES (?, ?, ?)
            """,
            (user_id, file_id, title),
        )
        return cursor.rowcount == 1


def get_user_playlist(user_id: int) -> list[dict[str, Any]]:
    with playlist_database() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, file_id, title, created_at
            FROM user_playlists
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_user_playlist_track(user_id: int, track_id: int) -> dict[str, Any] | None:
    with playlist_database() as connection:
        row = connection.execute(
            """
            SELECT id, user_id, file_id, title, created_at
            FROM user_playlists
            WHERE user_id = ? AND id = ?
            """,
            (user_id, track_id),
        ).fetchone()
    return dict(row) if row else None


def delete_user_playlist_track(user_id: int, track_id: int) -> bool:
    with playlist_database() as connection:
        cursor = connection.execute(
            "DELETE FROM user_playlists WHERE user_id = ? AND id = ?",
            (user_id, track_id),
        )
        return cursor.rowcount > 0


def clear_user_playlist(user_id: int) -> int:
    with playlist_database() as connection:
        cursor = connection.execute(
            "DELETE FROM user_playlists WHERE user_id = ?",
            (user_id,),
        )
        return int(cursor.rowcount)


def user_language(user_id: int) -> str:
    return LANGUAGE_PREFERENCES.get(user_id, "ru")


def tr(user_id: int, key: str, **values: Any) -> str:
    language = user_language(user_id)
    return TRANSLATIONS[language][key].format(**values)


def language_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": f"lang:{code}"}]
            for code, label in LANGUAGE_LABELS.items()
        ]
    }


def language_button(user_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": tr(user_id, "language_button"),
                    "callback_data": "lang:menu",
                }
            ]
        ]
    }


def main_menu_keyboard(user_id: int) -> dict[str, Any]:
    return {
        "keyboard": [
            [
                {"text": tr(user_id, "search_button")},
                {"text": tr(user_id, "playlist_button")},
            ]
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def show_language_menu(
    chat_id: int,
    user_id: int,
    *,
    message_id: int | None = None,
) -> None:
    prompt = tr(user_id, "language_prompt")
    if message_id is None:
        send_message(chat_id, prompt, reply_markup=language_keyboard())
    else:
        edit_message(
            chat_id,
            message_id,
            prompt,
            reply_markup=language_keyboard(),
        )


def state_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}:{user_id}"


def is_expensive_message(message: dict[str, Any], user_id: int) -> bool:
    if any(
        message.get(field_name)
        for field_name in ("audio", "voice", "video", "video_note", "document")
    ):
        return True

    text = str(message.get("text") or "").strip()
    if not text or text.startswith("/"):
        return False
    return text not in {
        tr(user_id, "playlist_button"),
        tr(user_id, "search_button"),
    }


def reserve_media_request(user_id: int) -> tuple[bool, bool]:
    """Apply a per-user cooldown and limit overload replies during a message flood."""
    now = time.monotonic()
    with MEDIA_REQUEST_STATE_LOCK:
        previous = MEDIA_REQUEST_STATE.pop(user_id, None)

        while len(MEDIA_REQUEST_STATE) >= MAX_MEDIA_REQUEST_STATE_USERS:
            oldest_user_id = next(iter(MEDIA_REQUEST_STATE))
            del MEDIA_REQUEST_STATE[oldest_user_id]

        if previous is None:
            MEDIA_REQUEST_STATE[user_id] = (now, float("-inf"))
            return True, False

        last_accepted, last_notice = previous
        if now - last_accepted < MIN_MEDIA_REQUEST_INTERVAL_SECONDS:
            notify = now - last_notice >= MEDIA_BUSY_NOTICE_INTERVAL_SECONDS
            MEDIA_REQUEST_STATE[user_id] = (
                last_accepted,
                now if notify else last_notice,
            )
            return False, notify

        MEDIA_REQUEST_STATE[user_id] = (now, last_notice)
        return True, False


def telegram_call(
    method: str,
    data: dict[str, Any] | None = None,
    *,
    files: dict[str, Any] | None = None,
    http_method: str = "POST",
    timeout: int = 30,
) -> Any:
    url = f"{TELEGRAM_API}/{method}"
    if http_method == "GET":
        response = requests.get(url, params=data, timeout=timeout)
    elif files:
        response = requests.post(url, data=data, files=files, timeout=timeout)
    else:
        response = requests.post(url, json=data, timeout=timeout)

    try:
        payload = response.json()
    except ValueError:
        if response.status_code >= 400:
            raise TelegramAPIError(
                f"{method} failed with HTTP {response.status_code}"
            ) from None
        raise TelegramAPIError(f"{method} returned invalid JSON") from None

    if not isinstance(payload, dict):
        raise TelegramAPIError(f"{method} returned an unexpected response")
    if response.status_code >= 400 or not payload.get("ok"):
        description = str(payload.get("description") or "Telegram API error")
        status = f" (HTTP {response.status_code})" if response.status_code >= 400 else ""
        raise TelegramAPIError(f"{method} failed{status}: {description}")
    return payload.get("result")


def send_message(
    chat_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = reply_markup
    return telegram_call("sendMessage", data)


def edit_message(
    chat_id: int,
    message_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> Any:
    data: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if reply_markup is not None:
        data["reply_markup"] = reply_markup
    return telegram_call("editMessageText", data)


def make_sent_audio_keyboard(
    user_id: int,
    reference_id: int,
    title: str,
    source_url: str | None,
) -> dict[str, Any]:
    share_url = "https://t.me/share/url?" + urlencode(
        {"url": source_url or "", "text": title}
    )
    # Telegram callback_data is limited to 64 bytes; use the compact DB reference
    # and look up the longer file_id server-side.
    return {
        "inline_keyboard": [
            [
                {
                    "text": tr(user_id, "track_add_button"),
                    "callback_data": f"add_fav_{reference_id}",
                }
            ],
            [{"text": tr(user_id, "track_share_button"), "url": share_url}],
        ]
    }


def make_playlist_keyboard(
    user_id: int,
    tracks: list[dict[str, Any]],
    page: int = 0,
) -> dict[str, Any]:
    total = len(tracks)
    last_page = max(0, (total - 1) // MAX_PLAYLIST_PAGE_SIZE)
    page = max(0, min(page, last_page))
    start = page * MAX_PLAYLIST_PAGE_SIZE
    visible_tracks = tracks[start : start + MAX_PLAYLIST_PAGE_SIZE]
    keyboard = [
        [
            {
                "text": f"🎵 {str(track['title'])[:56]}",
                "callback_data": f"play_track_{int(track['id'])}",
            }
        ]
        for track in visible_tracks
    ]

    if last_page > 0:
        page_buttons = []
        if page > 0:
            page_buttons.append(
                {
                    "text": tr(user_id, "playlist_previous"),
                    "callback_data": f"playlist_page_{page - 1}",
                }
            )
        if page < last_page:
            page_buttons.append(
                {
                    "text": tr(user_id, "playlist_next"),
                    "callback_data": f"playlist_page_{page + 1}",
                }
            )
        keyboard.append(page_buttons)

    keyboard.append(
        [
            {
                "text": tr(user_id, "playlist_shuffle"),
                "callback_data": "shuffle_playlist",
            },
            {
                "text": tr(user_id, "playlist_clear_yes"),
                "callback_data": "clear_playlist",
            },
        ]
    )
    return {"inline_keyboard": keyboard}


def show_playlist(
    chat_id: int,
    user_id: int,
    *,
    message_id: int | None = None,
    page: int = 0,
) -> None:
    tracks = get_user_playlist(user_id)
    if not tracks:
        text = tr(user_id, "playlist_empty")
        markup = {"inline_keyboard": []} if message_id is not None else None
    else:
        page_count = (len(tracks) + MAX_PLAYLIST_PAGE_SIZE - 1) // MAX_PLAYLIST_PAGE_SIZE
        page = max(0, min(page, page_count - 1))
        text = tr(user_id, "playlist_list", count=len(tracks))
        markup = make_playlist_keyboard(user_id, tracks, page)

    if message_id is not None:
        try:
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        except Exception as error:
            logger.debug("Could not edit playlist message: %s", safe_error_summary(error))
    send_message(chat_id, text, reply_markup=markup)


def make_playing_track_keyboard(user_id: int, track_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": tr(user_id, "track_remove_button"),
                    "callback_data": f"del_track_{track_id}",
                }
            ],
            [
                {
                    "text": tr(user_id, "track_back_button"),
                    "callback_data": "open_playlist",
                }
            ],
        ]
    }


def send_cached_audio(
    chat_id: int,
    track: dict[str, Any],
    *,
    reply_markup: dict[str, Any] | None = None,
) -> Any:
    display_title = str(track["title"])
    if " — " in display_title:
        performer, title = display_title.split(" — ", 1)
    else:
        performer, title = "", display_title
    data: dict[str, Any] = {
        "chat_id": chat_id,
        "audio": str(track["file_id"]),
        "title": title[:64],
        "caption": display_title[:1024],
    }
    if performer:
        data["performer"] = performer[:64]
    if reply_markup is not None:
        data["reply_markup"] = reply_markup
    return telegram_call("sendAudio", data, timeout=60)


def delete_telegram_message(chat_id: int, message_id: int) -> None:
    try:
        telegram_call(
            "deleteMessage",
            {"chat_id": chat_id, "message_id": message_id},
        )
    except Exception as error:
        logger.debug(
            "Could not delete subscription prompt: %s",
            safe_error_summary(error),
        )


def subscription_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "📢 Подписаться", "url": CHANNEL_URL}],
            [{"text": "✅ Я подписался", "callback_data": "check_sub"}],
        ]
    }


def check_channel_subscription(user_id: int) -> bool | None:
    try:
        member = telegram_call(
            "getChatMember",
            {"chat_id": CHANNEL_USERNAME, "user_id": user_id},
            timeout=10,
        )
    except Exception as error:
        logger.warning(
            "Channel membership check failed: %s",
            safe_error_summary(error),
        )
        return None

    if not isinstance(member, dict):
        return None
    return member.get("status") in {"member", "administrator", "creator"}


def verify_bot_channel_access(bot_id: int) -> bool:
    try:
        bot_member = telegram_call(
            "getChatMember",
            {"chat_id": CHANNEL_USERNAME, "user_id": bot_id},
            timeout=10,
        )
    except Exception as error:
        logger.error(
            "Cannot verify access to channel %s: %s. Add the bot as a channel administrator.",
            CHANNEL_USERNAME,
            safe_error_summary(error),
        )
        return False

    if not isinstance(bot_member, dict) or bot_member.get("status") not in {
        "administrator",
        "creator",
    }:
        logger.error(
            "The bot must be an administrator in %s to check users' subscriptions.",
            CHANNEL_USERNAME,
        )
        return False
    return True


def require_channel_subscription(
    chat_id: int,
    user_id: int,
    action: dict[str, Any],
) -> bool | None:
    subscribed = check_channel_subscription(user_id)
    if subscribed is None:
        return None

    key = state_key(chat_id, user_id)
    if subscribed:
        pending = PENDING_SUBSCRIPTION_ACTIONS.pop(key, None)
        if pending and pending.get("prompt_message_id"):
            delete_telegram_message(
                int(pending.get("chat_id", chat_id)),
                int(pending["prompt_message_id"]),
            )
        return True

    pending = PENDING_SUBSCRIPTION_ACTIONS.get(key)
    if pending is None:
        pending = {
            "chat_id": chat_id,
            "user_id": user_id,
            "prompt_message_id": None,
        }
        PENDING_SUBSCRIPTION_ACTIONS[key] = pending
    pending["action"] = action

    if not pending.get("prompt_message_id"):
        prompt = send_message(
            chat_id,
            "Подпишись на наш канал и дальше забудь про подписку",
            reply_markup=subscription_keyboard(),
        )
        if prompt and prompt.get("message_id"):
            pending["prompt_message_id"] = int(prompt["message_id"])
    return False


def format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "длительность неизвестна"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def artist_for(entry: dict[str, Any]) -> str:
    return str(
        entry.get("artist")
        or entry.get("creator")
        or entry.get("uploader")
        or entry.get("channel")
        or ""
    )


def search_tracks(query: str) -> list[dict[str, Any]]:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 25,
        "extract_flat": "in_playlist",
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        data = downloader.extract_info(
            f"ytsearch{MAX_SEARCH_RESULTS}:{query}",
            download=False,
        )

    tracks: list[dict[str, Any]] = []
    for entry in (data or {}).get("entries") or []:
        if not entry:
            continue
        video_id = entry.get("id")
        url = entry.get("webpage_url") or entry.get("url")
        if video_id and not str(url).startswith(("http://", "https://")):
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not url:
            continue
        tracks.append(
            {
                "id": str(video_id or uuid.uuid4().hex[:10]),
                "url": str(url),
                "title": str(entry.get("title") or ""),
                "artist": artist_for(entry),
                "duration": entry.get("duration"),
            }
        )
    return tracks


def make_telegram_thumbnail(output_dir: str) -> Path | None:
    image_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    candidates = [
        path
        for path in Path(output_dir).iterdir()
        if path.suffix.lower() in image_suffixes and path.is_file()
    ]
    if not candidates:
        return None

    thumbnail_path = Path(output_dir) / "telegram-thumbnail.jpg"
    source_path = candidates[0]
    for quality in (8, 12):
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source_path),
                    "-vf",
                    "scale=320:320:force_original_aspect_ratio=decrease",
                    "-frames:v",
                    "1",
                    "-q:v",
                    str(quality),
                    str(thumbnail_path),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("Could not convert the downloaded thumbnail")
            return None

        if (
            thumbnail_path.exists()
            and thumbnail_path.stat().st_size <= MAX_TELEGRAM_THUMBNAIL_BYTES
        ):
            return thumbnail_path

    return None


def download_mp3(
    track: dict[str, Any],
    output_dir: str,
) -> tuple[Path, Path | None, dict[str, Any]]:
    options = {
        "format": "bestaudio/best",
        "outtmpl": str(Path(output_dir) / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "max_filesize": MAX_TELEGRAM_UPLOAD_BYTES,
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration <= {MAX_TRACK_DURATION_SECONDS}"
        ),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(track["url"], download=True)

    mp3_files = list(Path(output_dir).glob("*.mp3"))
    if not mp3_files:
        raise DownloadError("MP3 conversion did not produce an output file")
    mp3_path = mp3_files[0]
    if mp3_path.stat().st_size > MAX_TELEGRAM_UPLOAD_BYTES:
        raise DownloadError("The converted audio is too large to send in Telegram")
    thumbnail_path = make_telegram_thumbnail(output_dir)
    return mp3_path, thumbnail_path, info if isinstance(info, dict) else {}


def make_search_keyboard(
    tracks: list[dict[str, Any]],
    search_id: str,
) -> dict[str, Any]:
    buttons = []
    for index, track in enumerate(tracks):
        buttons.append(
            {"text": str(index + 1), "callback_data": f"d:{search_id}:{index}"}
        )
    keyboard = [buttons[:5]]
    if len(buttons) > 5:
        keyboard.append(buttons[5:10])
    return {"inline_keyboard": keyboard}


def send_downloaded_track(
    chat_id: int,
    user_id: int,
    track: dict[str, Any],
    *,
    status_text: str | None = None,
) -> None:
    if not MEDIA_JOB_SEMAPHORE.acquire(timeout=0.2):
        send_message(chat_id, tr(user_id, "playlist_busy"))
        return

    try:
        status = send_message(
            chat_id,
            status_text
            or tr(
                user_id,
                "downloading",
                title=track.get("title") or tr(user_id, "unknown_title"),
                artist=track.get("artist") or tr(user_id, "unknown_artist"),
            ),
        )
    except Exception:
        MEDIA_JOB_SEMAPHORE.release()
        raise
    status_message_id = status.get("message_id")

    try:
        telegram_call("sendChatAction", {"chat_id": chat_id, "action": "upload_audio"})
        with tempfile.TemporaryDirectory(prefix="music-download-") as temp_dir:
            mp3_path, thumbnail_path, info = download_mp3(track, temp_dir)
            title = str(
                track.get("title")
                or info.get("title")
                or tr(user_id, "unknown_title")
            )
            artist = str(
                track.get("artist")
                or artist_for(info)
                or tr(user_id, "unknown_artist")
            )
            filename = re.sub(
                r'[\\/:*?"<>|]+',
                "-",
                f"{artist} - {title}",
            )[:120].strip(" .-")
            filename = f"{filename or 'track'}.mp3"
            audio_data = {
                "chat_id": chat_id,
                "title": title[:64],
                "performer": artist[:64],
                "caption": f"{title[:64]} — {artist[:64]}",
            }

            audio_message: Any = None
            with mp3_path.open("rb") as audio_file:
                files = {"audio": (filename, audio_file, "audio/mpeg")}
                if thumbnail_path:
                    with thumbnail_path.open("rb") as thumbnail_file:
                        files["thumbnail"] = (
                            "cover.jpg",
                            thumbnail_file,
                            "image/jpeg",
                        )
                        audio_message = telegram_call(
                            "sendAudio",
                            audio_data,
                            files=files,
                            timeout=120,
                        )
                else:
                    audio_message = telegram_call(
                        "sendAudio",
                        audio_data,
                        files=files,
                        timeout=120,
                    )

        if isinstance(audio_message, dict):
            audio = audio_message.get("audio")
            sent_message_id = audio_message.get("message_id")
            file_id = audio.get("file_id") if isinstance(audio, dict) else None
            if file_id and sent_message_id:
                try:
                    display_title = f"{artist} — {title}"
                    reference_id = register_sent_audio(
                        str(file_id),
                        display_title,
                        str(track.get("url") or "") or None,
                    )
                    telegram_call(
                        "editMessageReplyMarkup",
                        {
                            "chat_id": chat_id,
                            "message_id": sent_message_id,
                            "reply_markup": make_sent_audio_keyboard(
                                user_id,
                                reference_id,
                                display_title,
                                str(track.get("url") or "") or None,
                            ),
                        },
                    )
                except Exception as error:
                    logger.warning(
                        "Could not attach playlist controls to audio (%s)",
                        type(error).__name__,
                    )

        if status_message_id:
            edit_message(
                chat_id,
                status_message_id,
                tr(user_id, "downloaded", title=title, artist=artist),
            )
    except Exception as error:
        logger.warning(
            "Track download or Telegram upload failed (%s)",
            type(error).__name__,
        )
        if status_message_id:
            edit_message(
                chat_id,
                status_message_id,
                tr(user_id, "download_failed"),
            )
    finally:
        MEDIA_JOB_SEMAPHORE.release()


def run_search(
    chat_id: int,
    user_id: int,
    query: str,
    *,
    message_id: int | None = None,
    intro: str | None = None,
) -> None:
    if message_id is None:
        progress = send_message(chat_id, tr(user_id, "searching"))
        message_id = progress["message_id"]
    else:
        edit_message(chat_id, message_id, tr(user_id, "searching"))

    if not MEDIA_JOB_SEMAPHORE.acquire(timeout=0.2):
        edit_message(chat_id, message_id, tr(user_id, "playlist_busy"))
        return
    try:
        tracks = search_tracks(query)
    except Exception:
        logger.exception("yt-dlp track search failed")
        edit_message(
            chat_id,
            message_id,
            tr(user_id, "search_failed"),
        )
        return
    finally:
        MEDIA_JOB_SEMAPHORE.release()

    if not tracks:
        edit_message(
            chat_id,
            message_id,
            tr(user_id, "no_results"),
        )
        return

    for track in tracks:
        track["title"] = str(track.get("title") or tr(user_id, "unknown_title"))
        track["artist"] = str(track.get("artist") or tr(user_id, "unknown_artist"))

    key = state_key(chat_id, user_id)
    search_id = uuid.uuid4().hex[:12]
    SEARCH_STATE[key] = {"id": search_id, "tracks": tracks}
    lines = []
    for number, track in enumerate(tracks, start=1):
        title = " ".join(str(track["title"]).split())[:180]
        artist = " ".join(str(track["artist"]).split())[:100]
        line = f"{number}. {title} — {artist}"
        if track.get("duration"):
            line += f"  {format_duration(track['duration'])}"
        lines.append(line)

    heading = intro or tr(
        user_id,
        "results_header",
        query=query[:200],
        count=len(tracks),
    )
    edit_message(
        chat_id,
        message_id,
        f"{heading}\n\n" + "\n".join(lines),
        reply_markup=make_search_keyboard(tracks, search_id),
    )


def audd_recognize(file_path: Path) -> dict[str, Any] | None:
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    with file_path.open("rb") as audio_file:
        response = requests.post(
            AUDD_ENDPOINT,
            data={"api_token": AUDD_API_KEY},
            files={"file": (file_path.name, audio_file, mime_type)},
            timeout=(10, 60),
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "success":
        error = payload.get("error") or {}
        logger.warning(
            "AudD returned an error: %s",
            error.get("error_message", "unknown error"),
        )
        raise RuntimeError("AudD could not process the submitted audio")
    result = payload.get("result")
    return result if isinstance(result, dict) else None


def extract_audio_from_video(video_path: Path, audio_path: Path) -> None:
    """Extract a short MP3 sample from a video for AudD identification."""
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-t",
            "60",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("No audio stream was found in the video")


def download_telegram_file(file_id: str, destination: Path) -> None:
    info = telegram_call("getFile", {"file_id": file_id}, http_method="GET")
    remote_path = info.get("file_path")
    if not remote_path:
        raise TelegramAPIError("Telegram did not return a file path")

    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{remote_path}"
    downloaded = 0
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with destination.open("wb") as output:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_TELEGRAM_DOWNLOAD_BYTES:
                    raise ValueError("Audio file exceeds Telegram download limit")
                output.write(chunk)


def recognize_upload(
    chat_id: int,
    file_id: str,
    filename: str,
    file_size: int | None,
    user_id: int,
    *,
    is_video: bool = False,
) -> None:
    if file_size and file_size > MAX_TELEGRAM_DOWNLOAD_BYTES:
        send_message(chat_id, tr(user_id, "file_too_large"))
        return

    status = send_message(
        chat_id,
        tr(user_id, "extracting_video")
        if is_video
        else tr(user_id, "recognizing_audio"),
    )
    status_message_id = status["message_id"]
    try:
        if not MEDIA_JOB_SEMAPHORE.acquire(timeout=0.2):
            edit_message(
                chat_id,
                status_message_id,
                tr(user_id, "playlist_busy"),
            )
            return
        try:
            telegram_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
            suffix = Path(filename).suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                suffix = ".audio"
            with tempfile.TemporaryDirectory(prefix="music-recognition-") as temp_dir:
                source_path = Path(temp_dir) / f"upload{suffix}"
                download_telegram_file(file_id, source_path)
                audio_path = source_path
                if is_video:
                    audio_path = Path(temp_dir) / "video-audio.mp3"
                    extract_audio_from_video(source_path, audio_path)
                result = audd_recognize(audio_path)
        finally:
            MEDIA_JOB_SEMAPHORE.release()

        if not result:
            edit_message(
                chat_id,
                status_message_id,
                tr(user_id, "no_match"),
            )
            return

        title = str(result.get("title") or tr(user_id, "unknown_title"))
        artist = str(result.get("artist") or tr(user_id, "unknown_artist"))
        album = result.get("album")
        intro = tr(
            user_id,
            "audd_header",
            title=title[:160],
            artist=artist[:100],
        )
        if album:
            intro += "\n" + tr(user_id, "album", album=str(album)[:120])
        intro += "\n" + tr(user_id, "audd_options")
        run_search(
            chat_id,
            user_id,
            f"{artist[:100]} - {title[:160]}",
            message_id=status_message_id,
            intro=intro,
        )
    except requests.RequestException:
        logger.warning("A network request failed during audio recognition")
        edit_message(
            chat_id,
            status_message_id,
            tr(user_id, "recognition_unavailable"),
        )
    except Exception as error:
        logger.warning(
            "Audio recognition failed (%s)",
            type(error).__name__,
        )
        edit_message(
            chat_id,
            status_message_id,
            tr(user_id, "recognition_failed"),
        )


def media_details(
    message: dict[str, Any],
) -> tuple[str, str, int | None, bool] | None:
    for field_name in ("audio", "voice", "video", "video_note"):
        media = message.get(field_name)
        if media:
            is_video = field_name in ("video", "video_note")
            return (
                media["file_id"],
                str(
                    media.get("file_name")
                    or ("video.mp4" if is_video else "audio.ogg")
                ),
                media.get("file_size"),
                is_video,
            )

    document = message.get("document")
    if not document:
        return None

    filename = str(document.get("file_name") or "audio")
    mime_type = str(document.get("mime_type") or "")
    extension = Path(filename).suffix.lower()
    is_video = mime_type.startswith("video/") or extension in SUPPORTED_VIDEO_EXTENSIONS
    is_audio = mime_type.startswith("audio/") or extension in SUPPORTED_AUDIO_EXTENSIONS
    if not is_audio and not is_video:
        sender = message.get("from") or {}
        user_id = int(sender.get("id", message["chat"]["id"]))
        send_message(
            int(message["chat"]["id"]),
            tr(user_id, "unsupported_media"),
        )
        return None
    return (
        document["file_id"],
        filename,
        document.get("file_size"),
        is_video,
    )


def supported_video_url(text: str) -> str | None:
    for raw_url in re.findall(r"https?://[^\s<>\"']+", text, flags=re.IGNORECASE):
        url = raw_url.rstrip(".,!?;:)]}")
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() not in {"http", "https"} or not host:
            continue

        supported_host = any(
            host == domain or host.endswith(f".{domain}")
            for domain in (
                "youtube.com",
                "youtube-nocookie.com",
                "youtu.be",
                "tiktok.com",
                "instagram.com",
                "instagr.am",
                "vk.com",
                "vk.ru",
                "vkontakte.ru",
            )
        )
        if supported_host:
            return url
    return None


def handle_message(message: dict[str, Any]) -> None:
    chat_id = int(message["chat"]["id"])
    sender = message.get("from") or {}
    user_id = int(sender.get("id", chat_id))
    if is_expensive_message(message, user_id):
        allowed, notify = reserve_media_request(user_id)
        if not allowed:
            if notify:
                send_message(chat_id, tr(user_id, "playlist_busy"))
            return

    action = {"type": "message", "payload": message}
    subscribed = require_channel_subscription(chat_id, user_id, action)
    if subscribed is None:
        send_message(chat_id, "Не удалось проверить подписку. Попробуйте ещё раз позже.")
        return
    if not subscribed:
        return
    process_message(message)


def process_message(message: dict[str, Any]) -> None:
    chat_id = int(message["chat"]["id"])
    sender = message.get("from") or {}
    user_id = int(sender.get("id", chat_id))

    media = media_details(message)
    if media:
        recognize_upload(
            chat_id,
            media[0],
            media[1],
            media[2],
            user_id,
            is_video=media[3],
        )
        return

    text = str(message.get("text") or "").strip()
    if not text:
        return

    command = text.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
    if command in ("/start", "/help"):
        send_message(
            chat_id,
            tr(user_id, "start"),
            reply_markup=main_menu_keyboard(user_id),
        )
        send_message(
            chat_id,
            tr(user_id, "language_button_hint"),
            reply_markup=language_button(user_id),
        )
        return
    if command == "/language":
        show_language_menu(chat_id, user_id)
        return
    if command in ("/playlist", "/myplaylist") or text == tr(user_id, "playlist_button"):
        show_playlist(chat_id, user_id)
        return
    if text == tr(user_id, "search_button"):
        send_message(chat_id, tr(user_id, "search_prompt"))
        return

    if text.startswith("/"):
        return
    video_url = supported_video_url(text)
    if video_url:
        send_downloaded_track(
            chat_id,
            user_id,
            {"url": video_url},
            status_text=tr(user_id, "link_downloading"),
        )
        return
    if len(text) > 200:
        send_message(chat_id, tr(user_id, "query_too_long"))
        return
    run_search(chat_id, user_id, text)


def answer_callback(
    callback_id: str | None,
    *,
    text: str | None = None,
    show_alert: bool = False,
) -> bool:
    if not callback_id:
        return False
    data: dict[str, Any] = {"callback_query_id": callback_id}
    if text:
        data["text"] = text[:200]
    if show_alert:
        data["show_alert"] = True
    try:
        telegram_call("answerCallbackQuery", data)
    except Exception as error:
        logger.warning(
            "Could not answer callback query: %s",
            safe_error_summary(error),
        )
        return False
    return True


def answer_callback_with_message_fallback(
    callback_id: str | None,
    chat_id: int,
    text: str,
    *,
    show_alert: bool = False,
) -> None:
    if answer_callback(callback_id, text=text, show_alert=show_alert):
        return
    try:
        send_message(chat_id, text)
    except Exception as error:
        logger.error(
            "Could not send callback fallback message: %s",
            safe_error_summary(error),
        )


def process_playlist_callback(
    callback: dict[str, Any],
    *,
    callback_id: str | None,
    data: str,
    chat_id: int,
    user_id: int,
    message: dict[str, Any],
    message_id: int,
) -> bool:
    text_message_id = message_id if message.get("text") else None

    if data.startswith("add_fav_"):
        try:
            reference_id = int(data.removeprefix("add_fav_"))
        except ValueError:
            answer_callback(
                callback_id,
                text=tr(user_id, "playlist_track_ref_missing"),
                show_alert=True,
            )
            return True

        audio = get_sent_audio(reference_id)
        if not audio:
            answer_callback(
                callback_id,
                text=tr(user_id, "playlist_track_ref_missing"),
                show_alert=True,
            )
            return True
        added = add_playlist_track(
            user_id,
            str(audio["file_id"]),
            str(audio["title"]),
        )
        answer_callback_with_message_fallback(
            callback_id,
            chat_id,
            tr(user_id, "playlist_saved" if added else "playlist_duplicate"),
        )
        return True

    if data.startswith("play_track_"):
        try:
            track_id = int(data.removeprefix("play_track_"))
        except ValueError:
            track_id = -1
        track = get_user_playlist_track(user_id, track_id)
        if not track:
            answer_callback(
                callback_id,
                text=tr(user_id, "playlist_track_missing"),
                show_alert=True,
            )
            return True

        answer_callback_with_message_fallback(
            callback_id,
            chat_id,
            tr(user_id, "download_started", title=str(track["title"])[:100]),
        )
        try:
            send_cached_audio(
                chat_id,
                track,
                reply_markup=make_playing_track_keyboard(user_id, track_id),
            )
        except Exception as error:
            logger.warning(
                "Could not play saved playlist track (%s)",
                type(error).__name__,
            )
            send_message(chat_id, tr(user_id, "playlist_send_failed"))
        return True

    if data.startswith("del_track_"):
        try:
            track_id = int(data.removeprefix("del_track_"))
        except ValueError:
            track_id = -1
        removed = delete_user_playlist_track(user_id, track_id)
        answer_callback_with_message_fallback(
            callback_id,
            chat_id,
            tr(user_id, "playlist_removed" if removed else "playlist_track_missing"),
            show_alert=not removed,
        )
        show_playlist(
            chat_id,
            user_id,
            message_id=text_message_id,
        )
        return True

    if data == "open_playlist":
        answer_callback(callback_id)
        show_playlist(chat_id, user_id, message_id=text_message_id)
        return True

    if data.startswith("playlist_page_"):
        try:
            page = int(data.removeprefix("playlist_page_"))
        except ValueError:
            page = 0
        answer_callback(callback_id)
        show_playlist(chat_id, user_id, message_id=text_message_id, page=page)
        return True

    if data == "clear_playlist":
        confirmation_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": tr(user_id, "playlist_clear_yes"),
                        "callback_data": "confirm_clear_playlist",
                    },
                    {
                        "text": tr(user_id, "playlist_cancel"),
                        "callback_data": "cancel_clear_playlist",
                    },
                ]
            ]
        }
        answer_callback(callback_id)
        if text_message_id is not None:
            try:
                edit_message(
                    chat_id,
                    text_message_id,
                    tr(user_id, "playlist_clear_confirm"),
                    reply_markup=confirmation_markup,
                )
                return True
            except Exception as error:
                logger.debug(
                    "Could not edit playlist clear confirmation: %s",
                    safe_error_summary(error),
                )
        send_message(
            chat_id,
            tr(user_id, "playlist_clear_confirm"),
            reply_markup=confirmation_markup,
        )
        return True

    if data == "confirm_clear_playlist":
        clear_user_playlist(user_id)
        answer_callback_with_message_fallback(
            callback_id,
            chat_id,
            tr(user_id, "playlist_cleared"),
        )
        show_playlist(chat_id, user_id, message_id=text_message_id)
        return True

    if data == "cancel_clear_playlist":
        answer_callback(callback_id)
        show_playlist(chat_id, user_id, message_id=text_message_id)
        return True

    if data == "shuffle_playlist":
        tracks = get_user_playlist(user_id)
        if not tracks:
            answer_callback(
                callback_id,
                text=tr(user_id, "playlist_empty_shuffle"),
                show_alert=True,
            )
            return True

        with PLAYLIST_SHUFFLE_LOCK:
            if user_id in ACTIVE_PLAYLIST_SHUFFLES:
                answer_callback(
                    callback_id,
                    text=tr(user_id, "playlist_busy"),
                    show_alert=True,
                )
                return True
            ACTIVE_PLAYLIST_SHUFFLES.add(user_id)

        random.shuffle(tracks)
        selected_tracks = tracks[:MAX_PLAYLIST_SHUFFLE_TRACKS]
        if len(tracks) > MAX_PLAYLIST_SHUFFLE_TRACKS:
            notice = tr(
                user_id,
                "playlist_shuffle_limited",
                count=len(selected_tracks),
                total=len(tracks),
            )
        else:
            notice = tr(
                user_id,
                "playlist_shuffle_started",
                count=len(selected_tracks),
            )
        answer_callback_with_message_fallback(callback_id, chat_id, notice)
        try:
            for index, track in enumerate(selected_tracks):
                if index:
                    time.sleep(1.05)
                send_cached_audio(
                    chat_id,
                    track,
                    reply_markup=make_playing_track_keyboard(
                        user_id,
                        int(track["id"]),
                    ),
                )
        except Exception as error:
            logger.warning(
                "Could not send shuffled playlist (%s)",
                type(error).__name__,
            )
            send_message(chat_id, tr(user_id, "playlist_send_failed"))
        finally:
            with PLAYLIST_SHUFFLE_LOCK:
                ACTIVE_PLAYLIST_SHUFFLES.discard(user_id)
        return True

    return False


def handle_callback(callback: dict[str, Any]) -> None:
    data = str(callback.get("data") or "")
    if data == "check_sub":
        handle_subscription_check(callback)
        return

    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    sender = callback.get("from") or {}
    chat_id = int(chat.get("id", 0))
    user_id = int(sender.get("id", chat_id))
    if not chat_id or not user_id:
        answer_callback(callback_id)
        return

    action = {"type": "callback", "payload": callback}
    subscribed = require_channel_subscription(chat_id, user_id, action)
    if subscribed is None:
        answer_callback_with_message_fallback(
            callback_id,
            chat_id,
            text="Не удалось проверить подписку. Попробуйте позже.",
            show_alert=True,
        )
        return
    if not subscribed:
        answer_callback(callback_id)
        return
    process_callback(callback)


def process_callback(callback: dict[str, Any]) -> None:
    callback_id = callback.get("id")
    data = str(callback.get("data") or "")
    message = callback.get("message") or {}
    sender = callback.get("from") or {}
    chat = message.get("chat") or {}
    chat_id = int(chat.get("id", 0))
    message_id = int(message.get("message_id", 0))
    user_id = int(sender.get("id", chat_id))
    key = state_key(chat_id, user_id)

    if not chat_id or not message_id:
        answer_callback(callback_id)
        return

    if process_playlist_callback(
        callback,
        callback_id=callback_id,
        data=data,
        chat_id=chat_id,
        user_id=user_id,
        message=message,
        message_id=message_id,
    ):
        return

    if data == "lang:menu":
        answer_callback(callback_id)
        show_language_menu(chat_id, user_id, message_id=message_id)
        return
    if data.startswith("lang:"):
        language_code = data.partition(":")[2]
        if language_code not in LANGUAGE_LABELS:
            answer_callback(
                callback_id,
                text=tr(user_id, "language_error"),
                show_alert=True,
            )
            return
        LANGUAGE_PREFERENCES[user_id] = language_code
        answer_callback(callback_id)
        edit_message(
            chat_id,
            message_id,
            tr(
                user_id,
                "language_selected",
                language=LANGUAGE_LABELS[language_code],
            ),
            reply_markup=language_keyboard(),
        )
        return

    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "d":
        answer_callback(
            callback_id,
            text=tr(user_id, "choose_track"),
            show_alert=True,
        )
        return

    state = SEARCH_STATE.get(key) or {}
    if parts[1] != state.get("id"):
        answer_callback(
            callback_id,
            text=tr(user_id, "choose_track"),
            show_alert=True,
        )
        return
    try:
        track = state["tracks"][int(parts[2])]
    except (KeyError, IndexError, TypeError, ValueError):
        answer_callback(
            callback_id,
            text=tr(user_id, "invalid_choice"),
            show_alert=True,
        )
        return

    answer_callback(
        callback_id,
        text=tr(
            user_id,
            "download_started",
            title=str(track["title"])[:100],
        ),
    )
    send_downloaded_track(chat_id, user_id, track)


def handle_subscription_check(callback: dict[str, Any]) -> None:
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    sender = callback.get("from") or {}
    chat_id = int(chat.get("id", 0))
    message_id = int(message.get("message_id", 0))
    user_id = int(sender.get("id", chat_id))

    if not chat_id or not message_id or not user_id:
        answer_callback_with_message_fallback(
            callback_id,
            chat_id,
            text="Не удалось проверить подписку. Попробуйте позже.",
            show_alert=True,
        )
        return

    subscribed = check_channel_subscription(user_id)
    if subscribed is None:
        answer_callback_with_message_fallback(
            callback_id,
            chat_id,
            text="Не удалось проверить подписку. Попробуйте позже.",
            show_alert=True,
        )
        return
    if not subscribed:
        answer_callback_with_message_fallback(
            callback_id,
            chat_id,
            text="Подписка не обнаружена.",
            show_alert=True,
        )
        return

    answer_callback_with_message_fallback(
        callback_id,
        chat_id,
        text="Успешно!",
    )

    key = state_key(chat_id, user_id)
    pending = PENDING_SUBSCRIPTION_ACTIONS.get(key)
    matching_prompt = bool(
        pending
        and int(pending.get("prompt_message_id") or 0) == message_id
    )
    if not matching_prompt:
        # In group chats, another member can tap the same inline button.
        # Do not remove the original user's prompt or consume their request.
        if chat_id == user_id:
            delete_telegram_message(chat_id, message_id)
        return

    delete_telegram_message(chat_id, message_id)
    PENDING_SUBSCRIPTION_ACTIONS.pop(key, None)
    action = pending.get("action") or {}
    if action.get("type") == "message":
        process_message(action["payload"])
    elif action.get("type") == "callback":
        delayed_callback = dict(action["payload"])
        delayed_callback["id"] = None
        process_callback(delayed_callback)


def handle_update(update: dict[str, Any]) -> None:
    callback = update.get("callback_query")
    if callback:
        handle_callback(callback)
    elif update.get("message"):
        handle_message(update["message"])


def process_update_safely(update: dict[str, Any]) -> None:
    try:
        handle_update(update)
    except Exception as error:
        logger.error(
            "Could not process Telegram update %s: %s",
            update.get("update_id", "unknown"),
            safe_error_summary(error),
        )


def main() -> None:
    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("AUDD_API_KEY", AUDD_API_KEY),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Не заданы Secrets: " + ", ".join(missing) + ". Добавьте их перед запуском."
        )

    try:
        initialize_playlist_database()
    except (OSError, sqlite3.Error) as error:
        logger.error(
            "Could not initialize the playlist database (%s)",
            type(error).__name__,
        )
        raise SystemExit(1) from None

    try:
        bot_info = telegram_call("getMe", timeout=15)
    except Exception as error:
        logger.error(
            "Telegram authorization failed: %s. Check TELEGRAM_BOT_TOKEN.",
            safe_error_summary(error),
        )
        raise SystemExit(1) from None

    if not verify_bot_channel_access(int(bot_info["id"])):
        raise SystemExit(1)

    logger.info("Bot started: @%s", bot_info.get("username", "unknown"))
    next_update_id: int | None = None
    update_executor = ThreadPoolExecutor(
        max_workers=MAX_CONCURRENT_UPDATES,
        thread_name_prefix="telegram-update",
    )
    update_capacity = threading.BoundedSemaphore(
        MAX_CONCURRENT_UPDATES + MAX_QUEUED_UPDATES
    )
    try:
        while True:
            params: dict[str, Any] = {
                "timeout": 25,
                "allowed_updates": json.dumps(["message", "callback_query"]),
            }
            if next_update_id is not None:
                params["offset"] = next_update_id
            try:
                updates = telegram_call(
                    "getUpdates",
                    params,
                    http_method="GET",
                    timeout=35,
                )
                for update in updates or []:
                    next_update_id = int(update["update_id"]) + 1
                    update_capacity.acquire()
                    try:
                        future = update_executor.submit(process_update_safely, update)
                    except Exception:
                        update_capacity.release()
                        raise
                    future.add_done_callback(lambda _future: update_capacity.release())
            except KeyboardInterrupt:
                logger.info("Bot stopped")
                break
            except Exception as error:
                logger.warning(
                    "Telegram polling failed: %s; retrying in 5 seconds",
                    safe_error_summary(error),
                )
                time.sleep(5)
    finally:
        update_executor.shutdown(wait=True)


if __name__ == "__main__":
    main()