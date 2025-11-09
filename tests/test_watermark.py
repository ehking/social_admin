import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.video import BENITA_MUSIC_WATERMARK, WatermarkConfig, ensure_benita_watermark


def test_watermark_added_when_missing():
    overlays = [WatermarkConfig(text="Intro title", position="center")]

    result = ensure_benita_watermark(overlays)

    assert result[0] == BENITA_MUSIC_WATERMARK
    assert overlays[0] in result


def test_watermark_replaced_when_misconfigured():
    overlays = [
        WatermarkConfig(text="Benita Music", position="bottom-right", font_size=12),
        WatermarkConfig(text="CTA", position="bottom-center"),
    ]

    result = ensure_benita_watermark(overlays)

    assert result[0] == BENITA_MUSIC_WATERMARK
    assert result[1:] == overlays[1:]
