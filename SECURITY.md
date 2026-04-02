# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Signalstream, please report it responsibly:

1. **Do not** open a public GitHub issue
2. Email security concerns to [TODO: security email]
3. Include steps to reproduce if possible
4. We will respond within 72 hours

## Security Design

### API Key Handling

- API keys are stored in your browser's localStorage only
- Keys are sent as HTTP headers (`X-LLM-API-Key`) on each request
- Server-side middleware strips keys from request objects before any logging
- A logging filter redacts `sk-ant-*` and `sk-*` patterns from all log output
- Keys are never written to disk, database, or log files

### Content Security

- All responses include security headers (CSP, X-Frame-Options, nosniff)
- CSRF protection via double-submit cookie on all state-changing endpoints
- HTML content from Reddit is sanitized with `nh3` before storage
- Jinja2 templates use autoescaping by default
- PDF generation blocks all external resource loading

### Network Security

- Custom LLM endpoints are validated against SSRF attacks
- Private network ranges are blocked (except localhost for local LLM servers)
- The server binds to `127.0.0.1` by default
- No authentication — this is a local-first tool, not a multi-user service

### Database

- All SQL queries use parameterized statements
- No ORM — all SQL is in a single file (`db/repositories.py`) for audit
- WAL mode for concurrent reads; write serialization via threading lock

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
