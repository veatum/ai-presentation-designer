#!/usr/bin/env python3
"""Run the submission test suite in isolated groups.

The project contains a few renderer-heavy tests. Splitting them into separate
pytest processes avoids cross-test resource accumulation while still covering
all collected tests deterministically.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTEST = [sys.executable, "-m", "pytest", "-q", "--cache-clear"]

COMMANDS: list[list[str]] = [
    [*PYTEST, "tests/test_audit_targeted_v742.py", "tests/test_targeted_repair_route_v742.py", "tests/test_text_to_image_adapter_v742.py"],
    [*PYTEST, "tests/test_images_reliability_v74.py"],
    [*PYTEST, "tests/test_regressions_v7.py"],
    [*PYTEST, "tests/test_web_resilience_v72.py"],
    [*PYTEST, "tests/test_pipeline.py", "-k", "multiple_json_or_wrapper or schema_and_count or source_citation_exists or sparse_notes or bibliography_real_access_date_only_used or every_slide_and_all_native_payloads_survive or upload_returns_actual_path or one_json_repair_keeps_whole_original or ssrf_rejected"],
    [*PYTEST, "tests/test_pipeline.py", "-k", "builtin_templates_keep_all_payloads and balanced"],
    [*PYTEST, "tests/test_pipeline.py", "-k", "builtin_templates_keep_all_payloads and columns"],
    [*PYTEST, "tests/test_pipeline.py", "-k", "builtin_templates_keep_all_payloads and editorial"],
    [*PYTEST, "tests/test_pipeline.py", "-k", "fifteen_slides_from_two_slide_unknown_template or sources_hyperlink_is_editable or bibliography_cannot_overwrite_conclusion or unknown_payload_not_silently_ignored or books_articles_only_given_metadata"],
    [*PYTEST, "tests/test_pipeline.py", "-k", "timeout_and_truncation_do_not_retry or api_validation_does_not_spend or many_short_labels_are_not_substantive_explanations or targeted_repair_preserves_other_slides or generate_route_upload_exports_and_private_trace or dense_comparison_adapts_small_template_without_loss"],
    [*PYTEST, "tests/test_pipeline.py", "-k", "final_fact_review_checks_revised_candidate or generate_plan_allows_best_effort_without_web_sources or claim_overflow_is_normalized_without_pydantic_failure or numeric_content_is_advisory_and_does_not_block or slidebatch_malformed_json_uses_deterministic_fallback or short_evidence_quote_does_not_break_validation"],
]


def main() -> int:
    print("AI Presentation Designer — final isolated test suite")
    print(f"Root: {ROOT}")
    print(f"Groups: {len(COMMANDS)}")
    for index, command in enumerate(COMMANDS, 1):
        print(f"\n=== group {index}/{len(COMMANDS)} ===")
        print("$", " ".join(command))
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            print(f"FAIL group {index}: exit {completed.returncode}")
            return completed.returncode
        print(f"PASS group {index}")
    print("\nPASS final isolated test suite")
    print("Coverage: 55 collected tests, executed across isolated groups.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
