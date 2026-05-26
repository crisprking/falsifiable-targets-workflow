# Worked Example: Open Targets → Audit → Grant Report

This document walks through the full chain: pull a list of candidate
targets from Open Targets, run them through the falsifiability audit,
then generate a Markdown grant report for each. The goal is to show
how the integrations *compose* into a complete pre-submission workflow
for an academic group preparing a target-validation grant.

**Scenario.** A PI's lab is preparing an R01 on inflammatory bowel
disease (IBD; MONDO_0005265). They want to:

1. Identify the top 20 IBD-associated targets that Open Targets ranks
   highest.
2. For each one, run a falsifiability audit.
3. Pick the strongest candidate (SURVIVED with no caveats) and write
   a grant proposing it.
4. Include the audit report in the grant's Rigor & Reproducibility
   section.

This is what the PI types.

## Setup (one-time)

```bash
# Install the engine (v1.4.1 has the packaging fix; v1.4.0 won't work)
pip install "git+https://github.com/crisprking/falsifiable-targets.git@v1.4.1"

# Clone this workflow layer
git clone https://github.com/crisprking/falsifiable-targets-workflow.git
cd falsifiable-targets-workflow

# Confirm both work
ft-smoke   # → "Sentinel suite: 11/11 passed"
```

## Step 1: Pull candidates from Open Targets

```bash
# IBD = MONDO_0005265. Get the top 20 targets.
python integrations/opentargets/from_opentargets.py \
    --disease MONDO_0005265 \
    --top 20 \
    --output ibd_candidates/
```

**What this does.** Hits the Open Targets v4 GraphQL API, retrieves
the 20 highest-scoring targets for IBD, writes one claim YAML per
target into `ibd_candidates/`. Each claim records the OT association
score, evidence datatype breakdown, and Ensembl/UniProt cross-references.

**Why this matters.** Open Targets is the *evidence aggregator*: it
collects supporting data and assigns a confidence score. But OT does
*not* ask "what would falsify this hypothesis?" That's the gap the
audit fills.

## Step 2: Batch-audit all 20 candidates

```bash
python scripts/batch_audit.py \
    --claims-dir ibd_candidates/ \
    --reports-dir ibd_reports/ \
    --workers 4
```

**What this does.** Runs `ft-audit` against each claim in parallel,
querying UniProt + ChEMBL for live evidence. Produces:

- `ibd_reports/<target>_audit.json` — per-target audit
- `ibd_reports/audit_summary.json` — aggregated dashboard
- `ibd_reports/audit_summary.html` — visual dashboard (open in browser)

**Why this matters.** In ~30 seconds, the PI gets a structured view
of which OT-ranked targets actually survive a falsifiability check
and which don't. The verdict tiers are:

| Tier | Meaning for the PI |
|---|---|
| SURVIVED | Strong candidate. Public evidence supports without falsifying. |
| FALSIFIED_WITH_CAVEATS | Worth pursuing but the grant must address specific weaknesses. |
| FALSIFIED | Public evidence already argues against this. Don't grant around it. |
| INSUFFICIENT_DATA | Not enough public data; the grant would be exploratory. |

**Typical output for an IBD run** (illustrative; verdict mix depends
on current data):

```
=== Per-claim verdicts ===
  ✓ tnf                    SURVIVED                  (known anti-TNF success)
  ✓ il23a                  SURVIVED                  (Stelara precedent)
  ✓ jak1                   SURVIVED                  (Xeljanz precedent)
  ⚠ il17a                  FALSIFIED_WITH_CAVEATS    (failed in some indications)
  ⚠ smad7                  FALSIFIED_WITH_CAVEATS    (Mongersen failed P3)
  ✗ nod2                   FALSIFIED                 (decade of failed leads)
  ? card9                  INSUFFICIENT_DATA         (limited chemistry)
  ...
```

## Step 3: Pick a target, generate the grant report

The PI looks at `ibd_reports/audit_summary.html`, picks IL23A (SURVIVED,
strong precedent), and generates the formal audit report:

```bash
python integrations/grant_audit/grant_audit.py \
    --claim ibd_candidates/il23a.yaml \
    --report grant/il23a_rigor_section.md
```

**What this does.** Re-runs the audit on the chosen claim, then emits
a Markdown report structured for the grant's Rigor & Reproducibility
section. Includes:

- The verdict with explanation
- Cheapest falsification experiment (the go/no-go milestone)
- Any substantive caveats to address in the Approach section
- Pre-written paragraph the PI can paste into the grant

## Step 4: Submit the grant with the audit attached

The PI:

1. Copies the suggested Rigor section text from `il23a_rigor_section.md`
   into the grant.
