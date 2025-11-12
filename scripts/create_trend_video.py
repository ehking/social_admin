"""CLI utility for producing a short vertical video with trending audio and Persian captions."""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path
from typing import Sequence

from app.backend.config import get_settings
from app.backend.database import SessionLocal
from app.backend.services import TrendingVideoCreator, Worker, get_storage_service

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
LOGGER = logging.getLogger(__name__)


class TrendVideoCLI:
    """Object-oriented orchestrator for the ``create_trend_video`` workflow."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        settings_provider=get_settings,
        session_factory=SessionLocal,
        worker_factory=None,
        storage_factory=None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[1]
        self._settings_provider = settings_provider
        self._session_factory = session_factory
        self._worker_factory = worker_factory or (lambda settings: Worker(settings=settings))
        self._storage_factory = storage_factory or (
            lambda settings: get_storage_service(settings)
        )
        self.logger = logger or LOGGER

    def run(self, argv: Sequence[str] | None = None) -> None:
        """Execute the CLI workflow."""

        self.ensure_repository_is_current()
        args = self.parse_args(argv)
        tracks = self.fetch_tracks(limit=args.limit, country=args.country)
        track = self.select_track(tracks, args.index)
        result = self.create_video(track=track, args=args)
        if result is None:  # pragma: no cover - defensive guard
            return
        self.log_result(result)

    def ensure_repository_is_current(self) -> None:
        """Run ``git pull`` in the project root before continuing."""

        self.logger.info("Updating repository in %s", self.repo_root)
        try:
            result = subprocess.run(
                ["git", "pull"],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:  # pragma: no cover - environment guard
            raise SystemExit(
                "Git executable not found. Please install Git to continue."
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else str(exc)
            raise SystemExit(f"Failed to update repository: {stderr}") from exc

        stdout = result.stdout.strip()
        if stdout:
            self.logger.info("git pull output:\n%s", stdout)

        stderr = result.stderr.strip()
        if stderr:
            self.logger.warning("git pull reported:\n%s", stderr)

    def parse_args(self, argv: Sequence[str] | None = None) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("font", type=Path, help="Path to a Nastaliq (or compatible) font file")
        parser.add_argument(
            "output",
            type=Path,
            help="Desired filename for the rendered video (used as object key)",
        )
        parser.add_argument(
            "--country", default="us", help="Apple Music store country code (default: us)"
        )
        parser.add_argument("--limit", type=int, default=5, help="Number of trending tracks to fetch")
        parser.add_argument(
            "--index", type=int, default=0, help="Index of the track to render (default: 0)"
        )
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
        return parser.parse_args(argv)

    def fetch_tracks(self, *, limit: int, country: str):
        self.logger.info("Fetching top %s tracks for %s", limit, country.upper())
        tracks = TrendingVideoCreator.fetch_trending_tracks(country=country, limit=limit)
        if not tracks:
            raise SystemExit("No tracks found. Try a different country or limit.")
        return tracks

    def select_track(self, tracks, index: int):
        try:
            track = tracks[index]
        except IndexError as exc:  # pragma: no cover - guard clause
            raise SystemExit(
                f"Track index {index} is out of range for {len(tracks)} tracks"
            ) from exc
        self.logger.info("Selected track: %s", track.display_name)
        return track

    def create_video(self, *, track, args: argparse.Namespace):
        settings = self._settings_provider()
        worker = self._worker_factory(settings)
        storage_service = self._storage_factory(settings)

        session = self._session_factory()
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
        return result

    def log_result(self, result) -> None:
        self.logger.info("Video uploaded to storage with key %s", result.storage_key)
        if result.storage_url:
            self.logger.info("Storage URL: %s", result.storage_url)
        if result.job_media_id is not None:
            self.logger.info("Recorded JobMedia row with id %s", result.job_media_id)
        if result.local_path is not None:
            self.logger.info("Local copy saved to %s", result.local_path)


def main(argv: Sequence[str] | None = None) -> None:
    TrendVideoCLI().run(argv)


if __name__ == "__main__":
    main()
