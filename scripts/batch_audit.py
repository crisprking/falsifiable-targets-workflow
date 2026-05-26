#!/usr/bin/env python3
"""Batch audit runner for falsifiable-targets.

Discovers claim YAMLs, runs ft-audit on each in parallel, aggregates the
resulting JSON reports, and emits a summary JSON + self-contained HTML
dashboard. Exit code follows the README contract:

    0 = all SURVIVED
    1 = at least one FALSIFIED_WITH_CAVEATS, no worse
    2 = at least one FALSIFIED
    3 = at least one INSUFFICIENT_DATA, no FALSIFIED
    4 = processing error (missing engine, empty input, malformed report, etc.)
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

VERDICT_RANK = {
    "SURVIVED": 0,
    "FALSIFIED_WITH_CAVEATS": 1,
    "INSUFFICIENT_DATA": 3,  # treated worse than caveats per README
    "FALSIFIED": 2,
    "ERROR": 4,
}
RANK_TO_EXIT = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}


def discover_claims(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*") if p.suffix in (".yaml", ".yml"))


def audit_one(args: tuple[Path, Path, bool, int]) -> dict:
    claim_path, reports_dir, offline, timeout = args
    stem = claim_path.stem
    report_path = reports_dir / f"{stem}_audit.json"
    log_path = reports_dir / f"{stem}.log"
    cmd = ["ft-audit", str(claim_path), "--json-out", str(report_path)]
    if offline:
        cmd.append("--no-live")
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        log_path.write_text(
            f"$ {' '.join(cmd)}\n\n"
            f"--- STDOUT ---\n{result.stdout}\n\n"
            f"--- STDERR ---\n{result.stderr}\n"
        )
        elapsed = time.time() - t0
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text())
            except json.JSONDecodeError as e:
                return {
                    "claim": stem,
                    "verdict": "ERROR",
                    "error": f"malformed JSON report: {e}",
                    "elapsed_s": elapsed,
                }
            return {
                "claim": stem,
                "verdict": report.get("verdict", "ERROR"),
                "ruleset_sha256": report.get("ruleset_sha256"),
                "tool_version": (report.get("tool") or {}).get("version"),
                "report_path": str(report_path),
                "elapsed_s": elapsed,
            }
        return {
            "claim": stem,
            "verdict": "ERROR",
            "error": result.stderr.strip()[-500:] or f"ft-audit exited {result.returncode}",
            "elapsed_s": elapsed,
        }
    except subprocess.TimeoutExpired:
        return {
            "claim": stem,
            "verdict": "ERROR",
            "error": f"timeout after {timeout}s",
            "elapsed_s": timeout,
        }
    except FileNotFoundError as e:
        return {
            "claim": stem,
            "verdict": "ERROR",
            "error": f"ft-audit not found on PATH: {e}",
            "elapsed_s": 0.0,
        }


def aggregate(per_claim: list[dict]) -> dict:
    counts: dict[str, int] = {}
    rulesets: set[str] = set()
    versions: set[str] = set()
    for row in per_claim:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
        if row.get("ruleset_sha256"):
            rulesets.add(row["ruleset_sha256"])
        if row.get("tool_version"):
            versions.add(row["tool_version"])
    worst = max((VERDICT_RANK.get(r["verdict"], 4) for r in per_claim), default=4)
    worst_verdict = next((k for k, v in VERDICT_RANK.items() if v == worst), "ERROR")
    return {
        "total": len(per_claim),
        "counts": counts,
        "worst_verdict": worst_verdict,
        "exit_code": RANK_TO_EXIT.get(worst, 4),
        "ruleset_sha256": sorted(rulesets),
        "ruleset_divergence": len(rulesets) > 1,
        "tool_versions": sorted(versions),
        "per_claim": per_claim,
    }


VERDICT_COLOR = {
    "SURVIVED": "#1a7f37",
    "FALSIFIED_WITH_CAVEATS": "#bf8700",
    "FALSIFIED": "#cf222e",
    "INSUFFICIENT_DATA": "#6e7781",
    "ERROR": "#57606a",
}


def render_html(summary: dict) -> str:
    banner_color = VERDICT_COLOR.get(summary["worst_verdict"], "#57606a")
    rows = []
    for r in summary["per_claim"]:
        color = VERDICT_COLOR.get(r["verdict"], "#57606a")
        err = f" — {r['error']}" if r.get("error") else ""
        rows.append(
            f'<tr>'
            f'<td>{r["claim"]}</td>'
            f'<td style="color:{color};font-weight:600">{r["verdict"]}</td>'
            f'<td>{r.get("ruleset_sha256", "—") or "—"}</td>'
            f'<td>{r.get("tool_version", "—") or "—"}</td>'
            f'<td>{r["elapsed_s"]:.2f}s{err}</td>'
            f'</tr>'
        )
    counts_html = " · ".join(
        f'<span style="color:{VERDICT_COLOR.get(k, "#57606a")}">{k}: {v}</span>'
        for k, v in sorted(summary["counts"].items())
    )
    divergence_html = ""
    if summary["ruleset_divergence"]:
        divergence_html = (
            '<div style="background:#fff8c5;border:1px solid #d4a72c;'
            'padding:8px;border-radius:6px;margin:12px 0">'
            '⚠ Ruleset divergence detected: '
            f'{len(summary["ruleset_sha256"])} distinct SHAs across reports.</div>'
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Falsifiable Targets — Audit Summary</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 1100px;
       margin: 24px auto; padding: 0 16px; color: #1f2328; }}
.banner {{ background: {banner_color}; color: white; padding: 16px 20px;
          border-radius: 8px; font-size: 18px; font-weight: 600; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #d0d7de; }}
th {{ background: #f6f8fa; font-weight: 600; }}
.meta {{ color: #57606a; font-size: 13px; margin-top: 8px; }}
code {{ font-family: ui-monospace, monospace; font-size: 12px; }}
</style></head><body>
<div class="banner">Worst verdict: {summary["worst_verdict"]} · {summary["total"]} claims</div>
<div class="meta">{counts_html}</div>
{divergence_html}
<table>
<tr><th>Claim</th><th>Verdict</th><th>Ruleset SHA</th><th>Tool version</th><th>Time</th></tr>
{"".join(rows)}
</table>
<div class="meta">Ruleset SHA(s): <code>{", ".join(summary["ruleset_sha256"]) or "—"}</code> ·
Tool version(s): <code>{", ".join(summary["tool_versions"]) or "—"}</code></div>
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Parallel batch runner for ft-audit")
    p.add_argument("--claims-dir", type=Path, help="Directory of claim YAMLs (recursive)")
    p.add_argument("--reports-dir", type=Path, required=True, help="Output directory")
    p.add_argument("--workers", type=int, default=mp.cpu_count(), help="Parallel workers")
    p.add_argument("--offline", action="store_true", help="Pass --no-live to ft-audit")
    p.add_argument("--timeout", type=int, default=300, help="Per-claim timeout (s)")
    p.add_argument("--dry-run", action="store_true", help="List discovered claims, don't run")
    p.add_argument("--aggregate-only", action="store_true",
                   help="Skip audits, re-aggregate existing reports in --reports-dir")
    args = p.parse_args(argv)

    args.reports_dir.mkdir(parents=True, exist_ok=True)

    if args.aggregate_only:
        per_claim = []
        for report_path in sorted(args.reports_dir.glob("*_audit.json")):
            try:
                report = json.loads(report_path.read_text())
                per_claim.append({
                    "claim": report_path.stem.removesuffix("_audit"),
                    "verdict": report.get("verdict", "ERROR"),
                    "ruleset_sha256": report.get("ruleset_sha256"),
                    "tool_version": (report.get("tool") or {}).get("version"),
                    "report_path": str(report_path),
                    "elapsed_s": 0.0,
                })
            except (json.JSONDecodeError, OSError) as e:
                print(f"  ! skipping malformed {report_path.name}: {e}", file=sys.stderr)
        summary = aggregate(per_claim)
        (args.reports_dir / "audit_summary.json").write_text(json.dumps(summary, indent=2))
        (args.reports_dir / "audit_summary.html").write_text(render_html(summary))
        print(f"Summary: {summary['counts']}, exit code {summary['exit_code']}")
        return summary["exit_code"]

    if not args.claims_dir:
        print("ERROR: --claims-dir required (unless --aggregate-only)", file=sys.stderr)
        return 4

    claims = discover_claims(args.claims_dir)
    if not claims:
        print(f"ERROR: no claims found under {args.claims_dir}", file=sys.stderr)
        return 4
    print(f"Discovered {len(claims)} claim(s) under {args.claims_dir}")
    for c in claims:
        print(f"  · {c}")

    if args.dry_run:
        return 0

    if shutil.which("ft-audit") is None:
        print("ERROR: ft-audit not on PATH", file=sys.stderr)
        return 4

    print(f"\nRunning {len(claims)} audit(s) with {args.workers} worker(s)"
          f"{' (offline)' if args.offline else ''}...")
    pool_args = [(c, args.reports_dir, args.offline, args.timeout) for c in claims]
    if args.workers == 1 or len(claims) == 1:
        per_claim = [audit_one(a) for a in pool_args]
    else:
        with mp.Pool(args.workers) as pool:
            per_claim = pool.map(audit_one, pool_args)

    summary = aggregate(per_claim)
    (args.reports_dir / "audit_summary.json").write_text(json.dumps(summary, indent=2))
    (args.reports_dir / "audit_summary.html").write_text(render_html(summary))

    print("\n=== Per-claim verdicts ===")
    for r in per_claim:
        marker = "✓" if r["verdict"] == "SURVIVED" else "✗" if "FALSIFIED" in r["verdict"] else "?"
        err = f"  ({r['error']})" if r.get("error") else ""
        print(f"  {marker} {r['claim']:40} {r['verdict']:25} {r['elapsed_s']:6.2f}s{err}")

    print(f"\n=== Summary ===")
    print(f"  Total:          {summary['total']}")
    print(f"  Counts:         {summary['counts']}")
    print(f"  Worst verdict:  {summary['worst_verdict']}")
    print(f"  Exit code:      {summary['exit_code']}")
    print(f"  Ruleset SHA:    {summary['ruleset_sha256']}")
    if summary["ruleset_divergence"]:
        print(f"  ⚠ DIVERGENCE:   multiple ruleset SHAs detected")

    return summary["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
