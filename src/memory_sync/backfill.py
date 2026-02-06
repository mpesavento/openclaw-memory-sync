"""Memory file generation from session logs."""

from pathlib import Path
from datetime import date


def generate_daily_memory(log_date: date, sessions_dir: Path, output_path: Path) -> str:
    """
    Generate a daily memory file from session logs.
    
    Uses compaction summaries when available, falls back to message extraction.
    """
    # TODO: Implement
    pass


def backfill_all_missing(sessions_dir: Path, memory_dir: Path, dry_run: bool = False):
    """Backfill all missing daily memory files."""
    # TODO: Implement
    pass
