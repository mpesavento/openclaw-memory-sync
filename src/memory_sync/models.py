"""Data models for memory-sync."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Optional


@dataclass
class Message:
    """Represents a parsed message from a JSONL session log."""
    id: str
    timestamp: datetime
    role: Literal["user", "assistant", "toolResult"]
    text_content: str
    model: Optional[str] = None
    provider: Optional[str] = None
    has_tool_calls: bool = False
    has_thinking: bool = False


@dataclass
class ModelTransition:
    """Represents a model switch detected in session logs."""
    timestamp: datetime
    from_model: Optional[str]
    to_model: str
    session_id: str
    provider: str
    from_provider: Optional[str] = None


@dataclass
class DayActivity:
    """Summary of activity for a single day across all sessions."""
    date: date
    message_count: int
    user_messages: int
    assistant_messages: int
    tool_result_messages: int
    models_used: list[str] = field(default_factory=list)
    transitions: list[ModelTransition] = field(default_factory=list)
    session_ids: list[str] = field(default_factory=list)


@dataclass
class MemoryGap:
    """Represents a gap in memory coverage."""
    date: date
    gap_type: Literal["missing", "sparse"]
    activity: DayActivity
    memory_file_size: int
    reason: str


@dataclass
class ValidationIssue:
    """Represents a validation issue with a memory file."""
    file_path: str
    issue_type: Literal["naming", "header_mismatch", "too_small", "orphaned", "parse_error"]
    description: str
    severity: Literal["warning", "error"] = "warning"


@dataclass
class SessionStats:
    """Statistics about session logs."""
    file_count: int
    total_size_bytes: int
    message_count: int
    user_message_count: int
    assistant_message_count: int
    tool_result_count: int
    transition_count: int
    models_used: list[str] = field(default_factory=list)
    date_range: tuple[Optional[date], Optional[date]] = (None, None)


@dataclass
class MemoryStats:
    """Statistics about memory files."""
    file_count: int
    total_size_bytes: int
    date_range: tuple[Optional[date], Optional[date]] = (None, None)
    coverage_pct: float = 0.0
