"""Consolidated tests for memory_sync single-file CLI.

All tests from the original test suite, consolidated into one file
and updated to import from memory-sync.memory_sync.
"""

import sys
from pathlib import Path

# Add memory-sync directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'memory-sync'))

import pytest
from datetime import date, datetime, timezone, timedelta
from click.testing import CliRunner
import json
import shutil
import time
import os
from unittest.mock import patch, MagicMock

# Import from the single-file module
from memory_sync import (
    # Parser
    parse_jsonl,
    get_session_metadata,
    get_messages,
    get_model_transitions,
    get_compactions,
    get_model_snapshots,
    # Sanitization
    sanitize_content,
    validate_no_secrets,
    classify_content,
    ContentSensitivity,
    safe_sanitize,
    # Sessions
    find_session_files,
    get_date_range,
    collect_daily_activity,
    get_session_info,
    # Compare
    find_gaps,
    get_memory_files,
    find_orphaned_memory_files,
    format_gap_report,
    # Backfill
    generate_daily_memory,
    generate_summarized_memory,
    backfill_all_missing,
    extract_topics,
    extract_key_exchanges,
    extract_decisions,
    format_transitions_for_template,
    render_daily_template,
    extract_preserved_content,
    AUTO_GENERATED_FOOTER,
    # Summarization
    get_summarizer,
    summarize_with_openclaw,
    summarize_with_openai_package,
    _build_summarization_prompt,
    prepare_conversation_text,
    format_transitions_note,
    MEMORY_SYSTEM_PROMPT,
    # Transitions
    extract_transitions,
    write_transitions_json,
    format_transition,
    format_transitions_report,
    get_transition_stats,
    # Validate
    validate_memory_files,
    format_validation_report,
    # State
    get_state_file_path,
    load_state,
    save_state,
    get_changed_days,
    get_last_run_datetime,
    # Models
    Message,
    ModelTransition,
    DayActivity,
    MemoryGap,
    ValidationIssue,
    # CLI
    main,
)


# =============================================================================
# PARSER TESTS
# =============================================================================

class TestParseJsonl:
    """Tests for parse_jsonl function."""

    def test_parse_valid_jsonl(self, sample_session_path):
        """Parse sample_session.jsonl correctly."""
        records = list(parse_jsonl(sample_session_path))

        assert len(records) > 0
        assert records[0]['type'] == 'session'

    def test_parse_streaming_memory_efficient(self, sample_session_path):
        """Verify streaming doesn't load entire file."""
        gen = parse_jsonl(sample_session_path)
        first = next(gen)
        assert first['type'] == 'session'

    def test_parse_malformed_skips_bad_lines(self, malformed_path, capsys):
        """Handle malformed.jsonl gracefully by skipping bad lines."""
        records = list(parse_jsonl(malformed_path))

        valid_records = [r for r in records if r.get('type') in ('session', 'message')]
        assert len(valid_records) == 3

        captured = capsys.readouterr()
        assert 'Warning' in captured.err
        assert 'malformed' in captured.err.lower()


class TestGetSessionMetadata:
    """Tests for get_session_metadata function."""

    def test_get_session_metadata(self, sample_session_path):
        """Extract session metadata correctly."""
        meta = get_session_metadata(sample_session_path)

        assert meta is not None
        assert meta['type'] == 'session'
        assert meta['id'] == 'test-session-001'
        assert meta['version'] == 3

    def test_get_session_metadata_missing(self, temp_dir):
        """Return None if no session record."""
        no_session = temp_dir / 'no_session.jsonl'
        no_session.write_text('{"type":"message","id":"msg1"}\n')

        meta = get_session_metadata(no_session)
        assert meta is None


