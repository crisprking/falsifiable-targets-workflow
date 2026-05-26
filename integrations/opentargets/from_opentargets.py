#!/usr/bin/env python3
"""ft-from-opentargets — convert Open Targets prioritization to claim YAMLs.

Queries the Open Targets Platform GraphQL API for the top-N targets
associated with a disease (by EFO/MONDO ID), then writes one claim YAML
per target. The YAMLs are schema-valid for `ft-audit` / `ft-validate`.

Typical workflow:

    # 1. Pull top 50 targets for psoriasis
    python from_opentargets.py \\
        --disease MONDO_0005083 \\
        --top 50 \\
        --output claims_psoriasis/

    # 2. Audit them all in parallel
    python ../../scripts/batch_audit.py \\
        --claims-dir claims_psoriasis \\
        --reports-dir reports_psoriasis \\
        --workers 4

    # 3. Open the dashboard, look for the high-OT-score / FALSIFIED tier —
    #    these are the most interesting findings (Open Targets says
    #    "promising" but falsifiability audit says "kill the hypothesis").

This integration complements Open Targets (evidence aggregation) with
falsifiability auditing. It does NOT replace OT — it adds a structured
gate between OT prioritization and wet-lab investment.

API reference: https://platform-docs.opentargets.org/data-access/graphql-api
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OT_GRAPHQL = "https://api.platform.opentargets.org/api/v4/graphql"

# Open Targets target-disease association score thresholds.
# Below 0.05 the association is essentially noise; above 0.7 it's robust.
DEFAULT_MIN_SCORE = 0.10


def query_open_targets(disease_id: str, top_n: int, min_score: float) -> list[dict]:
    """Query OT GraphQL for top-N targets associated with a disease.

    disease_id is the EFO/MONDO/Orphanet ID with underscore form
    (MONDO_0005083, EFO_0000270, etc.). The OT API accepts the underscore
    form directly.
    """
    query = """
    query AssociatedTargets($efoId: String!, $size: Int!) {
      disease(efoId: $efoId) {
        id
        name
        associatedTargets(page: {index: 0, size: $size}, orderByScore: "score") {
          rows {
            score
            target {
              id
              approvedSymbol
              approvedName
              biotype
              proteinIds { id, source }
            }
            datatypeScores { id, score }
          }
        }
      }
    }
    """
    body = json.dumps({
        "query": query,
        "variables": {"efoId": disease_id, "size": top_n},
    }).encode()

    req = urllib.request.Request(
        OT_GRAPHQL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"Open Targets API error: HTTP {e.code} — {e.read()[:500].decode()}",
              file=sys.stderr)
        sys.exit(2)
    except urllib.error.URLError as e:
        print(f"Open Targets API unreachable: {e}", file=sys.stderr)
        sys.exit(2)

    if "errors" in payload:
        print(f"GraphQL errors: {payload['errors']}", file=sys.stderr)
        sys.exit(2)

    disease = payload.get("data", {}).get("disease")
    if disease is None:
        print(f"Disease {disease_id} not found in Open Targets.", file=sys.stderr)
        sys.exit(2)

    rows = disease["associatedTargets"]["rows"]
    rows = [r for r in rows if r["score"] >= min_score]
    return disease, rows


def first_uniprot(target: dict) -> str | None:
    """Extract the canonical UniProt accession from an OT target record."""
    for pid in target.get("proteinIds") or []:
        if pid.get("source") == "uniprot_swissprot":
            return pid["id"]
    # Fall back to any UniProt source
    for pid in target.get("proteinIds") or []:
        if pid.get("source", "").startswith("uniprot"):
            return pid["id"]
    return None


def datatypes_summary(datatype_scores: list[dict]) -> str:
    """Compact one-line summary of Open Targets evidence datatypes."""
    if not datatype_scores:
        return ""
    by_score = sorted(datatype_scores, key=lambda d: -d["score"])[:4]
    return ", ".join(f"{d['id']}={d['score']:.2f}" for d in by_score)


def slug(symbol: str) -> str:
    """Filename-safe slug from a gene symbol."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", symbol).lower()


