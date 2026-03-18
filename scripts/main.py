#!/usr/bin/env python3
"""
Main Orchestration Script

Coordinates the full social intelligence pipeline:
collection -> analysis -> themes -> report
"""

import argparse
import logging
import sys
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict
import yaml

# Add scripts directory to path for imports
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from collector import (
    load_config,
    collect_all_posts,
    save_raw_posts,
    deduplicate_posts,
    get_collection_provider,
)
from x_collector import collect_all_x_posts
from analyzer import (
    analyze_all_posts,
    save_analyzed_posts,
    check_ollama_running,
    load_posts_json
)
from thematic_analyzer import (
    analyze_all_themes,
    calculate_overall_statistics,
    save_thematic_analysis
)
from report_generator import create_report


def _project_path(*parts: str) -> Path:
    """Resolve a path relative to the project root."""
    return PROJECT_ROOT.joinpath(*parts)


def setup_logging(config: dict, verbose: bool = False) -> logging.Logger:
    """
    Configure logging based on config settings.

    Args:
        config: Configuration dictionary with logging settings
        verbose: Enable debug logging

    Returns:
        Configured logger instance
    """
    log_config = config.get('logging', {})
    log_level = logging.DEBUG if verbose else getattr(logging, log_config.get('level', 'INFO'))
    log_file = log_config.get('file', 'logs/reddit_intelligence.log')

    # Ensure log directory exists
    log_path = Path(log_file)
    if not log_path.is_absolute():
        log_path = _project_path(str(log_path))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create logger
    logger = logging.getLogger('reddit_intelligence')
    logger.setLevel(log_level)

    # Clear existing handlers
    logger.handlers = []

    # File handler
    file_handler = logging.FileHandler(str(log_path), encoding='utf-8')
    file_handler.setLevel(log_level)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger


def validate_environment(
    config: dict,
    logger: logging.Logger,
    *,
    require_collection: bool = True,
    require_ollama: bool = True,
    require_report: bool = True,
) -> list:
    """
    Check that all required services and dependencies are available.

    Args:
        config: Full configuration dictionary
        logger: Logger instance

    Returns:
        List of error messages (empty if all valid)
    """
    errors = []
    sources_cfg = config.get('sources', {})
    reddit_enabled = bool(sources_cfg.get('reddit', True)) and require_collection
    x_enabled = bool(sources_cfg.get('x', False)) and require_collection

    # Check analysis provider availability
    analysis_provider = str(config.get('analysis', {}).get('provider', 'auto')).strip().lower()
    if require_ollama:
        ollama_url = config.get('ollama', {}).get('base_url', 'http://localhost:11434')
        if not check_ollama_running(ollama_url):
            if analysis_provider == 'ollama':
                errors.append(f"Ollama is not running at {ollama_url}. Start it with: ollama serve")
            else:
                logger.warning("Ollama not running at %s (may fallback to Claude API if configured)", ollama_url)

    if analysis_provider in ('claude', 'auto'):
        claude_key = (
            config.get('analysis', {}).get('claude', {}).get('api_key')
            or os.getenv('ANTHROPIC_API_KEY')
        )
        if not claude_key and analysis_provider == 'claude':
            errors.append("Claude analysis provider selected but no API key found. "
                          "Set ANTHROPIC_API_KEY env var or analysis.claude.api_key in config.")

    # Check Reddit collector mode / credentials
    if reddit_enabled:
        collector_provider = get_collection_provider(config)
        if collector_provider == 'praw':
            reddit_config = config.get('reddit', {})
            if reddit_config.get('client_id', '').startswith('YOUR_'):
                errors.append("Reddit client_id not configured in config.yaml (required for PRAW mode)")
            if reddit_config.get('client_secret', '').startswith('YOUR_'):
                errors.append("Reddit client_secret not configured in config.yaml (required for PRAW mode)")
        else:
            logger.info("Using Reddit public JSON collector (no API keys required)")
    else:
        logger.info("Reddit collection disabled")

    # Check X API key (optional source but required if enabled)
    if x_enabled:
        x_cfg = config.get('x', {})
        x_key = (
            x_cfg.get('api_key')
            or x_cfg.get('bearer_token')
            or os.getenv('GETX_API_KEY')
            or os.getenv('X_API_BEARER_TOKEN')
            or os.getenv('TWITTER_BEARER_TOKEN')
        )
        if not x_key:
            errors.append(
                "X source enabled but no X API key/bearer token configured "
                "(set x.api_key in config.yaml or GETX_API_KEY env var)"
            )
    else:
        logger.info("X collection disabled")

    # Check required directories exist or can be created
    required_dirs = [
        _project_path('data', 'raw'),
        _project_path('data', 'analyzed'),
        _project_path('reports'),
        _project_path('logs'),
        _project_path('assets', 'fonts'),
        _project_path('assets', 'images', 'cache'),
    ]
    for dir_path in required_dirs:
        try:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Cannot create directory {dir_path}: {e}")

    # Check templates exist
    if require_report:
        template_dir = _project_path('templates')
        if not template_dir.exists():
            errors.append("Templates directory not found")
        else:
            if not (template_dir / 'report_template.html').exists():
                errors.append("report_template.html not found in templates/")
            if not (template_dir / 'report_styles.css').exists():
                errors.append("report_styles.css not found in templates/")

    # Check font files exist (warn only, not blocking)
    font_dir = _project_path('assets', 'fonts')
    required_fonts = ['DMSans-Regular.ttf', 'SourceSerif4-Regular.ttf', 'Caveat-Regular.ttf']
    for font in required_fonts:
        if not (font_dir / font).exists():
            logger.warning(f"Font file missing: {font_dir / font} "
                           f"(report will use fallback fonts)")

    return errors