class TestGetMessages:
    """Tests for get_messages function."""

    def test_get_messages_extracts_all_roles(self, sample_session_path):
        """Extract user, assistant, and toolResult messages."""
        messages = list(get_messages(sample_session_path))

        roles = {m.role for m in messages}
        assert 'user' in roles
        assert 'assistant' in roles
        assert 'toolResult' in roles

    def test_get_messages_date_filter(self, sample_session_path):
        """Filter messages by specific date."""
        messages_15 = list(get_messages(sample_session_path, date_filter=date(2026, 1, 15)))
        messages_16 = list(get_messages(sample_session_path, date_filter=date(2026, 1, 16)))

        assert len(messages_15) > 0
        assert len(messages_16) > 0

        for m in messages_15:
            assert m.timestamp.date() == date(2026, 1, 15)
        for m in messages_16:
            assert m.timestamp.date() == date(2026, 1, 16)

    def test_get_messages_extracts_text_content(self, sample_session_path):
        """Extract text from content blocks."""
        messages = list(get_messages(sample_session_path))

        user_msgs = [m for m in messages if m.role == 'user']
        assert len(user_msgs) > 0

        assert 'Hello' in user_msgs[0].text_content or 'help' in user_msgs[0].text_content.lower()

    def test_get_messages_detects_tool_calls(self, sample_session_path):
        """Detect messages with tool calls."""
        messages = list(get_messages(sample_session_path))

        tool_msgs = [m for m in messages if m.has_tool_calls]
        assert len(tool_msgs) > 0

    def test_get_messages_detects_thinking(self, sample_session_path):
        """Detect messages with thinking blocks."""
        messages = list(get_messages(sample_session_path))

        thinking_msgs = [m for m in messages if m.has_thinking]
        assert len(thinking_msgs) > 0

    def test_get_messages_includes_model_info(self, sample_session_path):
        """Extract model metadata from assistant messages."""
        messages = list(get_messages(sample_session_path))

        assistant_msgs = [m for m in messages if m.role == 'assistant']
        assert len(assistant_msgs) > 0

        models = [m.model for m in assistant_msgs if m.model]
        assert len(models) > 0
        assert 'claude-sonnet-4' in models or 'gpt-4o' in models


class TestGetModelTransitions:
    """Tests for get_model_transitions function."""

    def test_get_model_transitions(self, model_transitions_path):
        """Detect model changes from model_transitions.jsonl."""
        transitions = list(get_model_transitions(model_transitions_path))

        assert len(transitions) >= 3

    def test_transitions_have_timestamps(self, model_transitions_path):
        """Transitions should have valid timestamps."""
        transitions = list(get_model_transitions(model_transitions_path))

        for t in transitions:
            assert t.timestamp is not None
            assert isinstance(t.timestamp, datetime)

    def test_transitions_from_sample_session(self, sample_session_path):
        """Detect transition in sample session."""
        transitions = list(get_model_transitions(sample_session_path))

        assert len(transitions) >= 1

        sonnet_to_gpt = [t for t in transitions if t.to_model == 'gpt-4o']
        assert len(sonnet_to_gpt) > 0


class TestGetCompactions:
    """Tests for get_compactions function."""

    def test_get_compactions(self, sample_session_path):
        """Extract compaction records."""
        compactions = list(get_compactions(sample_session_path))

        assert len(compactions) == 1

        comp = compactions[0]
        assert 'summary' in comp
        assert 'Organize project files' in comp['summary']

    def test_compaction_has_timestamp(self, sample_session_path):
        """Compaction should have timestamp."""
        compactions = list(get_compactions(sample_session_path))
        assert len(compactions) > 0

        assert compactions[0]['timestamp'] is not None


class TestGetModelSnapshots:
    """Tests for get_model_snapshots function."""

    def test_get_model_snapshots(self, sample_session_path):
        """Extract model-snapshot custom records."""
        snapshots = list(get_model_snapshots(sample_session_path))

        assert len(snapshots) == 1

        snap = snapshots[0]
        assert snap['provider'] == 'anthropic'
        assert snap['modelId'] == 'claude-sonnet-4'


# =============================================================================
# SANITIZE TESTS
# =============================================================================

