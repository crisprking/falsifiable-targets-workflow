# Use Cases: How Researchers Use falsifiable-targets

This document describes who uses this tool, what problem it solves for
them, and how to wire it into their existing workflow. Each persona is
grounded in a documented pain point from the target-validation
literature; speculative use cases are flagged as such.

## The problem this tool exists to solve

Target validation in drug discovery has a documented reproducibility
problem. Bayer's internal review found only **20-25% of published
target-validation results reproduced** in-house; Amgen reported similar
numbers ([Gashaw et al., 2014](https://www.drugtargetreview.com/article/821/molecular-target-validation-in-preclinical-drug-discovery/);
[Bunnage 2011](https://www.tandfonline.com/doi/full/10.1080/17460441.2016.1182484)).
Phase 2 clinical attrition is driven primarily by efficacy failure
rooted in inadequate preclinical validation.

The dominant existing platforms (Open Targets, TTD, ChEMBL) are
**evidence-aggregation** tools: they collect supporting data for a
target-disease hypothesis and assign confidence scores. None of them
ask the falsificationist question: *what is the cheapest experiment
that would kill this hypothesis if it's wrong?*

`falsifiable-targets` is the complementary tool. Pre-publication
self-audit, pre-grant self-audit, pre-wet-lab triage, post-hoc
forensic review of failed programs — anywhere a falsifiability
question would have saved time and money.

---

## Persona 1: The Academic PI writing a target-validation grant

**Who:** Mid-career investigator submitting an R01 / ERC / MRC grant
claiming "we will validate target X as a therapeutic intervention
point for disease Y."

**Pain point:** Reviewers increasingly demand falsifiability statements
(NIH rigor & reproducibility rubric, ERC's 2024 reproducibility
guidelines). Most validation plans are written as *confirmation* plans
("we will demonstrate X causes Y") rather than *falsification* plans
("if X does not cause Y, we will see this signal in experiment Z, which
costs $K and takes T weeks").

**How they use the tool:**

1. Encode their proposed target claim as a YAML file.
2. Run `ft-audit claim.yaml` and inspect the `cheapest_falsifier` field
   of the JSON report.
3. Add the cheapest falsifier to their Specific Aims as "negative
   control experiment" or "go/no-go criterion."
4. Cite the audit report and ruleset SHA in the Rigor & Reproducibility
   section of the grant.

**Example wording for a grant's Rigor section:**

> Per the falsifiability audit (falsifiable-targets v1.4.1, ruleset SHA
> `35ef2b2ab5...`), our claim survives R1-R5 (orthology, chemistry,
> genetics, expression, replication) but is flagged by R7
> (selectivity counterscreen). We address this in Aim 2.3 by
> performing a paralog counterscreen against the three closest
> homologs; failure of selectivity in this assay terminates the
> project before chemistry investment.

**Concrete win:** A claim that passes the audit *survives* the
reviewer's "what would falsify this?" question with a pre-registered,
pre-costed answer.

---

## Persona 2: The Computational Biologist triaging CRISPR screen hits

**Who:** Postdoc or staff scientist in a drug-discovery group who just
ran a genome-wide CRISPR-Cas9 knockout screen and now has 50-300
candidate genes that scored above the MAGeCK / BAGEL2 / DrugZ
significance threshold.

**Pain point:** Not all 200 hits are worth following up. Some are
core-essential (DepMap common-essential — drug them and you kill all
cells); some are paralog-redundant (knocking out gene A is rescued by
gene B, so the wet-lab phenotype won't reproduce); some have no
chemical tractability (no known small-molecule binder, no PROTAC
handle, no antibody-accessible epitope). The team's bandwidth is
"orthogonal validation on 5-10 genes," so triage decisions are
load-bearing.

**How they use the tool:**

1. Convert the screen output to a directory of claim YAMLs, one per
   gene (script: `scripts/from_crispr_screen.py`, ships with the
   workflow repo).
2. Run `python scripts/batch_audit.py --claims-dir claims/ --reports-dir
   reports/ --offline --workers 8`. Takes ~5 minutes for 200 genes.
3. Open `reports/audit_summary.html` and sort by verdict tier. The
   FALSIFIED tier is the discard pile; FALSIFIED_WITH_CAVEATS is the
   "follow up but with these specific caveat-resolution experiments";
   SURVIVED is the prioritized list.
4. Take the SURVIVED list to the next group meeting.

**Concrete win:** A 200-gene hit list becomes a 10-gene prioritized
list with documented reasons-for-exclusion for the discarded 190.
Reproducibly. The discarded genes' rationale survives a "why did you
drop gene X?" question 18 months later when a reviewer or partner asks.

**Pipeline integration** (Nextflow):

```nextflow
process triage_screen_hits {
    input:
    path mageck_results

    output:
    path "reports/audit_summary.json"
    path "reports/audit_summary.html"
    path "reports/prioritized.txt"   // SURVIVED list

    script:
    """
    python from_crispr_screen.py $mageck_results --threshold 0.05 --output claims/
    python batch_audit.py --claims-dir claims/ --reports-dir reports/ --offline --workers 8
    jq -r '.per_claim[] | select(.verdict=="SURVIVED") | .claim' \\
        reports/audit_summary.json > reports/prioritized.txt
    """
}
```

This process drops cleanly into existing nf-core/crisprscreen-style
pipelines as a post-MAGeCK filtering step.

---

## Persona 3: The Open Targets Power User running disease-centric prioritization

**Who:** Computational drug discovery group at a pharma, biotech, or
academic translational center. Uses the Open Targets Platform daily
for target identification. Their workflow is: pick a disease, get
Open Targets to rank targets by overall association score, take the
top 50.

**Pain point:** Open Targets ranks by *evidence aggregation* — a
target with many weak signals scores high. But many high-scoring
targets are scientifically already-falsified (failed Phase 2/3 trials
that weren't deprioritized in the underlying evidence) or have known
fatal flaws (cross-kingdom orthology mismatches, paralog redundancy,
essentiality conflicts). The "traffic light" prioritization view helps
but doesn't surface these in a structured, auditable way.

**How they use the tool:**

1. Query Open Targets GraphQL API for top N targets for a disease.
2. Convert the JSON response to claim YAMLs (script:
   `scripts/from_opentargets.py`).
3. Run batch audit.
4. Cross-reference: a target that scores high on Open Targets but
   FALSIFIED on the audit is a *high-value finding* — either
   Open Targets data needs updating or the audit's fixtures are stale.
   Either way, worth a closer look.

**Concrete win:** Open Targets becomes the "evidence aggregator,"
falsifiable-targets becomes the "falsifiability gate." Together they
form a more complete prioritization pipeline than either alone.

**Worked example** (Python):

```python
import requests, yaml
from pathlib import Path

# Query Open Targets for psoriasis (MONDO:0005083)
query = """
{
  disease(efoId: "MONDO_0005083") {
    associatedTargets(page: {index: 0, size: 50}, orderByScore: "score") {
      rows {
        target { approvedSymbol, id }
        score
      }
    }
  }
}
"""
resp = requests.post("https://api.platform.opentargets.org/api/v4/graphql",
                     json={"query": query}).json()

claims_dir = Path("claims_psoriasis")
claims_dir.mkdir(exist_ok=True)

for row in resp["data"]["disease"]["associatedTargets"]["rows"]:
    symbol = row["target"]["approvedSymbol"]
    uniprot = row["target"]["id"]
    claim = {
        "claim": {
            "target_symbol": symbol,
            "uniprot_id": uniprot,
            "indication": "psoriasis",
            "mechanism": f"Open Targets association score: {row['score']:.3f}",
            "claim_type": "validated_mechanism",
        }
    }
    (claims_dir / f"{symbol}.yaml").write_text(yaml.safe_dump(claim))

# Then: python scripts/batch_audit.py --claims-dir claims_psoriasis --reports-dir reports/
```

---

## Persona 4: The Reviewer / Editor / Program Officer doing post-hoc audits

**Who:** Journal editor, grant program officer, or reproducibility
auditor (think Reproducibility Project: Cancer Biology) reviewing a
manuscript or grant that claims a target-disease link.

**Pain point:** Reviewing 50+ target-validation manuscripts a year.
Each one's evidence appears persuasive in isolation; few make their
falsifiability conditions explicit. No reproducible way to compare
"how falsifiable is claim X vs. claim Y?"

**How they use the tool:**

1. Encode the manuscript's target claim as YAML (5 minutes once
   you've done it twice).
2. Run `ft-audit claim.yaml`.
3. Include the audit JSON in the review record. The ruleset SHA
   guarantees that next year's reviewer of the same claim would get
   the same answer (modulo new ChEMBL / UniProt data).

**Concrete win:** Reviews become version-controlled and reproducible.
Two reviewers of the same claim get the same audit; disagreement is
about evidence interpretation, not about which rules were applied.

---

## Persona 5: The Internal Pharma Portfolio Reviewer (speculative)

**Who:** Senior scientist at a pharma running quarterly portfolio
reviews of pre-clinical programs.

**Pain point:** "Why are we still funding the X program when its
preclinical package looks weaker than Y, which we just killed?"
Portfolio decisions are often driven by champion enthusiasm rather
than head-to-head structured comparison.

**How they would use the tool** (this hasn't been validated by an
actual user yet — speculative):

1. Maintain a `programs/` directory of claim YAMLs for every active
   pre-clinical program.
2. Re-run `ft-audit` quarterly. Watch for verdict drift: a program
   that was SURVIVED in Q1 but flips to FALSIFIED_WITH_CAVEATS in Q3
   means new public evidence has emerged that contradicts the
   program's premise.
3. Verdict drift becomes the trigger for a manual review, not a
   replacement for it.

**Concrete win** (if it worked): Earlier detection of programs whose
premises have been silently invalidated by public data nobody internal
has noticed.

**Why this is speculative:** Pharma portfolio review involves
information the tool can't access (CMC, market access, IP, internal
data). The tool only handles the public-evidence layer of the
question. It would augment the review, not replace it.

---

## What this tool is NOT for

Being explicit about non-use-cases prevents misapplication:

- **Drug repurposing prediction.** This tool audits target-disease
  claims; it doesn't predict drug-disease associations. Use
  [DrugRepurposingHub](https://clue.io/repurposing) or similar.
- **De novo target identification.** This tool falsifies existing
  hypotheses; it doesn't generate new ones. Use Open Targets, TTD,
  or CRISPR screen hits as the upstream source of hypotheses.
- **Chemical structure-activity prediction.** This tool checks
  whether chemistry data *exists* (R6 chemistry-class collapse, R7
  selectivity counterscreen), not whether new chemistry will work.
  Use ChEMBL, DeepChem, or your QSAR tool of choice.
- **Clinical trial outcome prediction.** This tool flags pre-clinical
  red flags. It does not predict P2/P3 success.
- **Replacement for biological judgment.** A FALSIFIED verdict means
  "the public evidence as encoded falsifies this claim under the
  current ruleset." It does not mean "abandon this target." It means
  "explain why your inside knowledge overrides the public-evidence
  audit, in writing, in the next group meeting."

---

## Where this tool sits in the toolchain

```
                           ┌─────────────────────────────┐
                           │  HYPOTHESIS GENERATION       │
                           │  ─────────────────────────   │
                           │  • CRISPR screens (MAGeCK)   │
                           │  • Literature mining         │
                           │  • Open Targets prioritization│
                           │  • Internal knowledge        │
                           └──────────────┬──────────────┘
                                          │
                                          ▼
                           ┌─────────────────────────────┐
                           │  EVIDENCE AGGREGATION        │
                           │  ─────────────────────────   │
                           │  • Open Targets (scoring)    │
                           │  • TTD, ChEMBL, UniProt      │
                           │  • DepMap, PRIDE             │
                           └──────────────┬──────────────┘
                                          │
                                          ▼
                          ┌──────────────────────────────┐
                          │  FALSIFIABILITY AUDIT  ◄── HERE │
                          │  ─────────────────────────   │
                          │  • falsifiable-targets       │
                          │    (7 rules → verdict tier   │
                          │     + cheapest falsifier)    │
                          └──────────────┬──────────────┘
                                          │
                                          ▼
                           ┌─────────────────────────────┐
                           │  WET-LAB VALIDATION          │
                           │  ─────────────────────────   │
                           │  • Orthogonal assays         │
                           │  • CRISPR rescue             │
                           │  • Animal models / NAMs      │
                           └─────────────────────────────┘
```

The tool sits *between* evidence aggregation and wet-lab work. It is
not a replacement for either; it is the gating function that asks
"is this claim worth wet-lab investment?" before the money gets spent.

## Further reading

- [Bayer reproducibility study (Prinz et al., 2011)](https://www.nature.com/articles/nrd3439-c1) — the foundational paper on the 20-25% reproducibility rate.
- [Amgen / Begley & Ellis 2012](https://www.nature.com/articles/483531a) — the parallel finding from Amgen.
- [NIH Rigor & Reproducibility guidelines](https://grants.nih.gov/policy-and-compliance/policy-topics/reproducibility) — current requirements for NIH grants.
- [Open Targets Platform documentation](https://platform-docs.opentargets.org/) — the evidence-aggregation tool this audit complements.
