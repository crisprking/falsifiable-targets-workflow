# Researcher Integrations

This directory contains scripts that bridge `falsifiable-targets` to
the upstream tools researchers already use. Each integration is a
standalone script that converts an external format (Open Targets API
response, MAGeCK output, etc.) into schema-valid claim YAMLs that
`ft-audit` consumes.

The integrations are **optional**. The standalone batch runner at
`../scripts/batch_audit.py` works fine without them. They exist
because many researchers already have their inputs in these formats
and shouldn't need to write conversion code.

## What's here

### 1. `opentargets/from_opentargets.py` — pull disease-target rankings

For computational drug discovery teams who use the Open Targets
Platform daily. Queries the OT GraphQL API for the top-N targets for
a disease, converts them to claim YAMLs.

```bash
python opentargets/from_opentargets.py \
    --disease MONDO_0005083 \
    --top 50 \
    --output claims_psoriasis/
```

See [USE_CASES.md persona 3](../docs/USE_CASES.md#persona-3-the-open-targets-power-user-running-disease-centric-prioritization)
for the rationale and full integration recipe.

### 2. `crispr/from_crispr_screen.py` — triage screen hits

For computational biologists with a genome-wide CRISPR screen output
(MAGeCK, BAGEL2, DrugZ). Converts significant hits to claim YAMLs,
optionally flags DepMap common-essential genes.

```bash
python crispr/from_crispr_screen.py \
    --input screen_v1.gene_summary.txt \
    --format mageck \
    --indication "triple-negative breast cancer" \
    --fdr-cutoff 0.05 \
    --top 100 \
    --output claims_screen/
```

See [USE_CASES.md persona 2](../docs/USE_CASES.md#persona-2-the-computational-biologist-triaging-crispr-screen-hits)
for the rationale.

### 3. `grant_audit/grant_audit.py` — pre-submission grant rigor check

For academic PIs preparing a target-validation grant. Builds a claim
YAML (interactively or from an existing file), runs the audit, and
emits a Markdown report with copy-pasteable Rigor & Reproducibility
section text.

```bash
# Interactive mode
python grant_audit/grant_audit.py --interactive --output my_claim.yaml
python grant_audit/grant_audit.py --claim my_claim.yaml --report grant_audit.md

# From existing claim
python grant_audit/grant_audit.py --claim existing.yaml --report rigor_section.md
```

See [USE_CASES.md persona 1](../docs/USE_CASES.md#persona-1-the-academic-pi-writing-a-target-validation-grant)
for the rationale.

## Composing integrations

Integrations chain naturally. For instance, a "validate Open Targets'
top 20 psoriasis targets" workflow is:

```bash
# 1. Pull from Open Targets
python opentargets/from_opentargets.py \
    --disease MONDO_0005083 --top 20 --output psoriasis_claims/

# 2. Batch-audit
python ../scripts/batch_audit.py \
    --claims-dir psoriasis_claims/ --reports-dir psoriasis_reports/ --workers 4

# 3. For each FALSIFIED, generate a rigor report explaining why
jq -r '.per_claim[] | select(.verdict=="FALSIFIED") | .claim' \
    psoriasis_reports/audit_summary.json | while read claim; do
    python grant_audit/grant_audit.py \
        --claim "psoriasis_claims/${claim}.yaml" \
        --report "psoriasis_reports/${claim}_rigor.md"
done
```

## Adding new integrations

If your group has an upstream tool whose output you want to convert
to claim YAMLs, the pattern is:

1. Write a single-file script in `integrations/<name>/`.
2. It must produce YAMLs that `ft-validate` accepts.
3. It must include a `--dry-run` flag for safe testing.
4. Add it to this README and to `docs/USE_CASES.md`.
5. Ideally, add a smoke test in `tests/` that runs the converter
   on a small fixture file and checks `ft-validate` is happy.

PRs welcome. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
