"""LLM-based summarization for daily memory files.

Generates daily memory files in the narrative style used by OpenClaw agents,
organized by events/topics rather than abstract task categories.
"""

import os
from pathlib import Path
from datetime import date
from typing import Optional

from .models import Message, ModelTransition
from .parser import get_messages, get_model_transitions, get_compactions
from .sessions import find_session_files
from .sanitize import sanitize_content, validate_no_secrets
import sys


# =============================================================================
# Daily Memory Prompt (matches hand-written memory style)
# =============================================================================

MEMORY_SYSTEM_PROMPT = """You are an AI agent writing your daily memory file. This is YOUR journal - write in first person, capture what matters, and be authentic.

Your memory files help future-you maintain continuity across sessions. They're read days or weeks later to remember what happened, who was involved, and why things matter."""


DAILY_MEMORY_PROMPT = """Review this conversation from {date} ({day_name}) and write a daily memory entry.

STYLE GUIDE (based on how your memory files actually look):

1. **Organize by events/topics**, not abstract categories
   - Use descriptive headers: "## Trello Board Created" not "## Progress"
   - Add timestamps to headers when useful: "## Morning Session (9am-11am)"
   - Create sub-sections (###) for related details

2. **Mix narrative and bullets**
   - Narrative for context and "why it matters"
   - Bullets for lists, technical details, decisions

3. **Capture the human stuff**
   - Who was involved, what they said/wanted
   - Relationship context, emotional beats
   - Your own reactions, uncertainties, discoveries

4. **Preserve important technical details**
   - File names (not full paths to sensitive locations), URLs, IDs
   - Command names and error types (not full commands with arguments)
   - High-level technical decisions
   - These are critical for future-you

5. **End with forward-looking sections**
   - "## Open Threads" or "## Coming Up" for follow-ups
   - Optional closing note with personality

SECURITY - CRITICAL:
- **NEVER include API keys, tokens, passwords, or secrets** of any kind
- **NEVER include connection strings** with embedded credentials
- **NEVER include configuration values** that could be secrets (keys, tokens, passwords)
- **NEVER include environment variable values** for sensitive vars (API_KEY, TOKEN, SECRET, PASSWORD)
- **NEVER include full command arguments** that might contain credentials
- If something looks like it might be a secret, **DO NOT include it**
- When in doubt, describe what happened at a high level without the actual values

EXAMPLE STRUCTURE (adapt to what actually happened):

```markdown
# {date} ({day_name})

## [Major Event/Topic 1]
What happened, why it matters, who was involved.
- Key detail
- Technical specifics preserved exactly

## [Major Event/Topic 2]
...

## [Project Name] Updates
- What was accomplished
- Decisions made: **[Decision]** - rationale

## People & Context
- [Person]: relevant context learned today

## Open Threads
- Thing to follow up on
- Question to revisit

---

*[Brief closing note - vibes, status, personality]*
```

{transitions_note}

NOW WRITE THE MEMORY for {date}. Be thorough (500-1500 words). Capture what future-you needs to know.

---

CONVERSATION ({message_count} messages):

{conversation}"""


def prepare_conversation_text(
    messages: list[Message],
    max_chars: int = 100000,
    include_tool_results: bool = True
) -> str:
    """
    Prepare conversation text for summarization.
    
    Sanitizes all message content to remove secrets before formatting.
    """
    lines = []
    total_chars = 0

    for msg in messages:
        time_str = msg.timestamp.strftime('%H:%M')

        text = msg.text_content.strip()
        if not text:
            continue

        # CRITICAL: Sanitize content before any processing
        text = sanitize_content(text)

        # Truncate very long messages
        if len(text) > 2000:
            text = text[:2000] + "... [truncated]"

        # Format based on role
        if msg.role == 'user':
            line = f"[{time_str}] USER: {text}"
        elif msg.role == 'assistant':
            model_info = f" ({msg.model})" if msg.model else ""
            extras = []
            if msg.has_thinking:
                extras.append("thinking")
            if msg.has_tool_calls:
                extras.append("tool calls")
            extras_str = f" [{', '.join(extras)}]" if extras else ""
            line = f"[{time_str}] ASSISTANT{model_info}{extras_str}: {text}"
        else:  # toolResult
            # Keep tool results shorter
            text = text[:500] + "..." if len(text) > 500 else text
            line = f"[{time_str}] TOOL RESULT: {text}"

        if total_chars + len(line) > max_chars:
            remaining = len(messages) - len(lines)
            lines.append(f"\n... [{remaining} more messages truncated]")
            break

        lines.append(line)
        total_chars += len(line)

    return '\n\n'.join(lines)