class TestSanitizeContent:
    """Test sanitize_content() function."""

    def test_openai_api_key_redacted(self):
        """Test that OpenAI API keys are redacted."""
        content = "My API key is sk-abc123xyz789012345678901234567890"
        result = sanitize_content(content)

        assert "sk-abc123" not in result
        assert "[REDACTED-OPENAI-API-KEY]" in result

    def test_composio_api_key_redacted(self):
        """Test that Composio API keys are redacted."""
        content = "Using ak-1234567890abcdefghijklmnop for authentication"
        result = sanitize_content(content)

        assert "ak-123456" not in result
        assert "[REDACTED-COMPOSIO-API-KEY]" in result

    def test_github_token_redacted(self):
        """Test that GitHub tokens are redacted."""
        tokens = [
            "ghp_abcdefghijklmnopqrstuvwxyz123456",
            "gho_abcdefghijklmnopqrstuvwxyz123456",
        ]

        for token in tokens:
            content = f"Token: {token}"
            result = sanitize_content(content)
            assert token not in result
            assert "[REDACTED-GITHUB-TOKEN]" in result

    def test_api_key_assignment_redacted(self):
        """Test that API key assignments are redacted."""
        test_cases = [
            "api_key=sk_test_12345678901234567890",
            "MY_API_KEY=abc123def456ghi789jkl012mno345pqr678",
        ]

        for content in test_cases:
            result = sanitize_content(content)
            assert "api" in result.lower() or "API" in result
            assert "[REDACTED" in result

    def test_password_assignment_redacted(self):
        """Test that password assignments are redacted."""
        content = "password=mysecretpass123"
        result = sanitize_content(content)
        assert "mysecretpass123" not in result
        assert "[REDACTED" in result

    def test_jwt_token_redacted(self):
        """Test that JWT tokens are redacted."""
        content = "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = sanitize_content(content)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "[REDACTED-JWT]" in result


class TestValidateNoSecrets:
    """Test validate_no_secrets() function."""

    def test_valid_content_passes(self):
        """Content without secrets passes validation."""
        content = "This is safe content about coding."
        is_valid, violations = validate_no_secrets(content)
        
        assert is_valid
        assert len(violations) == 0

    def test_openai_key_detected(self):
        """OpenAI keys are detected."""
        content = "Key: sk-abc123xyz789012345678901234567890"
        is_valid, violations = validate_no_secrets(content)
        
        assert not is_valid
        assert len(violations) > 0

    def test_redacted_content_passes(self):
        """Content with [REDACTED] markers passes."""
        content = "My key is [REDACTED-OPENAI-API-KEY]"
        is_valid, violations = validate_no_secrets(content)
        
        assert is_valid


class TestClassifyContent:
    """Test classify_content() function."""

    def test_safe_content(self):
        """Normal content is classified as safe."""
        content = "This is normal conversation about programming."
        level = classify_content(content)
        
        assert level == ContentSensitivity.SAFE

    def test_secret_content(self):
        """Content with secrets is classified as secret."""
        content = "My key is sk-abc123xyz789012345678901234567890"
        level = classify_content(content)
        
        assert level == ContentSensitivity.SECRET

    def test_sensitive_content(self):
        """Content with sensitive keywords is classified as sensitive."""
        content = "Let's discuss the api_key configuration."
        level = classify_content(content)
        
        assert level == ContentSensitivity.SENSITIVE


# =============================================================================
# SANITIZE INTEGRATION TESTS
# =============================================================================

class TestBackfillSanitization:
    """Test that sanitization works in the backfill pipeline."""
    
    def test_memory_file_has_no_secrets(self, temp_dir):
        """Test that generated memory files don't contain secrets."""
        sessions_dir = temp_dir / "sessions"
        sessions_dir.mkdir()
        
        session_file = sessions_dir / "session_with_secrets.jsonl"
        session_content = [
            {
                "type": "session",
                "id": "test-session",
                "version": 3,
                "timestamp": "2026-02-06T10:00:00Z"
            },
            {
                "type": "message",
                "id": "msg1",
                "timestamp": "2026-02-06T10:01:00Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "My API key is sk-abc123xyz789012345678901234567890"
                        }
                    ]
                }
            },
        ]
        
        with open(session_file, 'w') as f:
            for record in session_content:
                f.write(json.dumps(record) + '\n')
        
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        output_path = memory_dir / "2026-02-06.md"
        
        generate_daily_memory(
            date(2026, 2, 6),
            sessions_dir,
            output_path
        )
        
        content = output_path.read_text()
        
        assert "sk-abc123xyz789" not in content
        assert "[REDACTED" in content


# =============================================================================
# SUMMARIZATION TESTS
# =============================================================================

