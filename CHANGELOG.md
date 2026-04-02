# Changelog

All notable changes to Signalstream will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Unreleased

### Added

- Reddit public data collection with rate limiting
- LLM provider system: Claude, OpenAI-compatible, Ollama
- Per-post sentiment and emotion analysis with checkpointing
- Cross-post thematic analysis with chunking
- Flask web interface with interactive Chart.js dashboard
- PDF report generation via WeasyPrint (optional)
- JSON export
- Security middleware: CSP, CSRF, API key redaction
- SSRF protection for custom LLM endpoints (with localhost exemption)
- Docker support with Ollama sidecar
- Demo data for first-run experience
- SQLite storage with WAL mode and auto-migration
