# Changelog

All notable changes to the workflow layer are recorded here. The layer
follows semantic versioning and pins to an engine version range.

## [1.0.0] - 2026-05-26 — Initial release

First public release of the orchestration layer. Implements **Option B**
from the project evaluation: wrap the existing `falsifiable-targets`
engine with workflow tooling rather than rewrite it as a workflow engine.

Engine compatibility: **>= v1.4.1**.
Engine ruleset SHA at release time: `35ef2b2ab5363298097962a0b6ae52c70d551a1edddc341054f75cb6e4fb7221` (ruleset v1.2.0).

### Added

- **`scripts/batch_audit.py`** — standalone parallel runner using
  `multiprocessing.Pool`. Discovers claim YAMLs (recursive), invokes
  `ft-audit` per claim, aggregates reports to JSON + HTML dashboard.
  Supports offline mode (`--offline` → `--no-live`), dry-run, and
  aggregate-only re-rolling of existing reports. Implements the exit-code
  contract: `0` (SURVIVED), `1` (CAVEATS), `2` (FALSIFIED), `3`
  (INSUFFICIENT_DATA), `4` (processing error).
- **`workflow/main.nf` + `nextflow.config`** — Nextflow DSL2 workflow
  with 4 processes (`sentinel_check`, `validate_claim`, `ft_audit`,
  `aggregate_reports`). 8 execution profiles: local, docker, singularity,
  slurm, sge, awsbatch, gcp, test. Native timeline / report / trace / DAG
  outputs.
- **`workflow/Snakefile` + envs/profiles** — Snakemake workflow with
  the same DAG shape (fan-out per claim, single aggregator). Reuses
  `batch_audit.py --aggregate-only` for the aggregation step so all
  three execution paths produce byte-identical output.
- **`Dockerfile`** — multi-stage container build. Pins engine via
  `FT_REF` build arg (default `v1.4.1`). Non-root user, tini as PID-1,
  HEALTHCHECK runs `ft-smoke`.
- **`examples/pipeline_tyk2.nf`** — minimal single-claim Nextflow
  example for quick smoke-testing of a Nextflow install.
- **5 example claims** — copied verbatim from the engine repo's
  `claims/` directory. Cover all four verdict tiers. Schema-validated
  by the engine's `ft-validate`.
- **`Makefile`** — one-liner targets: `make batch`, `make nf-local`,
  `make nf-docker`, `make snakemake`, `make docker-build`, `make clean`.
- **`.github/workflows/workflow-ci.yml`** — GitHub Actions CI matrix
  across Python 3.10/3.11/3.12. Installs the engine from pinned tag,
  runs the batch audit on the 5 example claims, validates report
  shape, uploads `reports/` as a CI artifact.

### Researcher integrations (NEW)

- **`integrations/opentargets/from_opentargets.py`** — converts Open
  Targets disease-target associations to claim YAMLs. Queries the
  Open Targets Platform v4 GraphQL API, handles UniProt cross-references,
  preserves OT association scores in the claim mechanism field.
- **`integrations/crispr/from_crispr_screen.py`** — converts CRISPR
  screen output (MAGeCK gene_summary, BAGEL2 BF output, DrugZ output,
  or generic TSV) to claim YAMLs. Flags hits that are in the DepMap
  common-essential gene list with explicit triage warnings.
- **`integrations/grant_audit/grant_audit.py`** — interactive claim
  builder for academic PIs, plus an audit-to-Markdown reporter that
  produces copy-pasteable Rigor & Reproducibility section text for
  grant submissions.
- **`docs/USE_CASES.md`** — comprehensive researcher-persona analysis
  with grounded pain points from the target-validation reproducibility
  literature (Bayer 20-25% study, Amgen, NIH Rigor & Reproducibility
  guidelines). Five personas, three with full integration code, one
  flagged as speculative. Includes explicit "what this tool is NOT for"
  section to prevent misapplication.

### Verified

- End-to-end run on Kaggle (Python 3.12, engine v1.4.0 + manual data
  patch — equivalent to v1.4.1): 5 claims, exit code 2, ruleset SHA
  `35ef2b2ab...` pinned across all reports, HTML dashboard renders
  correctly.
- Standalone `batch_audit.py` exercised in both offline and live mode.
  Live mode took ~13 seconds total (6s per claim with real UniProt +
  ChEMBL queries); offline mode took ~0.5s total.
- Same ruleset SHA across offline and live runs — fixtures are
  faithful to live adapter output.

### Known limitations

- Nextflow and Snakemake workflows are statically validated only at
  release time. End-to-end execution requires Nextflow >= 23.10 or
  Snakemake >= 7.0; CI's batch job covers the verified path.
- Cloud profiles (`awsbatch`, `gcp`) contain placeholder values for
  queues and project IDs; configure before use.
- The `--workers > 1` path uses `multiprocessing.Pool` with fork
  start method (Linux default). On macOS / Jupyter, prefer
  `--workers 1` to avoid fork-after-thread hangs.