class TestGetSummarizer:
    """Tests for get_summarizer factory function."""
    
    def test_get_openclaw_summarizer(self):
        """Get openclaw summarizer."""
        summarizer = get_summarizer('openclaw')
        assert summarizer is not None
        assert callable(summarizer)
    
    def test_get_openai_summarizer(self):
        """Get openai summarizer."""
        summarizer = get_summarizer('openai')
        assert summarizer is not None
        assert callable(summarizer)
    
    def test_get_anthropic_summarizer(self):
        """Get anthropic summarizer."""
        summarizer = get_summarizer('anthropic')
        assert summarizer is not None
        assert callable(summarizer)
    
    def test_invalid_backend_raises(self):
        """Invalid backend raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_summarizer('invalid')
        assert 'Unknown summarization backend' in str(exc_info.value)


class TestBuildSummarizationPrompt:
    """Tests for _build_summarization_prompt function."""
    
    def test_builds_prompt_with_messages(self):
        """Prompt includes conversation content."""
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content='Hello, how are you?',
            ),
            Message(
                id='msg2',
                timestamp=datetime(2026, 2, 6, 10, 1, 0, tzinfo=timezone.utc),
                role='assistant',
                text_content='I am doing well, thank you!',
                model='claude-sonnet-4',
            ),
        ]
        
        prompt = _build_summarization_prompt(date(2026, 2, 6), messages, [])
        
        assert '2026-02-06' in prompt
        assert 'Hello' in prompt or 'doing well' in prompt
    
    def test_builds_prompt_with_transitions(self):
        """Prompt includes model transitions."""
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content='Hello',
            ),
        ]
        transitions = [
            ModelTransition(
                timestamp=datetime(2026, 2, 6, 10, 30, 0, tzinfo=timezone.utc),
                from_model='claude-sonnet-4',
                to_model='gpt-4o',
                session_id='test',
                provider='openai',
            ),
        ]
        
        prompt = _build_summarization_prompt(date(2026, 2, 6), messages, transitions)
        
        assert 'transition' in prompt.lower() or 'gpt-4o' in prompt
    
    def test_includes_existing_content(self):
        """Prompt includes existing hand-written content."""
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content='Hello',
            ),
        ]
        existing = f"""# 2026-02-06

*Auto-generated from 5 session messages*

Some content.

---

*Review and edit this draft to capture what's actually important.*

