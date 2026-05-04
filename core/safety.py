import json
import random
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from aiogram import Bot


class Sentinel:
    """
    Единая точка обработки всех сбоев.
    При ошибке гарантированно публикует запасной пост и уведомляет владельца.
    """

    def __init__(
        self,
        bot: Bot,
        channel_id: int | str,
        owner_chat_id: int,
        fallback_file: str = "fallback_lessons.json",
    ):
        self.bot = bot
        self.channel_id = channel_id
        self.owner_chat_id = owner_chat_id
        self.fallback_file = Path(fallback_file)
        self._load_fallback()

    def _load_fallback(self):
        """Загружает базу резервных постов из JSON."""
        with open(self.fallback_file, "r", encoding="utf-8") as f:
            self.fallback_posts = json.load(f)
        if not self.fallback_posts:
            raise ValueError("Файл fallback_lessons.json не должен быть пустым!")

    async def safe_execute(self, coro: Coroutine[Any, Any, None], context: str = ""):
        """
        Выполняет корутину и при любом исключении публикует fallback + детальный отчёт.
        :param coro: основная логика генерации и постинга
        :param context: человекочитаемое описание операции для логов
        """
        try:
            await coro
        except Exception as e:
            tb = traceback.format_exc()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            error_msg = (
                f"🚨 *СБОЙ* в боте ({now})\n"
                f"📍 Модуль: {context or 'неизвестно'}\n"
                f"❗ Ошибка: {type(e).__name__}: {e}\n"
                f"```{tb[-1500:]}```"
            )
            # Пишем владельцу
            await self.bot.send_message(
                self.owner_chat_id, error_msg, parse_mode="Markdown"
            )
            # Публикуем резервный пост в канал
            await self._publish_fallback()

    async def _publish_fallback(self):
        """Отправляет случайный образовательный пост из резервного фонда."""
        post = random.choice(self.fallback_posts)
        text = f"{post['title']}\n\n{post['body']}"
        await self.bot.send_message(self.channel_id, text)