def get_enabled_sources(config: dict) -> Dict[str, bool]:
    """Return normalized enabled/disabled state for supported collection sources."""
    sources_cfg = config.get('sources', {})
    return {
        'reddit': bool(sources_cfg.get('reddit', True)),
        'x': bool(sources_cfg.get('x', False)),
    }


def resolve_x_credentials(config: dict) -> Dict[str, str]:
    """
    Resolve X API credentials from config/environment.

    For GetXAPI-style gateways, the same key can be used as both bearer token
    and `x-api-key` header.
    """
    x_cfg = config.get('x', {})
    api_key = (
        x_cfg.get('api_key')
        or os.getenv('GETX_API_KEY')
    )
    bearer_token = (
        x_cfg.get('bearer_token')
        or os.getenv('X_API_BEARER_TOKEN')
        or os.getenv('TWITTER_BEARER_TOKEN')
        or api_key
    )

    return {
        'api_key': api_key or '',
        'bearer_token': bearer_token or '',
    }


def cleanup_old_data(data_dir: str, retention_days: int, logger: logging.Logger) -> int:
    """
    Delete raw data files older than retention period (GDPR compliance).

    Args:
        data_dir: Path to data directory
        retention_days: Maximum age of files to keep
        logger: Logger instance

    Returns:
        Number of files deleted
    """
    data_path = Path(data_dir)
    if not data_path.is_absolute():
        data_path = _project_path(str(data_path))
    if not data_path.exists():
        return 0

    try:
        retention_days_int = max(1, int(retention_days))
    except (TypeError, ValueError):
        retention_days_int = 30
        logger.warning("Invalid output.data_retention_days=%r; defaulting to 30", retention_days)

    cutoff_date = datetime.now() - timedelta(days=retention_days_int)
    deleted_count = 0

    for json_file in data_path.glob('*.json'):
        file_mtime = datetime.fromtimestamp(json_file.stat().st_mtime)
        if file_mtime < cutoff_date:
            try:
                json_file.unlink()
                deleted_count += 1
                logger.info(f"Deleted old file: {json_file}")
            except Exception as e:
                logger.warning(f"Could not delete {json_file}: {e}")

    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} files older than {retention_days_int} days")

    return deleted_count


