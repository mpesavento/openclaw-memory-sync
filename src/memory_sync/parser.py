"""JSONL session log parser."""

from pathlib import Path
from typing import Iterator
import json


def parse_jsonl(path: Path) -> Iterator[dict]:
    """Stream parse a JSONL file, yielding records."""
    # TODO: Implement streaming parser
    pass


def get_messages(path: Path) -> Iterator[dict]:
    """Extract message records from a session log."""
    # TODO: Implement
    pass


def get_model_snapshots(path: Path) -> Iterator[dict]:
    """Extract model-snapshot records for transition tracking."""
    # TODO: Implement
    pass


def get_compactions(path: Path) -> Iterator[dict]:
    """Extract compaction summaries (useful for backfill)."""
    # TODO: Implement
    pass
