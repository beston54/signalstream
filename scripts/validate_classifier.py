"""
Classifier Validation Framework

Compares the project's LLM-based sentiment classifier against a VADER
baseline to measure inter-rater agreement, per-class precision/recall/F1,
and overall accuracy.

Usage examples
--------------
# Dry-run (VADER only, no API calls):
    python -m scripts.validate_classifier --dry-run

# Dry-run with a specific input file:
    python -m scripts.validate_classifier --input data/raw/posts_2026-02-25.json --dry-run

# Full validation (requires LLM API keys to be configured):
    python -m scripts.validate_classifier

# Full validation, saving results to JSON:
    python -m scripts.validate_classifier --output reports/classifier_validation.json

# Custom config:
    python -m scripts.validate_classifier --config config.yaml --input data/sample/sample_posts.json
"""

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except ImportError:
    print(
        "ERROR: vaderSentiment is not installed.\n"
        "Install it with:  pip install vaderSentiment>=3.3.2\n"
        "Or:               pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------

try:
    from scripts.analyzer import analyze_single_post, load_posts_json
    from scripts.config_utils import load_config_file
except ImportError:
    # Allow running directly: python scripts/validate_classifier.py
    from analyzer import analyze_single_post, load_posts_json
    from config_utils import load_config_file

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The four labels the LLM classifier can emit (see analyzer.py prompt).
SENTIMENT_LABELS = ["positive", "negative", "neutral", "mixed"]


# ---------------------------------------------------------------------------
# VADER baseline
# ---------------------------------------------------------------------------

def vader_classify(text: str, analyzer: SentimentIntensityAnalyzer) -> str:
    """Classify *text* into positive / negative / neutral using VADER.

    Thresholds follow the standard VADER recommendation:
        compound >= 0.05  -> positive
        compound <= -0.05 -> negative
        otherwise         -> neutral

    VADER has no native "mixed" label, so this function never returns it.
    """
    scores = analyzer.polarity_scores(text)
    compound = scores["compound"]
    if compound >= 0.05:
        return "positive"
    if compound <= -0.05:
        return "negative"
    return "neutral"


def vader_classify_post(post: Dict[str, Any], analyzer: SentimentIntensityAnalyzer) -> str:
    """Build a representative text blob from a post and classify it.

    Combines title and body text, plus the first top-comment body (if
    present), mirroring the context that the LLM prompt sees.
    """
    parts: List[str] = []
    if post.get("title"):
        parts.append(str(post["title"]))
    if post.get("text"):
        parts.append(str(post["text"]))
    # Include top comment for additional signal (matches LLM prompt context).
    top_comments = post.get("top_comments")
    if isinstance(top_comments, list) and top_comments:
        first = top_comments[0]
        if isinstance(first, dict) and first.get("body"):
            parts.append(str(first["body"]))
    combined = " ".join(parts).strip()
    if not combined:
        return "neutral"
    return vader_classify(combined, analyzer)


# ---------------------------------------------------------------------------
# LLM classifier wrapper
# ---------------------------------------------------------------------------

def llm_classify_post(post: Dict[str, Any], config: dict) -> str:
    """Run the project's LLM sentiment classifier on a single post.

    Returns one of: positive, negative, neutral, mixed, unknown.
    """
    try:
        result = analyze_single_post(post, config)
        sentiment = result.get("sentiment_analysis", {}).get("sentiment", "unknown")
        return sentiment
    except Exception as exc:
        logger.warning("LLM classification failed for %s: %s", post.get("post_id", "?"), exc)
        return "unknown"


# ---------------------------------------------------------------------------
# Normalisation helper
# ---------------------------------------------------------------------------

def _normalize_label(label: str) -> str:
    """Map 'mixed' to 'neutral' so both classifiers share the same label set.

    VADER never produces 'mixed', but the LLM sometimes does.  For
    agreement metrics we fold 'mixed' into 'neutral' (closest semantically
    to the zero-compound region).
    """
    label = label.strip().lower()
    if label == "mixed":
        return "neutral"
    if label in {"positive", "negative", "neutral"}:
        return label
    return "neutral"  # fallback for 'unknown' / 'error'


# ---------------------------------------------------------------------------
# Agreement & evaluation metrics
# ---------------------------------------------------------------------------

def _cohen_kappa(y_true: List[str], y_pred: List[str], labels: List[str]) -> float:
    """Compute Cohen's kappa between two lists of categorical labels.

    Implements the standard formula without requiring scikit-learn.
    """
    n = len(y_true)
    if n == 0:
        return 0.0

    # Build confusion counts
    pair_counts: Counter = Counter()
    for t, p in zip(y_true, y_pred):
        pair_counts[(t, p)] += 1

    # Observed agreement
    po = sum(pair_counts[(l, l)] for l in labels) / n

    # Expected agreement (product of marginals)
    true_counts = Counter(y_true)
    pred_counts = Counter(y_pred)
    pe = sum((true_counts[l] / n) * (pred_counts[l] / n) for l in labels)

    if pe == 1.0:
        return 1.0  # perfect agreement by chance
    return (po - pe) / (1.0 - pe)


def _confusion_matrix(
    y_true: List[str],
    y_pred: List[str],
    labels: List[str],
) -> List[List[int]]:
    """Return a len(labels) x len(labels) confusion matrix (list of lists).

    Rows = true (VADER), Columns = predicted (LLM).
    """
    idx = {l: i for i, l in enumerate(labels)}
    n = len(labels)
    matrix = [[0] * n for _ in range(n)]
    for t, p in zip(y_true, y_pred):
        ri = idx.get(t)
        ci = idx.get(p)
        if ri is not None and ci is not None:
            matrix[ri][ci] += 1
    return matrix


def _per_class_metrics(
    y_true: List[str],
    y_pred: List[str],
    labels: List[str],
) -> Dict[str, Dict[str, float]]:
    """Compute per-class precision, recall, and F1.

    Returns a dict keyed by label, each containing precision, recall, f1,
    and support (count in y_true).
    """
    results: Dict[str, Dict[str, float]] = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        support = tp + fn

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        results[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }
    return results


def _accuracy(y_true: List[str], y_pred: List[str]) -> float:
    """Overall accuracy (fraction of matching labels)."""
    if not y_true:
        return 0.0
    return sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)


# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------

def _print_distribution(title: str, labels: List[str]) -> None:
    """Print a frequency table for a list of labels."""
    counts = Counter(labels)
    total = len(labels)
    print(f"\n{'=' * 52}")
    print(f"  {title}")
    print(f"{'=' * 52}")
    print(f"  {'Label':<12} {'Count':>6} {'Pct':>8}")
    print(f"  {'-' * 30}")
    for label in ["positive", "negative", "neutral", "mixed"]:
        c = counts.get(label, 0)
        pct = (c / total * 100) if total else 0.0
        print(f"  {label:<12} {c:>6} {pct:>7.1f}%")
    print(f"  {'-' * 30}")
    print(f"  {'Total':<12} {total:>6}")


def _print_confusion_matrix(matrix: List[List[int]], labels: List[str]) -> None:
    """Print a confusion matrix with row/column headers."""
    col_w = 10
    print(f"\n{'=' * 52}")
    print("  Confusion Matrix  (rows=VADER, cols=LLM)")
    print(f"{'=' * 52}")
    header = "  " + " " * col_w + "".join(f"{l:>{col_w}}" for l in labels)
    print(header)
    for i, label in enumerate(labels):
        row_vals = "".join(f"{matrix[i][j]:>{col_w}}" for j in range(len(labels)))
        print(f"  {label:<{col_w}}{row_vals}")


def _print_classification_report(
    per_class: Dict[str, Dict[str, float]],
    accuracy_val: float,
    kappa: float,
) -> None:
    """Print a scikit-learn-style classification report."""
    print(f"\n{'=' * 52}")
    print("  Classification Report  (VADER as ground truth)")
    print(f"{'=' * 52}")
    print(f"  {'Label':<12} {'Prec':>8} {'Recall':>8} {'F1':>8} {'Support':>8}")
    print(f"  {'-' * 44}")
    total_support = 0
    weighted_p = weighted_r = weighted_f = 0.0
    for label in ["positive", "negative", "neutral"]:
        m = per_class.get(label, {"precision": 0, "recall": 0, "f1": 0, "support": 0})
        print(
            f"  {label:<12} {m['precision']:>8.4f} {m['recall']:>8.4f} "
            f"{m['f1']:>8.4f} {m['support']:>8}"
        )
        total_support += m["support"]
        weighted_p += m["precision"] * m["support"]
        weighted_r += m["recall"] * m["support"]
        weighted_f += m["f1"] * m["support"]
    print(f"  {'-' * 44}")
    if total_support > 0:
        print(
            f"  {'weighted avg':<12} {weighted_p / total_support:>8.4f} "
            f"{weighted_r / total_support:>8.4f} {weighted_f / total_support:>8.4f} "
            f"{total_support:>8}"
        )
    print(f"\n  Accuracy:      {accuracy_val:.4f}")
    print(f"  Cohen's kappa: {kappa:.4f}")


# ---------------------------------------------------------------------------
# Main validation logic
# ---------------------------------------------------------------------------

