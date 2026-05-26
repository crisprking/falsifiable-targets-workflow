# falsifiable-targets-workflow

**Parallel batch auditing of drug-target claims.**

[![Workflow CI](https://github.com/crisprking/falsifiable-targets-workflow/actions/workflows/workflow-ci.yml/badge.svg)](https://github.com/crisprking/falsifiable-targets-workflow/actions)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Engine](https://img.shields.io/badge/engine-v1.4.1-green.svg)](https://github.com/crisprking/falsifiable-targets)

Wraps the [falsifiable-targets](https://github.com/crisprking/falsifiable-targets) audit engine for scalable execution: process many claims in parallel on your laptop, an HPC cluster, or the cloud — without modifying the engine.

This is **Option B** from the project's evaluation document: orchestrate the existing tool rather than rewrite it as a workflow engine. Three execution paths, one engine, identical outputs.

## Quick start

```bash
# 1. Install the engine (requires v1.4.1+ for clean wheel install)
pip install "git+https://github.com/crisprking/falsifiable-targets.git@v1.4.1"

# 2. Clone this repo
git clone https://github.com/crisprking/falsifiable-targets-workflow.git
cd falsifiable-targets-workflow

# 3. Run the standalone batch audit (no workflow engine needed)
python scripts/batch_audit.py \
    --claims-dir claims \
    --reports-dir reports \
    --offline \
    --workers 4

# 4. View the dashboard
open reports/audit_summary.html
```

Expected output: 5 example claims, mixed verdicts (2 SURVIVED, 2 FALSIFIED_WITH_CAVEATS, 1 FALSIFIED), exit code 2.

## What's included

| Path | Purpose |
|---|---|
| `scripts/batch_audit.py` | Standalone parallel runner. Pure Python stdlib, no workflow engine. The path verified end-to-end on Kaggle. |
| `workflow/main.nf` + `nextflow.config` | Nextflow DSL2 workflow with 8 execution profiles (local, docker, singularity, slurm, sge, awsbatch, gcp, test). |
| `workflow/Snakefile` + `envs/` + `profiles/slurm/` | Snakemake workflow with conda env and SLURM profile. |
| `Dockerfile` | Multi-stage container build. Non-root user, tini PID-1, healthcheck on `ft-smoke`. |
| `examples/pipeline_tyk2.nf` | Minimal single-claim Nextflow example. |
| `claims/*.yaml` | 5 real example claims covering all 4 verdict tiers. |
| **`integrations/`** | **Bridges to upstream tools — see below.** |
| `Makefile` | One-liner targets: `make batch`, `make nf-local`, `make snakemake`, `make docker-build`. |

## Researcher integrations

Bridge `falsifiable-targets` to the tools researchers already use.
Each integration is a standalone script in `integrations/<name>/`.
See [`integrations/README.md`](integrations/README.md) and
[`docs/USE_CASES.md`](docs/USE_CASES.md) for full details and the
underlying persona/pain-point analysis.

| Integration | Who it's for | What it does |
|---|---|---|
| **`integrations/opentargets/`** | Computational drug discovery teams using the Open Targets Platform | Pulls top-N targets for a disease from the OT GraphQL API, converts to claim YAMLs |
| **`integrations/crispr/`** | Postdocs / staff scientists with CRISPR screen output | Converts MAGeCK / BAGEL2 / DrugZ output to claim YAMLs; flags DepMap common-essentials |
| **`integrations/grant_audit/`** | Academic PIs writing a target-validation grant | Interactive claim builder + Markdown report with copy-pasteable Rigor & Reproducibility section text |

These integrations compose: pull Open Targets' top 20 → audit them all →
generate per-claim Rigor reports → submit grant. See
[`integrations/README.md`](integrations/README.md#composing-integrations)
for the pipeline.

## Three execution paths, same result

All three paths produce identical `reports/audit_summary.json` and `reports/audit_summary.html`. Pick the one that fits your environment:

| Path | Use when |
|---|---|
| `make batch` | You want zero extra dependencies. Just Python + the engine. |
| `make nf-local` | You're on a host with Nextflow installed, or want to scale to HPC/cloud later. |
| `make snakemake` | You're already in the Snakemake ecosystem or need conda envs. |

The standalone path is the fastest to demonstrate and the one this repo's CI exercises. Nextflow and Snakemake paths are structurally validated; full end-to-end testing happens on hosts that have those engines installed.

## CLI reference

```
batch_audit.py [-h] --reports-dir REPORTS_DIR
               [--claims-dir CLAIMS_DIR]
               [--workers WORKERS] [--offline]
               [--timeout TIMEOUT] [--dry-run]
               [--aggregate-only]
```

| Flag | Default | What it does |
|---|---|---|
| `--claims-dir DIR` | — | Directory of claim YAMLs (recursive). Required unless `--aggregate-only`. |
| `--reports-dir DIR` | — | Output directory. Required. |
| `--workers N` | CPU count | Parallel workers. Use `1` inside Jupyter to avoid fork issues. |
| `--offline` | off | Pass `--no-live` to `ft-audit` (fixtures only, no UniProt/ChEMBL). |
| `--timeout S` | 300 | Per-claim timeout in seconds. |
| `--dry-run` | off | List discovered claims, exit without running. |
| `--aggregate-only` | off | Skip audits; re-aggregate existing `*_audit.json` reports. |

## Exit codes

Following the engine's verdict severity:

| Code | Meaning |
|---|---|
| 0 | All claims SURVIVED |
| 1 | At least one FALSIFIED_WITH_CAVEATS, no worse |
| 2 | At least one FALSIFIED |
| 3 | At least one INSUFFICIENT_DATA, no FALSIFIED |
| 4 | Processing error (no claims found, engine missing, malformed reports, etc.) |

## Verified verdict matrix

The 5 example claims exercise all 4 verdict tiers. Live mode on the v1.4.1 engine produces:

| Claim | Verdict | Notes |
|---|---|---|
| `example_hmgcr_statin` | SURVIVED | Gold-standard validated mechanism (statins / HMGCR). |
| `tyk2_psoriasis` | SURVIVED | Real-world success (deucravacitinib, FDA approval 2022). |
| `example_novel_caveats` | FALSIFIED_WITH_CAVEATS | Synthetic novel-target with selectivity gap. |
| `example_synthetic_retracted` | FALSIFIED | Synthetic retracted-replication case (STAP-style). |
| `ipi1_madurella` | FALSIFIED_WITH_CAVEATS | Cross-kingdom orthology, no chemistry, no UniProt accession. |

The Ipi1 verdict hardens to FALSIFIED if the live ChEMBL adapter can resolve the missing accession; in offline/fixture mode the engine correctly returns "data sparse" → caveat rather than "data confirms absence" → falsify.

Worst verdict: FALSIFIED → exit code 2 → CI fails. This is the contract.

## CI integration

Use the exit code to fail builds on FALSIFIED claims:

```yaml
- name: Audit drug-target claims
  run: |
    python scripts/batch_audit.py \
      --claims-dir claims/ \
      --reports-dir reports/ \
      --offline
```

A nonzero exit code fails the step automatically. The HTML dashboard at `reports/audit_summary.html` is uploadable as a CI artifact for review.

## Engine version pinning

This workflow layer requires engine **v1.4.1 or later**. v1.4.0 had a packaging bug where `sentinels/` and `claims/` YAML files weren't shipped with the wheel, causing `FileNotFoundError` on clean installs. v1.4.1 fixes the packaging only — the ruleset SHA (`35ef2b2ab5363298...`) is unchanged from v1.4.0.

Pin the engine version in your install command to lock reproducibility:

```bash
pip install "git+https://github.com/crisprking/falsifiable-targets.git@v1.4.1"
```

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Citing

If you use this workflow layer in a publication, please cite both the workflow and the engine. See `CITATION.cff` for full metadata.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and PRs welcome.