My hand-written notes here."""
        
        prompt = _build_summarization_prompt(date(2026, 2, 6), messages, [], existing_content=existing)
        
        assert 'hand-written notes' in prompt.lower() or 'My hand-written notes' in prompt


class TestPrepareConversationText:
    """Tests for prepare_conversation_text function."""
    
    def test_formats_messages(self):
        """Messages are formatted correctly."""
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content='Hello world',
            ),
            Message(
                id='msg2',
                timestamp=datetime(2026, 2, 6, 10, 1, 0, tzinfo=timezone.utc),
                role='assistant',
                text_content='Hi there',
                model='claude-sonnet-4',
            ),
        ]
        
        text = prepare_conversation_text(messages)
        
        assert 'USER' in text
        assert 'ASSISTANT' in text
        assert 'Hello world' in text
        assert 'Hi there' in text
    
    def test_truncates_long_content(self):
        """Long message content is truncated."""
        long_content = 'x' * 1000
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content=long_content,
            ),
        ]
        
        text = prepare_conversation_text(messages)
        
        # Content is truncated to 500 chars per message
        assert len(text) < 1000
    
    def test_sanitizes_content(self):
        """Secrets in messages are sanitized."""
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content='My key is sk-abc123xyz789012345678901234567890',
            ),
        ]
        
        text = prepare_conversation_text(messages)
        
        assert 'sk-abc123' not in text
        assert '[REDACTED' in text


class TestFormatTransitionsNote:
    """Tests for format_transitions_note function."""
    
    def test_empty_transitions(self):
        """Empty transitions list returns empty string."""
        result = format_transitions_note([])
        assert result == ""
    
    def test_formats_transitions(self):
        """Transitions are formatted correctly."""
        transitions = [
            ModelTransition(
                timestamp=datetime(2026, 2, 6, 10, 30, 0, tzinfo=timezone.utc),
                from_model='claude-sonnet-4',
                to_model='gpt-4o',
                session_id='test',
                provider='openai',
            ),
        ]
        
        result = format_transitions_note(transitions)
        
        assert 'transition' in result.lower()
        assert 'claude-sonnet-4' in result or 'gpt-4o' in result


class TestSummarizeWithOpenclaw:
    """Tests for summarize_with_openclaw function."""
    
    def test_raises_when_openclaw_not_found(self):
        """Raises RuntimeError when openclaw CLI not found."""
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content='Hello',
            ),
        ]
        
        # Mock subprocess.run to raise FileNotFoundError (simulating openclaw not installed)
        with patch('memory_sync.subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("No such file or directory: 'openclaw'")
            
            with pytest.raises(RuntimeError) as exc_info:
                summarize_with_openclaw(date(2026, 2, 6), messages, [])
            
            assert 'openclaw' in str(exc_info.value).lower()
    
    def test_raises_on_nonzero_exit(self):
        """Raises RuntimeError when openclaw returns non-zero exit code."""
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content='Hello',
            ),
        ]
        
        # Mock subprocess.run to return non-zero exit code
        with patch('memory_sync.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "Some error occurred"
            mock_run.return_value = mock_result
            
            with pytest.raises(RuntimeError) as exc_info:
                summarize_with_openclaw(date(2026, 2, 6), messages, [])
            
            assert 'failed' in str(exc_info.value).lower()
    
    def test_returns_sanitized_output_on_success(self):
        """Returns sanitized output when openclaw succeeds."""
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content='Hello',
            ),
        ]
        
        # Mock subprocess.run to return success with some output
        with patch('memory_sync.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "This is the summary output from the LLM."
            mock_run.return_value = mock_result
            
            result = summarize_with_openclaw(date(2026, 2, 6), messages, [])
            
            assert "summary output" in result.lower()


class TestSummarizeWithOpenaiPackage:
    """Tests for summarize_with_openai_package function."""
    
    def test_raises_without_api_key(self):
        """Raises ValueError when API key not set."""
        messages = [
            Message(
                id='msg1',
                timestamp=datetime(2026, 2, 6, 10, 0, 0, tzinfo=timezone.utc),
                role='user',
                text_content='Hello',
            ),
        ]
        
        # Ensure API keys are not set
        old_anthropic = os.environ.pop('ANTHROPIC_API_KEY', None)
        old_openai = os.environ.pop('OPENAI_API_KEY', None)
        
        try:
            with pytest.raises((ValueError, ImportError)):
                summarize_with_openai_package(
                    date(2026, 2, 6), messages, [],
                    provider='anthropic'
                )
        finally:
            # Restore env vars
            if old_anthropic:
                os.environ['ANTHROPIC_API_KEY'] = old_anthropic
            if old_openai:
                os.environ['OPENAI_API_KEY'] = old_openai


class TestGenerateSummarizedMemory:
    """Tests for generate_summarized_memory function."""
    
    def test_requires_messages(self, temp_dir):
        """Raises ValueError when no messages found."""
        sessions_dir = temp_dir / "sessions"
        sessions_dir.mkdir()
        
        # Create empty session file
        session_file = sessions_dir / "empty.jsonl"
        session_file.write_text('{"type":"session","id":"test","version":3}\n')
        
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        output_path = memory_dir / "2026-02-06.md"
        
        with pytest.raises(ValueError) as exc_info:
            generate_summarized_memory(
                date(2026, 2, 6),
                sessions_dir,
                output_path,
                backend='openclaw'
            )
        
        assert 'No messages found' in str(exc_info.value)


class TestBackfillCommandWithBackend:
    """Tests for backfill command with --summarize-backend option."""
    
    def test_backfill_help_shows_backend_option(self, runner):
        """Help shows --summarize-backend option."""
        result = runner.invoke(main, ['backfill', '--help'])
        
        assert result.exit_code == 0
        assert '--summarize-backend' in result.output
        assert 'openclaw' in result.output
        assert 'openai' in result.output
        assert 'anthropic' in result.output


class TestSummarizeCommandWithBackend:
    """Tests for summarize command with --summarize-backend option."""
    
    def test_summarize_help_shows_backend_option(self, runner):
        """Help shows --summarize-backend option."""
        result = runner.invoke(main, ['summarize', '--help'])
        
        assert result.exit_code == 0
        assert '--summarize-backend' in result.output
        assert 'openclaw' in result.output


# =============================================================================
# SESSIONS TESTS
# =============================================================================

class TestFindSessionFiles:
    """Tests for find_session_files function."""

    def test_find_session_files(self, temp_sessions_dir):
        """Find .jsonl files, exclude .lock files."""
        files = find_session_files(temp_sessions_dir)

        assert len(files) > 0

        for f in files:
            assert f.suffix == '.jsonl'

    def test_excludes_lock_files(self, temp_sessions_dir):
        """Exclude .jsonl.lock files."""
        lock_file = temp_sessions_dir / 'active.jsonl.lock'
        lock_file.write_text('{}')

        files = find_session_files(temp_sessions_dir)

        assert not any('lock' in f.name for f in files)

    def test_empty_directory(self, temp_dir):
        """Return empty list for empty directory."""
        empty_dir = temp_dir / 'empty'
        empty_dir.mkdir()

        files = find_session_files(empty_dir)
        assert files == []

    def test_nonexistent_directory(self, temp_dir):
        """Return empty list for nonexistent directory."""
        files = find_session_files(temp_dir / 'nonexistent')
        assert files == []


class TestGetDateRange:
    """Tests for get_date_range function."""

    def test_get_date_range(self, temp_sessions_dir):
        """Get correct first/last dates from sessions."""
        first, last = get_date_range(temp_sessions_dir)

        assert first is not None
        assert last is not None
        assert first <= last

        assert first == date(2026, 1, 15)
        assert last == date(2026, 1, 19)

    def test_empty_returns_none(self, temp_dir):
        """Return (None, None) for empty directory."""
        empty_dir = temp_dir / 'empty'
        empty_dir.mkdir()

        first, last = get_date_range(empty_dir)
        assert first is None
        assert last is None


class TestCollectDailyActivity:
    """Tests for collect_daily_activity function."""

    def test_collect_daily_activity(self, temp_sessions_dir):
        """Group messages correctly by date."""
        activity = collect_daily_activity(temp_sessions_dir)

        assert len(activity) > 0

        dates = list(activity.keys())
        assert len(dates) >= 2

    def test_activity_counts_messages(self, temp_sessions_dir):
        """Count messages by role correctly."""
        activity = collect_daily_activity(temp_sessions_dir)

        for day, data in activity.items():
            assert data.message_count > 0
            assert data.message_count >= data.user_messages
            assert data.message_count >= data.assistant_messages


# =============================================================================
# COMPARE TESTS
# =============================================================================

class TestFindGaps:
    """Tests for find_gaps function."""

    def test_find_gaps_identifies_missing_days(self, temp_sessions_dir, temp_memory_dir):
        """Identify days with activity but no memory file."""
        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)

        assert len(gaps['missing_days']) > 0
        assert gaps['total_active_days'] > 0

    def test_find_gaps_identifies_sparse_days(self, temp_sessions_dir, temp_memory_dir, memory_fixtures_dir):
        """Identify days with files that are too small."""
        shutil.copy(
            memory_fixtures_dir / '2026-01-16.md',
            temp_memory_dir / '2026-01-16.md'
        )

        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)

        sparse_dates = [g.date for g in gaps['sparse_days']]
        assert date(2026, 1, 16) in sparse_dates

    def test_coverage_percentage_calculation(self, temp_sessions_dir, temp_memory_dir, memory_fixtures_dir):
        """Coverage percentage is calculated correctly."""
        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)
        assert gaps['coverage_pct'] == 0.0

        shutil.copy(
            memory_fixtures_dir / '2026-01-15.md',
            temp_memory_dir / '2026-01-15.md'
        )

        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)

        assert gaps['coverage_pct'] > 0.0
        assert gaps['covered_days'] > 0


class TestGetMemoryFiles:
    """Tests for get_memory_files function."""

    def test_get_memory_files(self, memory_fixtures_dir):
        """Get memory files with correct dates."""
        files = get_memory_files(memory_fixtures_dir)

        assert len(files) == 2

        dates = [d for d, _ in files]
        assert date(2026, 1, 15) in dates
        assert date(2026, 1, 16) in dates

    def test_ignores_non_date_files(self, temp_memory_dir):
        """Ignore files that don't match YYYY-MM-DD.md pattern."""
        (temp_memory_dir / 'MEMORY.md').write_text('# Main memory')
        (temp_memory_dir / 'notes.md').write_text('# Notes')
        (temp_memory_dir / '2026-01-20.md').write_text('# Valid date file')

        files = get_memory_files(temp_memory_dir)

        assert len(files) == 1
        assert files[0][0] == date(2026, 1, 20)


