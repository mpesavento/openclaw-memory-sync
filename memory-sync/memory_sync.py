#!/usr/bin/env python3
"""Memory Sync - Single-file CLI for OpenClaw session log analysis.

Requires Python 3.11+ and click. Optional: anthropic for LLM summaries.

This tool scrapes JSONL session logs from OpenClaw and generates/backfills
daily memory files. It includes automatic secret sanitization, LLM-based
summarization, gap detection, and state tracking for incremental backfill.

Usage:
    python memory_sync.py compare                    # Check coverage
    python memory_sync.py backfill --today           # Backfill today
    python memory_sync.py backfill --all             # Backfill all missing
    python memory_sync.py backfill --today --summarize  # With LLM summary
"""

# =============================================================================
# IMPORTS
# =============================================================================

import sys
import os
import re
import json
import time
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field
from typing import Iterator, Optional, Tuple, List, Literal
from collections import defaultdict
from enum import Enum
import tempfile

import click

# Optional: anthropic for LLM summarization (only imported if needed)
# Will gracefully handle ImportError in summarization functions


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# Default paths for OpenClaw
DEFAULT_SESSIONS_DIR = Path.home() / '.openclaw' / 'agents' / 'main' / 'sessions'
DEFAULT_MEMORY_DIR = Path.home() / '.openclaw' / 'workspace' / 'memory'

# Local timezone for bucketing "days" (Mike/Wren live in PST/PDT)
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# Thresholds for gap detection (FIXED: sparse threshold lowered to 5)
MIN_FILE_SIZE_BYTES = 1024
MIN_BYTES_PER_MESSAGE = 3  # Heuristic floor; high tool-result volume can depress bytes/msg even with good summaries

# Markers for identifying auto-generated content
AUTO_GENERATED_HEADER_PATTERN = r'\*Auto-generated from \d+ session messages\*'
AUTO_GENERATED_FOOTER = '*Review and edit this draft to capture what\'s actually important.*'

# Validation thresholds
MIN_VALID_SIZE = 100  # bytes - minimum size for a memory file to be considered non-empty

# Default LLM model for summarization
DEFAULT_SUMMARIZE_MODEL = "claude-sonnet-4-5"
# Faster/cheaper model for individual chunk summaries (chunks get synthesized later)
DEFAULT_CHUNK_MODEL = "claude-3-haiku-20240307"
# Message threshold below which we use simple summarization (no chunking)
SIMPLE_SUMMARY_THRESHOLD = 200  # If <= 200 messages, don't bother chunking

# Rate limiting for batch LLM calls (seconds between requests)
LLM_BATCH_DELAY_SECONDS = 1.0


# =============================================================================
# DATA MODELS
# =============================================================================

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


# =============================================================================
# SECRET SANITIZATION
# =============================================================================

