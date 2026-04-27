"""Application configuration management."""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # OpenAI Configuration
    OPENAI_API_KEY: str = ""

    # File Upload Settings
    MAX_FILE_SIZE: int = 419430400  # 400MB in bytes

    # TTS Configuration (edge-tts, free, no API key)
    TTS_VOICE: str = "pt-BR-AntonioNeural"  # default voice
    TTS_MAX_CHARS_PER_CHAPTER: int = 50000  # safety cap per chapter
    TTS_ENABLED: bool = True

    # Summarization
    SUMMARIZER_BACKEND: str = "sumy"  # "sumy" or "huggingface"

    # Storage Paths
    UPLOAD_DIR: str = "./uploads"
    OUTPUT_DIR: str = "./outputs"

    # CORS Configuration
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"

    # Rate Limiting
    RATE_LIMIT_UPLOAD: int = 10
    RATE_LIMIT_GENERAL: int = 100

    # Task Management
    TASK_RETENTION_HOURS: int = 6
    MAX_DISK_USAGE_MB: int = 400  # auto-purge oldest tasks when exceeded

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    def ensure_directories(self):
        """Create necessary directories if they don't exist."""
        Path(self.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        Path(f"{self.OUTPUT_DIR}/audio").mkdir(parents=True, exist_ok=True)
        Path(f"{self.OUTPUT_DIR}/summaries").mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
settings.ensure_directories()