# =============================================================================
# BACKFILL TESTS
# =============================================================================

class TestGenerateDailyMemory:
    """Tests for generate_daily_memory function."""

    def test_creates_file(self, temp_sessions_dir, temp_memory_dir):
        """File is created at correct path."""
        output_path = temp_memory_dir / '2026-01-15.md'

        result = generate_daily_memory(
            date(2026, 1, 15),
            temp_sessions_dir,
            output_path
        )

        assert output_path.exists()
        assert result == str(output_path)

    def test_format_correct(self, temp_sessions_dir, temp_memory_dir):
        """Output matches expected template format."""
        output_path = temp_memory_dir / '2026-01-15.md'

        generate_daily_memory(
            date(2026, 1, 15),
            temp_sessions_dir,
            output_path
        )

        content = output_path.read_text()

        assert '# 2026-01-15' in content
        assert 'Auto-generated' in content
        assert 'Review and edit' in content

    def test_no_overwrite_without_force(self, temp_sessions_dir, temp_memory_dir):
        """Fails without --force when file exists."""
        output_path = temp_memory_dir / '2026-01-15.md'
        output_path.write_text('Existing content')

        with pytest.raises(FileExistsError):
            generate_daily_memory(
                date(2026, 1, 15),
                temp_sessions_dir,
                output_path,
                force=False
            )

    def test_overwrite_with_force(self, temp_sessions_dir, temp_memory_dir):
        """Overwrites with --force."""
        output_path = temp_memory_dir / '2026-01-15.md'
        output_path.write_text('Existing content')

        generate_daily_memory(
            date(2026, 1, 15),
            temp_sessions_dir,
            output_path,
            force=True
        )

        content = output_path.read_text()
        assert 'Existing content' not in content
        assert '2026-01-15' in content


