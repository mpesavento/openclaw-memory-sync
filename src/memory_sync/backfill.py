"""Memory file generation from session logs."""

from pathlib import Path
from datetime import date
from typing import Optional, Tuple
import re

from .models import Message, ModelTransition
from .parser import get_messages, get_model_transitions, get_compactions
from .sessions import find_session_files
from .compare import find_gaps
from .sanitize import sanitize_content, validate_no_secrets
import sys


# Markers for identifying auto-generated content
AUTO_GENERATED_HEADER_PATTERN = r'\*Auto-generated from \d+ session messages\*'
AUTO_GENERATED_FOOTER = '*Review and edit this draft to capture what\'s actually important.*'


def extract_preserved_content(existing_content: str) -> Tuple[str, str]:
    """
    Extract hand-written content from an existing memory file.

    Returns:
        Tuple of (auto_generated_section, hand_written_section)

    Hand-written content is anything after the footer marker.
    """
    if not existing_content:
        return "", ""

    # Find the footer marker
    footer_pos = existing_content.find(AUTO_GENERATED_FOOTER)

    if footer_pos == -1:
        # No footer marker - treat entire content as hand-written
        return "", existing_content

    # Content after footer marker (skip the marker itself)
    after_footer = existing_content[footer_pos + len(AUTO_GENERATED_FOOTER):]

    # Strip leading whitespace/newlines but preserve the rest
    hand_written = after_footer.lstrip('\n')

    # Auto-generated is everything up to and including footer
    auto_generated = existing_content[:footer_pos + len(AUTO_GENERATED_FOOTER)]

    return auto_generated, hand_written


def extract_topics(messages: list[Message], max_topics: int = 10) -> list[str]:
    """
    Extract main topics from messages using simple keyword analysis.

    Looks for common patterns in user questions and assistant responses.
    """
    # Common words to filter out
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

    # Extract words from user messages (more indicative of topics)
    word_counts: dict[str, int] = {}
    for msg in messages:
        if msg.role != 'user':
            continue

        # Simple tokenization
        words = re.findall(r'\b[a-zA-Z]{4,}\b', msg.text_content.lower())
        for word in words:
            if word not in stopwords:
                word_counts[word] = word_counts.get(word, 0) + 1

    # Get top words
    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    topics = [word.capitalize() for word, count in sorted_words[:max_topics] if count >= 2]

    return topics


def extract_key_exchanges(messages: list[Message], max_exchanges: int = 10) -> list[dict]:
    """
    Extract key user questions and responses.

    Returns list of dicts with 'time', 'user_excerpt', 'response_excerpt'.
    """
    exchanges = []

    # Find user messages that look like questions or requests
    question_patterns = [
        r'\?$',  # Ends with question mark
        r'^(can|could|would|will|how|what|why|when|where|who|is|are|do|does)\b',
        r'^(help|explain|show|tell|create|make|fix|implement|add|remove|update)\b',
    ]

    for i, msg in enumerate(messages):
        if msg.role != 'user':
            continue

        text = msg.text_content.strip()
        if not text:
            continue

        # Check if it looks like a question/request
        is_question = any(re.search(p, text, re.IGNORECASE) for p in question_patterns)
        if not is_question and len(text) < 20:
            continue  # Skip short non-questions

        # Find the next assistant response
        response_text = ""
        for j in range(i + 1, min(i + 5, len(messages))):
            if messages[j].role == 'assistant':
                response_text = messages[j].text_content.strip()
                break

        # Create excerpt (first 100 chars) and sanitize
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
    """
    Extract decisions and action items from assistant messages.

    Looks for patterns like "I will...", "Let's...", tool calls, etc.
    """
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

        # Look for decision patterns
        for pattern in decision_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                decision = match.strip()
                if len(decision) > 10 and len(decision) < 200:
                    # Sanitize decision text before adding
                    decision = sanitize_content(decision)
                    decisions.append(decision)

        # Note tool calls as actions
        if msg.has_tool_calls:
            decisions.append("Executed tool/command")

        if len(decisions) >= max_decisions:
            break

    # Deduplicate while preserving order
    seen = set()
    unique_decisions = []
    for d in decisions:
        d_lower = d.lower()
        if d_lower not in seen:
            seen.add(d_lower)
            unique_decisions.append(d)

    return unique_decisions[:max_decisions]


