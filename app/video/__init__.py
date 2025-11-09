"""Utilities for automatic video assembly and post-processing."""

from .watermark import BENITA_MUSIC_WATERMARK, WatermarkConfig, ensure_benita_watermark

__all__ = [
    "WatermarkConfig",
    "BENITA_MUSIC_WATERMARK",
    "ensure_benita_watermark",
]
