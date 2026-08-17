# Experimented On Without Consent — replication package

Materials for a disclosure audit of online experimentation on the platforms the
European Union designates as systemically important under the Digital Services
Act (DSA).

**Research question.** Twenty-six services — 24 Very Large Online Platforms and
2 Very Large Online Search Engines — are designated by the European Commission
under the DSA. What do those services tell their users, in the documents that
govern the relationship, about running behavioural experiments (A/B tests) on
them? And where such disclosure exists at all, does it live in binding documents
or in non-binding channels such as help centres and engineering blogs?

Because the designated list is exhaustive of the services the Union treats as
systemically important, this is a **census, not a sample**. The unit of analysis
is the *designated service*, not the provider: Google Search, Google Play, Google
Maps, Google Shopping and YouTube are coded separately, as are Facebook and
Instagram.

## Status

| | |
|---|---|
| Instrument | codebook v2, **frozen 2026-07-04** after a 3-platform pilot |
| Pass 1 | complete (26/26), automated pass, single coder — **provisional** |
| Pass 2 | in progress — independent human coder, blind |
| Reliability | pending pass 2 |
| Data release | after adjudication (see *What is not here yet*) |

The findings are **not final**. Pass 1 rests on a single coding pass whose
inter-coder reliability has not been established, and it was captured from
outside the European Union — which under-codes the legal-basis variable, since
five services gate their per-purpose legal-basis tables to EU traffic.

## What is here

```
index.html                      coding instrument for the second coder (single-file app)
api/state.js                    serverless persistence (GitHub Contents API)
protocol/codebook-v2.md         the frozen instrument, in full
protocol/sampling-frame.md      the 26 designated services + selection rule
notebooks/01-keyword-sweep      the §3 keyword protocol, run over the frozen corpus
notebooks/02-llm-recall-sweep   recall check: what the keyword list misses
notebooks/03-coding-flow        the second pass, one variable at a time
analysis/patterns.py            the twelve §3 terms — single source for both notebooks
analysis/codebook.py            the codebook, read from the instrument (not re-transcribed)
analysis/coding_flow.py         linear coding flow: one variable at a time, evidence gated
analysis/compute-agreement.py   inter-coder agreement
analysis/freeze-sources.py      capture, hash and archive the audited documents
analysis/snapshot-progress.py   progress snapshot — metadata only, never codes
analysis/nb-clean.py            keeps notebook output out of the repository
.github/workflows/              the daily snapshot job
```

### The coding instrument

`index.html` is a self-contained application (no build step, no dependencies)
that presents the codebook, the document manifest per service, and the nine
coding variables, and exports a JSON record set. It is deployed as a static site;
progress is saved to the browser and, where the persistence function is
configured, committed to a data branch of this repository — which yields a
timestamped audit trail of when each coding was entered.

The instrument is deliberately **blind**: it contains no codes from pass 1. It
does reproduce the three pilot anchors that the frozen codebook itself carries
(`protocol/codebook-v2.md` §2) — those come from the three-platform pilot of
2026-07-04, not from pass 1 — and the coding form **suppresses the anchor that
names the service being coded**, showing a notice in its place. Consulting the
reference is the coder's choice; having the answer in view during the decision
is not.

#### Instrument changes

Changes to the instrument are logged here with their date, so that any change
landing once coding is under way can be weighed in the reliability analysis.

| Date | Change |
|---|---|
| 2026-07-31 | The document manifest now points at the frozen corpus. Where a document has a frozen copy, its URL is shown struck through as provenance and the corpus filename is shown as the thing to open; the 19 documents without one stay live links. Fixes a long-standing defect in `linkify` uncovered by the change: URLs were matched after HTML-escaping, so `&` had become `&amp;` and the pattern — which excluded `;` — truncated the URL mid-entity, breaking eight Google links. **Landed before the second pass began — no coding had been entered.** No field name, option value, export key or coding rule changed. |
| 2026-07-28 | Contextual help added to the coding form: per-value definitions and a per-variable full criterion, transcribed from the frozen codebook; the Codebook tab now carries `protocol/codebook-v2.md` in full. Pilot-anchor suppression (above) introduced with it. No field name, option value, export key or coding rule changed. **Landed before the second pass began — no coding had been entered.** |

### The notebooks

The codebook (§3) requires, per document, a count of each of twelve keyword terms
— roughly 1,700 searches across the frozen corpus. `notebooks/01-keyword-sweep`
performs them. It verifies every document against its recorded hash first,
quarantines any that fail, then demonstrates on synthetic strings and on the
codebook's own published anchors that the patterns fire where they should and
stay silent where they should not, and only then sweeps. What it emits is counts
and keyword-in-context, per document: **the machine locates, the coder decides.**
No screen in either notebook shows a suggested code, level or score.

`notebooks/02-llm-recall-sweep` is a validity check on the keyword list itself,
not a coding aid. It asks a model to return verbatim passages describing
behavioural experimentation; every returned quote is verified programmatically
against the frozen text and discarded if it cannot be located there. Passages
that no §3 term would have found are the recall gap. Its findings do not enter
the coded dataset and are not shown to the second coder during the reliability
pass.

#### Notebook output does not enter the repository