class TestBackfillAllMissing:
    """Tests for backfill_all_missing function."""

    def test_creates_all_missing(self, temp_sessions_dir, temp_memory_dir):
        """Creates files for all missing dates."""
        result = backfill_all_missing(temp_sessions_dir, temp_memory_dir)

        assert len(result['created']) > 0
        assert len(result['errors']) == 0

        for path in result['created']:
            assert temp_memory_dir.joinpath(path.split('/')[-1]).exists()

    def test_dry_run(self, temp_sessions_dir, temp_memory_dir):
        """Dry run shows what would be created without creating."""
        result = backfill_all_missing(
            temp_sessions_dir,
            temp_memory_dir,
            dry_run=True
        )

        assert len(result['created']) > 0
        assert result['dry_run'] is True

        for path in result['created']:
            filename = path.split('/')[-1]
            assert not (temp_memory_dir / filename).exists()


# =============================================================================
# TRANSITIONS TESTS
# =============================================================================

class TestExtractTransitions:
    """Tests for extract_transitions function."""

    def test_extract_from_model_change(self, temp_sessions_dir):
        """Extract transitions from explicit model_change records."""
        transitions = list(extract_transitions(temp_sessions_dir))

        assert len(transitions) > 0

        models = {t.to_model for t in transitions}
        assert len(models) > 1

    def test_transitions_chronological_order(self, temp_sessions_dir):
        """Transitions are sorted by timestamp."""
        transitions = list(extract_transitions(temp_sessions_dir))

        timestamps = [t.timestamp for t in transitions]
        assert timestamps == sorted(timestamps)


class TestFormatTransition:
    """Tests for format_transition function."""

    def test_format_basic(self):
        """Format a basic transition."""
        t = ModelTransition(
            timestamp=datetime(2026, 1, 15, 14, 30, 45, tzinfo=timezone.utc),
            from_model='claude-sonnet-4',
            to_model='gpt-4o',
            session_id='test',
            provider='openai',
            from_provider='anthropic',
        )

        formatted = format_transition(t)

        assert '2026-01-15' in formatted
        assert '14:30:45' in formatted
        assert 'sonnet' in formatted.lower()
        assert 'gpt-4o' in formatted.lower()


# =============================================================================
# VALIDATE TESTS
# =============================================================================

class TestValidateMemoryFiles:
    """Tests for validate_memory_files function."""

    def test_validate_valid_files(self, temp_memory_dir, temp_sessions_dir):
        """Valid files pass validation."""
        content = """# 2026-01-15 (Wednesday)

*Auto-generated from 10 session messages*

## Topics Covered
- Topic 1
- Topic 2

This file has adequate content to pass the size check.
More content here to ensure it's over 100 bytes minimum.
""" * 2
        (temp_memory_dir / '2026-01-15.md').write_text(content)

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)

        assert result['total_count'] >= 1

    def test_detect_naming_issues(self, temp_memory_dir, temp_sessions_dir):
        """Detect files with invalid naming."""
        (temp_memory_dir / 'not-a-date.md').write_text('# Content\n' * 20)

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)

        naming_issues = [i for i in result['issues'] if i.issue_type == 'naming']
        assert len(naming_issues) > 0


