# Security Policy

## Supported Versions

We release security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security seriously. If you discover a vulnerability in `memory-sync`, please report it responsibly.

### How to Report

**Please DO NOT open a public issue for security vulnerabilities.**

Instead, report privately via one of these methods:

1. **GitHub Private Vulnerability Reporting** (preferred)
   - Go to the Security tab → Advisories → Report a vulnerability
   - This keeps details private until a fix is released

2. **Email** (if GitHub reporting is unavailable)
   - Contact the maintainer directly
   - Allow up to 48 hours for initial response

### What to Include

A good vulnerability report should include:

- **Description**: Clear explanation of the issue
- **Impact**: What could an attacker do?
- **Reproduction**: Steps to reproduce (proof-of-concept if possible)
- **Version**: Affected version(s)
- **Environment**: OS, Python version, OpenClaw version if relevant

### Response Timeline

| Phase | Target |
|-------|--------|
| Initial acknowledgment | 48 hours |
| Investigation complete | 7 days |
| Fix released | 14 days (critical), 30 days (high) |
| Public disclosure | After fix is available |

We will coordinate disclosure to give users time to update before details are made public.

## Scope

### In Scope

Security issues related to:
- JSONL log parsing and file handling
- Path traversal in session log access
- Command injection through CLI arguments
- Information disclosure from session logs
- Privilege escalation via file permissions

### Out of Scope

- Issues in OpenClaw itself (report to OpenClaw project)
- Session log content that users voluntarily parse
- Environment misconfigurations (file permissions, etc.)
- Social engineering attacks

## Security Considerations

`memory-sync` is designed to parse OpenClaw session logs, which may contain:
- Conversation history
- Tool call arguments (potentially sensitive)
- File paths from your system

**Best practices:**
- Run only on logs you own
- Be cautious sharing generated memory files
- Review generated content before committing to git
- Keep session logs and memory files with appropriate permissions

## Disclosure Policy

We follow responsible disclosure:
1. Reporter submits private report
2. We investigate and develop fix
3. Fix is released and announced
4. Public disclosure after reasonable delay (typically 30 days)

We credit reporters who follow this policy (with their permission).

## Acknowledgments

We thank security researchers and community members who help keep `memory-sync` safe.

---

*Last updated: 2026-02-06*