def format_transitions_note(transitions: list[ModelTransition]) -> str:
    """Format transitions as a note for the prompt."""
    if not transitions:
        return "MODEL TRANSITIONS: None today."

    lines = ["MODEL TRANSITIONS today:"]
    for t in transitions:
        time_str = t.timestamp.strftime('%H:%M')
        from_str = t.from_model or "start"
        to_str = f"{t.provider}/{t.to_model}" if t.provider else t.to_model
        lines.append(f"  {time_str}: {from_str} → {to_str}")

    lines.append("(Include these in your memory if relevant to context)")
    return '\n'.join(lines)


def summarize_with_anthropic(
    log_date: date,
    messages: list[Message],
    transitions: list[ModelTransition],
    api_key: Optional[str] = None,
    model: str = "claude-sonnet-4-20250514",
    existing_content: Optional[str] = None
) -> str:
    """
    Summarize a day's conversation using the Anthropic API.

    Args:
        log_date: The date being summarized
        messages: List of messages from that day
        transitions: Model transitions from that day
        api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        model: Model to use for summarization
        existing_content: Optional existing memory file content to incorporate

    Returns:
        Generated summary text
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropic package not installed. "
            "Install with: pip install anthropic"
        )

    api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError(
            "No API key provided. Set ANTHROPIC_API_KEY environment variable "
            "or pass api_key parameter."
        )

    # Prepare conversation text
    conversation = prepare_conversation_text(messages)

    # Format transitions note
    transitions_note = format_transitions_note(transitions)

    # Format prompt
    prompt = DAILY_MEMORY_PROMPT.format(
        date=log_date.strftime('%Y-%m-%d'),
        day_name=log_date.strftime('%A'),
        message_count=len(messages),
        transitions_note=transitions_note,
        conversation=conversation
    )

    # Include existing content if provided
    if existing_content:
        prompt += f"""

---

EXISTING MEMORY FILE (incorporate important hand-written content):
{existing_content}

IMPORTANT: The above is an existing memory file for this date. Please incorporate any important
hand-written notes, insights, or context that isn't captured in the new conversation data.
Merge the existing content's key points into your new summary rather than losing them."""

    # Call API
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=MEMORY_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.content[0].text


def generate_summarized_memory(
    log_date: date,
    sessions_dir: Path,
    output_path: Path,
    force: bool = False,
    preserve: bool = False,
    api_key: Optional[str] = None,
    model: str = "claude-sonnet-4-20250514"
) -> str:
    """
    Generate a daily memory file using LLM summarization.

    Args:
        log_date: The date to generate memory for
        sessions_dir: Path to session JSONL files
        output_path: Path to write the memory file
        force: Overwrite existing file if True
        preserve: Pass existing content to LLM to incorporate
        api_key: Anthropic API key
        model: Model to use for summarization

    Returns:
        Path to the created file as string
    """
    # Read existing content for preservation
    existing_content = None
    if output_path.exists():
        if not force and not preserve:
            raise FileExistsError(f"File already exists: {output_path}. Use --force to overwrite.")
        if preserve:
            existing_content = output_path.read_text()

    # Collect data for this date
    messages: list[Message] = []
    transitions: list[ModelTransition] = []

    for session_file in find_session_files(sessions_dir):
        for msg in get_messages(session_file, date_filter=log_date):
            messages.append(msg)

        for trans in get_model_transitions(session_file):
            if trans.timestamp.date() == log_date:
                transitions.append(trans)

    if not messages:
        raise ValueError(f"No messages found for {log_date}")

    # Sort by timestamp
    messages.sort(key=lambda m: m.timestamp)
    transitions.sort(key=lambda t: t.timestamp)

    # Generate summary using LLM
    content = summarize_with_anthropic(
        log_date=log_date,
        messages=messages,
        transitions=transitions,
        api_key=api_key,
        model=model,
        existing_content=existing_content
    )

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
                "Refusing to write file. This indicates the LLM included secrets despite instructions."
            )
        
        print("Content sanitized successfully.", file=sys.stderr)

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    output_path.write_text(content)

    return str(output_path)
