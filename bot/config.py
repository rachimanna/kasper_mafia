from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки читаются из переменных окружения или файла .env."""

    BOT_TOKEN: str = Field(..., description="Токен бота от @BotFather")
    BOT_USERNAME: str = Field(default="", description="Заполняется автоматически при старте")
    DB_PATH: str = Field(default="mafia.db")

    # --- Игроки ---
    MIN_PLAYERS: int = Field(default=4, ge=3)
    MAX_PLAYERS: int = Field(default=20, ge=4, le=30)

    # --- Тайминги, секунды ---
    REGISTRATION_TIME: int = Field(default=120, ge=5)
    REGISTRATION_EXTEND: int = Field(default=30, ge=5)
    NIGHT_TIME: int = Field(default=60, ge=5)
    DAY_TIME: int = Field(default=45, ge=5, description="Базовое время обсуждения днём")
    DAY_TIME_PER_PLAYER: int = Field(default=5, ge=0, description="+ секунд обсуждения за каждого живого игрока")
    VOTE_TIME: int = Field(default=45, ge=5)
    CONFIRM_TIME: int = Field(default=30, ge=5)
    LAST_WORDS_TIME: int = Field(default=45, ge=5)
    PHASE_PAUSE: float = Field(default=3, ge=0, description="Пауза между сообщениями фаз для драматизма")

    # --- Правила ---
    MAX_IDLE_ROUNDS: int = Field(default=3, ge=1, description="Ничья, если столько кругов подряд никто не погиб")
    AFK_LIMIT: int = Field(default=2, ge=0, description="Выбывает, пропустив столько голосований подряд (0 = выкл)")
    REVEAL_ROLES: bool = Field(default=True, description="Показывать роль погибшего")
    DELETE_MESSAGES: bool = Field(default=True, description="Удалять сообщения мёртвых и ночные сообщения (нужны права админа)")

    # --- Хостинг ---
    WEB_SERVER_ENABLED: bool = Field(default=True)
    PORT: int = Field(default=8080)
    API_SERVER: str = Field(default="", description="Свой сервер Bot API (для тестов), обычно пусто")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


config = Settings()
