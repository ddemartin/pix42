"""Application-wide configuration with sensible defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    """Return platform-appropriate user-data directory."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "LumaViewer"


@dataclass
class CacheConfig:
    max_ram_entries: int   = 64
    max_ram_mb:      float = 256.0
    db_path:         Path  = field(default_factory=lambda: _default_data_dir() / "cache.db")
    thumb_size:      int   = 256
    jpeg_quality:    int   = 80


@dataclass
class LoaderConfig:
    preview_size:      int   = 2048     # max side for fit-to-window preview
    tiled_threshold_mb: float = 512.0   # images larger than this → tiled mode
    thread_pool_size:  int   = 4


@dataclass
class UIConfig:
    window_width:   int  = 1280
    window_height:  int  = 800
    overlay_hide_ms: int = 2500
    zoom_step:      float = 1.25
    thumb_cell_size: int  = 152


@dataclass
class AppConfig:
    data_dir: Path       = field(default_factory=_default_data_dir)
    cache:    CacheConfig  = field(default_factory=CacheConfig)
    loader:   LoaderConfig = field(default_factory=LoaderConfig)
    ui:       UIConfig     = field(default_factory=UIConfig)
    log_level: str         = "INFO"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


# Module-level singleton — import and override fields as needed
config = AppConfig()

# Path to the bundled assets directory
ASSETS_DIR = Path(__file__).parent / "assets"
