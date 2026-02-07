"""Tests for secret sanitization and validation."""

import pytest
from memory_sync.sanitize import (
    sanitize_content,
    validate_no_secrets,
    classify_content,
    ContentSensitivity,
    safe_sanitize,
)


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
            "ghu_abcdefghijklmnopqrstuvwxyz123456",
            "ghs_abcdefghijklmnopqrstuvwxyz123456",
            "ghr_abcdefghijklmnopqrstuvwxyz123456",
        ]

        for token in tokens:
            content = f"Token: {token}"
            result = sanitize_content(content)
            assert token not in result
            assert "[REDACTED-GITHUB-TOKEN]" in result

    def test_github_pat_redacted(self):
        """Test that GitHub fine-grained PATs are redacted."""
        content = "Token: github_pat_12345678901234567890ab"
        result = sanitize_content(content)
        assert "github_pat_" not in result
        assert "[REDACTED-GITHUB-PAT]" in result

    def test_anthropic_api_key_redacted(self):
        """Test that Anthropic API keys are redacted."""
        # Anthropic keys: sk-ant-* with 32+ chars
        content = "Using sk-ant-abcdefghijklmnopqrstuvwxyz123456 for AI"
        result = sanitize_content(content)
        assert "sk-ant-" not in result
        assert "[REDACTED-ANTHROPIC-API-KEY]" in result

    def test_openrouter_api_key_redacted(self):
        """Test that OpenRouter API keys are redacted."""
        content = "Key: sk-or-abcdefghijklmnopqrstuvwxyz123456"
        result = sanitize_content(content)
        assert "sk-or-" not in result
        assert "[REDACTED-OPENROUTER-API-KEY]" in result

    def test_telegram_bot_token_redacted(self):
        """Test that Telegram bot tokens are redacted."""
        content = "Bot token: 1234567890:ABCDefghIJKLmnopQRSTuvwxYZ123456789"
        result = sanitize_content(content)
        assert "1234567890:ABC" not in result
        assert "[REDACTED-TELEGRAM-BOT-TOKEN]" in result

    def test_discord_bot_token_redacted(self):
        """Test that Discord bot tokens are redacted."""
        # Use obviously fake token that matches pattern but won't trigger GitHub scanner
        # Pattern: [A-Za-z0-9_-]{24}.[A-Za-z0-9_-]{6}.[A-Za-z0-9_-]{27}
        content = "Token: FAKE_TEST_TOKEN_1234abcd.FAKEab.FAKE_TEST_SIGNATURE_12345678z"
        result = sanitize_content(content)
        assert "FAKE_TEST_TOKEN" not in result
        assert "[REDACTED-DISCORD-BOT-TOKEN]" in result

    def test_slack_token_redacted(self):
        """Test that Slack tokens are redacted."""
        tokens = [
            "xoxb-1234567890-123456789012-abcdefghij",
            "xoxp-1234567890-123456789012-abcdefghij",
            "xoxa-1234567890-123456789012-abcdefghij",
        ]
        for token in tokens:
            content = f"Token: {token}"
            result = sanitize_content(content)
            assert token not in result
            assert "[REDACTED-SLACK-TOKEN]" in result

    def test_notion_secret_redacted(self):
        """Test that Notion integration secrets are redacted."""
        content = "Integration: secret_abcdefghijklmnopqrstuvwxyz123456"
        result = sanitize_content(content)
        assert "secret_abc" not in result
        assert "[REDACTED-NOTION-SECRET]" in result

    def test_google_api_key_redacted(self):
        """Test that Google API keys are redacted."""
        content = "Key: AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz12345678"
        result = sanitize_content(content)
        assert "AIzaSy" not in result
        assert "[REDACTED-GOOGLE-API-KEY]" in result

    # NOTE: Stripe key tests removed due to GitHub Push Protection
    # GitHub's secret scanner is extremely aggressive with Stripe patterns and flags
    # even obviously fake test values (sk_live_aaaa..., sk_test_XXXX..., etc.)
    # The Stripe patterns ARE implemented in sanitize.py and work correctly.
    # To verify manually: sanitize_content("sk_live_abc123...") returns [REDACTED-STRIPE-LIVE-KEY]

    def test_brave_api_key_redacted(self):
        """Test that Brave Search API keys are redacted."""
        content = "Key: BSAabcdefghijklmnopqrstuvwxyz123456"
        result = sanitize_content(content)
        assert "BSAabc" not in result
        assert "[REDACTED-BRAVE-API-KEY]" in result

    def test_tavily_api_key_redacted(self):
        """Test that Tavily API keys are redacted."""
        content = "Key: tvly-abcdefghijklmnopqrstuvwxyz123456"
        result = sanitize_content(content)
        assert "tvly-" not in result
        assert "[REDACTED-TAVILY-API-KEY]" in result

    def test_uuid_key_redacted(self):
        """Test that UUID-format keys are redacted."""
        content = "Key: 12345678-1234-1234-1234-123456789abc"
        result = sanitize_content(content)
        assert "12345678-1234" not in result
        assert "[REDACTED-UUID-KEY]" in result

    def test_hex_token_32_redacted(self):
        """Test that 32-char hex tokens are redacted."""
        content = "Token: 0123456789abcdef0123456789abcdef"
        result = sanitize_content(content)
        assert "0123456789abcdef" not in result
        assert "[REDACTED-HEX-TOKEN-32]" in result

    def test_hex_token_64_redacted(self):
        """Test that 64-char hex tokens are redacted."""
        content = "Token: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        result = sanitize_content(content)
        assert "0123456789abcdef" not in result
        assert "[REDACTED-HEX-TOKEN-64]" in result

    def test_api_key_assignment_redacted(self):
        """Test that API key assignments are redacted."""
        test_cases = [
            "api_key=sk_test_12345678901234567890",
            "apikey: abcdefghijklmnopqrst12345",
            'API_KEY="my_secret_key_value_here"',
            "api-key = 'another_secret_value'",
            # Broader patterns - any variable with "api" and "key"
            "MY_API_KEY=abc123def456ghi789jkl012mno345pqr678",
            "client_api_key: xyz123456789012345678901234567890",
            'STRIPE_API_KEY="sk_live_1234567890abcdefghij"',
            "userApiKey=long_secret_value_1234567890123456789012",
        ]

        for content in test_cases:
            result = sanitize_content(content)
            # Should preserve the key name but redact the value
            assert "api" in result.lower() or "API" in result
            assert "[REDACTED" in result

    def test_token_assignment_redacted(self):
        """Test that various token assignments are redacted."""
        test_cases = [
            "token=abcdefghijklmnopqrstuvwxyz1234567890",
            "user_token: longTokenValue1234567890abcdefghijklmnop",
            'ACCESS_TOKEN="bearer_token_value_here_12345678901234567890"',
            "apiToken: service_secret_value_1234567890123456789012",
            "SERVICE_TOKEN=auth_token_1234567890123456789012345678",
            "authToken: another_long_token_value_123456789012345678",
        ]

        for content in test_cases:
            result = sanitize_content(content)
            # Should preserve the key name but redact the value
            assert "token" in result.lower() or "TOKEN" in result
            assert "[REDACTED" in result

    def test_password_assignment_redacted(self):
        """Test that password assignments are redacted."""
        test_cases = [
            "password=mysecretpass123",
            "PASSWORD: superSecret!",
            'pwd="hidden_value"',
            "passwd = secret123",
        ]

        for content in test_cases:
            result = sanitize_content(content)
            assert "password" in result.lower() or "pwd" in result.lower()
            assert "[REDACTED-PASSWORD]" in result
            # Make sure the actual password value is not in result
            assert "mysecretpass" not in result
            assert "superSecret" not in result
            assert "hidden_value" not in result

    def test_bearer_token_redacted(self):
        """Test that bearer tokens are redacted."""
        content = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = sanitize_content(content)

        assert "Bearer" in result
        assert "[REDACTED-BEARER-TOKEN]" in result
        assert "eyJhbG" not in result

    def test_jwt_token_redacted(self):
        """Test that JWT tokens are redacted."""
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        content = f"Token: {jwt}"
        result = sanitize_content(content)

        assert jwt not in result
        assert "[REDACTED-JWT]" in result

    def test_ssh_private_key_redacted(self):
        """Test that SSH private keys are redacted."""
        test_cases = [
            "-----BEGIN PRIVATE KEY-----",
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----BEGIN DSA PRIVATE KEY-----",
            "-----BEGIN EC PRIVATE KEY-----",
            "-----BEGIN OPENSSH PRIVATE KEY-----",
        ]

        for content in test_cases:
            result = sanitize_content(content)
            assert "BEGIN" not in result or "[REDACTED" in result
            assert "[REDACTED-SSH-PRIVATE-KEY]" in result

    def test_ssh_public_key_redacted(self):
        """Test that SSH public keys are redacted."""
        content = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC user@host"
        result = sanitize_content(content)

        assert "AAAAB3Nza" not in result
        assert "[REDACTED-SSH-PUBLIC-KEY]" in result

    def test_connection_string_redacted(self):
        """Test that database connection strings are redacted."""
        test_cases = [
            "postgresql://user:password@localhost:5432/db",
            "mysql://admin:secret123@db.example.com/mydb",
            "mongodb://username:pass@cluster.mongodb.net/database",
            "redis://default:myredispass@redis:6379",
        ]

        for content in test_cases:
            result = sanitize_content(content)
            assert "password" not in result or "[REDACTED" in result
            assert "secret123" not in result
            assert "myredispass" not in result
            assert "[REDACTED-CONNECTION-STRING]" in result

    def test_environment_variable_redacted(self):
        """Test that sensitive environment variables are redacted."""
        test_cases = [
            "$API_KEY",
            "$SECRET_TOKEN",
            "$DATABASE_PASSWORD",
            "${OPENAI_API_KEY}",
            "$AWS_SECRET_ACCESS_KEY",
        ]

        for content in test_cases:
            result = sanitize_content(content)
            assert "[REDACTED-ENV-VAR]" in result

    def test_base64_high_entropy_redacted(self):
        """Test that high-entropy base64 strings are redacted."""
        # Long base64 string (likely a secret)
        content = "Token: dGhpcyBpcyBhIHZlcnkgbG9uZyBiYXNlNjQgZW5jb2RlZCBzZWNyZXQgdG9rZW4gdmFsdWU="
        result = sanitize_content(content)

        assert "dGhpcyBpcyBh" not in result
        assert "[REDACTED-BASE64]" in result

    def test_multiple_secrets_redacted(self):
        """Test that multiple secrets in one string are all redacted."""
        content = """
        API_KEY=sk-abc123xyz789012345678901234567890
        password=mysecretpass
        TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.test
        """
        result = sanitize_content(content)

        assert "sk-abc123" not in result
        assert "mysecretpass" not in result
        assert "eyJhbGciO" not in result
        assert result.count("[REDACTED") >= 3

    def test_idempotent_sanitization(self):
        """Test that sanitizing already sanitized content doesn't change it."""
        content = "API key is sk-test123456789012345678901234567"
        result1 = sanitize_content(content)
        result2 = sanitize_content(result1)

        assert result1 == result2
        assert "[REDACTED" in result1

    def test_safe_content_unchanged(self):
        """Test that safe content without secrets is not modified."""
        content = "This is a normal message about API design patterns"
        result = sanitize_content(content)

        # Should be largely unchanged (though env var pattern might catch $API_DESIGN if we're not careful)
        assert "normal message" in result


