#!/usr/bin/env python3
"""ft-from-crispr — convert CRISPR screen hits to claim YAMLs.

Takes the output of a genome-wide CRISPR-Cas9 knockout or activation
screen (MAGeCK, BAGEL2, DrugZ format) and writes one claim YAML per
significant hit. The YAMLs are schema-valid for ft-audit / ft-validate.

Typical workflow:

    # 1. Run MAGeCK as you normally would
    mageck test -k counts.txt -t treatment -c control -n screen_v1

    # 2. Convert hits to claim YAMLs
    python from_crispr_screen.py \\
        --input screen_v1.gene_summary.txt \\
        --format mageck \\
        --indication "triple-negative breast cancer" \\
        --fdr-cutoff 0.05 \\
        --top 100 \\
        --output claims_screen_v1/

    # 3. Batch-audit
    python ../../scripts/batch_audit.py \\
        --claims-dir claims_screen_v1 \\
        --reports-dir reports_screen_v1 \\
        --workers 8

    # 4. Filter SURVIVED hits for orthogonal validation:
    jq -r '.per_claim[] | select(.verdict=="SURVIVED") | .claim' \\
        reports_screen_v1/audit_summary.json

This integration bridges the gap between large-scale CRISPR screens
(which produce hundreds of putative targets) and structured
falsifiability auditing (which filters them to a wet-lab-tractable
shortlist).

Supported formats:
  - MAGeCK gene_summary.txt (default)
  - BAGEL2 .bf output
  - DrugZ output
  - Generic TSV with --gene-col and --score-col flags
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

# Common essential-gene list (DepMap common-essentials, top ~2000 by gene effect).
# Hits in this list should be downgraded — knocking them out kills any cell line,
# so a screen finding them as "lethal" is uninformative. This is a small
# representative set for the script's heuristic; real production use should
# load the full DepMap list.
DEPMAP_COMMON_ESSENTIAL_HINT = {
    # Ribosome / translation
    "RPL5", "RPL10", "RPL11", "RPS3", "RPS6", "RPS19", "EIF3A", "EIF4G1",
    # Proteasome
    "PSMA1", "PSMA2", "PSMB1", "PSMB5", "PSMD1", "PSMD4",
    # Spliceosome
    "SF3A1", "SF3B1", "U2AF1", "U2AF2", "SNRPA", "SNRPB",
    # DNA replication
    "POLD1", "POLE", "PCNA", "MCM2", "MCM3", "MCM4", "MCM5", "MCM6", "MCM7",
    # Cell cycle
    "CDK1", "CDK2", "CCNB1", "AURKA", "AURKB", "PLK1",
    # Sec61 / ER translocon
    "SEC61A1", "SEC61B", "SEC61G",
    # Other broad essentials
    "MYC", "RPA1", "RPA2", "RPA3", "PLK4", "CENPA",
}


def parse_mageck(path: Path, fdr_cutoff: float, top: int) -> list[dict]:
    """Parse MAGeCK gene_summary.txt → list of hit dicts."""
    rows = []
    with path.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            try:
                # MAGeCK columns: id, num, neg|score, neg|p-value, neg|fdr, neg|rank, ...
                fdr_neg = float(r.get("neg|fdr") or 1.0)
                fdr_pos = float(r.get("pos|fdr") or 1.0)
                fdr = min(fdr_neg, fdr_pos)
                if fdr > fdr_cutoff:
                    continue
                direction = "depleted" if fdr_neg < fdr_pos else "enriched"
                score = float(r.get("neg|score" if direction == "depleted" else "pos|score") or 0)
                rows.append({
                    "gene": r["id"],
                    "fdr": fdr,
                    "score": score,
                    "direction": direction,
                    "raw": r,
                })
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda x: x["fdr"])
    return rows[:top]


def parse_bagel(path: Path, bf_cutoff: float, top: int) -> list[dict]:
    """Parse BAGEL2 output: GENE, GENE_BF columns. BF > cutoff = essential."""
    rows = []
    with path.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            try:
                bf = float(r.get("GENE_BF") or r.get("BF") or 0)
                if bf < bf_cutoff:
                    continue
                rows.append({
                    "gene": r.get("GENE") or r.get("gene"),
                    "fdr": None,  # BAGEL2 uses Bayes factor, not FDR
                    "score": bf,
                    "direction": "depleted",  # BAGEL2 scores essentiality
                    "raw": r,
                })
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda x: -x["score"])
    return rows[:top]


def parse_drugz(path: Path, fdr_cutoff: float, top: int) -> list[dict]:
    """Parse DrugZ output: GENE, sumZ, numObs, normZ, pval_synth, fdr_synth, pval_supp, fdr_supp."""
    rows = []
    with path.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            try:
                fdr_synth = float(r.get("fdr_synth") or 1.0)
                fdr_supp = float(r.get("fdr_supp") or 1.0)
                fdr = min(fdr_synth, fdr_supp)
                if fdr > fdr_cutoff:
                    continue
                direction = "synthetic_lethal" if fdr_synth < fdr_supp else "suppressor"
                rows.append({
                    "gene": r["GENE"],
                    "fdr": fdr,
                    "score": float(r.get("normZ") or 0),
                    "direction": direction,
                    "raw": r,
                })
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda x: x["fdr"])
    return rows[:top]


def parse_generic(path: Path, gene_col: str, score_col: str,
                  score_cutoff: float, top: int) -> list[dict]:
    """Generic TSV/CSV parser."""
    delim = "\t" if path.suffix in (".tsv", ".txt") else ","
    rows = []
    with path.open() as f:
        reader = csv.DictReader(f, delimiter=delim)
        for r in reader:
            try:
                score = float(r[score_col])
                if score < score_cutoff:
                    continue
                rows.append({
                    "gene": r[gene_col],
                    "fdr": None,
                    "score": score,
                    "direction": "screen_hit",
                    "raw": r,
                })
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda x: -x["score"])
    return rows[:top]


def slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", s).lower()


def claim_yaml(hit: dict, indication: str, screen_format: str,
               screen_name: str, screen_url: str | None,
               input_filename: str) -> tuple[str, list[str]]:
    """Render a CRISPR hit to schema-valid claim YAML.

    Returns (yaml_text, warnings). Warnings flag known triage problems
    (e.g. hit is in DepMap common-essential list).
    """
    gene = hit["gene"]
    warnings = []
    if gene in DEPMAP_COMMON_ESSENTIAL_HINT:
        warnings.append(
            f"{gene} is in the DepMap common-essential gene list. Knockout "
            "is lethal in most cell lines and likely uninformative as a "
            "disease-specific target. Audit should treat this as a strong "
            "FALSIFIED signal."
        )

    fdr_str = f"FDR={hit['fdr']:.2e}" if hit["fdr"] is not None else f"score={hit['score']:.2f}"
    mechanism = (
        f"CRISPR-Cas9 {screen_format.upper()} screen hit ({hit['direction']}, "
        f"{fdr_str}). Screen: {screen_name!r}. From input file {input_filename!r}."
    )

    if warnings:
        mechanism += " WARNING: DepMap common-essential gene flagged."

    # CRISPR screen hits are novel_target claims by default — they're
    # hypotheses, not established mechanisms.
    claim_type = "novel_target"
    today = time.strftime("%Y-%m-%d")

    lines = [
        "# Auto-generated by ft-from-crispr",
        f"# Screen: {screen_name} ({screen_format})",
        f"# Hit: {gene}, direction={hit['direction']}, {fdr_str}",
    ]
    if warnings:
        for w in warnings:
            lines.append(f"# WARNING: {w}")
    lines.append("")
    lines.append("claim:")
    lines.append(f"  target_symbol: {gene!r}")
    lines.append(f"  indication: {indication!r}")
    lines.append(f"  mechanism: {mechanism!r}")
    lines.append(f"  claim_type: {claim_type!r}")
    if screen_url:
        lines.append(f"  source_url: {screen_url!r}")
    lines.append(f"  notes: 'Imported from {screen_format} screen output on {today}'")
    return "\n".join(lines) + "\n", warnings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--input", required=True, type=Path,
                   help="Path to screen output file.")
    p.add_argument("--format", choices=["mageck", "bagel", "drugz", "generic"],
                   default="mageck", help="Screen output format.")
    p.add_argument("--indication", required=True,
                   help="Disease/condition this screen is interrogating.")
    p.add_argument("--output", "-o", required=True, type=Path,
                   help="Output directory for claim YAMLs.")
    p.add_argument("--fdr-cutoff", type=float, default=0.05,
                   help="FDR threshold for MAGeCK/DrugZ (default: 0.05).")
    p.add_argument("--bf-cutoff", type=float, default=6.0,
                   help="Bayes factor threshold for BAGEL2 (default: 6.0).")
    p.add_argument("--score-cutoff", type=float, default=0.0,
                   help="Score threshold for --format generic.")
    p.add_argument("--top", type=int, default=200,
                   help="Maximum number of hits to convert (default: 200).")
    p.add_argument("--screen-name", default=None,
                   help="Human-readable name for this screen (default: input filename).")
    p.add_argument("--screen-url", default=None,
                   help="Provenance URL (e.g. GEO accession, Zenodo DOI).")
    p.add_argument("--gene-col", default="gene",
                   help="Gene column name for --format generic (default: gene).")
    p.add_argument("--score-col", default="score",
                   help="Score column name for --format generic (default: score).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print summary, don't write files.")
    args = p.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 2

    args.output.mkdir(parents=True, exist_ok=True)
    screen_name = args.screen_name or args.input.stem

    print(f"Parsing {args.format} screen output: {args.input}")
    if args.format == "mageck":
        hits = parse_mageck(args.input, args.fdr_cutoff, args.top)
    elif args.format == "bagel":
        hits = parse_bagel(args.input, args.bf_cutoff, args.top)
    elif args.format == "drugz":
        hits = parse_drugz(args.input, args.fdr_cutoff, args.top)
    else:
        hits = parse_generic(args.input, args.gene_col, args.score_col,
                             args.score_cutoff, args.top)

    if not hits:
        print("No hits passed the threshold. Try loosening --fdr-cutoff or --top.",
              file=sys.stderr)
        return 1

    print(f"Got {len(hits)} hit(s) above threshold.")

    common_essential_count = 0
    written = 0
    for hit in hits:
        path = args.output / f"{slug(hit['gene'])}.yaml"
        yaml_text, warnings = claim_yaml(
            hit, args.indication, args.format, screen_name,
            args.screen_url, args.input.name,
        )
        if warnings:
            common_essential_count += 1

        if args.dry_run:
            marker = "⚠" if warnings else "·"
            fdr_str = f"FDR={hit['fdr']:.2e}" if hit['fdr'] is not None else f"BF={hit['score']:.1f}"
            print(f"  {marker} {hit['gene']:12} ({fdr_str}, {hit['direction']})")
        else:
            path.write_text(yaml_text)
            written += 1

    if common_essential_count:
        print(f"\n⚠ {common_essential_count} hit(s) flagged as DepMap common-essential.")
        print("  These are likely lethal in any cell line and uninformative as disease-specific targets.")

    if args.dry_run:
        print(f"\n[dry-run] {len(hits)} claim(s) prepared (not written).")
    else:
        print(f"\nWrote {written} claim YAMLs to {args.output}/")
        print(f"\nNext steps:")
        print(f"  python ../../scripts/batch_audit.py \\")
        print(f"    --claims-dir {args.output} \\")
        print(f"    --reports-dir reports_{slug(screen_name)} \\")
        print(f"    --workers 8")
        print()
        print(f"  # To get just the SURVIVED hits (the prioritized shortlist):")
        print(f"  jq -r '.per_claim[] | select(.verdict==\"SURVIVED\") | .claim' \\")
        print(f"    reports_{slug(screen_name)}/audit_summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