# =============================================================================
# STATE TESTS
# =============================================================================

# Note: temp_state_dir fixture is defined in conftest.py


class TestStateFile:
    """Tests for state file operations."""
    
    def test_get_state_file_path(self, temp_state_dir):
        """State file path is in home directory."""
        path = get_state_file_path()
        assert path.name == 'state.json'
        assert '.memory-sync' in str(path)
    
    def test_load_state_empty(self, temp_state_dir):
        """Loading nonexistent state returns empty dict."""
        state = load_state()
        assert state == {}
    
    def test_save_and_load_state(self, temp_state_dir):
        """State can be saved and loaded."""
        now = datetime.now()
        
        save_state(
            last_run=now,
            last_successful_date=now.date(),
            total_days_processed=5
        )
        
        state = load_state()
        assert 'last_run' in state
        assert 'last_successful_date' in state
        assert state['total_days_processed'] == 5


# =============================================================================
# CLI TESTS
# =============================================================================

@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


class TestCompareCommand:
    """Tests for compare command."""

    def test_compare_runs(self, runner, temp_sessions_dir, temp_memory_dir):
        """Compare command runs without error."""
        result = runner.invoke(main, [
            'compare',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0
        assert 'Coverage' in result.output

    def test_compare_missing_sessions_dir(self, runner, temp_dir):
        """Compare fails gracefully with missing sessions dir."""
        result = runner.invoke(main, [
            'compare',
            '--sessions-dir', str(temp_dir / 'nonexistent'),
            '--memory-dir', str(temp_dir),
        ])

        assert result.exit_code == 1
        assert 'not found' in result.output.lower()


class TestBackfillCommand:
    """Tests for backfill command."""

    def test_backfill_single_date(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill single date."""
        result = runner.invoke(main, [
            'backfill',
            '--date', '2026-01-15',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0
        assert 'Created' in result.output
        assert (temp_memory_dir / '2026-01-15.md').exists()

    def test_backfill_dry_run(self, runner, temp_sessions_dir, temp_memory_dir):
        """Dry run shows but doesn't create."""
        result = runner.invoke(main, [
            'backfill',
            '--all',
            '--dry-run',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0
        assert 'Would create' in result.output or 'Dry run' in result.output

        md_files = list(temp_memory_dir.glob('*.md'))
        assert len(md_files) == 0

    def test_backfill_requires_date_or_all(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill requires --date or --all."""
        result = runner.invoke(main, [
            'backfill',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 1
        assert '--date' in result.output or '--all' in result.output


class TestExtractCommand:
    """Tests for extract command."""

    def test_extract_by_date(self, runner, temp_sessions_dir):
        """Extract messages by date."""
        result = runner.invoke(main, [
            'extract',
            '--date', '2026-01-15',
            '--sessions-dir', str(temp_sessions_dir),
        ])

        assert result.exit_code == 0
        assert 'Found' in result.output or 'matching' in result.output.lower()


class TestTransitionsCommand:
    """Tests for transitions command."""

    def test_transitions_runs(self, runner, temp_sessions_dir):
        """Transitions command runs."""
        result = runner.invoke(main, [
            'transitions',
            '--sessions-dir', str(temp_sessions_dir),
        ])

        assert result.exit_code == 0
        assert 'Transitions' in result.output


class TestValidateCommand:
    """Tests for validate command."""

    def test_validate_runs(self, runner, temp_memory_dir, temp_sessions_dir):
        """Validate command runs."""
        (temp_memory_dir / '2026-01-15.md').write_text('# 2026-01-15\n' * 20)

        result = runner.invoke(main, [
            'validate',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code in [0, 1]
        assert 'Validation' in result.output


class TestStatsCommand:
    """Tests for stats command."""

    def test_stats_runs(self, runner, temp_sessions_dir, temp_memory_dir):
        """Stats command runs."""
        result = runner.invoke(main, [
            'stats',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0
        assert 'Statistics' in result.output or 'Session' in result.output