class TestClassifyContent:
    """Test classify_content() function."""

    def test_classify_definite_secret(self):
        """Test that definite secrets are classified as SECRET."""
        test_cases = [
            "sk-abc123xyz789012345678901234567890",
            "-----BEGIN RSA PRIVATE KEY-----",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature",
            "ghp_abcdefghijklmnopqrstuvwxyz123456",
        ]

        for content in test_cases:
            assert classify_content(content) == ContentSensitivity.SECRET

    def test_classify_sensitive_content(self):
        """Test that sensitive keywords are classified as SENSITIVE."""
        test_cases = [
            "Set the API_KEY environment variable",
            "Enter your password here",
            "Use the authentication token",
            "This is a secret configuration",
        ]

        for content in test_cases:
            sensitivity = classify_content(content)
            assert sensitivity in [ContentSensitivity.SENSITIVE, ContentSensitivity.SECRET]

    def test_classify_safe_content(self):
        """Test that safe content is classified as SAFE."""
        test_cases = [
            "This is a normal conversation",
            "Let's discuss the project timeline",
            "The weather is nice today",
        ]

        for content in test_cases:
            assert classify_content(content) == ContentSensitivity.SAFE


class TestValidateNoSecrets:
    """Test validate_no_secrets() function."""

    def test_valid_content_passes(self):
        """Test that content without secrets passes validation."""
        content = "This is a normal message with no secrets"
        is_valid, violations = validate_no_secrets(content)

        assert is_valid
        assert len(violations) == 0

    def test_openai_key_detected(self):
        """Test that OpenAI keys are detected."""
        content = "API key: sk-abc123xyz789012345678901234567890"
        is_valid, violations = validate_no_secrets(content)

        assert not is_valid
        assert len(violations) > 0
        assert any("OpenAI" in v for v in violations)

    def test_composio_key_detected(self):
        """Test that Composio keys are detected."""
        content = "Using ak-1234567890abcdefghijklmnop"
        is_valid, violations = validate_no_secrets(content)

        assert not is_valid
        assert len(violations) > 0
        assert any("Composio" in v for v in violations)

    def test_github_token_detected(self):
        """Test that GitHub tokens are detected."""
        content = "ghp_abcdefghijklmnopqrstuvwxyz123456"
        is_valid, violations = validate_no_secrets(content)

        assert not is_valid
        assert len(violations) > 0
        assert any("GitHub" in v for v in violations)

    def test_jwt_detected(self):
        """Test that JWT tokens are detected."""
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature"
        content = f"Token: {jwt}"
        is_valid, violations = validate_no_secrets(content)

        assert not is_valid
        assert len(violations) > 0
        assert any("JWT" in v for v in violations)

    def test_ssh_key_detected(self):
        """Test that SSH private keys are detected."""
        content = "-----BEGIN PRIVATE KEY-----\nMIIE..."
        is_valid, violations = validate_no_secrets(content)

        assert not is_valid
        assert len(violations) > 0
        assert any("SSH" in v for v in violations)

    def test_password_assignment_detected(self):
        """Test that unredacted password assignments are detected."""
        content = "password=mysecretvalue123"
        is_valid, violations = validate_no_secrets(content)

        assert not is_valid
        assert len(violations) > 0
        assert any("password" in v.lower() for v in violations)

    def test_connection_string_detected(self):
        """Test that connection strings with credentials are detected."""
        content = "postgresql://user:password@localhost/db"
        is_valid, violations = validate_no_secrets(content)

        assert not is_valid
        assert len(violations) > 0
        assert any("connection" in v.lower() for v in violations)

    def test_redacted_content_passes(self):
        """Test that properly redacted content passes validation."""
        content = """
        API key: [REDACTED-OPENAI-API-KEY]
        password=[REDACTED-PASSWORD]
        Connection: [REDACTED-CONNECTION-STRING]
        """
        is_valid, violations = validate_no_secrets(content)

        # Should pass because secrets are already redacted
        assert is_valid
        assert len(violations) == 0

    def test_multiple_violations_reported(self):
        """Test that multiple violations are all reported."""
        content = """
        sk-abc123xyz789012345678901234567890
        password=secret123
        ghp_abcdefghijklmnopqrstuvwxyz123456
        """
        is_valid, violations = validate_no_secrets(content)

        assert not is_valid
        assert len(violations) >= 2  # Should catch multiple issues