# Regex patterns for detecting secrets (must be redacted)
# IMPORTANT: Order matters! More specific patterns must come before generic ones.
SECRET_PATTERNS = [
    # ==========================================================================
    # EXPLICIT KEY PATTERNS (Specific formats first)
    # ==========================================================================

    # --- LLM Providers ---
    (r'sk-(?:proj-)?[a-zA-Z0-9]{30,}', 'OPENAI-API-KEY'),
    (r'sk-ant-[a-zA-Z0-9\-_]{32,}', 'ANTHROPIC-API-KEY'),
    (r'sk-or-[a-zA-Z0-9]{32,}', 'OPENROUTER-API-KEY'),
    (r'ak-[a-zA-Z0-9]{20,}', 'COMPOSIO-API-KEY'),

    # --- GitHub / Git ---
    (r'ghp_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),
    (r'gho_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),
    (r'ghu_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),
    (r'ghs_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),
    (r'ghr_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),
    (r'gh[pousr]_[A-Za-z0-9]{20,}', 'GITHUB-TOKEN'),
    (r'github_pat_[A-Za-z0-9_]{22,}', 'GITHUB-PAT'),

    # --- AWS ---
    (r'AKIA[A-Z0-9]{16}', 'AWS-ACCESS-KEY'),
    (r'ASIA[A-Z0-9]{16}', 'AWS-SESSION-KEY'),

    # --- Communication / Channels ---
    (r'\d{9,10}:[A-Za-z0-9_-]{35}', 'TELEGRAM-BOT-TOKEN'),
    (r'[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}', 'DISCORD-BOT-TOKEN'),
    (r'xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*', 'SLACK-TOKEN'),

    # --- Productivity / Integrations ---
    (r'secret_[A-Za-z0-9]{32,}', 'NOTION-SECRET'),
    (r'AIza[0-9A-Za-z_-]{35}', 'GOOGLE-API-KEY'),

    # --- Payment ---
    (r'sk_live_[0-9a-zA-Z]{24,}', 'STRIPE-LIVE-KEY'),
    (r'sk_test_[0-9a-zA-Z]{24,}', 'STRIPE-TEST-KEY'),
    (r'pk_live_[0-9a-zA-Z]{24,}', 'STRIPE-PUBLISHABLE-KEY'),
    (r'pk_test_[0-9a-zA-Z]{24,}', 'STRIPE-TEST-PUBLISHABLE-KEY'),

    # --- Search / Data ---
    (r'BSA[0-9a-zA-Z_-]{32,}', 'BRAVE-API-KEY'),
    (r'tvly-[A-Za-z0-9]{32,}', 'TAVILY-API-KEY'),
    (r'serp-[0-9a-z]{32,}', 'SERPAPI-KEY'),

    # NOTE: UUID pattern removed - too aggressive, matches session IDs and message IDs
    # NOTE: HEX-32 pattern removed - matches git commit hashes and MD5 checksums

    # ==========================================================================
    # STRUCTURAL PATTERNS (Format-based detection)
    # ==========================================================================

    (r'eyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}', 'JWT'),
    (r'-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----', 'SSH-PRIVATE-KEY'),
    (r'ssh-(?:rsa|dss|ed25519|ecdsa)\s+[A-Za-z0-9+/]{30,}={0,3}', 'SSH-PUBLIC-KEY'),
    (r'(?:postgresql|mysql|mongodb|redis)://[^:@\s]+:[^@\s]+@[^\s]+', 'CONNECTION-STRING'),
    (r'\w+://[^:]+:[^@]+@\S+', 'CONNECTION-STRING'),
    (r'\b[0-9a-f]{64}\b', 'HEX-TOKEN-64'),
    # HEX-32 removed: (r'\b[0-9a-f]{32}\b', 'HEX-TOKEN-32') - matches git hashes
    (r'\b[A-Za-z0-9+/]{40,}={0,2}\b', 'BASE64'),

    # ==========================================================================
    # GENERIC PATTERNS (Catch-all)
    # ==========================================================================

    (r'(?i)(\w*api\w*[_-]?\w*key\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'API-KEY'),
    (r'(?i)(\w*secret\w*[_-]?\w*key\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'SECRET'),
    (r'(?i)(\w*access\w*[_-]?\w*token\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'ACCESS-TOKEN'),
    (r'(?i)(\w*auth\w*[_-]?\w*token\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'AUTH-TOKEN'),
    (r'(?i)(\w*api\w*[_-]?\w*token\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'API-TOKEN'),
    (r'(?i)(bearer\s+)(?!\[REDACTED)([^\s"\'\n\[]{16,})', 'BEARER-TOKEN'),
    (r'(?i)(\w*token\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'TOKEN'),
    (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\'\n]{8,})["\']?', 'PASSWORD'),
    (r'(?i)(private[_-]?key|privkey)\s*[=:]\s*["\']?([^\s"\'\n]{20,})["\']?', 'PRIVATE-KEY'),
    (r'\$[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)[A-Z_]*\b', 'ENV-VAR'),
    (r'\$\{[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)[A-Z_]*\}', 'ENV-VAR'),
]


SENSITIVE_ENV_VAR_NAMES = [
    'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY',
    'COMPOSIO_API_KEY', 'COMPOSIO_ENTITY_ID',
    'COMPOSIO_CALENDAR_ACCOUNT', 'COMPOSIO_GMAIL_ACCOUNT',
    'MOONSHOT_API_KEY', 'KIMI_API_KEY',
    'GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_PAT',
    'TELEGRAM_BOT_TOKEN', 'DISCORD_BOT_TOKEN', 'DISCORD_TOKEN',
    'SLACK_BOT_TOKEN', 'SLACK_TOKEN',
    'NOTION_API_KEY', 'NOTION_TOKEN', 'NOTION_SECRET',
    'TRELLO_API_KEY', 'TRELLO_TOKEN',
    'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS',
    'STRIPE_API_KEY', 'STRIPE_SECRET_KEY', 'STRIPE_PUBLISHABLE_KEY',
    'BRAVE_API_KEY', 'TAVILY_API_KEY', 'SERPAPI_KEY',
    'PINECONE_API_KEY', 'SUPABASE_KEY', 'SUPABASE_ANON_KEY',
    'SUPABASE_SERVICE_KEY', 'QDRANT_API_KEY',
    'ELEVENLABS_API_KEY', 'ELEVENLABS_KEY',
    'OURA_PAT', 'OURA_PERSONAL_ACCESS_TOKEN',
    'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
]


class ContentSensitivity(Enum):
    """Content sensitivity level for classification."""
    SAFE = "safe"
    SENSITIVE = "sensitive"
    SECRET = "secret"


def classify_content(content: str) -> ContentSensitivity:
    """Classify content sensitivity level based on pattern matching."""
    definite_secret_patterns = [
        r'sk-(?:proj-|ant-)?[a-zA-Z0-9\-_]{30,}',
        r'AKIA[A-Z0-9]{16}',
        r'-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----',
        r'eyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}',
        r'gh[pousr]_[A-Za-z0-9]{20,}',
    ]

    for pattern in definite_secret_patterns:
        if re.search(pattern, content):
            return ContentSensitivity.SECRET

    sensitive_patterns = [
        r'\$[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD)',
        r'(?i)\bapi[_-]?key\b',
        r'(?i)\bpassword\b',
        r'(?i)\btoken\b',
        r'(?i)\bsecret\b',
    ]

    sensitive_count = sum(
        1 for pattern in sensitive_patterns
        if re.search(pattern, content, re.IGNORECASE)
    )

    if sensitive_count > 0:
        return ContentSensitivity.SENSITIVE

    return ContentSensitivity.SAFE


def _make_context_replacer(pattern: str, redaction_type: str):
    """Factory function to create a replacement function with proper closure capture.

    This avoids the closure variable capture bug where loop variables are
    captured by reference rather than value.
    """
    def replace_with_context(match):
        if len(match.groups()) >= 2:
            key_part = match.group(1)
            return f"{key_part}=[REDACTED-{redaction_type}]"
        elif 'bearer' in pattern.lower():
            return f"{match.group(1)}[REDACTED-{redaction_type}]"
        else:
            return f"[REDACTED-{redaction_type}]"
    return replace_with_context


def sanitize_content(content: str) -> str:
    """Remove all potentially sensitive content before processing.

    Replaces detected secrets with [REDACTED-TYPE] placeholders.
    This function is idempotent.
    """
    sanitized = content

    for pattern, redaction_type in SECRET_PATTERNS:
        if '(' in pattern and ')' in pattern:
            if any(kw in pattern for kw in ['api', 'secret', 'password', 'token', 'bearer']):
                replacer = _make_context_replacer(pattern, redaction_type)
                sanitized = re.sub(pattern, replacer, sanitized)
            else:
                sanitized = re.sub(pattern, f"[REDACTED-{redaction_type}]", sanitized)
        else:
            sanitized = re.sub(pattern, f"[REDACTED-{redaction_type}]", sanitized)

    return sanitized


def validate_no_secrets(content: str) -> Tuple[bool, List[str]]:
    """Validate that content contains no unredacted secrets.

    Returns:
        Tuple of (is_valid, list_of_violations)
    """
    violations = []

    if re.search(r'sk-(?:proj-)?[a-zA-Z0-9]{30,}', content):
        violations.append("Found potential OpenAI API key (sk-...)")

    if re.search(r'sk-ant-[a-zA-Z0-9\-_]{32,}', content):
        violations.append("Found potential Anthropic API key (sk-ant-...)")

    if re.search(r'ak-[a-zA-Z0-9]{20,}', content):
        violations.append("Found potential Composio API key (ak-...)")

    if re.search(r'gh[pousr]_[A-Za-z0-9]{20,}', content):
        violations.append("Found potential GitHub token (gh*_...)")

    if re.search(r'AKIA[A-Z0-9]{16}', content):
        violations.append("Found potential AWS access key (AKIA...)")

    if re.search(r'ASIA[A-Z0-9]{16}', content):
        violations.append("Found potential AWS session key (ASIA...)")

    base64_matches = re.findall(r'\b[A-Za-z0-9+/]{40,}={0,2}\b', content)
    for match in base64_matches:
        if 'REDACTED' not in match:
            violations.append(f"Found unredacted high-entropy base64 string")
            break

    password_pattern = r'(?i)password\s*[=:]\s*["\']?([^\s"\'\[]+)'
    for match in re.finditer(password_pattern, content):
        value = match.group(1)
        if not value.startswith('[REDACTED'):
            violations.append("Found unredacted password assignment")
            break

    if re.search(r'eyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}', content):
        violations.append("Found potential JWT token")

    if re.search(r'-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----', content):
        violations.append("Found SSH private key header")

    if re.search(r'\w+://[^:@\s]+:[^@\s]+@', content):
        conn_matches = re.findall(r'\w+://[^:@\s]+:[^@\s]+@\S+', content)
        for match in conn_matches:
            if 'REDACTED' not in match:
                violations.append("Found connection string with embedded credentials")
                break

    return (len(violations) == 0, violations)


def safe_sanitize(content: str) -> str:
    """Sanitize content and ensure it's valid (no secrets remain).

    STRICT: if any secret patterns still match after sanitization, abort.
    This prevents accidental writes/sends of sensitive material.
    """
    sanitized = sanitize_content(content)
    is_valid, violations = validate_no_secrets(sanitized)

    if not is_valid:
        raise ValueError(
            f"Secrets still detected after sanitization: {violations}. "
            "Refusing to proceed."
        )

    return sanitized


# =============================================================================
# PARSER
# =============================================================================

def parse_jsonl(path: Path) -> Iterator[dict]:
    """Stream parse a JSONL file, yielding records."""
    with open(path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"Warning: Skipping malformed JSON at {path}:{line_num} ({type(e).__name__})", file=sys.stderr)


def get_session_metadata(path: Path) -> Optional[dict]:
    """Extract session record (first line with type: "session")."""
    for record in parse_jsonl(path):
        if record.get('type') == 'session':
            return record
    return None


def _parse_timestamp(record: dict) -> Optional[datetime]:
    """Parse timestamp from a record.

    FIXED: Converts UTC to local timezone using .astimezone()
    """
    # Try outer timestamp first (ISO 8601)
    if 'timestamp' in record:
        ts = record['timestamp']
        if isinstance(ts, str):
            try:
                ts_str = ts.replace('Z', '+00:00')
                return datetime.fromisoformat(ts_str)
            except ValueError:
                pass
        elif isinstance(ts, (int, float)):
            # FIXED: Convert to local timezone
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone()

    # Try nested message timestamp (Unix ms)
    if 'message' in record and 'timestamp' in record['message']:
        ts = record['message']['timestamp']
        if isinstance(ts, (int, float)):
            # FIXED: Convert to local timezone
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone()

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
    """Extract message records from a session log."""
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
            if _local_date(timestamp) != date_filter:
                continue

        role = msg.get('role')
        if role not in ('user', 'assistant', 'toolResult'):
            continue

        content = msg.get('content', [])
        if not isinstance(content, list):
            content = []

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
    """Extract model transitions from a session log."""
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

        # Track model from messages too
        elif record_type == 'message':
            msg = record.get('message', {})
            model = msg.get('model')
            provider = msg.get('provider')

            if model and model != current_model:
                timestamp = _parse_timestamp(record)
                if timestamp:
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
    """Extract compaction summaries from a session log."""
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
    """Extract model-snapshot custom records for transition tracking."""
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


# =============================================================================
# SESSION DISCOVERY
# =============================================================================

def find_session_files(sessions_dir: Path) -> list[Path]:
    """Find all session JSONL files in a directory."""
    if not sessions_dir.exists():
        return []

    files = []
    # Match *.jsonl and also *.jsonl.reset.* and *.jsonl.deleted.* (moved-aside sessions)
    for pattern in ['*.jsonl', '*.jsonl.reset.*', '*.jsonl.deleted.*']:
        for f in sessions_dir.glob(pattern):
            if f.suffix == '.lock' or f.name.endswith('.jsonl.lock'):
                continue
            if f not in files:  # Avoid duplicates
                files.append(f)

    files.sort(key=lambda p: p.stat().st_mtime)
    return files


def _local_date(dt: datetime) -> date:
    """Convert a datetime to the local (America/Los_Angeles) date for bucketing."""
    try:
        if dt.tzinfo is not None:
            return dt.astimezone(LOCAL_TZ).date()
    except Exception:
        pass
    return dt.date()


def get_date_range(sessions_dir: Path) -> tuple[Optional[date], Optional[date]]:
    """Get the date range of activity across all session files (bucketed by LOCAL_TZ)."""
    first_date: Optional[date] = None
    last_date: Optional[date] = None

    for session_file in find_session_files(sessions_dir):
        for msg in get_messages(session_file):
            msg_date = _local_date(msg.timestamp)

            if first_date is None or msg_date < first_date:
                first_date = msg_date
            if last_date is None or msg_date > last_date:
                last_date = msg_date

    return first_date, last_date


def collect_daily_activity(sessions_dir: Path) -> dict[date, DayActivity]:
    """Collect activity summary for each day across all sessions."""
    daily_data: dict[date, dict] = defaultdict(lambda: {
        'message_count': 0,
        'user_messages': 0,
        'assistant_messages': 0,
        'tool_result_messages': 0,
        'models': set(),
        'transitions': [],
        'session_ids': set(),
    })

    session_files = find_session_files(sessions_dir)

    for session_file in session_files:
        session_meta = get_session_metadata(session_file)
        session_id = session_meta.get('id', session_file.stem) if session_meta else session_file.stem

        for msg in get_messages(session_file):
            msg_date = _local_date(msg.timestamp)
            data = daily_data[msg_date]

            data['message_count'] += 1
            data['session_ids'].add(session_id)

            if msg.role == 'user':
                data['user_messages'] += 1
            elif msg.role == 'assistant':
                data['assistant_messages'] += 1
                if msg.model:
                    data['models'].add(msg.model)
            elif msg.role == 'toolResult':
                data['tool_result_messages'] += 1

        for transition in get_model_transitions(session_file):
            trans_date = _local_date(transition.timestamp)
            daily_data[trans_date]['transitions'].append(transition)

    result: dict[date, DayActivity] = {}
    for day, data in daily_data.items():
        result[day] = DayActivity(
            date=day,
            message_count=data['message_count'],
            user_messages=data['user_messages'],
            assistant_messages=data['assistant_messages'],
            tool_result_messages=data['tool_result_messages'],
            models_used=sorted(data['models']),
            transitions=data['transitions'],
            session_ids=sorted(data['session_ids']),
        )

    return result


def get_session_info(session_file: Path) -> dict:
    """Get summary information about a single session file."""
    session_meta = get_session_metadata(session_file)
    session_id = session_meta.get('id', session_file.stem) if session_meta else session_file.stem

    file_size = session_file.stat().st_size

    message_count = 0
    user_count = 0
    assistant_count = 0
    tool_result_count = 0
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    models: set[str] = set()

    for msg in get_messages(session_file):
        message_count += 1
        msg_date = _local_date(msg.timestamp)

        if first_date is None or msg_date < first_date:
            first_date = msg_date
        if last_date is None or msg_date > last_date:
            last_date = msg_date

        if msg.role == 'user':
            user_count += 1
        elif msg.role == 'assistant':
            assistant_count += 1
            if msg.model:
                models.add(msg.model)
        elif msg.role == 'toolResult':
            tool_result_count += 1

    transitions = list(get_model_transitions(session_file))

    return {
        'session_id': session_id,
        'file_path': str(session_file),
        'file_size': file_size,
        'message_count': message_count,
        'user_messages': user_count,
        'assistant_messages': assistant_count,
        'tool_result_messages': tool_result_count,
        'models_used': sorted(models),
        'transition_count': len(transitions),
        'date_range': (first_date, last_date),
        'metadata': session_meta,
    }


# =============================================================================
# STATE TRACKING (for incremental backfill)
# =============================================================================

def get_state_file_path() -> Path:
    """Get the path to the state file."""
    state_dir = Path.home() / '.memory-sync'
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / 'state.json'


def load_state() -> dict:
    """Load state from the state file."""
    state_file = get_state_file_path()

    if not state_file.exists():
        return {}

    try:
        with state_file.open('r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_state(
    last_run: Optional[datetime] = None,
    last_successful_date: Optional[date] = None,
    total_days_processed: Optional[int] = None
) -> None:
    """Save state to the state file."""
    state_file = get_state_file_path()

    state = load_state()

    if last_run is not None:
        state['last_run'] = last_run.isoformat()
    elif 'last_run' not in state:
        state['last_run'] = datetime.now().isoformat()

    if last_successful_date is not None:
        state['last_successful_date'] = last_successful_date.isoformat()

    if total_days_processed is not None:
        state['total_days_processed'] = total_days_processed
    elif 'total_days_processed' not in state:
        state['total_days_processed'] = 0

    with state_file.open('w') as f:
        json.dump(state, f, indent=2)


def get_changed_days(sessions_dir: Path, since: datetime) -> set[date]:
    """Get set of dates with session activity since a given timestamp."""
    changed_days: set[date] = set()
    since_timestamp = since.timestamp()

    for session_file in find_session_files(sessions_dir):
        file_mtime = session_file.stat().st_mtime

        if file_mtime > since_timestamp:
            for msg in get_messages(session_file):
                changed_days.add(_local_date(msg.timestamp))

    return changed_days


def get_last_run_datetime() -> Optional[datetime]:
    """Get the last run timestamp from state."""
    state = load_state()
    last_run_str = state.get('last_run')

    if not last_run_str:
        return None

    try:
        return datetime.fromisoformat(last_run_str)
    except (ValueError, TypeError):
        return None


# =============================================================================
# COMPARE (gap detection)
# =============================================================================

def find_gaps(sessions_dir: Path, memory_dir: Path, *, exclude_today: bool = True) -> dict:
    """Compare session logs against memory files to identify coverage gaps.

    By default, excludes *today* from coverage/sparsity checks because the day is usually still in progress
    (especially when this is run early morning by cron).
    """
    first_date, last_date = get_date_range(sessions_dir)

    if first_date is None or last_date is None:
        return {
            'missing_days': [],
            'sparse_days': [],
            'coverage_pct': 100.0,
            'total_active_days': 0,
            'first_date': None,
            'last_date': None,
        }

    daily_activity = collect_daily_activity(sessions_dir)

    missing_gaps: list[MemoryGap] = []
    sparse_gaps: list[MemoryGap] = []
    covered_days = 0

    today_local = datetime.now(tz=LOCAL_TZ).date()

    for day, activity in sorted(daily_activity.items()):
        if activity.message_count == 0:
            continue

        # Skip "today" unless explicitly included; partial-day logs make the sparse heuristic noisy.
        if exclude_today and day == today_local:
            continue

        memory_file = memory_dir / f"{day}.md"

        if not memory_file.exists():
            missing_gaps.append(MemoryGap(
                date=day,
                gap_type='missing',
                activity=activity,
                memory_file_size=0,
                reason=f"No memory file for {activity.message_count} messages"
            ))
        else:
            file_size = memory_file.stat().st_size
            bytes_per_msg = file_size / activity.message_count if activity.message_count > 0 else 0

            if file_size < MIN_FILE_SIZE_BYTES or bytes_per_msg < MIN_BYTES_PER_MESSAGE:
                sparse_gaps.append(MemoryGap(
                    date=day,
                    gap_type='sparse',
                    activity=activity,
                    memory_file_size=file_size,
                    reason=f"Only {file_size} bytes for {activity.message_count} messages ({bytes_per_msg:.1f} bytes/msg)"
                ))
            else:
                covered_days += 1

    total_active_days = len(daily_activity)
    coverage_pct = (covered_days / total_active_days * 100) if total_active_days > 0 else 100.0

    return {
        'missing_days': missing_gaps,
        'sparse_days': sparse_gaps,
        'coverage_pct': coverage_pct,
        'total_active_days': total_active_days,
        'covered_days': covered_days,
        'first_date': first_date,
        'last_date': last_date,
    }


def get_memory_files(memory_dir: Path) -> list[tuple[date, Path]]:
    """Get all memory files in the memory directory."""
    if not memory_dir.exists():
        return []

    files = []
    for f in memory_dir.glob('*.md'):
        try:
            file_date = date.fromisoformat(f.stem)
            files.append((file_date, f))
        except ValueError:
            continue

    return sorted(files, key=lambda x: x[0])


def find_orphaned_memory_files(sessions_dir: Path, memory_dir: Path) -> list[tuple[date, Path]]:
    """Find memory files that have no corresponding session activity."""
    daily_activity = collect_daily_activity(sessions_dir)
    memory_files = get_memory_files(memory_dir)

    orphaned = []
    for file_date, file_path in memory_files:
        if file_date not in daily_activity or daily_activity[file_date].message_count == 0:
            orphaned.append((file_date, file_path))

    return orphaned


def format_gap_report(gaps: dict) -> str:
    """Format gap detection results as a human-readable report."""
    lines = []

    lines.append("Memory Coverage Report")
    lines.append("=" * 50)
    lines.append("")

    if gaps['first_date'] and gaps['last_date']:
        lines.append(f"Date range: {gaps['first_date']} to {gaps['last_date']}")
    lines.append(f"Active days: {gaps['total_active_days']}")
    lines.append(f"Covered days: {gaps.get('covered_days', 0)}")
    lines.append(f"Coverage: {gaps['coverage_pct']:.1f}%")
    lines.append("")

    missing = gaps['missing_days']
    sparse = gaps['sparse_days']

    if missing:
        lines.append(f"Missing Memory Files ({len(missing)} days)")
        lines.append("-" * 40)
        for gap in missing:
            models_str = ', '.join(gap.activity.models_used) if gap.activity.models_used else 'unknown'
            lines.append(f"  {gap.date}: {gap.activity.message_count} msgs ({models_str})")
        lines.append("")

    if sparse:
        lines.append(f"Sparse Memory Files ({len(sparse)} days)")
        lines.append("-" * 40)
        for gap in sparse:
            lines.append(f"  {gap.date}: {gap.reason}")
        lines.append("")

    if not missing and not sparse:
        lines.append("All days have adequate memory coverage!")

    return '\n'.join(lines)


# =============================================================================
# TRANSITIONS
# =============================================================================

def extract_transitions(
    sessions_dir: Path,
    since: Optional[date] = None
) -> Iterator[ModelTransition]:
    """Extract all model transitions from session logs."""
    all_transitions: list[ModelTransition] = []

    for session_file in find_session_files(sessions_dir):
        for transition in get_model_transitions(session_file):
            if since is not None and _local_date(transition.timestamp) < since:
                continue
            all_transitions.append(transition)

    all_transitions.sort(key=lambda t: t.timestamp)

    yield from all_transitions


def write_transitions_json(transitions: list[ModelTransition], output_path: Path):
    """Write transitions to JSON file for tracking."""
    data = {
        'generated_at': datetime.now().isoformat(),
        'count': len(transitions),
        'transitions': [
            {
                'timestamp': t.timestamp.isoformat(),
                'from_model': t.from_model,
                'to_model': t.to_model,
                'from_provider': t.from_provider,
                'provider': t.provider,
                'session_id': t.session_id,
            }
            for t in transitions
        ]
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2))


def format_transition(transition: ModelTransition) -> str:
    """Format a single transition for display."""
    time_str = transition.timestamp.strftime('%Y-%m-%d %H:%M:%S')

    if transition.from_model:
        from_str = f"{transition.from_provider}/{transition.from_model}" if transition.from_provider else transition.from_model
    else:
        from_str = "(start)"

    to_str = f"{transition.provider}/{transition.to_model}" if transition.provider else transition.to_model

    return f"{time_str}: {from_str} -> {to_str}"


def format_transitions_report(
    transitions: list[ModelTransition],
    since: Optional[date] = None
) -> str:
    """Format transitions as a human-readable report."""
    lines = []

    lines.append("Model Transitions Report")
    lines.append("=" * 50)

    if since:
        lines.append(f"Since: {since}")

    lines.append(f"Total transitions: {len(transitions)}")
    lines.append("")

    if not transitions:
        lines.append("No model transitions found.")
        return '\n'.join(lines)

    by_date: dict[date, list[ModelTransition]] = {}
    for t in transitions:
        d = _local_date(t.timestamp)
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(t)

    for d in sorted(by_date.keys()):
        lines.append(f"{d} ({d.strftime('%A')})")
        lines.append("-" * 30)
        for t in by_date[d]:
            time_str = t.timestamp.strftime('%H:%M:%S')
            from_str = t.from_model or "(start)"
            to_str = f"{t.provider}/{t.to_model}" if t.provider else t.to_model
            lines.append(f"  {time_str}: {from_str} -> {to_str}")
        lines.append("")

    return '\n'.join(lines)


def get_transition_stats(transitions: list[ModelTransition]) -> dict:
    """Calculate statistics about model transitions."""
    if not transitions:
        return {
            'total_transitions': 0,
            'models_used': [],
            'providers_used': [],
            'transitions_by_model': {},
            'transitions_by_provider': {},
            'most_common_model': None,
            'date_range': (None, None),
        }

    models: set[str] = set()
    providers: set[str] = set()
    model_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}

    first_date: Optional[date] = None
    last_date: Optional[date] = None

    for t in transitions:
        if t.to_model:
            models.add(t.to_model)
            model_counts[t.to_model] = model_counts.get(t.to_model, 0) + 1

        if t.provider:
            providers.add(t.provider)
            provider_counts[t.provider] = provider_counts.get(t.provider, 0) + 1

        trans_date = _local_date(t.timestamp)
        if first_date is None or trans_date < first_date:
            first_date = trans_date
        if last_date is None or trans_date > last_date:
            last_date = trans_date

    most_common = max(model_counts.items(), key=lambda x: x[1])[0] if model_counts else None

    return {
        'total_transitions': len(transitions),
        'models_used': sorted(models),
        'providers_used': sorted(providers),
        'transitions_by_model': model_counts,
        'transitions_by_provider': provider_counts,
        'most_common_model': most_common,
        'date_range': (first_date, last_date),
    }


# =============================================================================
# BACKFILL (simple extraction)
# =============================================================================

def extract_preserved_content(existing_content: str) -> Tuple[str, str]:
    """Extract hand-written content from an existing memory file."""
    if not existing_content:
        return "", ""

    footer_pos = existing_content.find(AUTO_GENERATED_FOOTER)

    if footer_pos == -1:
        return "", existing_content

    after_footer = existing_content[footer_pos + len(AUTO_GENERATED_FOOTER):]
    hand_written = after_footer.lstrip('\n')
    auto_generated = existing_content[:footer_pos + len(AUTO_GENERATED_FOOTER)]

    return auto_generated, hand_written


def extract_topics(messages: list[Message], max_topics: int = 10) -> list[str]:
    """Extract main topics from messages using simple keyword analysis."""
    stopwords = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
        'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as',
        'into', 'through', 'during', 'before', 'after', 'above', 'below',
        'between', 'under', 'again', 'further', 'then', 'once', 'here',
        'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few',
        'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
        'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just',
        'and', 'but', 'if', 'or', 'because', 'until', 'while', 'this',
        'that', 'these', 'those', 'what', 'which', 'who', 'whom', 'it',
        'its', 'you', 'your', 'i', 'me', 'my', 'we', 'our', 'they', 'them',
        'their', 'he', 'she', 'him', 'her', 'his', 'let', 'file', 'files',
        'please', 'thanks', 'thank', 'yes', 'no', 'okay', 'ok', 'sure',
    }

    word_counts: dict[str, int] = {}
    for msg in messages:
        if msg.role != 'user':
            continue

        words = re.findall(r'\b[a-zA-Z]{4,}\b', msg.text_content.lower())
        for word in words:
            if word not in stopwords:
                word_counts[word] = word_counts.get(word, 0) + 1

    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    topics = [word.capitalize() for word, count in sorted_words[:max_topics] if count >= 2]

    return topics


def extract_key_exchanges(messages: list[Message], max_exchanges: int = 10) -> list[dict]:
    """Extract key user questions and responses."""
    exchanges = []

    question_patterns = [
        r'\?$',
        r'^(can|could|would|will|how|what|why|when|where|who|is|are|do|does)\b',
        r'^(help|explain|show|tell|create|make|fix|implement|add|remove|update)\b',
    ]

    for i, msg in enumerate(messages):
        if msg.role != 'user':
            continue

        text = msg.text_content.strip()
        if not text:
            continue

        is_question = any(re.search(p, text, re.IGNORECASE) for p in question_patterns)
        if not is_question and len(text) < 20:
            continue

        response_text = ""
        for j in range(i + 1, min(i + 5, len(messages))):
            if messages[j].role == 'assistant':
                response_text = messages[j].text_content.strip()
                break

        user_excerpt = text[:100] + ('...' if len(text) > 100 else '')
        user_excerpt = sanitize_content(user_excerpt)

        response_excerpt = response_text[:100] + ('...' if len(response_text) > 100 else '') if response_text else ""
        response_excerpt = sanitize_content(response_excerpt)

        exchanges.append({
            'time': msg.timestamp.strftime('%H:%M'),
            'user_excerpt': user_excerpt,
            'response_excerpt': response_excerpt,
        })

        if len(exchanges) >= max_exchanges:
            break

    return exchanges


def extract_decisions(messages: list[Message], max_decisions: int = 10) -> list[str]:
    """Extract decisions and action items from assistant messages."""
    decision_patterns = [
        r"I(?:'ll| will) ([^.!?]+[.!?])",
        r"Let(?:'s| us) ([^.!?]+[.!?])",
        r"I(?:'m going to| am going to) ([^.!?]+[.!?])",
        r"We should ([^.!?]+[.!?])",
        r"The (?:solution|fix|answer) is ([^.!?]+[.!?])",
    ]

    decisions = []

    for msg in messages:
        if msg.role != 'assistant':
            continue

        text = msg.text_content

        for pattern in decision_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                decision = match.strip()
                if len(decision) > 10 and len(decision) < 200:
                    decision = sanitize_content(decision)
                    decisions.append(decision)

        if msg.has_tool_calls:
            decisions.append("Executed tool/command")

        if len(decisions) >= max_decisions:
            break

    seen = set()
    unique_decisions = []
    for d in decisions:
        d_lower = d.lower()
        if d_lower not in seen:
            seen.add(d_lower)
            unique_decisions.append(d)

    return unique_decisions[:max_decisions]


def format_transitions_for_template(transitions: list[ModelTransition]) -> list[dict]:
    """Format transitions for template rendering."""
    result = []
    for t in transitions:
        from_str = f"{t.from_provider}/{t.from_model}" if t.from_provider and t.from_model else (t.from_model or "start")
        to_str = f"{t.provider}/{t.to_model}" if t.provider else t.to_model

        result.append({
            'time': t.timestamp.strftime('%H:%M'),
            'from': from_str,
            'to': to_str,
        })

    return result


def render_daily_template(context: dict) -> str:
    """Render daily memory file content from context dict."""
    lines = []

    lines.append(f"# {context['date']} ({context['day_name']})")
    lines.append("")
    lines.append(f"*Auto-generated from {context['message_count']} session messages*")
    lines.append("")

    if context.get('compaction_summary'):
        lines.append("## Context Summary")
        sanitized_summary = sanitize_content(context['compaction_summary'])
        lines.append(sanitized_summary)
        lines.append("")

    if context.get('topics'):
        lines.append("## Topics Covered")
        for topic in context['topics']:
            lines.append(f"- {topic}")
        lines.append("")

    if context.get('key_exchanges'):
        lines.append("## Key Exchanges")
        for exchange in context['key_exchanges']:
            lines.append(f"- [{exchange['time']}] {exchange['user_excerpt']}")
        lines.append("")

    if context.get('decisions'):
        lines.append("## Decisions/Actions")
        for decision in context['decisions']:
            lines.append(f"- {decision}")
        lines.append("")

    if context.get('transitions'):
        lines.append("## Model Transitions")
        for trans in context['transitions']:
            lines.append(f"- {trans['time']}: {trans['from']} -> {trans['to']}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Review and edit this draft to capture what's actually important.*")

    return '\n'.join(lines)


def generate_daily_memory(
    log_date: date,
    sessions_dir: Path,
    output_path: Path,
    force: bool = False,
    preserve: bool = False
) -> str:
    """Generate a daily memory file from session logs."""
    existing_content = ""
    if output_path.exists():
        if not force and not preserve:
            raise FileExistsError(f"File already exists: {output_path}. Use --force to overwrite.")
        if preserve:
            existing_content = output_path.read_text()

    messages: list[Message] = []
    transitions: list[ModelTransition] = []
    compaction_summary: Optional[str] = None

    for session_file in find_session_files(sessions_dir):
        for msg in get_messages(session_file, date_filter=log_date):
            messages.append(msg)

        for trans in get_model_transitions(session_file):
            if _local_date(trans.timestamp) == log_date:
                transitions.append(trans)

        for comp in get_compactions(session_file):
            if comp['timestamp'] and _local_date(comp['timestamp']) == log_date:
                if comp.get('summary'):
                    compaction_summary = comp['summary']

    if not messages:
        raise ValueError(f"No messages found for {log_date}")

    messages.sort(key=lambda m: m.timestamp)
    transitions.sort(key=lambda t: t.timestamp)

    topics = extract_topics(messages)
    key_exchanges = extract_key_exchanges(messages)
    decisions = extract_decisions(messages)

    content = render_daily_template({
        'date': log_date.strftime('%Y-%m-%d'),
        'day_name': log_date.strftime('%A'),
        'message_count': len(messages),
        'topics': topics,
        'key_exchanges': key_exchanges,
        'decisions': decisions,
        'transitions': format_transitions_for_template(transitions),
        'compaction_summary': compaction_summary,
    })

    if preserve and existing_content:
        _, hand_written = extract_preserved_content(existing_content)
        if hand_written:
            hand_written = sanitize_content(hand_written)
            content = content + "\n\n" + hand_written

    is_valid, violations = validate_no_secrets(content)

    if not is_valid:
        print(f"Warning: Generated content contains potential secrets: {violations}", file=sys.stderr)
        print("Attempting to sanitize...", file=sys.stderr)

        content = sanitize_content(content)

        is_valid, violations = validate_no_secrets(content)

        if not is_valid:
            # Write to .rejected file for manual review
            rejected_path = output_path.with_suffix('.md.rejected')
            rejected_path.parent.mkdir(parents=True, exist_ok=True)
            rejected_path.write_text(content)
            print(f"Draft saved to: {rejected_path}", file=sys.stderr)
            print("⚠️  MANUAL REVIEW REQUIRED: Edit the .rejected file to remove secrets, then rename to .md", file=sys.stderr)
            raise ValueError(
                f"Memory file contains secrets after sanitization: {violations}. "
                f"Draft saved to {rejected_path} for manual editing."
            )

        print("Content sanitized successfully.", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)

    return str(output_path)


def backfill_all_missing(
    sessions_dir: Path,
    memory_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    preserve: bool = False
) -> dict:
    """Backfill all missing daily memory files."""
    gaps = find_gaps(sessions_dir, memory_dir)

    created = []
    skipped = []
    errors = []

    for gap in gaps['missing_days']:
        output_path = memory_dir / f"{gap.date}.md"

        if dry_run:
            created.append(str(output_path))
            continue

        try:
            path = generate_daily_memory(gap.date, sessions_dir, output_path, force=force, preserve=preserve)
            created.append(path)
        except FileExistsError:
            skipped.append(gap.date)
        except Exception as e:
            errors.append((gap.date, str(e)))

    if force:
        for gap in gaps['sparse_days']:
            output_path = memory_dir / f"{gap.date}.md"

            if dry_run:
                created.append(str(output_path))
                continue

            try:
                path = generate_daily_memory(gap.date, sessions_dir, output_path, force=True, preserve=preserve)
                created.append(path)
            except Exception as e:
                errors.append((gap.date, str(e)))

    return {
        'created': created,
        'skipped': skipped,
        'errors': errors,
        'dry_run': dry_run,
    }


# =============================================================================
# SUMMARIZE (LLM-based)
# =============================================================================

# LLM system prompt for memory generation
MEMORY_SYSTEM_PROMPT = """You are a memory synthesizer for an AI assistant. Your task is to generate *high-signal, detailed* daily memory summaries from conversation logs.

## CRITICAL PRIORITY ORDER (follow strictly)

**HIGHEST PRIORITY - Always include first:**
1. USER CONVERSATIONS: Questions, requests, discussions, decisions, and strategic topics the human raised
2. USER INSIGHTS: Philosophical discussions, personal reflections, creative work, writing projects
3. USER DECISIONS: Explicit choices made by the user about strategy, direction, priorities

**MEDIUM PRIORITY:**
4. Significant technical accomplishments (new features, bug fixes, integrations)
5. System failures and their resolutions
6. Important discoveries or learnings

**LOWEST PRIORITY (include only if space allows):**
7. Routine cron job execution (unless failures)
8. Standard health checks (unless failures)
9. Automated maintenance tasks

## Key Principles
- USER CONVERSATIONS ARE THE MOST IMPORTANT CONTENT. Never skip them for technical work.
- When there are 500+ messages with heavy automated/cron activity, explicitly scan for USER role messages first
- Capture the *substance* of user discussions, not just that they happened
- Focus on WHAT was discussed and any conclusions/decisions reached
- Include enough detail that a future session can continue the conversation
- Write in past tense. Be clear and structured.

## Length Guidance
- Default target: ~800–1500 words when there were substantial conversations/tool calls
- If the day was light, shorter is fine — but don't force brevity
- If there were rich user discussions, err on the side of more detail

## Structure
1) Overview (2–5 sentences, mention key USER topics first)
2) User discussions & decisions (REQUIRED section if any user conversations occurred)
3) Key accomplishments / technical changes (bulleted; include *why* it mattered)
4) Notable findings / insights / patterns  
5) Operational notes (auth issues, cron/tooling failures, environment changes)
6) Open loops / next actions (bulleted, actionable)

## Do NOT Include
- Long verbatim logs (short quotes only if they capture a key decision)
- Secrets, credentials, tokens, raw personal data (PII)
- Extensive cron job details unless they failed

Your output should read like a pragmatic journal entry that prioritizes what the HUMAN cared about that day."""


# Concise prompt for individual time-block chunks (used in chunked summarization)
# These get synthesized later, so they should be BRIEF bullet points, not full narratives
CHUNK_SYSTEM_PROMPT = """You are summarizing a SHORT TIME BLOCK (typically 30-90 minutes) from an AI assistant's session logs.

## YOUR GOAL: Extract ONLY the essential facts in 100-300 words MAX.

## FORMAT (use this exact structure):
**User:** [1-2 sentences max - what the user asked/discussed, or "No user messages"]
**Work:** [Bullet points - what was accomplished, max 3-5 bullets]
**Outcome:** [1 sentence - result/status]

## RULES:
- NO headers, NO sections, NO elaborate structure
- NO code blocks or command examples (just mention "updated X" or "ran Y")
- NO step-by-step procedures (summarize as "configured X" or "fixed Y")
- NO philosophical commentary or pattern analysis
- If pure automation with no user messages, say so and keep to 50 words max
- BREVITY IS CRITICAL - these chunks get combined later

## EXAMPLE OUTPUT:
**User:** Asked about calendar OAuth failures, frustrated this is recurring
**Work:**
- Investigated gog token storage (~/.config/gogcli/keyring/)
- Found keyring empty after reboot
- Tested re-authentication via SSH X11 forwarding
**Outcome:** OAuth working again, but root cause (token persistence) still unclear

## WHAT TO SKIP:
- Routine heartbeats/health checks (unless failures)
- Tool output details (just note "fetched X" or "searched Y")
- Cron job execution logs (unless errors)
- Full error messages (just note "X failed with Y error")"""


def strip_telegram_envelope(text: str) -> str:
    """Strip Telegram/channel metadata envelope to extract actual user message.
    
    Messages from Telegram arrive wrapped in metadata like:
    
        Conversation info (untrusted metadata):
        ```json
        { "message_id": "123", ... }
        ```
        
        Sender (untrusted metadata):
        ```json
        { ... }
        ```
        
        Actual message here
    
    This function extracts just the actual message content.
    """
    import re
    
    # Pattern to match the envelope blocks
    # Look for the end of the last ``` block after "Sender" info
    patterns = [
        # Match full envelope: Conversation info + Sender info + content
        r'^Conversation info \(untrusted metadata\):.*?```\s*\n\nSender \(untrusted metadata\):.*?```\s*\n\n(.*)$',
        # Simpler: just find content after last ``` block  
        r'```\s*\n\n([^`].*)$',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            content = match.group(1).strip()
            if content and len(content) > 10:  # Sanity check
                return content
    
    # If no envelope found, return original (might be direct message)
    return text


def prepare_conversation_text_full(messages: list[Message]) -> tuple[str, str]:
    """Prepare FULL conversation text without truncation.
    
    Returns (user_section, assistant_section) as separate strings.
    NO TRUNCATION - caller handles chunking if needed.
    
    Separates USER messages into a priority section to ensure they're not lost
    when there's heavy automated/assistant activity.
    """
    # Separate user messages from others
    user_lines = []
    other_lines = []
    
    for msg in messages:
        raw_content = msg.text_content
        
        # For user messages, strip Telegram envelope to get actual content
        if msg.role == 'user':
            raw_content = strip_telegram_envelope(raw_content)
        
        sanitized_content = sanitize_content(raw_content)
        time_str = msg.timestamp.strftime('%H:%M')
        role = msg.role.upper()
        model_str = f" [{msg.model}]" if msg.model else ""
        
        # Skip cron job triggers and system messages for the main log
        is_cron = sanitized_content.startswith('[cron:') or 'A scheduled reminder has been triggered' in sanitized_content
        
        # FULL content - no truncation
        line = f"[{time_str}] {role}{model_str}: {sanitized_content}"
        
        if msg.role == 'user' and not is_cron:
            user_lines.append((msg.timestamp, line))
        elif not is_cron:  # Skip cron for assistant section too unless interesting
            other_lines.append((msg.timestamp, line))
    
    # Sort by timestamp
    user_lines.sort(key=lambda x: x[0])
    other_lines.sort(key=lambda x: x[0])
    
    user_section = "\n\n".join(line for _, line in user_lines)
    assistant_section = "\n\n".join(line for _, line in other_lines)
    
    return user_section, assistant_section


def chunk_messages_by_size(messages: list[Message], max_chunk_chars: int = 120000, max_single_msg_chars: int = 15000) -> list[list[Message]]:
    """Split messages into size-based chunks for incremental summarization.
    
    For days with heavy activity, we summarize in chunks then combine.
    Each chunk is guaranteed to be under max_chunk_chars.
    
    Oversized individual messages (>max_single_msg_chars) are truncated with a note.
    """
    if not messages:
        return []
    
    chunks = []
    current_chunk = []
    current_chars = 0
    
    for msg in sorted(messages, key=lambda m: m.timestamp):
        # Estimate this message's contribution
        content = msg.text_content
        if msg.role == 'user':
            content = strip_telegram_envelope(content)
        
        sanitized = sanitize_content(content)
        msg_chars = len(sanitized)
        
        # Truncate oversized individual messages
        if msg_chars > max_single_msg_chars:
            # Create a truncated copy of the message
            truncated_content = sanitized[:max_single_msg_chars] + f"\n\n[... TRUNCATED - original was {msg_chars:,} chars ...]"
            # Create new Message with truncated content
            msg = Message(
                id=msg.id,
                timestamp=msg.timestamp,
                role=msg.role,
                text_content=truncated_content,
                model=msg.model,
                provider=msg.provider,
                has_tool_calls=msg.has_tool_calls,
                has_thinking=msg.has_thinking
            )
            msg_chars = len(truncated_content)
        
        # If adding this message would exceed limit, start new chunk
        if current_chars + msg_chars > max_chunk_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [msg]
            current_chars = msg_chars
        else:
            current_chunk.append(msg)
            current_chars += msg_chars
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def estimate_tokens(text: str) -> int:
    """Rough token estimate (1 token ≈ 4 chars for English)."""
    return len(text) // 4


def prepare_conversation_text(messages: list[Message], max_chars: int = 100000) -> str:
    """Prepare conversation text for summarization.
    
    If content fits in max_chars, returns full text.
    If content exceeds max_chars, returns with a note that chunked summarization is needed.
    
    NO TRUNCATION of individual messages - full content preserved.
    """
    user_section, assistant_section = prepare_conversation_text_full(messages)
    
    total_chars = len(user_section) + len(assistant_section)
    
    # Count actual user messages (not cron)
    user_msg_count = sum(1 for m in messages if m.role == 'user' and 
                         not m.text_content.startswith('[cron:') and
                         'A scheduled reminder has been triggered' not in m.text_content)
    
    output_parts = []
    
    # Header with stats
    output_parts.append(f"=== USER CONVERSATIONS ({user_msg_count} messages - PRIORITY) ===\n")
    output_parts.append(user_section)
    output_parts.append("\n\n=== ASSISTANT ACTIVITY & CONTEXT ===\n")
    output_parts.append(assistant_section)
    
    full_text = "\n".join(output_parts)
    
    # If we exceed limit, add warning but DON'T truncate
    if total_chars > max_chars:
        warning = f"\n\n[NOTE: Total content is {total_chars:,} chars ({estimate_tokens(full_text):,} est. tokens). Full content included - no truncation.]\n"
        full_text = warning + full_text
    
    return full_text


def format_transitions_note(transitions: list[ModelTransition]) -> str:
    """Format transitions as a note for the prompt."""
    if not transitions:
        return ""

    lines = ["\nModel transitions:"]
    for t in transitions:
        time_str = t.timestamp.strftime('%H:%M')
        from_str = t.from_model or "start"
        to_str = t.to_model
        lines.append(f"- {time_str}: {from_str} -> {to_str}")

    return '\n'.join(lines)


def _build_summarization_prompt(
    log_date: date,
    messages: list[Message],
    transitions: list[ModelTransition],
    existing_content: Optional[str] = None
) -> str:
    """Build the prompt for LLM summarization."""
    conversation_text = prepare_conversation_text(messages)
    transitions_note = format_transitions_note(transitions)

    day_name = log_date.strftime('%A, %Y-%m-%d')
    
    # Count user vs other messages for context
    user_msg_count = sum(1 for m in messages if m.role == 'user' and 
                         not m.text_content.startswith('[cron:') and
                         'A scheduled reminder has been triggered' not in m.text_content)
    total_msg_count = len(messages)

    user_prompt = f"""Generate a daily memory summary for {day_name}.

MESSAGE STATISTICS: {user_msg_count} human user messages out of {total_msg_count} total messages.

{conversation_text}
{transitions_note}

CRITICAL REQUIREMENTS:
1. START with a "User Conversations & Decisions" section - MANDATORY if any user messages exist
2. Every substantive user question, discussion topic, or decision MUST be captured
3. Do NOT let automated/cron activity overshadow user discussions
4. Include the *substance* of conversations (what was discussed, what was concluded)
5. Technical accomplishments come AFTER user content
6. Do NOT include secrets or raw PII

The "USER CONVERSATIONS" section above contains the MOST IMPORTANT content.
If you find yourself writing mostly about cron jobs or automated tasks, STOP and re-read the user messages.

Write with the structure: Overview → User Discussions → Technical Work → Open Loops."""

    if existing_content:
        _, hand_written = extract_preserved_content(existing_content)
        if hand_written:
            user_prompt += f"\n\nExisting hand-written notes (PRESERVE AND INCORPORATE):\n{hand_written}"

    return user_prompt


import subprocess


def _extract_text_from_openclaw_response(output: dict) -> Optional[str]:
    """Extract text content from various OpenClaw response formats.
    
    OpenClaw agent --json can return different structures depending on
    the model and response type. This function handles all known formats:
    
    1. result.payloads[0].text - Standard format
    2. result.payloads[0].content[0].text - Nested content format  
    3. message.content[0].text - Direct message format
    4. response - Simple response key
    5. text - Direct text key
    6. output - Direct output key
    """
    if not isinstance(output, dict):
        return None
    
    # Format 1: result.payloads[0].text (most common)
    if 'result' in output and isinstance(output['result'], dict):
        result = output['result']
        payloads = result.get('payloads', [])
        if payloads and isinstance(payloads, list) and len(payloads) > 0:
            payload = payloads[0]
            if isinstance(payload, dict):
                # Direct text in payload
                if 'text' in payload and payload['text']:
                    return payload['text']
                # Nested content array in payload
                if 'content' in payload and isinstance(payload['content'], list):
                    for block in payload['content']:
                        if isinstance(block, dict) and block.get('type') == 'text':
                            text = block.get('text', '')
                            if text:
                                return text
    
    # Format 2: message.content[0].text
    if 'message' in output:
        msg = output['message']
        if isinstance(msg, dict) and 'content' in msg:
            content = msg['content']
            if isinstance(content, list) and len(content) > 0:
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text = block.get('text', '')
                        if text:
                            return text
                # Try first block directly
                first = content[0]
                if isinstance(first, dict) and 'text' in first:
                    return first['text']
            elif isinstance(content, str):
                return content
    
    # Format 3: Simple top-level keys
    for key in ['response', 'text', 'output', 'content']:
        if key in output:
            val = output[key]
            if isinstance(val, str) and val.strip():
                return val
    
    return None


def summarize_with_openclaw(
    log_date: date,
    messages: list[Message],
    transitions: list[ModelTransition],
    existing_content: Optional[str] = None,
    model: Optional[str] = None,
    is_chunk: bool = False
) -> str:
    """Use OpenClaw's sessions_spawn to summarize via the user's configured model.

    This is the preferred method as it uses the user's existing OpenClaw setup
    and doesn't require separate API keys.
    
    Args:
        is_chunk: If True, use concise CHUNK_SYSTEM_PROMPT for time-block summaries
    """
    user_prompt = _build_summarization_prompt(log_date, messages, transitions, existing_content)

    # Use concise prompt for chunks, full prompt for day summaries
    system_prompt = CHUNK_SYSTEM_PROMPT if is_chunk else MEMORY_SYSTEM_PROMPT

    # Combine system prompt and user prompt for the task
    full_prompt = f"""{system_prompt}

---

{user_prompt}"""

    # Use OpenClaw CLI to run an agent turn via the gateway
    import json
    import tempfile

    # Write prompt to a temp file to avoid shell escaping issues with large prompts
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(full_prompt)
        prompt_file = f.name

    # Timeout configuration: 45 minutes for heavy days with chunked summarization
    # Heavy days (800+ messages) can take 10-15 minutes for full summarization
    AGENT_TIMEOUT_SECONDS = 2700  # 45 minutes
    SUBPROCESS_TIMEOUT_SECONDS = 2760  # 46 minutes (slightly more than agent timeout)
    
    try:
        # Use openclaw agent with a unique session ID to avoid locking the main session
        import time
        session_id = f"memory-sync-{int(time.time())}"
        cmd = [
            "openclaw", "agent",
            "--session-id", session_id,
            "--message", full_prompt,
            "--json",
            "--timeout", str(AGENT_TIMEOUT_SECONDS)
        ]
        
        # Model override via dedicated agent
        # Pre-configured agents allow model selection without modifying main agent:
        #   - memory-sync: google/gemini-2.5-pro (large context, fast)
        # Create with: openclaw agents add memory-sync --model google/gemini-2.5-pro --workspace ~/.openclaw/workspace --non-interactive
        # 
        # Model aliases supported: gemini, opus, sonnet, gpt, kimi
        # Full model IDs also work: google/gemini-2.5-pro, anthropic/claude-opus-4-5, etc.
        if model:
            model_lower = model.lower()
            if model_lower in ('gemini', 'google/gemini-2.5-pro', 'google/gemini-2.5-flash'):
                cmd.extend(["--agent", "memory-sync"])
                print(f"  Using memory-sync agent (Gemini)", file=sys.stderr)
            else:
                # For other models, warn that they need a dedicated agent configured
                print(f"  Warning: --model {model} specified but no dedicated agent configured.", file=sys.stderr)
                print(f"  Using default agent. To use {model}, run:", file=sys.stderr)
                print(f"    openclaw agents add memory-sync-{model_lower.replace('/', '-')} --model {model} --workspace ~/.openclaw/workspace --non-interactive", file=sys.stderr)

        print(f"  Running OpenClaw agent (timeout: {AGENT_TIMEOUT_SECONDS}s)...", file=sys.stderr)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            env={**os.environ}
        )

        if result.returncode == 0:
            # Parse JSON output to extract the agent's response
            try:
                output = json.loads(result.stdout)
                text = _extract_text_from_openclaw_response(output)
                if text:
                    return sanitize_content(text.strip())
                # If we couldn't extract text, log the structure for debugging
                print(f"  Warning: Could not extract text from response. Keys: {list(output.keys()) if isinstance(output, dict) else type(output)}", file=sys.stderr)
                raise RuntimeError(f"Could not parse OpenClaw response structure: {json.dumps(output)[:500]}")
            except json.JSONDecodeError as e:
                # Not JSON - maybe plain text response
                if result.stdout.strip():
                    return sanitize_content(result.stdout.strip())
                raise RuntimeError(f"OpenClaw returned non-JSON output: {result.stdout[:200]} (parse error: {e})")
        else:
            raise RuntimeError(f"openclaw agent failed (exit {result.returncode}): {result.stderr or result.stdout}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"OpenClaw summarization timed out after {SUBPROCESS_TIMEOUT_SECONDS} seconds")
    except FileNotFoundError:
        raise RuntimeError(
            "openclaw CLI not found. "
            "Make sure OpenClaw is installed and in your PATH, "
            "or use --summarize-backend=anthropic or --summarize-backend=openai"
        )
    finally:
        # Clean up temp file
        try:
            os.unlink(prompt_file)
        except:
            pass


def summarize_with_openai_package(
    log_date: date,
    messages: list[Message],
    transitions: list[ModelTransition],
    existing_content: Optional[str] = None,
    model: Optional[str] = None,
    provider: str = "openai",
    is_chunk: bool = False
) -> str:
    """Fallback summarization using OpenAI package (works with OpenAI and Anthropic APIs).
    
    Args:
        is_chunk: If True, use concise CHUNK_SYSTEM_PROMPT for time-block summaries
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "openai package not installed. "
            "Install with: pip install openai"
        )

    # Configure based on provider
    if provider == "anthropic":
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        base_url = "https://api.anthropic.com/v1"
        default_model = "claude-sonnet-4-5"
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. "
                "Set it with: export ANTHROPIC_API_KEY=sk-ant-..."
            )
    else:  # openai
        api_key = os.environ.get('OPENAI_API_KEY')
        base_url = None  # Use default
        default_model = "gpt-4o"
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not set. "
                "Set it with: export OPENAI_API_KEY=sk-..."
            )

    client = OpenAI(api_key=api_key, base_url=base_url)

    user_prompt = _build_summarization_prompt(log_date, messages, transitions, existing_content)
    
    # Use concise prompt for chunks, full prompt for day summaries
    system_prompt = CHUNK_SYSTEM_PROMPT if is_chunk else MEMORY_SYSTEM_PROMPT
    # Chunks should be much shorter
    max_tokens = 800 if is_chunk else 3500

    response = client.chat.completions.create(
        model=model or default_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=max_tokens,
        temperature=0.3
    )

    return sanitize_content(response.choices[0].message.content)


def summarize_chunked(
    log_date: date,
    messages: list[Message],
    transitions: list[ModelTransition],
    existing_content: Optional[str] = None,
    model: Optional[str] = None,
    backend: str = 'openclaw',
    max_chunk_chars: int = 120000,
    max_context_chars: int = 80000
) -> str:
    """Summarize large days by chunking into size-based segments.
    
    For days with heavy activity that would exceed context limits:
    1. Split messages into size-based chunks (each under max_chunk_chars)
    2. Summarize each chunk independently (using fast Haiku model)
    3. Combine chunk summaries into final daily summary (using Sonnet)
    
    For light days (<= SIMPLE_SUMMARY_THRESHOLD messages), uses simple summarization.
    """
    # Light days: skip chunking entirely, use simple summarization
    if len(messages) <= SIMPLE_SUMMARY_THRESHOLD:
        print(f"  Light day ({len(messages)} messages) - using simple summarization...")
        summarizer = get_summarizer(backend)
        return summarizer(log_date, messages, transitions, existing_content, model)
    
    # Check if we need chunking based on size
    user_section, assistant_section = prepare_conversation_text_full(messages)
    total_chars = len(user_section) + len(assistant_section)
    
    # Gemini has 1M+ token context, BUT shell ARG_MAX is ~2MB
    # So we're limited by command line length, not model context
    use_gemini = model and model.lower() in ('gemini', 'google/gemini-2.5-pro', 'google/gemini-2.5-flash')
    SHELL_ARG_MAX = 1_500_000  # Safe limit under 2MB ARG_MAX
    
    if use_gemini:
        # First, try to fit by truncating tool outputs
        if total_chars > SHELL_ARG_MAX:
            print(f"  Day too large for CLI ({total_chars:,} chars > {SHELL_ARG_MAX:,})", file=sys.stderr)
            print(f"  Truncating tool outputs...", file=sys.stderr)
            
            # Truncate tool results aggressively (500 chars each)
            # Note: role is 'toolResult' in Message dataclass
            truncated_messages = []
            for msg in messages:
                if msg.role == 'toolResult' and len(msg.text_content) > 500:
                    # Create a copy with truncated content
                    truncated_msg = Message(
                        id=msg.id,
                        timestamp=msg.timestamp,
                        role=msg.role,
                        text_content=msg.text_content[:500] + "\n[...truncated...]",
                        model=msg.model,
                        provider=msg.provider,
                        has_tool_calls=msg.has_tool_calls,
                        has_thinking=msg.has_thinking
                    )
                    truncated_messages.append(truncated_msg)
                else:
                    truncated_messages.append(msg)
            
            # Recalculate size
            user_section, assistant_section = prepare_conversation_text_full(truncated_messages)
            new_total = len(user_section) + len(assistant_section)
            print(f"  After truncation: {new_total:,} chars", file=sys.stderr)
            
            if new_total <= SHELL_ARG_MAX:
                print(f"  Using Gemini (truncated) - skipping chunking...", file=sys.stderr)
                summarizer = get_summarizer(backend)
                return summarizer(log_date, truncated_messages, transitions, existing_content, model)
            else:
                print(f"  Still too large ({new_total:,} chars) - falling back to chunked summarization", file=sys.stderr)
                # Fall through to chunked processing below
        else:
            print(f"  Using Gemini ({total_chars:,} chars) - skipping chunking...", file=sys.stderr)
            summarizer = get_summarizer(backend)
            return summarizer(log_date, messages, transitions, existing_content, model)
    
    if total_chars <= max_context_chars:
        # Fits in context - use normal summarization
        summarizer = get_summarizer(backend)
        return summarizer(log_date, messages, transitions, existing_content, model)
    
    # Need chunking - use SIZE-based chunking to guarantee each chunk fits
    print(f"  Large day ({len(messages)} messages, {total_chars:,} chars) - using chunked summarization...")
    
    # Determine if we should use Gemini for synthesis
    use_gemini = model and model.lower() in ('gemini', 'google/gemini-2.5-pro', 'google/gemini-2.5-flash')
    
    chunks = chunk_messages_by_size(messages, max_chunk_chars)
    print(f"  Split into {len(chunks)} chunks (max {max_chunk_chars:,} chars each)")
    
    chunk_summaries = []
    # Use concise chunk summarizer with FAST model (Haiku for chunks via Anthropic API)
    # is_chunk=True produces brief bullet-point summaries
    # Note: Use 'anthropic' backend for chunks because openclaw CLI doesn't support --model override
    # Synthesis will use the main 'backend' (openclaw) with default Sonnet
    try:
        chunk_summarizer = get_summarizer('anthropic', is_chunk=True)
        chunk_model = DEFAULT_CHUNK_MODEL  # Haiku for speed
        print(f"  Using Anthropic API with {chunk_model} for fast chunk summarization...")
    except Exception as e:
        # Fall back to OpenClaw backend if Anthropic not available
        print(f"  Anthropic API not available ({e}), using OpenClaw backend...")
        chunk_summarizer = get_summarizer(backend, is_chunk=True)
        chunk_model = None
    
    # Parallel chunk summarization using ThreadPoolExecutor
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    
    def summarize_chunk(chunk_info):
        i, chunk = chunk_info
        if not chunk:
            return None
        chunk_start = chunk[0].timestamp.strftime('%H:%M')
        chunk_end = chunk[-1].timestamp.strftime('%H:%M')
        print(f"  [Thread {threading.current_thread().name}] Summarizing chunk {i+1}/{len(chunks)} ({chunk_start}-{chunk_end}, {len(chunk)} messages)...")
        try:
            # Use Haiku for chunks (fast), synthesis will use Sonnet via OpenClaw
            summary = chunk_summarizer(log_date, chunk, [], None, chunk_model)
            return (i, f"### Time Block {i+1}: {chunk_start}-{chunk_end}\n\n{summary}")
        except Exception as e:
            print(f"  [Thread] Chunk {i+1} failed: {e}")
            return (i, f"### Time Block {i+1}: {chunk_start}-{chunk_end}\n\n[Summarization failed: {e}]")
    
    # Use 3 parallel workers (balance between speed and API rate limits)
    MAX_WORKERS = 3
    print(f"  Parallelizing with {MAX_WORKERS} workers...")
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(summarize_chunk, (i, chunk)): i for i, chunk in enumerate(chunks)}
        results = {}
        for future in as_completed(futures):
            result = future.result()
            if result:
                idx, summary = result
                results[idx] = summary
    
    # Reassemble in order
    chunk_summaries = [results[i] for i in sorted(results.keys())]
    
    # Now combine chunk summaries into final summary
    combined_chunks = "\n\n---\n\n".join(chunk_summaries)
    
    day_name = log_date.strftime('%A, %Y-%m-%d')
    
    # Use OpenClaw for synthesis
    import subprocess
    import json
    import time as time_module
    
    # Synthesis timeout: 10 minutes per synthesis call
    SYNTHESIS_TIMEOUT = 600
    # Max chars for a single synthesis call (stay well under shell arg limits)
    MAX_SYNTHESIS_CHARS = 100000  # ~100KB safe for command line
    
    def run_synthesis(prompt_text: str, session_suffix: str = "", use_gemini: bool = False) -> Optional[str]:
        """Run a single synthesis call via OpenClaw agent."""
        session_id = f"memory-sync-synthesis-{int(time_module.time())}{session_suffix}"
        cmd = [
            "openclaw", "agent",
            "--session-id", session_id,
            "--message", prompt_text,
            "--json",
            "--timeout", str(SYNTHESIS_TIMEOUT)
        ]
        
        # Use memory-sync agent (Gemini) if requested
        if use_gemini:
            cmd.extend(["--agent", "memory-sync"])
            print(f"    Using Gemini for synthesis...", file=sys.stderr)
        
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=SYNTHESIS_TIMEOUT + 60,
                env={**os.environ}
            )
            
            if result.returncode == 0:
                output = json.loads(result.stdout)
                return _extract_text_from_openclaw_response(output)
        except Exception as e:
            print(f"  Synthesis call failed: {e}", file=sys.stderr)
        return None
    
    # Check if we need hierarchical synthesis (combined chunks too large)
    if len(combined_chunks) > MAX_SYNTHESIS_CHARS:
        print(f"  Large synthesis needed ({len(combined_chunks):,} chars) - using hierarchical approach...", file=sys.stderr)
        
        # Group chunks into batches that fit in synthesis calls
        CHUNKS_PER_BATCH = 8  # ~8 chunks × ~10KB each = ~80KB per batch
        batches = []
        for i in range(0, len(chunk_summaries), CHUNKS_PER_BATCH):
            batches.append(chunk_summaries[i:i + CHUNKS_PER_BATCH])
        
        print(f"  Synthesizing {len(batches)} batches of chunks...", file=sys.stderr)
        
        # First pass: synthesize each batch
        batch_summaries = []
        for i, batch in enumerate(batches):
            batch_text = "\n\n---\n\n".join(batch)
            batch_prompt = f"""Synthesize these {len(batch)} time-block summaries from {day_name} into a single cohesive section.
Preserve all user conversations, decisions, and key technical details.
Write in past tense. Be detailed but remove redundancy.

{batch_text}

---

Write a synthesized summary (target: 1000-2000 words) covering all important content from these time blocks."""
            
            print(f"  Batch {i+1}/{len(batches)}...", file=sys.stderr)
            batch_result = run_synthesis(batch_prompt, f"-batch{i}", use_gemini=use_gemini)
            
            if batch_result:
                batch_summaries.append(f"## Part {i+1} (Time Blocks {i*CHUNKS_PER_BATCH + 1}-{min((i+1)*CHUNKS_PER_BATCH, len(chunk_summaries))})\n\n{batch_result}")
            else:
                # Fallback: use raw chunks for this batch
                batch_summaries.append(f"## Part {i+1} (Time Blocks {i*CHUNKS_PER_BATCH + 1}-{min((i+1)*CHUNKS_PER_BATCH, len(chunk_summaries))})\n\n{batch_text}")
        
        # Second pass: final synthesis of batch summaries
        combined_batches = "\n\n---\n\n".join(batch_summaries)
        
        if len(combined_batches) <= MAX_SYNTHESIS_CHARS:
            final_prompt = f"""You have {len(batches)} synthesized sections from {day_name}.
Create the final daily memory file by merging these sections.

{combined_batches}

---

Create the final daily summary with the standard structure:
1. Overview (2-5 sentences covering the whole day)
2. User Conversations & Decisions (consolidated from all sections)
3. Key Accomplishments / Technical Changes
4. Notable Findings / Insights / Patterns
5. Open Loops / Next Actions

Merge related topics across sections. Preserve all important user discussions."""
            
            print(f"  Final synthesis of {len(batches)} batch summaries...", file=sys.stderr)
            final_result = run_synthesis(final_prompt, "-final", use_gemini=use_gemini)
            
            if final_result:
                return sanitize_content(final_result.strip())
        
        # Fallback: return batch summaries without final synthesis
        print(f"  Final synthesis skipped (too large), returning batch summaries", file=sys.stderr)
        return f"# {day_name}\n\n*Hierarchical summary ({len(batches)} batches)*\n\n{combined_batches}"
    
    else:
        # Small enough for single synthesis
        synthesis_prompt = f"""You have summarized a large day ({day_name}) in {len(chunks)} time-based chunks.
Now synthesize these chunk summaries into a single coherent daily memory file.

CHUNK SUMMARIES:

{combined_chunks}

---

Create the final daily summary with the standard structure:
1. Overview (2-5 sentences covering the whole day)
2. User Conversations & Decisions (consolidated from all chunks)
3. Key Accomplishments / Technical Changes
4. Notable Findings / Insights / Patterns
5. Open Loops / Next Actions

Merge related topics across chunks. Preserve all important user discussions.
Remove redundancy but keep detail for significant events."""

        print(f"  Synthesizing {len(chunks)} chunk summaries...", file=sys.stderr)
        result = run_synthesis(synthesis_prompt, use_gemini=use_gemini)
        
        if result:
            return sanitize_content(result.strip())
        
        # Fallback: return combined chunks
        print(f"  Synthesis failed, returning raw chunks", file=sys.stderr)
        return f"# {day_name}\n\n*Chunked summary (synthesis failed)*\n\n{combined_chunks}"


def get_summarizer(backend: str, is_chunk: bool = False):
    """Factory function to get the appropriate summarizer based on backend choice.
    
    Args:
        backend: Which LLM backend to use (openclaw, openai, anthropic)
        is_chunk: If True, returns a summarizer that uses concise chunk prompts
    """

    def openclaw_summarizer(log_date, messages, transitions, existing_content=None, model=None):
        return summarize_with_openclaw(log_date, messages, transitions, existing_content, model, is_chunk=is_chunk)

    def openai_summarizer(log_date, messages, transitions, existing_content=None, model=None):
        return summarize_with_openai_package(log_date, messages, transitions, existing_content, model, provider="openai", is_chunk=is_chunk)

    def anthropic_summarizer(log_date, messages, transitions, existing_content=None, model=None):
        return summarize_with_anthropic(log_date, messages, transitions, existing_content, model, is_chunk=is_chunk)

    backends = {
        'openclaw': openclaw_summarizer,
        'openai': openai_summarizer,
        'anthropic': anthropic_summarizer,
    }

    if backend not in backends:
        raise ValueError(f"Unknown summarization backend: {backend}. Choose from: {list(backends.keys())}")

    return backends[backend]


def summarize_with_anthropic(
    log_date: date,
    messages: list[Message],
    transitions: list[ModelTransition],
    existing_content: Optional[str] = None,
    model: Optional[str] = None,
    is_chunk: bool = False
) -> str:
    """Summarize a day's conversation using Anthropic API.
    
    Args:
        is_chunk: If True, use concise CHUNK_SYSTEM_PROMPT for time-block summaries
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropic package not installed. "
            "Install with: pip install anthropic"
        )

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Set it with: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    client = anthropic.Anthropic(api_key=api_key)

    # Use default model if not specified
    if model is None:
        model = DEFAULT_SUMMARIZE_MODEL

    conversation_text = prepare_conversation_text(messages)
    transitions_note = format_transitions_note(transitions)

    day_name = log_date.strftime('%A, %Y-%m-%d')
    
    # Count user vs other messages for context  
    user_msg_count = sum(1 for m in messages if m.role == 'user' and 
                         not m.text_content.startswith('[cron:') and
                         'A scheduled reminder has been triggered' not in m.text_content)
    total_msg_count = len(messages)

    user_prompt = f"""Generate a daily memory summary for {day_name}.

MESSAGE STATISTICS: {user_msg_count} human user messages out of {total_msg_count} total messages.

{conversation_text}
{transitions_note}

CRITICAL REQUIREMENTS:
1. START with a "User Conversations & Decisions" section - MANDATORY if any user messages exist
2. Every substantive user question, discussion topic, or decision MUST be captured
3. Do NOT let automated/cron activity overshadow user discussions
4. Include the *substance* of conversations (what was discussed, what was concluded)
5. Technical accomplishments come AFTER user content
6. Do NOT include secrets or raw PII

The "USER CONVERSATIONS" section above contains the MOST IMPORTANT content.
If you find yourself writing mostly about cron jobs or automated tasks, STOP and re-read the user messages.

Write with the structure: Overview → User Discussions → Technical Work → Open Loops."""

    if existing_content:
        _, hand_written = extract_preserved_content(existing_content)
        if hand_written:
            user_prompt += f"\n\nExisting hand-written notes (PRESERVE AND INCORPORATE):\n{hand_written}"

    # Use concise prompt for chunks, full prompt for day summaries
    system_prompt = CHUNK_SYSTEM_PROMPT if is_chunk else MEMORY_SYSTEM_PROMPT
    # Chunks should be much shorter
    max_tokens = 800 if is_chunk else 3500

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": user_prompt
        }]
    )

    summary = response.content[0].text

    return sanitize_content(summary)


def generate_summarized_memory(
    log_date: date,
    sessions_dir: Path,
    output_path: Path,
    force: bool = False,
    preserve: bool = False,
    model: Optional[str] = None,
    backend: str = 'openclaw'
) -> str:
    """Generate a daily memory file using LLM summarization.

    Args:
        log_date: The date to generate memory for
        sessions_dir: Path to session logs directory
        output_path: Path to write the memory file
        force: Overwrite existing files
        preserve: Preserve hand-written content from existing files
        model: Model override for summarization
        backend: Summarization backend ('openclaw', 'openai', or 'anthropic')
    """
    existing_content = ""
    if output_path.exists():
        if not force and not preserve:
            raise FileExistsError(f"File already exists: {output_path}. Use --force to overwrite.")
        if preserve:
            existing_content = output_path.read_text()

    messages: list[Message] = []
    transitions: list[ModelTransition] = []

    for session_file in find_session_files(sessions_dir):
        for msg in get_messages(session_file, date_filter=log_date):
            messages.append(msg)

        for trans in get_model_transitions(session_file):
            if _local_date(trans.timestamp) == log_date:
                transitions.append(trans)

    if not messages:
        raise ValueError(f"No messages found for {log_date}")

    messages.sort(key=lambda m: m.timestamp)
    transitions.sort(key=lambda t: t.timestamp)

    # Check content size to decide on chunking
    user_section, assistant_section = prepare_conversation_text_full(messages)
    total_chars = len(user_section) + len(assistant_section)
    
    # Use chunked summarization for large days (>80k chars ≈ 20k tokens)
    MAX_CONTEXT_CHARS = 80000
    
    try:
        if total_chars > MAX_CONTEXT_CHARS:
            print(f"  Large day detected ({total_chars:,} chars) - using chunked summarization")
            summary = summarize_chunked(
                log_date, messages, transitions,
                existing_content=existing_content if preserve else None,
                model=model,
                backend=backend,
                max_context_chars=MAX_CONTEXT_CHARS
            )
        else:
            # Normal summarization
            summarizer = get_summarizer(backend)
            summary = summarizer(
                log_date, messages, transitions,
                existing_content=existing_content if preserve else None,
                model=model
            )
    except Exception as e:
        # If openclaw backend fails, provide helpful error message
        if backend == 'openclaw':
            print(f"Warning: OpenClaw summarization failed ({e})", file=sys.stderr)
            print("Try using --summarize-backend=anthropic (recommended) or --summarize-backend=openai", file=sys.stderr)
        raise

    lines = []
    lines.append(f"# {log_date} ({log_date.strftime('%A')})")
    lines.append("")
    lines.append(f"*Auto-generated from {len(messages)} session messages*")
    lines.append("")
    lines.append(summary)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Review and edit this draft to capture what's actually important.*")

    content = '\n'.join(lines)

    is_valid, violations = validate_no_secrets(content)

    if not is_valid:
        print(f"Warning: LLM output contains potential secrets: {violations}", file=sys.stderr)
        print("Attempting to sanitize...", file=sys.stderr)

        content = sanitize_content(content)

        is_valid, violations = validate_no_secrets(content)

        if not is_valid:
            # Write to .rejected file for manual review
            rejected_path = output_path.with_suffix('.md.rejected')
            rejected_path.parent.mkdir(parents=True, exist_ok=True)
            rejected_path.write_text(content)
            print(f"Draft saved to: {rejected_path}", file=sys.stderr)
            print("⚠️  MANUAL REVIEW REQUIRED: Edit the .rejected file to remove secrets, then rename to .md", file=sys.stderr)
            raise ValueError(
                f"Memory file contains secrets after sanitization: {violations}. "
                f"Draft saved to {rejected_path} for manual editing."
            )

        print("Content sanitized successfully.", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)

    return str(output_path)


# =============================================================================
# VALIDATE
# =============================================================================

def validate_memory_files(memory_dir: Path, sessions_dir: Path) -> dict:
    """Validate memory files for consistency issues."""
    issues: list[ValidationIssue] = []
    valid_count = 0
    total_count = 0

    if not memory_dir.exists():
        return {
            'issues': [ValidationIssue(
                file_path=str(memory_dir),
                issue_type='parse_error',
                description='Memory directory does not exist',
                severity='error'
            )],
            'valid_count': 0,
            'total_count': 0,
        }

    daily_activity = collect_daily_activity(sessions_dir) if sessions_dir.exists() else {}

    for file_path in memory_dir.glob('*.md'):
        total_count += 1
        file_issues: list[ValidationIssue] = []

        if file_path.name.upper() == 'MEMORY.MD':
            continue

        file_date = _validate_filename(file_path)
        if file_date is None:
            file_issues.append(ValidationIssue(
                file_path=str(file_path),
                issue_type='naming',
                description=f'Filename does not match YYYY-MM-DD.md pattern: {file_path.name}',
                severity='warning'
            ))
        else:
            header_issue = _validate_header(file_path, file_date)
            if header_issue:
                file_issues.append(header_issue)

            if file_date not in daily_activity or daily_activity[file_date].message_count == 0:
                file_issues.append(ValidationIssue(
                    file_path=str(file_path),
                    issue_type='orphaned',
                    description=f'No session activity found for {file_date}',
                    severity='warning'
                ))

        file_size = file_path.stat().st_size
        if file_size < MIN_VALID_SIZE:
            file_issues.append(ValidationIssue(
                file_path=str(file_path),
                issue_type='too_small',
                description=f'File too small: {file_size} bytes (minimum: {MIN_VALID_SIZE})',
                severity='warning'
            ))

        if file_issues:
            issues.extend(file_issues)
        else:
            valid_count += 1

    return {
        'issues': issues,
        'valid_count': valid_count,
        'total_count': total_count,
    }


def _validate_filename(file_path: Path) -> date | None:
    """Validate filename matches YYYY-MM-DD.md pattern."""
    try:
        return date.fromisoformat(file_path.stem)
    except ValueError:
        return None


def _validate_header(file_path: Path, expected_date: date) -> ValidationIssue | None:
    """Validate that the file's date header matches the filename."""
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        return ValidationIssue(
            file_path=str(file_path),
            issue_type='parse_error',
            description=f'Could not read file: {e}',
            severity='error'
        )

    first_line = content.split('\n')[0] if content else ''

    date_pattern = r'\b(\d{4}-\d{2}-\d{2})\b'
    match = re.search(date_pattern, first_line)

    if match:
        header_date_str = match.group(1)
        try:
            header_date = date.fromisoformat(header_date_str)
            if header_date != expected_date:
                return ValidationIssue(
                    file_path=str(file_path),
                    issue_type='header_mismatch',
                    description=f'Header date {header_date} does not match filename date {expected_date}',
                    severity='warning'
                )
        except ValueError:
            pass

    return None


def format_validation_report(validation_result: dict) -> str:
    """Format validation results as a human-readable report."""
    lines = []

    lines.append("Memory File Validation Report")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"Total files checked: {validation_result['total_count']}")
    lines.append(f"Valid files: {validation_result['valid_count']}")
    lines.append(f"Files with issues: {validation_result['total_count'] - validation_result['valid_count']}")
    lines.append("")

    issues = validation_result['issues']
    if not issues:
        lines.append("All files passed validation!")
        return '\n'.join(lines)

    by_type: dict[str, list[ValidationIssue]] = {}
    for issue in issues:
        if issue.issue_type not in by_type:
            by_type[issue.issue_type] = []
        by_type[issue.issue_type].append(issue)

    type_labels = {
        'naming': 'Naming Issues',
        'header_mismatch': 'Header Mismatches',
        'too_small': 'Files Too Small',
        'orphaned': 'Orphaned Files (no session activity)',
        'parse_error': 'Parse Errors',
    }

    for issue_type, type_issues in by_type.items():
        label = type_labels.get(issue_type, issue_type)
        severity_icon = "!" if any(i.severity == 'error' for i in type_issues) else "~"

        lines.append(f"{severity_icon} {label} ({len(type_issues)})")
        lines.append("-" * 40)
        for issue in type_issues:
            file_name = Path(issue.file_path).name
            lines.append(f"  {file_name}: {issue.description}")
        lines.append("")

    return '\n'.join(lines)


# =============================================================================
# CLI
# =============================================================================

def get_default_sessions_dir() -> Path:
    return DEFAULT_SESSIONS_DIR


def get_default_memory_dir() -> Path:
    return DEFAULT_MEMORY_DIR


def parse_date_str(date_str: str) -> date:
    """Parse a date string in YYYY-MM-DD format."""
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise click.BadParameter(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")


@click.group()
@click.version_option()
def main():
    """Memory Sync - OpenClaw session log analysis and memory backfill."""
    pass


@main.command()
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
@click.option("--memory-dir", default=None, help="Path to memory files directory")
@click.option("--include-today", is_flag=True, help="Include today's partial logs in coverage/sparsity checks")
def compare(sessions_dir, memory_dir, include_today):
    """Compare JSONL logs against memory files, identify gaps."""
    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()
    memory_path = Path(memory_dir) if memory_dir else get_default_memory_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    if not memory_path.exists():
        click.echo(f"Warning: Memory directory not found: {memory_path}", err=True)
        click.echo("Will treat all days as missing.", err=True)
        memory_path.mkdir(parents=True, exist_ok=True)

    click.echo(f"Sessions: {sessions_path}")
    click.echo(f"Memory: {memory_path}")
    click.echo("")

    gaps = find_gaps(sessions_path, memory_path, exclude_today=not include_today)
    report = format_gap_report(gaps)
    click.echo(report)


@main.command()
@click.option("--date", "target_date", default=None, help="Specific date to backfill (YYYY-MM-DD)")
@click.option("--all", "backfill_all", is_flag=True, help="Backfill all missing dates")
@click.option("--today", "today", is_flag=True, help="Backfill only today's date (local timezone)")
@click.option("--since", "since_date", default=None, help="Backfill from date to present (YYYY-MM-DD)")
@click.option("--until", "until_date", default=None, help="End date for backfill (YYYY-MM-DD), exclusive (use with --since or --incremental)")
@click.option("--incremental", "incremental", is_flag=True, help="Backfill only dates changed since last run")
@click.option("--dry-run", is_flag=True, help="Show what would be created")
@click.option("--force", is_flag=True, help="Overwrite existing files")
@click.option("--preserve", is_flag=True, help="Preserve hand-written content from existing files")
@click.option("--summarize", is_flag=True, help="Use LLM to generate narrative summaries")
@click.option("--summarize-backend", "summarize_backend",
              type=click.Choice(['openclaw', 'openai', 'anthropic']),
              default='openclaw',
              help="Backend for LLM summarization (default: openclaw - uses your gateway's configured models)")
@click.option("--model", default=None, help=f"Model override for summarization (default varies by backend)")
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
@click.option("--memory-dir", default=None, help="Path to memory files directory")
def backfill(target_date, backfill_all, today, since_date, until_date, incremental, dry_run, force, preserve, summarize, summarize_backend, model, sessions_dir, memory_dir):
    """Generate missing daily memory files from JSONL logs."""
    # Validate mutual exclusivity
    date_flags = [target_date, backfill_all, today, since_date, incremental]
    date_flags_count = sum(1 for flag in date_flags if flag)

    if date_flags_count == 0:
        click.echo("Error: Must specify one of: --date, --today, --since, --all, or --incremental", err=True)
        sys.exit(1)

    if date_flags_count > 1:
        click.echo("Error: Cannot combine --date, --today, --since, --all, and --incremental", err=True)
        sys.exit(1)

    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()
    memory_path = Path(memory_dir) if memory_dir else get_default_memory_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    memory_path.mkdir(parents=True, exist_ok=True)

    # Choose generator function
    if summarize:
        def generate_fn(log_date, sessions_dir, output_path, force, preserve=False):
            return generate_summarized_memory(
                log_date, sessions_dir, output_path, force=force, preserve=preserve,
                model=model, backend=summarize_backend
            )
    else:
        def generate_fn(log_date, sessions_dir, output_path, force, preserve=False):
            return generate_daily_memory(
                log_date, sessions_dir, output_path, force=force, preserve=preserve
            )

    # Determine dates to process
    dates_to_process = []

    if target_date:
        log_date = parse_date_str(target_date)
        dates_to_process = [log_date]

    elif today:
        log_date = datetime.now().date()
        dates_to_process = [log_date]
        click.echo(f"Processing today: {log_date}")

    elif since_date:
        from_date = parse_date_str(since_date)
        to_date = parse_date_str(until_date) if until_date else datetime.now().date()
        # until_date is exclusive, so subtract 1 day if specified
        if until_date:
            to_date = to_date - timedelta(days=1)

        if from_date > to_date:
            click.echo(f"Error: --since date {from_date} is {'in the future' if not until_date else f'after --until date {until_date}'}", err=True)
            sys.exit(1)

        current = from_date
        while current <= to_date:
            dates_to_process.append(current)
            current += timedelta(days=1)

        until_msg = f" (until {until_date}, exclusive)" if until_date else ""
        click.echo(f"Processing dates from {from_date} to {to_date}{until_msg} ({len(dates_to_process)} days)")

    elif incremental:
        last_run = get_last_run_datetime()

        if last_run is None:
            click.echo("No previous run found. Use --all for initial backfill.", err=True)
            sys.exit(1)

        changed_dates = get_changed_days(sessions_path, last_run)
        dates_to_process = sorted(changed_dates)

        if dates_to_process:
            click.echo(f"Found {len(dates_to_process)} days with changes since {last_run.strftime('%Y-%m-%d %H:%M')}")
        else:
            click.echo(f"No changes since last run at {last_run.strftime('%Y-%m-%d %H:%M')}")

    # Apply until_date filter if specified
    if until_date and dates_to_process:
        until = parse_date_str(until_date)
        original_count = len(dates_to_process)
        dates_to_process = [d for d in dates_to_process if d < until]
        if len(dates_to_process) < original_count:
            click.echo(f"Filtered to dates before {until}: {len(dates_to_process)} days (excluded {original_count - len(dates_to_process)})")

    # Process specific dates
    if dates_to_process and not backfill_all:
        created = []
        skipped = []
        errors = []

        for log_date in dates_to_process:
            output_path = memory_path / f"{log_date}.md"

            if dry_run:
                click.echo(f"Would create: {output_path}")
                created.append(str(output_path))
            else:
                try:
                    path = generate_fn(log_date, sessions_path, output_path, force=force, preserve=preserve)
                    created.append(path)
                    click.echo(f"Created: {path}")
                except FileExistsError:
                    skipped.append(log_date)
                    if len(dates_to_process) > 1:
                        click.echo(f"Skipped: {output_path} (already exists)")
                    else:
                        click.echo(f"Error: File already exists: {output_path}", err=True)
                        click.echo("Use --force or --preserve to overwrite.", err=True)
                        sys.exit(1)
                except ValueError as e:
                    errors.append((log_date, str(e)))
                    if len(dates_to_process) > 1:
                        click.echo(f"Error for {log_date}: {e}", err=True)
                    else:
                        click.echo(f"Error: {e}", err=True)
                        sys.exit(1)

        if len(dates_to_process) > 1:
            click.echo("")
            if created:
                action = "Would create" if dry_run else "Created"
                click.echo(f"{action} {len(created)} files")
            if skipped:
                click.echo(f"Skipped {len(skipped)} existing files (use --force to overwrite)")
            if errors:
                click.echo(f"Errors: {len(errors)}", err=True)

        if incremental and created and not dry_run:
            state = load_state()
            total = state.get('total_days_processed', 0) + len(created)
            last_date = max(dates_to_process) if dates_to_process else None
            save_state(
                last_run=datetime.now(),
                last_successful_date=last_date,
                total_days_processed=total
            )
            click.echo(f"Updated state: {total} total days processed")

    elif backfill_all:
        if summarize:
            gaps = find_gaps(sessions_path, memory_path)
            created = []
            errors = []

            all_gaps = gaps['missing_days'] + (gaps['sparse_days'] if force else [])

            if dry_run:
                click.echo("Dry run - no files created")
                for gap in all_gaps:
                    click.echo(f"Would create: {memory_path / f'{gap.date}.md'}")
            else:
                for i, gap in enumerate(all_gaps):
                    output_path = memory_path / f"{gap.date}.md"
                    click.echo(f"Summarizing {gap.date}...", nl=False)
                    try:
                        path = generate_fn(gap.date, sessions_path, output_path, force=True, preserve=preserve)
                        created.append(path)
                        click.echo(" done")
                        # Rate limiting: delay between LLM calls to avoid hitting API limits
                        if i < len(all_gaps) - 1:  # Don't delay after the last one
                            time.sleep(LLM_BATCH_DELAY_SECONDS)
                    except Exception as e:
                        errors.append((gap.date, str(e)))
                        click.echo(f" error: {e}")

                if created:
                    click.echo(f"\nCreated {len(created)} files")
                if errors:
                    click.echo(f"Errors: {len(errors)}", err=True)
                if not created and not errors:
                    click.echo("No missing files to backfill.")
        else:
            result = backfill_all_missing(sessions_path, memory_path, dry_run=dry_run, force=force, preserve=preserve)

            if dry_run:
                click.echo("Dry run - no files created")
                click.echo("")

            if result['created']:
                action = "Would create" if dry_run else "Created"
                click.echo(f"{action} {len(result['created'])} files:")
                for path in result['created']:
                    click.echo(f"  {path}")

            if result['skipped']:
                click.echo(f"\nSkipped {len(result['skipped'])} existing files (use --force to overwrite)")

            if result['errors']:
                click.echo(f"\nErrors ({len(result['errors'])}):", err=True)
                for err_date, err_msg in result['errors']:
                    click.echo(f"  {err_date}: {err_msg}", err=True)

            if not result['created'] and not result['errors']:
                click.echo("No missing files to backfill.")


@main.command()
@click.option("--date", "target_date", default=None, help="Filter by date (YYYY-MM-DD)")
@click.option("--query", default=None, help="Search term in messages")
@click.option("--model", default=None, help="Filter by model used")
@click.option("--format", "output_format", default="md", type=click.Choice(['md', 'json', 'text']), help="Output format")
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
def extract(target_date, query, model, output_format, sessions_dir):
    """Extract conversations matching criteria."""
    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    date_filter = parse_date_str(target_date) if target_date else None

    messages = []
    for session_file in find_session_files(sessions_path):
        for msg in get_messages(session_file, date_filter=date_filter):
            if query and query.lower() not in msg.text_content.lower():
                continue

            if model and msg.model != model:
                continue

            messages.append(msg)

    messages.sort(key=lambda m: m.timestamp)

    if not messages:
        click.echo("No matching messages found.")
        return

    click.echo(f"Found {len(messages)} matching messages")
    click.echo("")

    if output_format == 'json':
        data = [
            {
                'id': m.id,
                'timestamp': m.timestamp.isoformat(),
                'role': m.role,
                'text': sanitize_content(m.text_content),
                'model': m.model,
                'provider': m.provider,
            }
            for m in messages
        ]
        click.echo(json.dumps(data, indent=2))

    elif output_format == 'text':
        for msg in messages:
            time_str = msg.timestamp.strftime('%Y-%m-%d %H:%M')
            role = msg.role.upper()
            text = sanitize_content(msg.text_content)
            click.echo(f"[{time_str}] {role}: {text}")
            click.echo("")

    else:  # md
        for msg in messages:
            time_str = msg.timestamp.strftime('%Y-%m-%d %H:%M')
            role = msg.role.capitalize()
            model_str = f" ({msg.model})" if msg.model else ""
            click.echo(f"### [{time_str}] {role}{model_str}")
            click.echo("")
            text = sanitize_content(msg.text_content)
            click.echo(text)
            click.echo("")


@main.command()
@click.option("--date", "target_date", required=True, help="Date to summarize (YYYY-MM-DD)")
@click.option("--summarize-backend", "summarize_backend",
              type=click.Choice(['openclaw', 'openai', 'anthropic']),
              default='openclaw',
              help="Backend for LLM summarization (default: openclaw - uses your gateway's configured models)")
@click.option("--model", default=None, help="Model override for summarization (default varies by backend)")
@click.option("--output", default=None, help="Write to file (default: stdout)")
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
def summarize(target_date, summarize_backend, model, output, sessions_dir):
    """Generate an LLM summary for a single day."""
    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    log_date = parse_date_str(target_date)

    # Track whether we're using a temp file for cleanup
    using_temp_file = output is None
    if output:
        output_path = Path(output)
    else:
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
        output_path = Path(tmp.name)
        tmp.close()

    try:
        generate_summarized_memory(
            log_date, sessions_path, output_path,
            force=True, model=model, backend=summarize_backend
        )

        if using_temp_file:
            content = output_path.read_text()
            click.echo(content)
        else:
            click.echo(f"Wrote summary to: {output_path}")

    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error generating summary: {e}", err=True)
        sys.exit(1)
    finally:
        # Clean up temp file regardless of success or failure
        if using_temp_file and output_path.exists():
            output_path.unlink()


@main.command()
@click.option("--date", "since_date", default=None, help="Show transitions since date (YYYY-MM-DD)")
@click.option("--output", default=None, help="Write JSON to file")
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
def transitions(since_date, output, sessions_dir):
    """List model transitions with context."""
    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    since_date_parsed = parse_date_str(since_date) if since_date else None

    trans_list = list(extract_transitions(sessions_path, since=since_date_parsed))

    if output:
        output_path = Path(output)
        write_transitions_json(trans_list, output_path)
        click.echo(f"Wrote {len(trans_list)} transitions to {output_path}")
    else:
        report = format_transitions_report(trans_list, since=since_date_parsed)
        click.echo(report)


@main.command()
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
@click.option("--memory-dir", default=None, help="Path to memory files directory")
def validate(sessions_dir, memory_dir):
    """Check memory files for consistency issues."""
    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()
    memory_path = Path(memory_dir) if memory_dir else get_default_memory_dir()

    if not memory_path.exists():
        click.echo(f"Error: Memory directory not found: {memory_path}", err=True)
        sys.exit(1)

    click.echo(f"Validating: {memory_path}")
    click.echo(f"Sessions reference: {sessions_path}")
    click.echo("")

    result = validate_memory_files(memory_path, sessions_path)
    report = format_validation_report(result)
    click.echo(report)

    if any(i.severity == 'error' for i in result['issues']):
        sys.exit(1)


@main.command()
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
@click.option("--memory-dir", default=None, help="Path to memory files directory")
def stats(sessions_dir, memory_dir):
    """Show coverage statistics."""
    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()
    memory_path = Path(memory_dir) if memory_dir else get_default_memory_dir()

    click.echo("Memory Sync Statistics")
    click.echo("=" * 50)
    click.echo("")

    click.echo("Session Logs")
    click.echo("-" * 30)

    if sessions_path.exists():
        session_files = find_session_files(sessions_path)
        click.echo(f"  Session files: {len(session_files)}")

        total_size = sum(f.stat().st_size for f in session_files)
        click.echo(f"  Total size: {total_size / 1024 / 1024:.1f} MB")

        first_date, last_date = get_date_range(sessions_path)
        if first_date and last_date:
            click.echo(f"  Date range: {first_date} to {last_date}")

        daily_activity = collect_daily_activity(sessions_path)
        total_messages = sum(d.message_count for d in daily_activity.values())
        total_user = sum(d.user_messages for d in daily_activity.values())
        total_assistant = sum(d.assistant_messages for d in daily_activity.values())
        total_tool = sum(d.tool_result_messages for d in daily_activity.values())

        click.echo(f"  Total messages: {total_messages}")
        click.echo(f"    User: {total_user}")
        click.echo(f"    Assistant: {total_assistant}")
        click.echo(f"    Tool results: {total_tool}")

        all_models: set[str] = set()
        for activity in daily_activity.values():
            all_models.update(activity.models_used)
        if all_models:
            click.echo(f"  Models used: {', '.join(sorted(all_models))}")

        trans_list = list(extract_transitions(sessions_path))
        trans_stats = get_transition_stats(trans_list)
        click.echo(f"  Model transitions: {trans_stats['total_transitions']}")

    else:
        click.echo(f"  Directory not found: {sessions_path}")

    click.echo("")

    click.echo("Memory Files")
    click.echo("-" * 30)

    if memory_path.exists():
        memory_files = get_memory_files(memory_path)
        click.echo(f"  Daily files: {len(memory_files)}")

        total_size = sum(f.stat().st_size for _, f in memory_files)
        click.echo(f"  Total size: {total_size / 1024:.1f} KB")

        if memory_files:
            first_mem = memory_files[0][0]
            last_mem = memory_files[-1][0]
            click.echo(f"  Date range: {first_mem} to {last_mem}")

        if sessions_path.exists():
            gaps = find_gaps(sessions_path, memory_path, exclude_today=True)
            click.echo(f"  Coverage: {gaps['coverage_pct']:.1f}%")
            click.echo(f"    Active days: {gaps['total_active_days']}")
            click.echo(f"    Covered days: {gaps.get('covered_days', 0)}")
            click.echo(f"    Missing: {len(gaps['missing_days'])}")
            click.echo(f"    Sparse: {len(gaps['sparse_days'])}")
    else:
        click.echo(f"  Directory not found: {memory_path}")

    click.echo("")


if __name__ == "__main__":
    main()