def format_transitions(transitions: list[ModelTransition]) -> list[dict]:
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
    """
    Render daily memory file content from context dict.

    Uses simple string formatting (no Jinja2 required).
    """
    lines = []

    # Header
    lines.append(f"# {context['date']} ({context['day_name']})")
    lines.append("")
    lines.append(f"*Auto-generated from {context['message_count']} session messages*")
    lines.append("")

    # Compaction summary if available (sanitized)
    if context.get('compaction_summary'):
        lines.append("## Context Summary")
        sanitized_summary = sanitize_content(context['compaction_summary'])
        lines.append(sanitized_summary)
        lines.append("")

    # Topics
    if context.get('topics'):
        lines.append("## Topics Covered")
        for topic in context['topics']:
            lines.append(f"- {topic}")
        lines.append("")

    # Key exchanges
    if context.get('key_exchanges'):
        lines.append("## Key Exchanges")
        for exchange in context['key_exchanges']:
            lines.append(f"- [{exchange['time']}] {exchange['user_excerpt']}")
        lines.append("")

    # Decisions
    if context.get('decisions'):
        lines.append("## Decisions/Actions")
        for decision in context['decisions']:
            lines.append(f"- {decision}")
        lines.append("")

    # Model transitions
    if context.get('transitions'):
        lines.append("## Model Transitions")
        for trans in context['transitions']:
            lines.append(f"- {trans['time']}: {trans['from']} -> {trans['to']}")
        lines.append("")

    # Footer
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
    """
    Generate a daily memory file from session logs.

    Args:
        log_date: The date to generate memory for
        sessions_dir: Path to session JSONL files
        output_path: Path to write the memory file
        force: Overwrite existing file if True
        preserve: Preserve hand-written content from existing file

    Returns:
        Path to the created file as string

    Raises:
        FileExistsError: If file exists and force=False
    """
    # Read existing content for preservation
    existing_content = ""
    if output_path.exists():
        if not force and not preserve:
            raise FileExistsError(f"File already exists: {output_path}. Use --force to overwrite.")
        if preserve:
            existing_content = output_path.read_text()

    # Collect data for this date
    messages: list[Message] = []
    transitions: list[ModelTransition] = []
    compaction_summary: Optional[str] = None

    for session_file in find_session_files(sessions_dir):
        # Get messages for this date
        for msg in get_messages(session_file, date_filter=log_date):
            messages.append(msg)

        # Get transitions for this date
        for trans in get_model_transitions(session_file):
            if trans.timestamp.date() == log_date:
                transitions.append(trans)

        # Get compaction summary (use the most recent one)
        for comp in get_compactions(session_file):
            if comp['timestamp'] and comp['timestamp'].date() == log_date:
                if comp.get('summary'):
                    compaction_summary = comp['summary']

    if not messages:
        raise ValueError(f"No messages found for {log_date}")

    # Sort messages by timestamp
    messages.sort(key=lambda m: m.timestamp)
    transitions.sort(key=lambda t: t.timestamp)

    # Extract content
    topics = extract_topics(messages)
    key_exchanges = extract_key_exchanges(messages)
    decisions = extract_decisions(messages)

    # Render template
    content = render_daily_template({
        'date': log_date.strftime('%Y-%m-%d'),
        'day_name': log_date.strftime('%A'),
        'message_count': len(messages),
        'topics': topics,
        'key_exchanges': key_exchanges,
        'decisions': decisions,
        'transitions': format_transitions(transitions),
        'compaction_summary': compaction_summary,
    })

    # Preserve hand-written content if requested
    if preserve and existing_content:
        _, hand_written = extract_preserved_content(existing_content)
        if hand_written:
            # Sanitize hand-written content too (in case it was manually added before sanitization was implemented)
            hand_written = sanitize_content(hand_written)
            content = content + "\n\n" + hand_written

    # CRITICAL: Validate no secrets before writing
    is_valid, violations = validate_no_secrets(content)
    
    if not is_valid:
        print(f"Warning: Generated content contains potential secrets: {violations}", file=sys.stderr)
        print("Attempting to sanitize...", file=sys.stderr)
        
        # Fallback: sanitize the output
        content = sanitize_content(content)
        
        # Re-validate
        is_valid, violations = validate_no_secrets(content)
        
        if not is_valid:
            # Still has secrets after sanitization - this is a critical error
            raise ValueError(
                f"Generated memory file still contains secrets after sanitization: {violations}. "
                "Refusing to write file."
            )
        
        print("Content sanitized successfully.", file=sys.stderr)

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    output_path.write_text(content)

    return str(output_path)


def backfill_all_missing(
    sessions_dir: Path,
    memory_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    preserve: bool = False
) -> dict:
    """
    Backfill all missing daily memory files.

    Returns dict with:
    - created: list of created file paths
    - skipped: list of skipped dates (already exist)
    - errors: list of (date, error_message) tuples
    """
    gaps = find_gaps(sessions_dir, memory_dir)

    created = []
    skipped = []
    errors = []

    # Process missing days
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

    # Optionally process sparse days too if force is set
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