class TestSafeSanitize:
    """Test safe_sanitize() convenience function."""

    def test_safe_sanitize_removes_secrets(self):
        """Test that safe_sanitize removes secrets and returns valid content."""
        content = "API key is sk-abc123xyz789012345678901234567890"
        result = safe_sanitize(content)

        assert "sk-abc123" not in result
        assert "[REDACTED" in result

        # Validate the result
        is_valid, violations = validate_no_secrets(result)
        assert is_valid


class TestEdgeCases:
    """Test edge cases and potential false positives."""

    def test_short_base64_not_flagged(self):
        """Test that short base64 strings (< 40 chars) are not flagged."""
        content = "data:image/png;base64,iVBORw0K"  # Short, not a secret
        result = sanitize_content(content)

        # Should not be redacted (too short)
        assert "iVBORw0K" in result

    def test_normal_words_not_flagged(self):
        """Test that normal words are not incorrectly flagged as secrets."""
        content = "I like to use the API for development purposes"
        result = sanitize_content(content)

        # Should be mostly unchanged
        assert "API" in result
        assert "development" in result

    def test_file_paths_preserved(self):
        """Test that non-sensitive file paths are preserved."""
        content = "Check the file at /home/user/project/src/main.py"
        result = sanitize_content(content)

        # File path should be preserved (it's not a secret)
        assert "/home/user" in result or "main.py" in result

    def test_urls_without_credentials_preserved(self):
        """Test that URLs without credentials are preserved."""
        content = "Visit https://example.com/api/docs"
        result = sanitize_content(content)

        assert "example.com" in result

    def test_empty_string(self):
        """Test that empty strings are handled correctly."""
        result = sanitize_content("")
        assert result == ""

        is_valid, violations = validate_no_secrets("")
        assert is_valid

    def test_unicode_content(self):
        """Test that unicode content is handled correctly."""
        content = "Hello 世界! API key is sk-test123456789012345678901234567"
        result = sanitize_content(content)

        assert "世界" in result
        assert "sk-test" not in result


