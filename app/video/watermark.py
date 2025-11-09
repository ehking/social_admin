"""Watermark helpers used by the automated video compositor.

The system assembles clips based on scene specifications.  Each scene exposes a
list of overlay instructions (images, captions, logos, etc.).  Historically the
watermark was injected manually at the final rendering stage which caused
inconsistent placement and occasional omissions.  The helpers in this module
ensure that the "Benita Music" label is always present in the upper-left corner
before the scene instructions are sent to the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class WatermarkConfig:
    """Describes a text watermark overlay that the renderer can draw."""

    text: str
    position: str
    font: str = "IRANSans-Bold"
    font_size: int = 48
    padding: int = 32
    opacity: float = 0.9
    color: str = "#FFFFFF"
    background_color: str = "#00000080"

    def to_payload(self) -> dict:
        """Return a serialisable payload used by downstream rendering workers."""

        return {
            "type": "text",
            "text": self.text,
            "position": self.position,
            "font": self.font,
            "font_size": self.font_size,
            "padding": self.padding,
            "opacity": self.opacity,
            "color": self.color,
            "background_color": self.background_color,
        }


BENITA_MUSIC_WATERMARK = WatermarkConfig(
    text="Benita Music",
    position="top-left",
    font="IRANSans-Bold",
    font_size=48,
    padding=32,
    opacity=0.92,
    color="#FFFFFF",
    background_color="#000000B3",
)


def ensure_benita_watermark(overlays: Iterable[WatermarkConfig]) -> List[WatermarkConfig]:
    """Return overlays with the Benita Music watermark guaranteed to exist.

    The helper keeps the watermark idempotent so callers can safely run it on
    every scene configuration without worrying about duplicate entries.  It
    preserves the order of existing overlays while inserting the watermark at
    the beginning to keep it consistently on top of other layers.
    """

    overlays_list = list(overlays)
    if not any(overlay.text.strip().lower() == "benita music" for overlay in overlays_list):
        overlays_list.insert(0, BENITA_MUSIC_WATERMARK)
    else:
        overlays_list = [
            BENITA_MUSIC_WATERMARK if overlay.text.strip().lower() == "benita music" else overlay
            for overlay in overlays_list
        ]
    return overlays_list