2. Attaches the JSON audit reports as supplementary materials.
3. Cites the audit tool version and ruleset SHA in the grant's
   Methods section:

   > Target candidates were prioritized using Open Targets Platform
   > v25.06 (Ochoa et al., 2024) and audited for falsifiability using
   > falsifiable-targets v1.4.1 (ruleset SHA 35ef2b2ab5363298...).
   > The chosen target (IL23A) was selected from a pool of 20 OT-ranked
   > candidates as the highest-scoring SURVIVED claim. Audit reports
   > for all 20 candidates are provided in Supplementary File S1
   > (audit_summary.json) and the individual JSON records.

**Why this matters for the grant's competitiveness.**

- **Pre-empts the "but what would falsify this?" reviewer question.**
  The R3-style reviewer who wants to see a falsifiability statement
  gets a *structured* one.
- **Differentiates the proposal from the median.** Most R01s argue
  by accumulation of supporting evidence. Few present a structured
  falsifiability gate that pre-killed alternatives. NIH's Rigor &
  Reproducibility rubric explicitly rewards this.
- **Reproducible.** A reviewer (or program officer 18 months later)
  can re-run the audit and get the same result, modulo data updates.
  The ruleset SHA pins the rules; the audit JSON pins the inputs.

## What about FALSIFIED candidates?

In the example above, NOD2 was FALSIFIED. The PI does **not** want to
silently drop it — that creates the same selection-bias problem the
tool exists to prevent. Instead, NOD2 belongs in the grant's
Background section as a *known dead end*:

> NOD2 was an early candidate (Hugot et al., 2001) but a decade of
> chemistry effort has not produced a clinically successful inhibitor;
> our pre-submission falsifiability audit (Supplementary File S1,
> NOD2 audit) flags this with R6 (chemistry class collapse). We
> therefore prioritized IL23A, where the equivalent audit returns
> SURVIVED.

Documenting *why* you didn't pursue a target is as important as
documenting why you did. Reviewers notice.

## Pipeline integration (Nextflow)

For groups running this regularly (quarterly portfolio reviews,
PhD-student-onboarding orientation, etc.), the chain can be wrapped
as a Nextflow workflow:

```nextflow
nextflow.enable.dsl = 2

params.disease = "MONDO_0005265"
params.top = 20

process pull_targets {
    output: path 'candidates/'
    script: """
    python ${projectDir}/integrations/opentargets/from_opentargets.py \\
        --disease ${params.disease} --top ${params.top} --output candidates/
    """
}

process batch_audit {
    publishDir 'reports', mode: 'copy'
    input: path candidates
    output:
        path 'audit_summary.json'
        path 'audit_summary.html'
    script: """
    python ${projectDir}/scripts/batch_audit.py \\
        --claims-dir $candidates --reports-dir . --workers 4
    """
}

process grant_reports {
    publishDir 'grant_reports', mode: 'copy'
    input:
        path summary_json
        path candidates
    output: path '*.md'
    script: """
    # For each SURVIVED claim, generate a grant report
    jq -r '.per_claim[] | select(.verdict=="SURVIVED") | .claim' $summary_json | while read c; do
        python ${projectDir}/integrations/grant_audit/grant_audit.py \\
            --claim ${candidates}/\${c}.yaml \\
            --report \${c}_rigor.md
    done
    """
}

workflow {
    candidates_ch = pull_targets()
    audit_ch = batch_audit(candidates_ch)
    grant_reports(audit_ch[0], candidates_ch)
}
```

Run: `nextflow run pipeline.nf --disease MONDO_0005265 --top 20`

This is the same pattern that nf-core/crisprscreen and nf-core/rnaseq
use: pull → process → aggregate → publish. The falsifiability audit
slots into existing target-prioritization pipelines as a structured
gate, not a replacement for any of them.

## Caveats and honest framing

A few notes the PI should keep in mind:

- **A SURVIVED verdict is not a green light.** It means "public
  evidence as encoded does not currently falsify this." It does not
  mean "this target is correct" or "this grant will succeed." It means
  the PI's hypothesis isn't *already dead* under the public-evidence
  audit.
- **A FALSIFIED verdict is not a kill order.** It's a signal to either
  (a) revise the hypothesis to address the falsifying evidence, or
  (b) document explicitly in the grant *why* the PI's inside knowledge
  overrides the public-evidence audit. Both are scientifically
  defensible; silently ignoring it is not.
- **The audit is only as good as its fixtures and live adapters.**
  Some rules abstain in offline mode (R5, R7) because they need data
  that's not in fixture form. For grant submissions, run in live mode
  unless network access is restricted.
- **This tool does not replace the grant's biology.** The Aims, the
  Significance, the experimental design, the preliminary data — all
  still need to be there and to be good. The audit just makes one
  specific reviewer concern (falsifiability) addressable in a
  structured way.