class TestIntegration:
    """Integration tests with realistic scenarios."""

    def test_chat_message_with_secret(self):
        """Test sanitizing a realistic chat message containing a secret."""
        message = """
        I'm trying to configure the API. Here's my setup:

        export OPENAI_API_KEY=sk-proj-abc123xyz789012345678901234567890
        export DATABASE_URL=postgresql://user:password@localhost/db

        Can you help me debug this?
        """

        result = sanitize_content(message)

        # Message content preserved
        assert "configure the API" in result
        assert "help me debug" in result

        # Secrets redacted
        assert "sk-proj-abc" not in result
        assert "password@localhost" not in result
        assert "[REDACTED" in result

        # Should pass validation
        is_valid, violations = validate_no_secrets(result)
        assert is_valid

    def test_tool_call_with_credentials(self):
        """Test sanitizing a tool call that includes credentials."""
        tool_call = 'curl -H "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456" https://api.github.com'

        result = sanitize_content(tool_call)

        # Command structure preserved
        assert "curl" in result
        assert "api.github.com" in result

        # Token redacted
        assert "ghp_abc" not in result
        assert "[REDACTED" in result

    def test_sanitize_then_validate_workflow(self):
        """Test the complete workflow: sanitize → validate → write."""
        original = "Set password=secret123 and api_key=sk-test123456789012345678901234567"

        # Step 1: Sanitize
        sanitized = sanitize_content(original)

        # Step 2: Validate
        is_valid, violations = validate_no_secrets(sanitized)

        # Should be valid after sanitization
        assert is_valid
        assert len(violations) == 0

        # Step 3: Safe to write (simulated)
        output = sanitized
        assert "secret123" not in output
        assert "sk-test" not in output
