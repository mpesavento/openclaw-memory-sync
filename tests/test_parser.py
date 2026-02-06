"""Tests for JSONL parser module."""

import pytest
from datetime import date, datetime, timezone

from memory_sync.parser import (
    parse_jsonl,
    get_session_metadata,
    get_messages,
    get_model_transitions,
    get_compactions,
    get_model_snapshots,
)


class TestParseJsonl:
    """Tests for parse_jsonl function."""

    def test_parse_valid_jsonl(self, sample_session_path):
        """Parse sample_session.jsonl correctly."""
        records = list(parse_jsonl(sample_session_path))

        assert len(records) > 0
        # First record should be session
        assert records[0]['type'] == 'session'

    def test_parse_streaming_memory_efficient(self, sample_session_path):
        """Verify streaming doesn't load entire file."""
        # Should work with generators
        gen = parse_jsonl(sample_session_path)
        first = next(gen)
        assert first['type'] == 'session'

    def test_parse_malformed_skips_bad_lines(self, malformed_path, capsys):
        """Handle malformed.jsonl gracefully by skipping bad lines."""
        records = list(parse_jsonl(malformed_path))

        # Should have session record and 2 valid messages
        valid_records = [r for r in records if r.get('type') in ('session', 'message')]
        assert len(valid_records) == 3

        # Should have printed warnings
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
        # Create file with no session record
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
        # Sample session has messages on 2026-01-15 and 2026-01-16
        messages_15 = list(get_messages(sample_session_path, date_filter=date(2026, 1, 15)))
        messages_16 = list(get_messages(sample_session_path, date_filter=date(2026, 1, 16)))

        assert len(messages_15) > 0
        assert len(messages_16) > 0

        # All messages should be on the filtered date
        for m in messages_15:
            assert m.timestamp.date() == date(2026, 1, 15)
        for m in messages_16:
            assert m.timestamp.date() == date(2026, 1, 16)

    def test_get_messages_extracts_text_content(self, sample_session_path):
        """Extract text from content blocks."""
        messages = list(get_messages(sample_session_path))

        # Find a user message
        user_msgs = [m for m in messages if m.role == 'user']
        assert len(user_msgs) > 0

        # First user message should have text
        assert 'Hello' in user_msgs[0].text_content or 'help' in user_msgs[0].text_content.lower()

    def test_get_messages_detects_tool_calls(self, sample_session_path):
        """Detect messages with tool calls."""
        messages = list(get_messages(sample_session_path))

        # Find assistant message with tool call
        tool_msgs = [m for m in messages if m.has_tool_calls]
        assert len(tool_msgs) > 0

    def test_get_messages_detects_thinking(self, sample_session_path):
        """Detect messages with thinking blocks."""
        messages = list(get_messages(sample_session_path))

        # Find assistant message with thinking
        thinking_msgs = [m for m in messages if m.has_thinking]
        assert len(thinking_msgs) > 0

    def test_get_messages_includes_model_info(self, sample_session_path):
        """Extract model metadata from assistant messages."""
        messages = list(get_messages(sample_session_path))

        assistant_msgs = [m for m in messages if m.role == 'assistant']
        assert len(assistant_msgs) > 0

        # At least one should have model info
        models = [m.model for m in assistant_msgs if m.model]
        assert len(models) > 0
        assert 'claude-sonnet-4' in models or 'gpt-4o' in models


class TestGetModelTransitions:
    """Tests for get_model_transitions function."""

    def test_get_model_transitions(self, model_transitions_path):
        """Detect model changes from model_transitions.jsonl."""
        transitions = list(get_model_transitions(model_transitions_path))

        # Should have 3 explicit model_change records
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

        # Sample session has one model_change (sonnet -> gpt-4o)
        assert len(transitions) >= 1

        # Check the transition
        sonnet_to_gpt = [t for t in transitions if t.to_model == 'gpt-4o']
        assert len(sonnet_to_gpt) > 0


class TestGetCompactions:
    """Tests for get_compactions function."""

    def test_get_compactions(self, sample_session_path):
        """Extract compaction records."""
        compactions = list(get_compactions(sample_session_path))

        # Sample session has one compaction
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

        # Sample session has one model-snapshot
        assert len(snapshots) == 1

        snap = snapshots[0]
        assert snap['provider'] == 'anthropic'
        assert snap['modelId'] == 'claude-sonnet-4'
