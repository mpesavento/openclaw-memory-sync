"""Model transition tracking."""

from pathlib import Path
from typing import Iterator
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ModelTransition:
    timestamp: datetime
    from_model: str | None
    to_model: str
    session_id: str
    provider: str


def extract_transitions(sessions_dir: Path) -> Iterator[ModelTransition]:
    """Extract all model transitions from session logs."""
    # TODO: Implement
    pass


def write_transitions_json(transitions: list[ModelTransition], output_path: Path):
    """Write transitions to JSON file for tracking."""
    # TODO: Implement
    pass
