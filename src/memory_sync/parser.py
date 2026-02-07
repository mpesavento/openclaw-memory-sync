"""JSONL session log parser."""

from pathlib import Path
from typing import Iterator, Optional
from datetime import datetime, date, timezone
import json
import sys

from .models import Message, ModelTransition


def parse_jsonl(path: Path) -> Iterator[dict]:
    """
    Stream parse a JSONL file, yielding records.

    Handles malformed lines by skipping them with a warning to stderr.
    Memory-efficient: processes line-by-line without loading entire file.
    """
    with open(path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                # Only log error type and location, not the content (which might contain secrets)
                print(f"Warning: Skipping malformed JSON at {path}:{line_num} ({type(e).__name__})", file=sys.stderr)


def get_session_metadata(path: Path) -> Optional[dict]:
    """
    Extract session record (first line with type: "session").

    Returns None if no session record found.
    """
    for record in parse_jsonl(path):
        if record.get('type') == 'session':
            return record
    return None


def _parse_timestamp(record: dict) -> Optional[datetime]:
    """
    Parse timestamp from a record.

    Handles both ISO 8601 strings (outer record timestamp) and
    Unix milliseconds (message.timestamp).
    """
    # Try outer timestamp first (ISO 8601)
    if 'timestamp' in record:
        ts = record['timestamp']
        if isinstance(ts, str):
            try:
                # Handle ISO 8601 format with Z suffix
                ts_str = ts.replace('Z', '+00:00')
                return datetime.fromisoformat(ts_str)
            except ValueError:
                pass
        elif isinstance(ts, (int, float)):
            # Unix milliseconds
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

    # Try nested message timestamp (Unix ms)
    if 'message' in record and 'timestamp' in record['message']:
        ts = record['message']['timestamp']
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

    return None


def _extract_text_content(content: list) -> str:
    """Extract text content from a content array."""
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get('type') == 'text':
            text = block.get('text', '')
            if text:
                texts.append(text)
    return '\n'.join(texts)


def _has_tool_calls(content: list) -> bool:
    """Check if content contains tool calls."""
    for block in content:
        if isinstance(block, dict) and block.get('type') == 'toolCall':
            return True
    return False


def _has_thinking(content: list) -> bool:
    """Check if content contains thinking blocks."""
    for block in content:
        if isinstance(block, dict) and block.get('type') == 'thinking':
            return True
    return False


def get_messages(path: Path, date_filter: Optional[date] = None) -> Iterator[Message]:
    """
    Extract message records from a session log.

    Args:
        path: Path to the JSONL file
        date_filter: Optional date to filter messages by (UTC date)

    Yields:
        Message objects for user, assistant, and toolResult messages
    """
    for record in parse_jsonl(path):
        if record.get('type') != 'message':
            continue

        msg = record.get('message', {})
        if not msg:
            continue

        timestamp = _parse_timestamp(record)
        if timestamp is None:
            continue

        # Apply date filter
        if date_filter is not None:
            if timestamp.date() != date_filter:
                continue

        role = msg.get('role')
        if role not in ('user', 'assistant', 'toolResult'):
            continue

        content = msg.get('content', [])
        if not isinstance(content, list):
            content = []

        # For toolResult, content might be in a different format
        if role == 'toolResult':
            text_content = _extract_text_content(content)
        else:
            text_content = _extract_text_content(content)

        yield Message(
            id=record.get('id', ''),
            timestamp=timestamp,
            role=role,
            text_content=text_content,
            model=msg.get('model'),
            provider=msg.get('provider'),
            has_tool_calls=_has_tool_calls(content),
            has_thinking=_has_thinking(content),
        )


def get_model_transitions(path: Path) -> Iterator[ModelTransition]:
    """
    Extract model transitions from a session log.

    Tracks both explicit model_change records and model field changes in messages.
    """
    session_meta = get_session_metadata(path)
    session_id = session_meta.get('id', path.stem) if session_meta else path.stem

    current_model: Optional[str] = None
    current_provider: Optional[str] = None

    for record in parse_jsonl(path):
        record_type = record.get('type')

        # Handle explicit model_change records
        if record_type == 'model_change':
            new_model = record.get('modelId')
            new_provider = record.get('provider', '')
            timestamp = _parse_timestamp(record)

            if timestamp and new_model:
                yield ModelTransition(
                    timestamp=timestamp,
                    from_model=current_model,
                    to_model=new_model,
                    session_id=session_id,
                    provider=new_provider,
                    from_provider=current_provider,
                )
                current_model = new_model
                current_provider = new_provider

        # Track model from messages too (in case model_change records are missing)
        elif record_type == 'message':
            msg = record.get('message', {})
            model = msg.get('model')
            provider = msg.get('provider')

            if model and model != current_model:
                timestamp = _parse_timestamp(record)
                if timestamp:
                    # Only yield if we had a previous model (not first message)
                    if current_model is not None:
                        yield ModelTransition(
                            timestamp=timestamp,
                            from_model=current_model,
                            to_model=model,
                            session_id=session_id,
                            provider=provider or '',
                            from_provider=current_provider,
                        )
                    current_model = model
                    current_provider = provider


def get_compactions(path: Path) -> Iterator[dict]:
    """
    Extract compaction summaries from a session log.

    Compaction records contain AI-generated summaries of conversation context,
    useful for memory backfill.
    """
    for record in parse_jsonl(path):
        if record.get('type') != 'compaction':
            continue

        timestamp = _parse_timestamp(record)

        yield {
            'id': record.get('id'),
            'timestamp': timestamp,
            'summary': record.get('summary', ''),
            'firstKeptEntryId': record.get('firstKeptEntryId'),
            'tokensBefore': record.get('tokensBefore'),
            'details': record.get('details', {}),
        }


def get_model_snapshots(path: Path) -> Iterator[dict]:
    """
    Extract model-snapshot custom records for transition tracking.

    These records provide detailed model configuration snapshots.
    """
    for record in parse_jsonl(path):
        if record.get('type') != 'custom':
            continue
        if record.get('customType') != 'model-snapshot':
            continue

        data = record.get('data', {})
        timestamp = _parse_timestamp(record)

        yield {
            'id': record.get('id'),
            'timestamp': timestamp,
            'provider': data.get('provider'),
            'modelId': data.get('modelId'),
            'modelApi': data.get('modelApi'),
        }
