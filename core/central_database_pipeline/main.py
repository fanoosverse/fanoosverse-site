"""
Module: central_database_pipeline/main.py
Description: Master Single-Ad End-to-End Pipeline Orchestrator for Fanoos.

Executes the strict single-advertisement lifecycle:
  [1. Scraper] -> RawJobAd
       │
       ▼
  [2. Extractor Agent] ◄──(Rejection Criteria)── [3. Supervisor Agent (Stage 1)]
       │ (Approved -> processed.jsonl)
       ▼
  [4. Normalizer Agent] ◄─(Rejection Criteria)── [5. Supervisor Agent (Stage 2)]
       │ (Approved -> normalized_records.jsonl & vdb_payloads.jsonl)
       ▼
  [6. PostgreSQL (`job_ads` / `dropped_ads`) + Scraper Ledger ACK]

CLI Usage Examples:
    # 1. Seed new URLs from Jobinja (1 page) and process 5 ads one-by-one:
    python main.py --platform jobinja --seed --max-pages 1 --limit 5

    # 2. Only seed URLs into database/scraper_ledger.db without processing yet:
    python main.py --platform jobinja --seed-only --max-pages 2

    # 3. Check SQLite scraper_ledger.db queue status:
    python main.py --status

    # 4. Process 5 already-seeded pending ads across all platforms:
    python main.py --limit 5

    # 5. Process ads one-by-one from an existing raw JSONL file (offline test):
    python main.py --input-jsonl path/to/raw_persian_jobs.jsonl --limit 3
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

# Ensure both central_database_pipeline/ and central_database_pipeline/scraper/ are importable
PIPELINE_DIR = Path(__file__).resolve().parent
SCRAPER_DIR = PIPELINE_DIR / "scraper"

if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))
if str(SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(SCRAPER_DIR))

import llm_config
from database.postgres_store import FanoosDataStore
from extractor.extractor_agent import build_enriched_ad_text, extract_single_ad
from normalizer.normalizer_agent import normalize_single_ad
from prompt_manager import PROMPTS_JSONL_PATH, init_prompts_jsonl
from schema import JobAd
from supervisor.supervisor_agent import supervise_extraction, supervise_normalization

logger = logging.getLogger("fanoos.main")


# =====================================================================
# Single-Ad End-to-End Execution Engine
# =====================================================================

def process_single_job_ad(
    raw_ad: Any,
    store: FanoosDataStore,
    max_rounds: int = 3,
    version: str = "v2",
) -> str:
    """
    Runs the complete Extraction <-> Supervisor and Normalization <-> Supervisor
    pipeline for ONE single job advertisement.

    Returns:
        "completed" | "dropped_extraction" | "dropped_normalization"
    """
    # 1. Unpack provenance metadata from either a `RawJobAd` instance or a JSONL dict
    if isinstance(raw_ad, dict):
        doc_id = str(
            raw_ad.get("job_id")
            or raw_ad.get("document_id")
            or f"ad-{int(datetime.now().timestamp())}"
        )
        collector = str(raw_ad.get("platform") or raw_ad.get("collector") or "scraper")
        source_url = raw_ad.get("url")
        is_expired = bool(raw_ad.get("is_expired", False))
        scraped_at_raw = raw_ad.get("scraped_at") or raw_ad.get("collected_at")
        if isinstance(scraped_at_raw, str) and len(scraped_at_raw) >= 10:
            collected_at = date.fromisoformat(scraped_at_raw[:10])
        else:
            collected_at = date.today()
    else:
        doc_id = raw_ad.job_id
        collector = raw_ad.platform
        source_url = raw_ad.url
        is_expired = raw_ad.is_expired
        collected_at = (
            raw_ad.scraped_at.date()
            if hasattr(raw_ad, "scraped_at") and raw_ad.scraped_at
            else date.today()
        )

    enriched_text = build_enriched_ad_text(raw_ad)
    logger.info("▶️ [Ad: %s] Starting single-ad pipeline (platform=%s)...", doc_id, collector)

    # =================================================================
    # STAGE 1: Extraction <-> Supervisor Feedback Loop
    # =================================================================
    approved_extracted_ad: JobAd | None = None
    prev_extract_dict: dict | None = None
    extract_criteria: list[str] = []

    for round_num in range(1, max_rounds + 1):
        logger.info("   [Ad: %s] Stage-1 Extraction (Round %d/%d)...", doc_id, round_num, max_rounds)
        candidate_ad, raw_dict, problems = extract_single_ad(
            document_id=doc_id,
            collector=collector,
            collected_at=collected_at,
            ad_text=enriched_text,
            version=version,
            previous_attempt=prev_extract_dict,
            rejection_criteria=extract_criteria if extract_criteria else None,
        )
        prev_extract_dict = raw_dict or prev_extract_dict

        # If Pydantic schema or deterministic rules failed, feed problems back into next round
        if problems or candidate_ad is None:
            extract_criteria = problems
            logger.warning(
                "   [Ad: %s] Extractor validation issues on Round %d: %s",
                doc_id,
                round_num,
                "; ".join(problems)[:250],
            )
            continue

        # Schema & rules passed -> Evaluate with Stage-1 Supervisor Agent
        sup_decision = supervise_extraction(candidate_ad, enriched_text)
        if sup_decision.is_approved:
            approved_extracted_ad = candidate_ad
            store.save_stage1_processed(approved_extracted_ad)
            logger.info("   ✅ [Ad: %s] Stage-1 Extraction APPROVED on Round %d.", doc_id, round_num)
            break
        else:
            extract_criteria = [sup_decision.rejection_reason]
            prev_extract_dict = candidate_ad.model_dump(mode="json")

    # If Stage 1 failed after all rounds, record as dropped and stop processing this ad
    if approved_extracted_ad is None:
        logger.error(
            "   ❌ [Ad: %s] Dropped at Stage-1 (Extraction) after %d rounds.",
            doc_id,
            max_rounds,
        )
        store.save_dropped_ad(
            document_id=doc_id,
            collector=collector,
            stage_failed="extraction",
            rounds_attempted=max_rounds,
            drop_reason=extract_criteria or ["Exceeded max extraction rounds"],
            raw_text=enriched_text,
            source_url=source_url,
            last_candidate=prev_extract_dict,
        )
        return "dropped_extraction"

    # =================================================================
    # STAGE 2: Normalization <-> Supervisor Feedback Loop
    # =================================================================
    approved_normalized_ad: JobAd | None = None
    prev_normalized_ad: JobAd | None = None
    norm_criteria: list[str] = []

    for round_num in range(1, max_rounds + 1):
        logger.info("   [Ad: %s] Stage-2 Normalization (Round %d/%d)...", doc_id, round_num, max_rounds)
        norm_candidate, norm_problems = normalize_single_ad(
            extracted_ad=approved_extracted_ad,
            previous_normalized=prev_normalized_ad,
            rejection_criteria=norm_criteria if norm_criteria else None,
        )

        if norm_problems or norm_candidate is None:
            norm_criteria = norm_problems
            logger.warning(
                "   [Ad: %s] Normalizer validation issues on Round %d: %s",
                doc_id,
                round_num,
                "; ".join(norm_problems)[:250],
            )
            continue

        prev_normalized_ad = norm_candidate

        # Evaluate with Stage-2 Supervisor Agent
        sup_norm_decision = supervise_normalization(approved_extracted_ad, norm_candidate)
        if sup_norm_decision.is_approved:
            approved_normalized_ad = norm_candidate
            logger.info("   ✅ [Ad: %s] Stage-2 Normalization APPROVED on Round %d.", doc_id, round_num)
            break
        else:
            norm_criteria = [sup_norm_decision.rejection_reason]

    # If Stage 2 failed after all rounds, record as dropped
    if approved_normalized_ad is None:
        logger.error(
            "   ❌ [Ad: %s] Dropped at Stage-2 (Normalization) after %d rounds.",
            doc_id,
            max_rounds,
        )
        store.save_dropped_ad(
            document_id=doc_id,
            collector=collector,
            stage_failed="normalization",
            rounds_attempted=max_rounds,
            drop_reason=norm_criteria or ["Exceeded max normalization rounds"],
            raw_text=enriched_text,
            source_url=source_url,
            last_candidate=(
                prev_normalized_ad.model_dump(mode="json") if prev_normalized_ad else None
            ),
        )
        return "dropped_normalization"

    # =================================================================
    # STAGE 3: Save to PostgreSQL + `normalized_records.jsonl`
    # =================================================================
    store.save_final_normalized(
        job_ad=approved_normalized_ad,
        source_url=source_url,
        is_expired=is_expired,
    )
    logger.info(
        "🎉 [Ad: %s] Pipeline COMPLETE -> Saved to PostgreSQL & normalized_records.jsonl!",
        doc_id,
    )
    return "completed"


# =====================================================================
# CLI Helpers & Entrypoint
# =====================================================================

def _iter_jsonl_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yields parsed JSON objects one by one from a JSONL file."""
    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                if isinstance(data, str):
                    yield {"document_id": f"line_{line_num}", "raw_text": data}
                elif isinstance(data, dict):
                    yield data
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSON on line %d of %s: %s", line_num, path, exc)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fanoos-pipeline",
        description="Fanoos Central Database Pipeline (Single-Ad End-to-End Orchestrator)",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        help="Target a specific scraper platform (e.g., jobinja, jobvision, quera). Defaults to all enabled.",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Run URL discovery seeder before leasing and processing job ads.",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Only run URL discovery seeder to populate scraper_ledger.db, then exit.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current SQLite scraper_ledger.db statistics and exit.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Override max_pages_per_seed during URL discovery.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of job ads to process one-by-one in this run (default: 10).",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Maximum Supervisor retry rounds per stage (default: 3).",
    )
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        default=None,
        help="Optional: process ads one-by-one from an existing JSONL file instead of live scraping.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PIPELINE_DIR / "database" / "artifacts",
        help="Directory for JSONL checkpoints (processed.jsonl, normalized_records.jsonl, dropped.jsonl).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console logging level (default: INFO).",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    start_time = time.perf_counter()

    # Ensure prompt_library.jsonl exists and is populated
    if not PROMPTS_JSONL_PATH.exists() or PROMPTS_JSONL_PATH.stat().st_size == 0:
        init_prompts_jsonl(PROMPTS_JSONL_PATH)
        logger.info("Initialized default prompts in %s", PROMPTS_JSONL_PATH)

    # -----------------------------------------------------------------
    # Mode A: Offline JSONL Input Mode (--input-jsonl)
    # -----------------------------------------------------------------
    if args.input_jsonl is not None:
        if not args.input_jsonl.exists():
            logger.error("Input JSONL file not found: %s", args.input_jsonl)
            return 1

        store = FanoosDataStore(data_dir=args.data_dir)
        metrics = Counter()
        try:
            for idx, raw_record in enumerate(_iter_jsonl_records(args.input_jsonl), start=1):
                if args.limit and idx > args.limit:
                    break
                outcome = process_single_job_ad(
                    raw_record,
                    store=store,
                    max_rounds=args.max_rounds,
                )
                metrics[outcome] += 1
        finally:
            store.close()

        _print_summary(metrics, start_time, args.data_dir)
        return 0

    # -----------------------------------------------------------------
    # Mode B: Live Scraper + End-to-End Pipeline Mode
    # -----------------------------------------------------------------
    from scraper.scraper_service import ScraperService 

    with ScraperService() as scraper:
        # 1. Check Status Only (--status)
        if args.status:
            status_snapshot = scraper.get_pipeline_status()
            print("\n=== FANOOS SCRAPER LEDGER STATUS ===")
            print(json.dumps(status_snapshot["ledger_stats"], indent=2, ensure_ascii=False))
            return 0

        # 2. Seed URLs (--seed or --seed-only)
        if args.seed or args.seed_only:
            seed_results = scraper.seed_urls(
                platform=args.platform,
                max_pages_override=args.max_pages,
            )
            logger.info("URL Seeding Summary: %s", seed_results)
            if args.seed_only:
                print("\n=== URL SEEDING COMPLETE ===")
                print(json.dumps(seed_results, indent=2, ensure_ascii=False))
                return 0

        # 3. Single-Ad Lease -> Extract <-> Supervise -> Normalize <-> Supervise -> DB
        store = FanoosDataStore(data_dir=args.data_dir)
        metrics = Counter()

        try:
            processed_ads = 0
            lease_attempts = 0
            max_lease_attempts = max(args.limit * 3, args.limit + 5)

            while processed_ads < args.limit and lease_attempts < max_lease_attempts:
                stats_by_status = scraper.ledger.get_ledger_stats()["by_status"]
                eligible = stats_by_status.get("PENDING", 0) + stats_by_status.get("FAILED_RETRYABLE", 0)
                if eligible == 0 and scraper.ledger.reclaim_expired_leases() == 0:
                    logger.info("No more PENDING or retryable job URLs in scraper_ledger.db.")
                    break

                lease_attempts += 1
                raw_ad = scraper.lease_and_scrape_next(platform=args.platform, auto_ack=False)
                if raw_ad is None:
                    continue

                processed_ads += 1
                try:
                    outcome = process_single_job_ad(
                        raw_ad,
                        store=store,
                        max_rounds=args.max_rounds,
                    )
                    metrics[outcome] += 1
                    # ACK the job in scraper_ledger.db once it reaches a final state (DB or dropped_ads)
                    scraper.ack_job(raw_ad.job_id)
                except Exception as exc:
                    logger.error(
                        "Unexpected error processing job_id=%s: %s",
                        raw_ad.job_id,
                        exc,
                        exc_info=True,
                    )
                    scraper.nack_job(raw_ad.job_id, error_message=str(exc), retryable=True)
                    metrics["failed_exception"] += 1
        finally:
            store.close()

    _print_summary(metrics, start_time, args.data_dir)
    return 0


def _print_summary(metrics: Counter, start_time: float, data_dir: Path) -> None:
    elapsed = round(time.perf_counter() - start_time, 2)
    summary = {
        "elapsed_seconds": elapsed,
        "completed_and_stored": metrics["completed"],
        "dropped_at_extraction": metrics["dropped_extraction"],
        "dropped_at_normalization": metrics["dropped_normalization"],
        "failed_exceptions": metrics["failed_exception"],
        "artifacts_dir": str(data_dir),
        "token_usage": dict(llm_config.USAGE),
    }
    print("\n=== FANOOS CENTRAL PIPELINE SUMMARY ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())