def claim_yaml(disease: dict, row: dict, source_url: str) -> str:
    """Render a row to a schema-valid claim YAML string.

    Open Targets gives us:
      - target symbol, UniProt ID, biotype
      - association score (0..1)
      - per-datatype evidence scores (genetic, drug, literature, etc.)
    The audit engine consumes claim-level metadata; live adapters
    (UniProt, ChEMBL) fill in the rest at audit time.
    """
    target = row["target"]
    symbol = target["approvedSymbol"]
    uniprot = first_uniprot(target)
    score = row["score"]
    datatypes = datatypes_summary(row.get("datatypeScores") or [])

    # Claim type: anything above 0.7 OT score is treated as a validated_mechanism
    # claim (the platform considers it well-supported); below that, novel_target.
    claim_type = "validated_mechanism" if score >= 0.70 else "novel_target"

    # Indication: prefer the disease name if available, else fall back to ID.
    indication = disease.get("name") or disease["id"].replace("_", ":")

    mechanism = (
        f"Open Targets disease-target association (overall score {score:.3f}). "
        f"Evidence datatypes: {datatypes or 'none reported above threshold'}. "
        f"Biotype: {target.get('biotype', 'unknown')}."
    )

    # YAML emitted manually (no PyYAML dep needed at this step)
    lines = [
        "# Auto-generated by ft-from-opentargets",
        f"# Open Targets: https://platform.opentargets.org/target/{target['id']}/associations",
        f"# Disease: {disease['id']} ({indication})",
        f"# Association score: {score:.3f}",
        "",
        "claim:",
        f"  target_symbol: {symbol!r}",
    ]
    if uniprot:
        lines.append(f"  uniprot_id: {uniprot!r}")
    lines.append(f"  ensembl_id: {target['id']!r}")
    today = time.strftime("%Y-%m-%d")
    lines.extend([
        f"  indication: {indication!r}",
        f"  mechanism: {mechanism!r}",
        f"  claim_type: {claim_type!r}",
        f"  source_url: {source_url!r}",
        f"  notes: 'Imported from Open Targets v4 API on {today}'",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Pull top-N Open Targets associations for a disease and "
                    "convert them to claim YAMLs for ft-audit."
    )
    p.add_argument("--disease", required=True,
                   help="EFO/MONDO/Orphanet ID, underscore form (e.g. MONDO_0005083 for psoriasis).")
    p.add_argument("--top", type=int, default=50,
                   help="Number of top targets to fetch (default: 50).")
    p.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                   help=f"Minimum OT association score (default: {DEFAULT_MIN_SCORE}). "
                        "Below 0.05 = noise; above 0.7 = robust.")
    p.add_argument("--output", "-o", required=True, type=Path,
                   help="Output directory for claim YAMLs.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print summary but don't write files.")
    args = p.parse_args(argv)

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"Querying Open Targets for disease {args.disease}, top {args.top} targets...")
    disease, rows = query_open_targets(args.disease, args.top, args.min_score)
    print(f"Disease: {disease['id']} ({disease.get('name', '?')})")
    print(f"Got {len(rows)} target(s) above score threshold {args.min_score}")

    if not rows:
        print("No targets above threshold. Try lowering --min-score.", file=sys.stderr)
        return 1

    source_url = f"https://platform.opentargets.org/disease/{disease['id']}/associations"

    written = 0
    for row in rows:
        symbol = row["target"]["approvedSymbol"]
        score = row["score"]
        path = args.output / f"{slug(symbol)}.yaml"
        yaml_text = claim_yaml(disease, row, source_url)
        if args.dry_run:
            print(f"  [dry-run] would write {path}  (score={score:.3f})")
        else:
            path.write_text(yaml_text)
            written += 1

    if args.dry_run:
        print(f"\n[dry-run] {len(rows)} claim(s) prepared (not written).")
    else:
        print(f"\nWrote {written} claim YAMLs to {args.output}/")
        print(f"\nNext step:")
        print(f"  python ../../scripts/batch_audit.py \\")
        print(f"    --claims-dir {args.output} \\")
        print(f"    --reports-dir reports_{slug(disease['id'])} \\")
        print(f"    --workers 4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