`*.ipynb` is filtered on the way into the index, and `.githooks/pre-commit`
refuses a commit whose staged notebook still carries output. The reason is not
diff hygiene: notebook 02 returns passages the human coder did not find, and
notebook 01 instructs the second coder to clone this repository — so a saved
output would arrive through the door the protocol itself opened.

Neither the filter nor the hooks path travels with a clone. Once per clone:

```
python3 analysis/nb-clean.py --install
```

The filter affects only what reaches the index; the file on disk keeps the
output of your run.

### Progress snapshots

Every autosave from the instrument is a commit on the data branch, which records
*when* each coding changed but says nothing about how much of the frame is done.
A scheduled job (`.github/workflows/coding-snapshot.yml`) supplies the second
view: once a day it measures the coded state and writes `audit/PROGRESS.md`
plus a dated snapshot under `audit/snapshots/` on the data branch. It commits
only when something actually changed, so the snapshot series is a record of
progress rather than a heartbeat.

What it emits is **metadata only** — per service, how many of the thirteen core
fields and seven evidence fields are filled, whether the keyword log is present,
and the timestamp of the last edit. It never emits a coded value: no code, no
evidence, no keyword log, no notes. That constraint is what lets progress be
public while the second pass is still blind and the codings are still withheld.

### Agreement analysis

`analysis/compute-agreement.py` takes the two coding passes and reports agreement
per variable:

```bash
python3 analysis/compute-agreement.py pass1.json pass2.json
```

Three of the nine variables need care, and the script handles each explicitly.
Two variables did not vary at all in pass 1 (26 × "no"), which makes Cohen's
kappa **undefined** rather than low — the chance-agreement term goes to 1 and the
statistic evaluates 0/0. A third varied minimally (25/1), which puts it in the
territory of the kappa paradox, where high observed agreement can yield a
negative coefficient because the coefficient is penalising the skew of the
marginal distribution rather than any disagreement between coders. For those
variables the script reports **percent agreement and the contingency table**, and
the substantive claims of absence rest on the logged keyword search that the
protocol requires per document — which any reader can re-run against the same
documents. Kappa is reported where it is defined, weighted (linear) for the
ordinal variable, and Jaccard plus per-category agreement for the multi-select
variables.

### Freezing the audited documents

The documents this study codes are live web pages that their publishers revise
without notice, which puts two things at risk. A reader cannot re-run the
keyword search "against the same documents" if the documents have moved on. And
more sharply, if the two coding passes read different versions of a page, the
resulting disagreement is not coder disagreement — it is document drift, and
after the fact the two are not separable, which is precisely what an agreement
statistic must not confound.

`analysis/freeze-sources.py` performs the capture:

```bash
python3 analysis/freeze-sources.py preflight                    # where am I coming from?
python3 analysis/freeze-sources.py inventory --coded <pass1>.json --out frozen/inventory.json
python3 analysis/freeze-sources.py capture --inventory frozen/inventory.json --out-dir frozen
python3 analysis/freeze-sources.py verify --out-dir frozen      # has anything moved since?
```

Two tracks, because neither alone is sufficient. The **local** capture stores
the extracted text and its SHA-256: it is authoritative, because it is taken
from the same EU vantage the coding requires, and it is what the keyword search
and the verbatim quotations actually run against. The **Wayback** capture is
third-party and citable, but Save Page Now fetches from the Internet Archive's
own infrastructure rather than through the operator's connection, so for the
services that gate their legal-basis tables to EU traffic it necessarily
freezes the non-EU view. It evidences that the URL existed and what it said to
the world; it does not evidence what the coder read.

The published package carries the snapshot URLs and the text hashes, not the
captured documents. A hash lets a reader prove a document is or is not the one
that was coded without this repository redistributing platform policies
wholesale — which is the same line the data licence already draws around
verbatim quotation.

Because vantage decides what several of these documents even say, `capture`
refuses to run from outside the EU/EEA unless explicitly overridden, rather
than silently freezing the wrong view.

## What is not here yet, and why

Pass-1 codings, the pilot memo, results and the adjudication log are **withheld
until the second coding pass is complete**. Publishing them now would be visible
to the second coder and would compromise the independence that the second pass
exists to establish. They are added at release, together with the frozen dataset.

## Reproducing the audit

1. Read `protocol/codebook-v2.md` — the nine variables, the decision rules, and
   the binding/non-binding register distinction that the study turns on.
2. Read `protocol/sampling-frame.md` for the frame and the selection rule.
3. Capture each service's EU-facing documents **from an EU IP**. This matters:
   several services serve their per-purpose legal-basis tables only to EU
   traffic, so auditing from elsewhere silently under-codes that variable.
4. Code with `index.html`, or with any tool that produces the same fields.
5. Compare passes with `analysis/compute-agreement.py`.

Every code carries a verbatim quotation, its document, and its URL; every code of
absence carries the keyword-search log that demonstrates the search was run.

## Notes for reuse

The codebook is written in Portuguese, since it was produced for a
Portuguese-speaking coder; an English translation is planned for the release.
The instrument itself is not specific to this frame — the variables and the
register distinction apply to any set of consumer-facing platform documents, and
the manifest can be swapped for a different roster.

## Licence

Code (`index.html`, `api/`, `analysis/`) — MIT, see `LICENSE`.
Protocol, codebook and data — CC BY 4.0, see `LICENSE-DATA`.

## Citation

See `CITATION.cff`. A versioned archive with a DOI will accompany the paper.
