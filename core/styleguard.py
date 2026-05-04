import json
from typing import Dict, Tuple

REQUIRED_FIELDS = {"human_part", "mentor_part", "lesson"}  # подставьте свои поля


class StyleGuard:
    """
    Валидирует пост на соответствие стилю, запрещённым словам и структуре.
    """

    def __init__(self, forbidden_words_file: str = "forbidden_words.json"):
        with open(forbidden_words_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.forbidden_words = set(data.get("forbidden", []))
        self.style_markers = data.get("style_markers", [])  # слова/фразы, которые ДОЛЖНЫ быть

    def validate(self, post: dict) -> tuple[bool, str]:
        """
        Возвращает (True, "") если пост корректен, иначе (False, "причина").
        """
        # 1. Проверка структуры
        missing = REQUIRED_FIELDS - post.keys()
        if missing:
            return False, f"Отсутствуют обязательные поля: {missing}"

        # 2. Проверка запрещённых слов (сканируем все текстовые поля)
        for key, value in post.items():
            if isinstance(value, str):
                lower_val = value.lower()
                for word in self.forbidden_words:
                    if word in lower_val:
                        return False, f"Запрещённое слово '{word}' в поле '{key}'"

        # 3. Проверка наличия хотя бы одного маркера стиля
        all_text = " ".join(
            str(v) for v in post.values() if isinstance(v, str)
        ).lower()
        if self.style_markers:
            if not any(marker in all_text for marker in self.style_markers):
                return False, "Нет ни одного маркера фирменного стиля"

        return True, ""