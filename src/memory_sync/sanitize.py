"""Security sanitization for session logs and memory content.

This module provides secret detection, content sanitization, and validation
to prevent secrets from leaking into memory files, LLM prompts, or CLI output.
"""

import re
from enum import Enum
from typing import Tuple, List


# =============================================================================
# Secret Detection Patterns
# =============================================================================

# Regex patterns for detecting secrets (must be redacted)
# IMPORTANT: Order matters! More specific patterns must come before generic ones.
# Use a list of tuples to ensure explicit ordering.
SECRET_PATTERNS = [
    # ==========================================================================
    # EXPLICIT KEY PATTERNS (Specific formats first)
    # ==========================================================================
    
    # --- LLM Providers ---
    # OpenAI API keys: sk-proj-* (~64 chars) or sk-* (~48-51 chars)
    (r'sk-(?:proj-)?[a-zA-Z0-9]{30,}', 'OPENAI-API-KEY'),
    # Anthropic API keys: sk-ant-* format (32+ chars after prefix)
    (r'sk-ant-[a-zA-Z0-9\-_]{32,}', 'ANTHROPIC-API-KEY'),
    # OpenRouter API keys: sk-or-* format
    (r'sk-or-[a-zA-Z0-9]{32,}', 'OPENROUTER-API-KEY'),
    # Composio API keys: ak-* followed by alphanumeric
    (r'ak-[a-zA-Z0-9]{20,}', 'COMPOSIO-API-KEY'),
    
    # --- GitHub / Git ---
    # GitHub tokens: gh[pousr]_* format (36-40 chars standard)
    (r'ghp_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),  # Personal access token
    (r'gho_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),  # OAuth token
    (r'ghu_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),  # User token
    (r'ghs_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),  # Server token
    (r'ghr_[A-Za-z0-9]{32,40}', 'GITHUB-TOKEN'),  # Refresh token
    (r'gh[pousr]_[A-Za-z0-9]{20,}', 'GITHUB-TOKEN'),  # Fallback for variations
    # GitHub fine-grained PAT: github_pat_* format
    (r'github_pat_[A-Za-z0-9_]{22,}', 'GITHUB-PAT'),
    
    # --- AWS ---
    (r'AKIA[A-Z0-9]{16}', 'AWS-ACCESS-KEY'),
    (r'ASIA[A-Z0-9]{16}', 'AWS-SESSION-KEY'),
    
    # --- Communication / Channels ---
    # Telegram Bot Token: <bot_id>:<token>
    (r'\d{9,10}:[A-Za-z0-9_-]{35}', 'TELEGRAM-BOT-TOKEN'),
    # Discord Bot Token: <id>.<timestamp>.<hmac>
    (r'[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}', 'DISCORD-BOT-TOKEN'),
    # Slack Token: xox[baprs]-*
    (r'xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*', 'SLACK-TOKEN'),
    
    # --- Productivity / Integrations ---
    # Notion Integration Secret: secret_*
    (r'secret_[A-Za-z0-9]{32,}', 'NOTION-SECRET'),
    # Google API Key: AIza*
    (r'AIza[0-9A-Za-z_-]{35}', 'GOOGLE-API-KEY'),
    
    # --- Payment ---
    # Stripe Keys: sk_live_*, sk_test_*, pk_live_*, pk_test_*
    (r'sk_live_[0-9a-zA-Z]{24,}', 'STRIPE-LIVE-KEY'),
    (r'sk_test_[0-9a-zA-Z]{24,}', 'STRIPE-TEST-KEY'),
    (r'pk_live_[0-9a-zA-Z]{24,}', 'STRIPE-PUBLISHABLE-KEY'),
    (r'pk_test_[0-9a-zA-Z]{24,}', 'STRIPE-TEST-PUBLISHABLE-KEY'),
    
    # --- Search / Data ---
    # Brave Search API Key: BSA*
    (r'BSA[0-9a-zA-Z_-]{32,}', 'BRAVE-API-KEY'),
    # Tavily API Key: tvly-*
    (r'tvly-[A-Za-z0-9]{32,}', 'TAVILY-API-KEY'),
    # SerpAPI Key: serp-*
    (r'serp-[0-9a-z]{32,}', 'SERPAPI-KEY'),
    
    # --- Vector DB / Storage ---
    # UUID pattern (Pinecone, Supabase, etc.)
    (r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UUID-KEY'),
    
    # ==========================================================================
    # STRUCTURAL PATTERNS (Format-based detection)
    # Order: More specific first, then more general
    # ==========================================================================
    
    # JWT tokens: eyJ*.eyJ*.*
    (r'eyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}', 'JWT'),
    
    # SSH keys
    (r'-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----', 'SSH-PRIVATE-KEY'),
    (r'ssh-(?:rsa|dss|ed25519|ecdsa)\s+[A-Za-z0-9+/]{30,}={0,3}', 'SSH-PUBLIC-KEY'),
    
    # Database connection strings (with embedded credentials)
    (r'(?:postgresql|mysql|mongodb|redis)://[^:@\s]+:[^@\s]+@[^\s]+', 'CONNECTION-STRING'),
    (r'\w+://[^:]+:[^@]+@\S+', 'CONNECTION-STRING'),
    
    # Hex tokens BEFORE base64 (hex is subset of base64 charset)
    # 64-char hex strings (Trello tokens, etc.)
    (r'\b[0-9a-f]{64}\b', 'HEX-TOKEN-64'),
    # 32-char hex strings (Trello API keys, ElevenLabs, Oura, etc.)
    (r'\b[0-9a-f]{32}\b', 'HEX-TOKEN-32'),
    
    # High-entropy base64 strings (40+ chars likely a secret)
    # Must come AFTER hex patterns since hex chars are valid base64
    (r'\b[A-Za-z0-9+/]{40,}={0,2}\b', 'BASE64'),
    
    # ==========================================================================
    # GENERIC PATTERNS (Catch-all for unknown formats)
    # These use flexible lengths (16+) and negative lookahead to avoid re-matching
    # ==========================================================================
    
    (r'(?i)(\w*api\w*[_-]?\w*key\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'API-KEY'),
    (r'(?i)(\w*secret\w*[_-]?\w*key\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'SECRET'),
    (r'(?i)(\w*access\w*[_-]?\w*token\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'ACCESS-TOKEN'),
    (r'(?i)(\w*auth\w*[_-]?\w*token\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'AUTH-TOKEN'),
    (r'(?i)(\w*api\w*[_-]?\w*token\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'API-TOKEN'),
    (r'(?i)(bearer\s+)(?!\[REDACTED)([^\s"\'\n\[]{16,})', 'BEARER-TOKEN'),
    (r'(?i)(\w*token\w*)\s*[=:]\s*["\']?(?!\[REDACTED)([^\s"\'\n\[]{16,})["\']?', 'TOKEN'),  # Most generic, last
    
    # Passwords (shorter minimum since passwords vary)
    (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\'\n]{8,})["\']?', 'PASSWORD'),
    (r'(?i)(private[_-]?key|privkey)\s*[=:]\s*["\']?([^\s"\'\n]{20,})["\']?', 'PRIVATE-KEY'),
    
    # Environment variable patterns (with sensitive keywords)
    (r'\$[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)[A-Z_]*\b', 'ENV-VAR'),
    (r'\$\{[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)[A-Z_]*\}', 'ENV-VAR'),
]


# =============================================================================
# Known sensitive environment variable names
# =============================================================================
SENSITIVE_ENV_VAR_NAMES = [
    # LLM Providers
    'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY',
    'COMPOSIO_API_KEY', 'COMPOSIO_ENTITY_ID', 
    'COMPOSIO_CALENDAR_ACCOUNT', 'COMPOSIO_GMAIL_ACCOUNT',
    'MOONSHOT_API_KEY', 'KIMI_API_KEY',
    
    # GitHub / Git
    'GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_PAT',
    
    # Communication / Channels
    'TELEGRAM_BOT_TOKEN', 'DISCORD_BOT_TOKEN', 'DISCORD_TOKEN',
    'SLACK_BOT_TOKEN', 'SLACK_TOKEN',
    
    # Productivity / Integrations
    'NOTION_API_KEY', 'NOTION_TOKEN', 'NOTION_SECRET',
    'TRELLO_API_KEY', 'TRELLO_TOKEN',
    'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS',
    
    # Payment
    'STRIPE_API_KEY', 'STRIPE_SECRET_KEY', 'STRIPE_PUBLISHABLE_KEY',
    
    # Search / Data
    'BRAVE_API_KEY', 'TAVILY_API_KEY', 'SERPAPI_KEY',
    
    # Vector DB / Storage
    'PINECONE_API_KEY', 'SUPABASE_KEY', 'SUPABASE_ANON_KEY', 
    'SUPABASE_SERVICE_KEY', 'QDRANT_API_KEY',
    
    # TTS / Voice
    'ELEVENLABS_API_KEY', 'ELEVENLABS_KEY',
    
    # Wearables / Health
    'OURA_PAT', 'OURA_PERSONAL_ACCESS_TOKEN',
    
    # AWS
    'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
]


# Tool call arguments that commonly contain secrets
SENSITIVE_TOOL_PATTERNS = {
    'read': ['.env', 'secrets', 'key', 'token', 'password', 'config'],
    'write': ['.env', 'secrets', 'config.json', 'tokens.json'],
    'exec': ['env', 'export', 'printenv', 'cat.*password', 'cat.*secret'],
    'curl': ['-H.*Authorization', '-u ', '--user', '-d.*password'],
    'wget': ['--password', '--user'],
}


# =============================================================================
# Content Sensitivity Classification
# =============================================================================

class ContentSensitivity(Enum):
    """Content sensitivity level for classification."""
    SAFE = "safe"           # Can summarize and store
    SENSITIVE = "sensitive" # Summarize carefully, store redacted
    SECRET = "secret"       # Do not summarize, do not store


def classify_content(content: str) -> ContentSensitivity:
    """
    Classify content sensitivity level based on pattern matching.
    
    Args:
        content: Text content to classify
        
    Returns:
        ContentSensitivity enum value
    """
    # Check for definite secrets (high-confidence patterns)
    definite_secret_patterns = [
        r'sk-(?:proj-|ant-)?[a-zA-Z0-9\-_]{30,}',  # OpenAI/Anthropic keys
        r'AKIA[A-Z0-9]{16}',  # AWS access keys
        r'-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----',  # SSH private keys
        r'eyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}',  # JWT tokens
        r'gh[pousr]_[A-Za-z0-9]{20,}',  # GitHub tokens
    ]
    
    for pattern in definite_secret_patterns:
        if re.search(pattern, content):
            return ContentSensitivity.SECRET
    
    # Check for sensitive but not necessarily secret content
    sensitive_patterns = [
        r'\$[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD)',  # Env var references
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


# =============================================================================
# Content Sanitization
# =============================================================================

def sanitize_content(content: str) -> str:
    """
    Remove all potentially sensitive content before processing.
    
    Replaces detected secrets with [REDACTED-TYPE] placeholders.
    This function is idempotent - running it multiple times produces
    the same result.
    
    Patterns are processed in order - more specific patterns first,
    generic patterns last.
    
    Args:
        content: Raw text content that may contain secrets
        
    Returns:
        Sanitized content with secrets replaced by placeholders
    """
    sanitized = content
    
    # Apply each pattern in order (specific to generic)
    for pattern, redaction_type in SECRET_PATTERNS:
        # For patterns that capture groups (like key=value), we need special handling
        if '(' in pattern and ')' in pattern:
            # Check if this is a key-value pattern
            if any(kw in pattern for kw in ['api', 'secret', 'password', 'token', 'bearer']):
                # Replace just the value part, keep the key for context
                def replace_with_context(match):
                    # If there are 2 groups, first is the key, second is the value
                    if len(match.groups()) >= 2:
                        key_part = match.group(1)
                        return f"{key_part}=[REDACTED-{redaction_type}]"
                    # For bearer tokens, group 1 is "bearer ", group 2 is the token
                    elif 'bearer' in pattern.lower():
                        return f"{match.group(1)}[REDACTED-{redaction_type}]"
                    else:
                        return f"[REDACTED-{redaction_type}]"
                
                sanitized = re.sub(pattern, replace_with_context, sanitized)
            else:
                # For other grouped patterns, just replace the whole match
                sanitized = re.sub(pattern, f"[REDACTED-{redaction_type}]", sanitized)
        else:
            # Simple pattern without groups - replace the whole match
            sanitized = re.sub(pattern, f"[REDACTED-{redaction_type}]", sanitized)
    
    return sanitized


# =============================================================================
# Post-Generation Validation
# =============================================================================

def validate_no_secrets(content: str) -> Tuple[bool, List[str]]:
    """
    Validate that content contains no unredacted secrets.
    
    This is the final safety check before writing content to disk or
    displaying it to the user. Should be called after all processing.
    
    Args:
        content: Content to validate
        
    Returns:
        Tuple of (is_valid, list_of_violations)
        - is_valid: True if no secrets detected, False otherwise
        - violations: List of human-readable violation messages
    """
    violations = []
    
    # Check for unredacted API keys (known formats)
    if re.search(r'sk-(?:proj-)?[a-zA-Z0-9]{30,}', content):
        violations.append("Found potential OpenAI API key (sk-...)")
    
    if re.search(r'sk-ant-[a-zA-Z0-9\-_]{90,}', content):
        violations.append("Found potential Anthropic API key (sk-ant-...)")
    
    if re.search(r'ak-[a-zA-Z0-9]{20,}', content):
        violations.append("Found potential Composio API key (ak-...)")
    
    if re.search(r'gh[pousr]_[A-Za-z0-9]{20,}', content):
        violations.append("Found potential GitHub token (gh*_...)")
    
    if re.search(r'AKIA[A-Z0-9]{16}', content):
        violations.append("Found potential AWS access key (AKIA...)")
    
    if re.search(r'ASIA[A-Z0-9]{16}', content):
        violations.append("Found potential AWS session key (ASIA...)")
    
    # Check for unredacted base64 (high entropy strings)
    # Only flag if not already marked as redacted
    base64_matches = re.findall(r'\b[A-Za-z0-9+/]{40,}={0,2}\b', content)
    for match in base64_matches:
        if 'REDACTED' not in match:
            violations.append(f"Found unredacted high-entropy base64 string")
            break  # Only report once
    
    # Check for unredacted password assignments
    # Look for password=<value> where value is NOT [REDACTED...]
    password_pattern = r'(?i)password\s*[=:]\s*["\']?([^\s"\'\[]+)'
    for match in re.finditer(password_pattern, content):
        value = match.group(1)
        if not value.startswith('[REDACTED'):
            violations.append("Found unredacted password assignment")
            break
    
    # Check for JWT tokens
    if re.search(r'eyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}', content):
        violations.append("Found potential JWT token")
    
    # Check for SSH private keys
    if re.search(r'-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----', content):
        violations.append("Found SSH private key header")
    
    # Check for connection strings with embedded credentials
    if re.search(r'\w+://[^:@\s]+:[^@\s]+@', content):
        # Make sure it's not already redacted
        conn_matches = re.findall(r'\w+://[^:@\s]+:[^@\s]+@\S+', content)
        for match in conn_matches:
            if 'REDACTED' not in match:
                violations.append("Found connection string with embedded credentials")
                break
    
    return (len(violations) == 0, violations)


# =============================================================================
# Convenience Functions
# =============================================================================

def safe_sanitize(content: str) -> str:
    """
    Sanitize content and ensure it's valid (no secrets remain).
    
    This is a convenience function that combines sanitization and validation.
    If secrets are still detected after sanitization, logs a warning but
    returns the sanitized content anyway (defense in depth).
    
    Args:
        content: Content to sanitize
        
    Returns:
        Sanitized and validated content
    """
    sanitized = sanitize_content(content)
    is_valid, violations = validate_no_secrets(sanitized)
    
    if not is_valid:
        # This should not happen if our patterns are correct
        # Log to stderr as a warning
        import sys
        print(
            f"Warning: Secrets still detected after sanitization: {violations}",
            file=sys.stderr
        )
    
    return sanitized
