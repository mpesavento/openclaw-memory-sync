"""Integration tests for sanitization in the full pipeline."""

import pytest
from pathlib import Path
from datetime import date
import json

from memory_sync.backfill import generate_daily_memory, extract_key_exchanges, extract_decisions
from memory_sync.parser import get_messages


class TestBackfillSanitization:
    """Test that sanitization works in the backfill pipeline."""
    
    def test_memory_file_has_no_secrets(self, temp_dir):
        """Test that generated memory files don't contain secrets."""
        # Create a session with secrets
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
            {
                "type": "message",
                "id": "msg2",
                "timestamp": "2026-02-06T10:02:00Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4",
                    "content": [
                        {
                            "type": "text",
                            "text": "I'll help you configure that. Use export DATABASE_URL=postgresql://user:password@localhost/db"
                        }
                    ]
                }
            }
        ]
        
        with open(session_file, 'w') as f:
            for record in session_content:
                f.write(json.dumps(record) + '\n')
        
        # Generate memory file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        output_path = memory_dir / "2026-02-06.md"
        
        generate_daily_memory(
            date(2026, 2, 6),
            sessions_dir,
            output_path
        )
        
        # Read generated file
        content = output_path.read_text()
        
        # Verify secrets are NOT in the file
        assert "sk-abc123xyz789" not in content
        assert "password@localhost" not in content
        
        # Verify redaction markers ARE present
        assert "[REDACTED" in content
    
    def test_extract_functions_sanitize_content(self, temp_dir):
        """Test that extract functions sanitize their output."""
        # Create session with secrets
        sessions_dir = temp_dir / "sessions"
        sessions_dir.mkdir()
        
        session_file = sessions_dir / "session_extract_test.jsonl"
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
                            "text": "Can you help me with password=mysecret123?"
                        }
                    ]
                }
            },
            {
                "type": "message",
                "id": "msg2",
                "timestamp": "2026-02-06T10:02:00Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4",
                    "content": [
                        {
                            "type": "text",
                            "text": "I'll use the token ghp_abcdefghijklmnopqrstuvwxyz123456 to authenticate."
                        }
                    ]
                }
            }
        ]
        
        with open(session_file, 'w') as f:
            for record in session_content:
                f.write(json.dumps(record) + '\n')
        
        # Extract messages and process
        messages = list(get_messages(session_file))
        
        # Test extract_key_exchanges
        exchanges = extract_key_exchanges(messages)
        assert len(exchanges) > 0
        
        # Verify secrets are redacted in excerpts
        user_text = exchanges[0]['user_excerpt']
        assert "mysecret123" not in user_text
        assert "[REDACTED" in user_text or "password=[REDACTED" in user_text
        
        # Test extract_decisions
        decisions = extract_decisions(messages)
        if decisions:
            # If any decisions were extracted, they should be sanitized
            all_decisions = ' '.join(decisions)
            assert "ghp_abc" not in all_decisions


class TestCLISanitization:
    """Test that CLI commands sanitize output."""
    
    def test_extract_command_sanitizes_output(self, temp_dir):
        """Test that the extract command sanitizes secrets in output."""
        # Create session with secrets
        sessions_dir = temp_dir / "sessions"
        sessions_dir.mkdir()
        
        session_file = sessions_dir / "session_cli_test.jsonl"
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
                            "text": "Test with sk-test123456789012345678901234567"
                        }
                    ]
                }
            }
        ]
        
        with open(session_file, 'w') as f:
            for record in session_content:
                f.write(json.dumps(record) + '\n')
        
        # Read messages (simulating what CLI does)
        from memory_sync.sanitize import sanitize_content
        
        messages = list(get_messages(session_file))
        assert len(messages) > 0
        
        # Simulate CLI output formatting with sanitization
        for msg in messages:
            sanitized_text = sanitize_content(msg.text_content[:200])
            
            # Verify secret is not in output
            assert "sk-test123456" not in sanitized_text
            # Verify redaction marker is present
            assert "[REDACTED" in sanitized_text


class TestValidationRejectsSecrets:
    """Test that validation prevents secrets from being written."""
    
    def test_generate_with_secret_in_preserved_content(self, temp_dir):
        """Test that secrets in hand-written preserved content are sanitized."""
        sessions_dir = temp_dir / "sessions"
        sessions_dir.mkdir()
        
        session_file = sessions_dir / "session_preserve_test.jsonl"
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
                            "text": "Normal message"
                        }
                    ]
                }
            }
        ]
        
        with open(session_file, 'w') as f:
            for record in session_content:
                f.write(json.dumps(record) + '\n')
        
        # Create existing file with hand-written content containing a secret
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        output_path = memory_dir / "2026-02-06.md"
        
        existing_content = """# 2026-02-06 (Thursday)

*Auto-generated from 1 session messages*

---

*Review and edit this draft to capture what's actually important.*

## My Notes

I accidentally included my token: ghp_abcdefghijklmnopqrstuvwxyz123456
"""
        output_path.write_text(existing_content)
        
        # Regenerate with preserve=True
        generate_daily_memory(
            date(2026, 2, 6),
            sessions_dir,
            output_path,
            force=True,
            preserve=True
        )
        
        # Read result
        new_content = output_path.read_text()
        
        # Secret should be sanitized even in preserved content
        assert "ghp_abc" not in new_content
        # Should have redaction marker
        assert "[REDACTED" in new_content


class TestParserWarningsSanitized:
    """Test that parser warnings don't leak secrets."""
    
    def test_malformed_json_warning_no_content(self, temp_dir, capsys):
        """Test that malformed JSON warnings don't include line content."""
        from memory_sync.parser import parse_jsonl
        
        # Create file with malformed JSON that contains a secret
        test_file = temp_dir / "malformed_with_secret.jsonl"
        test_file.write_text("""{"type":"session","id":"test"}
{"type":"message","secret":"sk-abc123xyz789012345678901234567890"
{"type":"message","id":"msg2","message":{"role":"user"}}
""")
        
        # Parse and consume all records
        list(parse_jsonl(test_file))
        
        # Check stderr output
        captured = capsys.readouterr()
        
        # Should have warning
        assert "Warning" in captured.err
        assert "malformed" in captured.err.lower()
        
        # Should NOT include the secret from the malformed line
        assert "sk-abc123" not in captured.err
