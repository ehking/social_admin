"""CLI utility for producing a short vertical video with trending audio and Persian captions."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.backend.config import get_settings
from app.backend.database import SessionLocal
from app.backend.services import TrendingVideoCreator, Worker, get_storage_service

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", type=Path, help="Path to a Nastaliq (or compatible) font file")
    parser.add_argument(
        "output",
        type=Path,
        help="Desired filename for the rendered video (used as object key)",
    )
    parser.add_argument("--country", default="us", help="Apple Music store country code (default: us)")
    parser.add_argument("--limit", type=int, default=5, help="Number of trending tracks to fetch")
    parser.add_argument("--index", type=int, default=0, help="Index of the track to render (default: 0)")
    parser.add_argument(
        "--caption",
        default="بهترین ترند این هفته: {track}",
        help="Caption template. Use {track} as placeholder for title and artist.",
    )
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="Disable automatic translation (expects Persian text in caption).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    LOGGER.info("Fetching top %s tracks for %s", args.limit, args.country.upper())
    tracks = TrendingVideoCreator.fetch_trending_tracks(country=args.country, limit=args.limit)
    if not tracks:
        raise SystemExit("No tracks found. Try a different country or limit.")

    try:
        track = tracks[args.index]
    except IndexError as exc:  # pragma: no cover - guard clause
        raise SystemExit(f"Track index {args.index} is out of range for {len(tracks)} tracks") from exc

    LOGGER.info("Selected track: %s", track.display_name)
    settings = get_settings()
    worker = Worker(settings=settings)
    storage_service = get_storage_service(settings)

    session = SessionLocal()
    result = None
    try:
        creator = TrendingVideoCreator(
            font_path=args.font,
            worker=worker,
            storage_service=storage_service,
            db_session=session,
            settings=settings,
        )
        result = creator.generate_trend_video(
            track=track,
            caption_template=args.caption,
            output_path=args.output,
            translate=not args.no_translate,
            job_name=f"trend-video:{track.display_name}",
        )
    finally:
        session.close()

    if result is None:  # pragma: no cover - defensive guard
        return

    LOGGER.info("Video uploaded to storage with key %s", result.storage_key)
    if result.storage_url:
        LOGGER.info("Storage URL: %s", result.storage_url)
    if result.job_media_id is not None:
        LOGGER.info("Recorded JobMedia row with id %s", result.job_media_id)


if __name__ == "__main__":
    main()
