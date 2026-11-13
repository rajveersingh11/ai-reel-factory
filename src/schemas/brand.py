"""
Brand Configuration Schemas & Registry
======================================
Loads brand identities dynamically from config/brands.yaml (Requirement 4.B).
Neither SKYON nor R4Realty is hardcoded in core logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field

from src.core.config import PROJECT_ROOT


class BrandConfig(BaseModel):
    id: str
    name: str
    tagline: str
    target_audience: str
    tone: str
    primary_color: str = "#00D4FF"
    secondary_color: str = "#0D1B2A"
    accent_color: str = "#00E5FF"
    font_family: str = "Inter Bold"
    topics: list[str] = Field(default_factory=list)
    bgm_track: Optional[str] = None
    bgm_volume: float = Field(default=0.18, ge=0.0, le=1.0)


class BrandRegistry:
    """Loads and caches brand configuration profiles."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (PROJECT_ROOT / "config" / "brands.yaml")
        self._brands: dict[str, BrandConfig] = {}
        self.load()

    def load(self) -> None:
        if not self.config_path.exists():
            return
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        for b_id, b_data in data.get("brands", {}).items():
            self._brands[b_id.lower().strip()] = BrandConfig(**b_data)

    def get(self, brand_id: str) -> BrandConfig:
        b_id = brand_id.lower().strip()
        if b_id not in self._brands:
            raise KeyError(
                f"Brand '{brand_id}' not found in registry. "
                f"Available brands: {list(self._brands.keys())}"
            )
        return self._brands[b_id]

    def list_brands(self) -> list[BrandConfig]:
        return list(self._brands.values())

    def list_all(self) -> list[BrandConfig]:
        """Alias for list_brands."""
        return self.list_brands()


# Global brand registry instance
brand_registry = BrandRegistry()

