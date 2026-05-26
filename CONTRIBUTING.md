# Contributing

Thanks for your interest in improving the falsifiable-targets workflow
layer. A few notes before opening an issue or PR.

## Scope

This repository is an **orchestration layer** around the
[falsifiable-targets](https://github.com/crisprking/falsifiable-targets)
engine. Bug reports and feature requests fall into two buckets:

1. **Workflow / orchestration issues** — `batch_audit.py` behavior,
   Nextflow / Snakemake wiring, Docker image, CI, examples,
   documentation. These belong here.
2. **Engine issues** — audit rules, claim schema, verdict logic,
   ruleset SHA, sentinel calibration, UniProt / ChEMBL adapters.
   These belong in the
   [engine repository](https://github.com/crisprking/falsifiable-targets/issues).

If you're unsure which bucket your issue belongs to: file it here and
we'll redirect if needed.

## Development setup

```bash
# Clone and install the engine
git clone https://github.com/crisprking/falsifiable-targets.git
cd falsifiable-targets
pip install -e ".[dev]"

# Clone this repo as a sibling
cd ..
git clone https://github.com/crisprking/falsifiable-targets-workflow.git
cd falsifiable-targets-workflow

# Smoke test the workflow layer
make batch
```

If `make batch` returns exit code 2 and writes `reports/audit_summary.json`
with 5 entries, you're set up correctly.

## Running tests locally

The workflow layer's CI exercises the full path end-to-end. To run
the same checks locally:

```bash
# Standalone runner (~1 second)
python scripts/batch_audit.py --claims-dir claims --reports-dir reports --offline

# Aggregation-only path
python scripts/batch_audit.py --aggregate-only --reports-dir reports

# Dry run
python scripts/batch_audit.py --claims-dir claims --reports-dir /tmp/r --dry-run
```

For Nextflow and Snakemake paths, install the respective engines and run
`make nf-local` / `make snakemake`.

## Coding standards

- Python: `ruff check` clean; line length 100. Type hints required for
  new public functions.
- Shell / Make: POSIX-compatible. Avoid bashisms unless behind a clear
  shebang.
- Documentation: README updates that affect user-facing commands must
  match `--help` output verbatim. The README's verdict table must be
  reproduced by running `make batch` (CI verifies this).

## PR checklist

- [ ] `make batch` succeeds with the expected exit code (2 by default,
  due to the FALSIFIED example claim).
- [ ] CI workflow passes.
- [ ] New features include at least one CI assertion.
- [ ] Documentation updated if user-visible behavior changes.
- [ ] Pinned engine version updated if needed (in `README.md`,
  `Dockerfile`, `workflow/envs/falsifiable-targets.yaml`, and CI).

## Engine version pinning

This workflow layer pins to a minimum engine version (`>= v1.4.1`).
When bumping the pin, update all four locations:

1. `README.md` (Quick Start install command and Engine Version Pinning section)
2. `Dockerfile` (`ARG FT_REF=v1.4.1`)
3. `workflow/envs/falsifiable-targets.yaml` (pip URL fragment)
4. `.github/workflows/workflow-ci.yml` (pip install line)

A bump should typically also bump this layer's minor version.

## Reporting bugs

Include:
- Engine version (`python -c "from _version import __version__; print(__version__)"`)
- Workflow version (this repo's `CHANGELOG.md` top entry)
- Exact command that reproduced the issue
- `reports/audit_summary.json` if a batch run was involved
- OS and Python version