def run_collection_phase(
    config: dict,
    logger: logging.Logger,
    dry_run: bool = False
) -> str:
    """
    Execute the data collection phase.

    Args:
        config: Full configuration dictionary
        logger: Logger instance
        dry_run: If True, limit to 10 posts for testing

    Returns:
        Path to saved posts JSON, or empty string on failure
    """
    logger.info("=" * 50)
    logger.info("PHASE 1: Data Collection")
    logger.info("=" * 50)

    try:
        enabled_sources = get_enabled_sources(config)
        logger.info(
            "Enabled sources: %s",
            ", ".join([name for name, enabled in enabled_sources.items() if enabled]) or "none"
        )

        combined_posts = []

        if enabled_sources.get('reddit'):
            reddit_posts = collect_all_posts(config, dry_run=dry_run)
            logger.info("Collected %d Reddit posts", len(reddit_posts))
            combined_posts.extend(reddit_posts)

        if enabled_sources.get('x'):
            x_creds = resolve_x_credentials(config)
            if not x_creds['bearer_token']:
                raise ValueError(
                    "X source is enabled but no X API key/bearer token is configured "
                    "(x.api_key / x.bearer_token or GETX_API_KEY)"
                )

            x_posts = collect_all_x_posts(
                config=config,
                bearer_token=x_creds['bearer_token'],
                dry_run=dry_run,
                api_key_header=x_creds['api_key'] or None,
            )
            logger.info("Collected %d X posts", len(x_posts))
            combined_posts.extend(x_posts)

        if not combined_posts:
            logger.warning("No posts collected")
            return ""

        combined_posts = deduplicate_posts(combined_posts)
        filepath = save_raw_posts(combined_posts, str(_project_path('data', 'raw')))
        logger.info(f"Collected {len(combined_posts)} combined posts -> {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"Collection phase failed: {e}")
        return ""


def run_analysis_phase(
    posts_path: str,
    config: dict,
    logger: logging.Logger
) -> str:
    """
    Execute the sentiment analysis phase.

    Args:
        posts_path: Path to collected posts JSON
        config: Full configuration dictionary
        logger: Logger instance

    Returns:
        Path to analyzed posts JSON, or empty string on failure
    """
    logger.info("=" * 50)
    logger.info("PHASE 2: Sentiment Analysis")
    logger.info("=" * 50)

    try:
        # Load posts
        posts = load_posts_json(posts_path)
        logger.info(f"Loaded {len(posts)} posts for analysis")

        # Analyze
        def progress(current, total):
            if current % 5 == 0 or current == total:
                logger.info(f"Analysis progress: {current}/{total}")

        analyzed = analyze_all_posts(posts, config, progress_callback=progress)

        # Save
        filepath = save_analyzed_posts(analyzed, str(_project_path('data', 'analyzed')))
        logger.info(f"Analyzed {len(analyzed)} posts -> {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"Analysis phase failed: {e}")
        return ""


def run_thematic_phase(
    analyzed_path: str,
    config: dict,
    logger: logging.Logger
) -> str:
    """
    Execute the thematic analysis phase.

    Args:
        analyzed_path: Path to analyzed posts JSON
        config: Full configuration dictionary
        logger: Logger instance

    Returns:
        Path to themes JSON, or empty string on failure
    """
    logger.info("=" * 50)
    logger.info("PHASE 3: Thematic Analysis")
    logger.info("=" * 50)

    try:
        # Load analyzed posts
        with open(analyzed_path, 'r', encoding='utf-8') as f:
            posts = json.load(f)
        logger.info(f"Loaded {len(posts)} analyzed posts")

        # Run thematic analysis
        themes = analyze_all_themes(posts, config)

        # Calculate statistics
        statistics = calculate_overall_statistics(posts, themes)

        # Save
        filepath = save_thematic_analysis(themes, statistics, str(_project_path('data', 'analyzed')))
        logger.info(f"Thematic analysis complete -> {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"Thematic analysis phase failed: {e}")
        return ""


def run_report_phase(
    analyzed_path: str,
    themes_path: str,
    config: dict,
    logger: logging.Logger
) -> str:
    """
    Execute the report generation phase.

    Args:
        analyzed_path: Path to analyzed posts JSON
        themes_path: Path to themes JSON
        config: Full configuration dictionary
        logger: Logger instance

    Returns:
        Path to generated PDF, or empty string on failure
    """
    logger.info("=" * 50)
    logger.info("PHASE 4: Report Generation")
    logger.info("=" * 50)

    try:
        pdf_path = create_report(
            analyzed_posts_path=analyzed_path,
            themes_path=themes_path,
            config=config,
            output_dir=str(_project_path('reports')),
            template_dir=str(_project_path('templates'))
        )
        logger.info(f"Report generated -> {pdf_path}")
        return pdf_path

    except Exception as e:
        logger.error(f"Report generation phase failed: {e}")
        return ""


def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description='Social Intelligence Pipeline - Collect, analyze, and report on combined social discussions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Run full pipeline
  python main.py --dry-run          # Test with limited data
  python main.py --skip-collection  # Use existing collected data
  python main.py --skip-thematic    # Reuse latest themes file
  python main.py --only-report      # Only generate report from existing analyzed + themes files

For first-time setup:
  1. Edit config.yaml source settings (Reddit and/or X)
  2. If using X via GetXAPI, set GETX_API_KEY in your shell (or x.api_key in config)
  3. If using Reddit PRAW mode, add Reddit API credentials (optional in public_json mode)
  4. Ensure Ollama is running: ollama serve
  5. Run: python main.py --dry-run
        """
    )

    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Test mode: limit to 10 posts, skip some validations'
    )
    parser.add_argument(
        '--skip-collection',
        action='store_true',
        help='Skip collection phase, use most recent raw data'
    )
    parser.add_argument(
        '--skip-analysis',
        action='store_true',
        help='Skip analysis phase, use most recent analyzed data'
    )
    parser.add_argument(
        '--skip-thematic',
        action='store_true',
        help='Skip thematic analysis phase, use most recent themes data'
    )
    parser.add_argument(
        '--only-report',
        action='store_true',
        help='Only generate report from existing analyzed + themes files (implies --skip-collection --skip-analysis --skip-thematic)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose (debug) logging'
    )
    parser.add_argument(
        '--no-cleanup',
        action='store_true',
        help='Skip old data cleanup (GDPR retention)'
    )

    return parser.parse_args()


def find_latest_file(directory: str, prefix: str) -> str:
    """Find the most recent file with given prefix in directory."""
    path = Path(directory)
    if not path.is_absolute():
        path = _project_path(str(path))
    if not path.exists():
        return ""

    files = list(path.glob(f"{prefix}*.json"))
    if not files:
        return ""

    return str(max(files, key=lambda p: p.stat().st_mtime))


def main():
    """
    Main entry point for the social intelligence pipeline.

    Workflow:
    1. Parse arguments and load config
    2. Setup logging
    3. Validate environment
    4. Cleanup old data (GDPR)
    5. Run collection (unless skipped)
    6. Run analysis (unless skipped)
    7. Run thematic analysis (unless skipped)
    8. Generate report
    9. Log summary and exit
    """
    # Parse arguments
    args = parse_arguments()

    # Handle --only-report flag
    if args.only_report:
        args.skip_collection = True
        args.skip_analysis = True
        args.skip_thematic = True

    # Load configuration
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"Error: Configuration file not found: {args.config}")
        print("Make sure config.yaml exists with your source settings.")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error: Invalid configuration file: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Error: Invalid configuration values: {e}")
        sys.exit(1)

    # Setup logging
    logger = setup_logging(config, args.verbose)
    logger.info("Social Intelligence Pipeline Starting")
    logger.info(f"Configuration: {args.config}")
    logger.info(f"Dry run: {args.dry_run}")

    require_collection = not args.skip_collection
    # Only require Ollama if analysis/thematic phases will run AND the
    # configured provider is not purely "claude".
    analysis_provider = str(config.get("analysis", {}).get("provider", "auto")).strip().lower()
    require_ollama = (
        ((not args.skip_analysis) or (not args.skip_thematic))
        and analysis_provider != "claude"
    )
    require_report = True

    # Validate environment (allow dry-run to continue on non-fatal setup issues)
    errors = validate_environment(
        config,
        logger,
        require_collection=require_collection,
        require_ollama=require_ollama,
        require_report=require_report,
    )
    if errors:
        for error in errors:
            logger.error(error)
        if not args.dry_run:
            logger.error("Environment validation failed. Fix errors and try again.")
            sys.exit(1)
        logger.warning("Continuing in dry-run mode despite validation errors")

    # Cleanup old data (GDPR compliance)
    if not args.no_cleanup:
        retention_days = config.get('output', {}).get('data_retention_days', 30)
        cleanup_old_data(str(_project_path('data', 'raw')), retention_days, logger)

    # Track file paths through pipeline
    posts_path = ""
    analyzed_path = ""
    themes_path = ""

    # Phase 1: Collection
    if not args.skip_collection:
        posts_path = run_collection_phase(config, logger, args.dry_run)
        if not posts_path:
            logger.error("Collection failed, cannot continue")
            sys.exit(1)
    else:
        posts_path = find_latest_file(str(_project_path('data', 'raw')), 'posts_')
        if not posts_path:
            # Try sample data
            sample_path = _project_path('data', 'sample', 'sample_posts.json')
            if sample_path.exists():
                posts_path = str(sample_path)
                logger.info(f"Using sample data: {posts_path}")
            else:
                logger.error("No raw data found. Run without --skip-collection first.")
                sys.exit(1)
        else:
            logger.info(f"Using existing raw data: {posts_path}")

    # Phase 2: Analysis
    if not args.skip_analysis:
        analyzed_path = run_analysis_phase(posts_path, config, logger)
        if not analyzed_path:
            logger.error("Analysis failed, cannot continue")
            sys.exit(1)
    else:
        analyzed_path = find_latest_file(str(_project_path('data', 'analyzed')), 'analyzed_')
        if not analyzed_path:
            logger.error("No analyzed data found. Run without --skip-analysis first.")
            sys.exit(1)
        logger.info(f"Using existing analyzed data: {analyzed_path}")

    # Phase 3: Thematic Analysis
    if not args.skip_thematic:
        themes_path = run_thematic_phase(analyzed_path, config, logger)
        if not themes_path:
            logger.error("Thematic analysis failed, cannot continue")
            sys.exit(1)
    else:
        themes_path = find_latest_file(str(_project_path('data', 'analyzed')), 'themes_')
        if not themes_path:
            logger.error("No themes data found. Run without --skip-thematic first.")
            sys.exit(1)
        logger.info(f"Using existing themes data: {themes_path}")

    # Phase 4: Report Generation
    report_path = run_report_phase(analyzed_path, themes_path, config, logger)
    if not report_path:
        logger.error("Report generation failed")
        sys.exit(1)

    # Summary
    logger.info("=" * 50)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 50)
    logger.info(f"Raw data:     {posts_path}")
    logger.info(f"Analysis:     {analyzed_path}")
    logger.info(f"Themes:       {themes_path}")
    logger.info(f"Report:       {report_path}")

    print("\n" + "=" * 50)
    print("SUCCESS! Pipeline completed.")
    print("=" * 50)
    print(f"\nReport generated: {report_path}")
    print("\nOpen the PDF to view your intelligence report.")


if __name__ == "__main__":
    main()