def run_validation(
    posts: List[Dict[str, Any]],
    config: Optional[dict],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run the full validation pipeline.

    Args:
        posts: List of post dicts (same format as sample_posts.json).
        config: Pipeline config dict (needed for LLM calls).
        dry_run: If True, skip LLM calls and only report VADER distribution.

    Returns:
        A results dict suitable for JSON serialisation.
    """
    vader = SentimentIntensityAnalyzer()

    # -- VADER baseline -------------------------------------------------------
    vader_raw: List[str] = []
    for post in posts:
        vader_raw.append(vader_classify_post(post, vader))

    _print_distribution("VADER Sentiment Distribution", vader_raw)

    if dry_run:
        return {
            "mode": "dry_run",
            "n_posts": len(posts),
            "vader_distribution": dict(Counter(vader_raw)),
        }

    # -- LLM classifier -------------------------------------------------------
    if config is None:
        print("\nERROR: Config is required for LLM classification.", file=sys.stderr)
        sys.exit(1)

    llm_raw: List[str] = []
    for i, post in enumerate(posts, 1):
        print(f"  LLM classifying post {i}/{len(posts)}: {post.get('post_id', '?')}", end="\r")
        llm_raw.append(llm_classify_post(post, config))
    print()  # clear the carriage return line

    _print_distribution("LLM Sentiment Distribution (raw)", llm_raw)

    # -- Normalise labels for comparison --------------------------------------
    eval_labels = ["positive", "negative", "neutral"]
    vader_norm = [_normalize_label(v) for v in vader_raw]
    llm_norm = [_normalize_label(l) for l in llm_raw]

    # -- Compute metrics ------------------------------------------------------
    kappa = _cohen_kappa(vader_norm, llm_norm, eval_labels)
    cm = _confusion_matrix(vader_norm, llm_norm, eval_labels)
    per_class = _per_class_metrics(vader_norm, llm_norm, eval_labels)
    acc = _accuracy(vader_norm, llm_norm)

    # -- Display results ------------------------------------------------------
    _print_confusion_matrix(cm, eval_labels)
    _print_classification_report(per_class, acc, kappa)

    # -- Build serialisable results dict --------------------------------------
    results: Dict[str, Any] = {
        "mode": "full",
        "n_posts": len(posts),
        "vader_distribution": dict(Counter(vader_raw)),
        "llm_distribution_raw": dict(Counter(llm_raw)),
        "vader_distribution_normalized": dict(Counter(vader_norm)),
        "llm_distribution_normalized": dict(Counter(llm_norm)),
        "cohens_kappa": round(kappa, 4),
        "accuracy": round(acc, 4),
        "confusion_matrix": {
            "labels": eval_labels,
            "matrix": cm,
        },
        "per_class_metrics": per_class,
        "per_post": [],
    }

    for post, v_raw, l_raw, v_norm, l_norm in zip(posts, vader_raw, llm_raw, vader_norm, llm_norm):
        results["per_post"].append({
            "post_id": post.get("post_id", "unknown"),
            "vader_raw": v_raw,
            "llm_raw": l_raw,
            "vader_normalized": v_norm,
            "llm_normalized": l_norm,
            "agree": v_norm == l_norm,
        })

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the LLM sentiment classifier against a VADER baseline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m scripts.validate_classifier --dry-run\n"
            "  python -m scripts.validate_classifier --input data/sample/sample_posts.json\n"
            "  python -m scripts.validate_classifier --output reports/classifier_validation.json\n"
        ),
    )
    parser.add_argument(
        "--input",
        default=None,
        help=(
            "Path to a JSON file of posts. "
            "Defaults to data/sample/sample_posts.json if it exists."
        ),
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the pipeline config file (default: config.yaml).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Path to write JSON results. "
            "If omitted, results are printed to console only."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only run VADER (no LLM API calls). Reports VADER distribution.",
    )
    args = parser.parse_args()

    # -- Resolve input file ---------------------------------------------------
    input_path: Optional[Path] = None
    if args.input:
        input_path = Path(args.input)
        if not input_path.is_absolute():
            input_path = PROJECT_ROOT / input_path
    else:
        default = PROJECT_ROOT / "data" / "sample" / "sample_posts.json"
        if default.exists():
            input_path = default
            print(f"Using default input: {input_path}")
        else:
            print(
                "ERROR: No input file specified and data/sample/sample_posts.json not found.\n"
                "Provide --input <path-to-posts.json>.",
                file=sys.stderr,
            )
            sys.exit(1)

    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # -- Load posts -----------------------------------------------------------
    posts = load_posts_json(str(input_path))
    print(f"Loaded {len(posts)} posts from {input_path}")

    # -- Load config (only needed for LLM mode) ------------------------------
    config: Optional[dict] = None
    if not args.dry_run:
        try:
            config = load_config_file(args.config)
        except Exception as exc:
            print(f"ERROR: Could not load config ({args.config}): {exc}", file=sys.stderr)
            sys.exit(1)

    # -- Run validation -------------------------------------------------------
    results = run_validation(posts, config, dry_run=args.dry_run)

    # -- Optionally save JSON output ------------------------------------------
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
