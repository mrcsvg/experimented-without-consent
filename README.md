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
analysis/compute-agreement.py   inter-coder agreement
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
| 2026-07-28 | Contextual help added to the coding form: per-value definitions and a per-variable full criterion, transcribed from the frozen codebook; the Codebook tab now carries `protocol/codebook-v2.md` in full. Pilot-anchor suppression (above) introduced with it. No field name, option value, export key or coding rule changed. **Landed before the second pass began — no coding had been entered.** |

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
