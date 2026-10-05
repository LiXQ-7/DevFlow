"""Environment configuration; secrets never appear in model dumps."""

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, model_validator


class Config(BaseModel):
    project_root: Path = Field(default_factory=Path.cwd)
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr = SecretStr("")
    max_steps: int = Field(default=20, ge=1, le=100)
    context_window: int = Field(default=32000, ge=2048)
    reserve_tokens: int = Field(default=4096, ge=256)
    keep_recent_rounds: int = Field(default=3, ge=1)
    output_max_bytes: int = Field(default=12000, ge=256)
    output_max_lines: int = Field(default=200, ge=4)
    command_timeout: int = Field(default=30, ge=1, le=300)
    allow_shell: bool = False
    request_timeout: int = Field(default=60, ge=1, le=300)
    temperature: float = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def validate_budget(self):
        self.project_root = self.project_root.resolve()
        if not self.project_root.is_dir():
            raise ValueError("project_root must be a directory")
        if self.reserve_tokens >= self.context_window:
            raise ValueError("reserve_tokens must be smaller than context_window")
        return self

    @property
    def state_dir(self) -> Path:
        path = self.project_root / ".devflow"
        if not path.resolve().is_relative_to(self.project_root):
            raise ValueError(".devflow must not resolve outside project_root")
        for child in ("outputs", "sessions", "traces", "locks"):
            if not (path / child).resolve().is_relative_to(self.project_root):
                raise ValueError(f".devflow/{child} must not resolve outside project_root")
        return path

    @classmethod
    def load(cls, root: Path | None = None):
        root = (root or Path.cwd()).resolve()
        env = {**dotenv_values(root / ".env"), **os.environ}
        values = {"project_root": root}
        for name in cls.model_fields:
            key = "DEVFLOW_" + name.upper()
            if env.get(key) is not None:
                values[name] = env[key]
        for name, aliases in {
            "api_key": ["LLM_API_KEY", "OPENAI_API_KEY"],
            "model": ["LLM_MODEL_ID", "OPENAI_MODEL"],
            "base_url": ["LLM_BASE_URL", "OPENAI_BASE_URL"],
        }.items():
            if name not in values:
                for alias in aliases:
                    if env.get(alias):
                        values[name] = env[alias]
                        break
        return cls(**values)
