"""Validated service configuration."""
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    environment: str = "development"

    def __post_init__(self):
        if self.environment not in {"development", "test", "staging", "production"}:
            raise ValueError("Invalid service environment")

    @classmethod
    def from_env(cls):
        return cls(environment=os.getenv("ITHUTECODE_ENVIRONMENT", "development"))
