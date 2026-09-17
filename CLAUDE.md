# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

The virtualenv lives at `./venv` (Python 3.12) and `python` is not on PATH, so call it explicitly. There is no package install or pytest config; run everything from the repo root with `PYTHONPATH=.`.

```bash
# API server (Swagger at http://localhost:8000/docs, routes under /api/v1)
PYTHONPATH=. ./venv/bin/uvicorn app.main:app --reload --port 8000
docker compose up --build            # same app in a container

# Tests -- always target tests/: the repo root holds ad-hoc test_*.py scripts that
# pytest would otherwise collect
PYTHONPATH=. ./venv/bin/python -m pytest tests -q
PYTHONPATH=. ./venv/bin/python -m pytest tests/test_antecedent_route.py::test_route_reports_missing_and_reverse_antecedents -q

# Frontend (Vite + React; gitignored, talks to VITE_API_URL, default http://localhost:8000)
cd frontend && npm run dev | npm run build | npm run lint
```

- **Known failures, not regressions:** `tests/test_api_routes.py` (`/version`, `/metrics`, `/parse/batch`, `/export/zip`) and `test_pdf_generator.py::test_parse_and_download_flow`. Those routes are commented out in `app/api/multi-endpoints.py`, which is not registered in `app/api/routes.py`.
- `tests/test_antecedent_regression.py` reads `/home/sig/Downloads/test_Aug_18.docx` and skips when it is absent.
- System dependencies: LibreOffice (Word → PDF), Tesseract, libmagic, and DejaVu fonts (the report embeds DejaVu Sans for its ✔/✘/⚠ glyphs).
- `__pycache__/*.pyc` files are tracked in git and block `git stash pop`/checkout; restore them with `git checkout -- '*.pyc'` rather than committing them.
- Settings come from `.env` via `app/core/config.py`. Generated PDFs go to `OUTPUT_DIR`, default `/tmp/claim_parser/outputs`. `TERM_OVERRIDES_PATH` optionally points at a term-grouping override file (see §III below); unset, the antecedent module behaves as if it did not exist.

## Architecture

Two pipelines share one claim parser.

**1. Claim parsing** (`/parse`, `/parse/pdf`) — `app/services/parser_service.py`:

- `FileTypeDetector` (python-magic) → extractor from `app/extractor/factory.py`:
  - Word is converted to PDF by LibreOffice, then read by PyMuPDF.
  - Scanned PDFs fall back to Tesseract, then Groq.
  - USPTO XML is parsed structurally by `extractor/xml.py` and skips the steps below.
- `app/normalizer/engine.py` merges wrapped lines. It must keep claim-start lines intact, including the bracketed numbers `[12.]` and `12.[13.]` that a PDF of a tracked-change rendering contains.
- `app/parser/engine.py`:
  - `claim_detector` discards everything before "What is claimed is:".
  - `claim_splitter` splits the claims.
  - `dependency_detector` resolves parents.
  - `hierarchy_builder` builds the element tree.
- The result is a `ClaimDocument` (`app/models/`). `app/formatter/pdf_generator.py` renders the formatted claims PDF.

**2. Claim Master (CM) report** (`/report`, `/report/pdf`, `/analyze/antecedents`, `/analyze/antecedents/pdf`) — `app/report/service.py`:

- `app/document/loader.py` builds a `PatentDocument`, which keeps the whole application as rendered pages of numbered lines:
  - .docx files are laid out by LibreOffice first, so `[Page N, line M]` citations match the printed document.
  - `document/sections.py` detects sections, running headers and footers are flagged, and `document/figures.py` reads drawing sheets.
  - The claims section is fed to the same normalizer and `ParserEngine` as pipeline 1.
  - XML uploads go through `parser_service` instead.
- Analyzers in `app/analysis/` each take a `ClaimDocument`:
  - `hierarchy/` (report §I) — claim trees, statutory category, amendment status markers, invalid parents. Category is classified from the *claimed subject* (the noun phrase before the first preposition), not the whole preamble.
  - `claim_errors/` (§II) — independent check functions, each carrying its CFR/MPEP authority.
  - `antecedent/` (§III):
    - `claim_walker.iter_claim_blocks` → `term_extractor` (records character offsets) → `term_registry` (ordered by block, then character).
    - Then `resolver` (missing/reverse), `ambiguity`, `preamble_checker` and `plural_checker`.
    - **Term-grouping overrides** (`overrides.py`, spec section 5) are the escape hatch for phrase boundaries no rule gets right: `force_group` keeps a listed phrase whole, `truncate` cuts an over-grouped phrase back to the listed words, `ignore` drops a phrase entirely. A JSON file named by `TERM_OVERRIDES_PATH`, read once on first use and matched on words (case, hyphens and punctuation are ignored). Unset by default, and inert when unset — prefer a general rule; reach for these only when a phrasing resists one.
    - `analyze(errors_only=True)` returns the antecedent findings only: missing and reverse (errors) and possibly missing (warnings). The standalone `/analyze/antecedents` routes use this. The CM report adds the limiting-preamble and singular/plural checks.
    - **Severity is decided by finding type**, in `DEFAULT_SEVERITY` (`app/analysis/models.py`): missing and reverse are ERROR, possibly-missing and singular/plural are WARNING, limiting preamble is INFO. No checker sets its own tier. `AntecedentAnalysisResult.severity_summary` carries all three counts, and the report never adds them together — a section of nothing but notes is announced as notes, never as errors (spec section 4).
    - `plural_checker` reports a reference recited in a number its **own claim chain** never introduced. "each container" and "at least one X" introduce a number without being able to contradict one, and a dependent claim's opening back-reference ("The lens according to claim 1") recites nothing at all.
- `report/cm_report_generator.py` renders a `CMReport`:
  - `generate()` produces the full report.
  - `generate_antecedent_report()` produces the standalone antecedent PDF: §III only, no contents page or section numbering.
  - Sections IV–VIII (specification checks) are not implemented yet and render as "Not analysed".

### Invariants that span files

- **Finding locations** are a block index plus character offsets into the text from `iter_claim_blocks`. Block -1 is the header; body elements are numbered depth-first. Every renderer must walk claims through that same function, or highlights land on the wrong words.
- **Headerless claims:** the first markerless top-level element is drawn on the claim number's line, not below it (`PDFGenerator._opens_claim_line`). `AnnotatedPDFGenerator` and the CM claim cells mirror this rule.
- **Tracked changes and claim numbers:**
  - A .docx is read with its tracked changes accepted (`app/document/revisions.py`, applied in `office.convert_to_pdf` for both pipelines). Never read LibreOffice's rendering of tracked changes: it prints deleted and inserted words side by side and shows shifted list numbers as `12.[13.]`.
  - Claims containing tracked edits get `metadata["tracked_edits"]`, which drives §II's amended-without-status check. It is only attached when the .docx's numbered-claim count matches the parsed claims.
  - Where a number is still shown twice (a PDF of such a rendering), the bracketed one is the claim number; the other is kept as `metadata["rendered_number"]`. Brackets never mean "cancelled" — only a `(Canceled)` status does. Cancelled claims are left out of `ClaimDocument.claims`, listed in `metadata["cancelled_claims"]`, and still count toward the numbering sequence.
- **Dependencies:** `claim.metadata["parent_claims"]` holds the full parent list ("claims 1 and 2", ranges) and is authoritative. `claim.parent_claim` is only the first parent.
- **CM report conventions:**
  - Every section opens with a status banner: green "No errors found for this section." versus red or amber with a breakdown.
  - "Not analysed" is kept distinct from a clean result.
  - An explanation prints once per issue type.
  - §III table rows split within the row (`ROW_SPLIT`). Splitting between rows raises `LayoutError` on tall claims and repeats headers mid-page.
    - Every cell handed to a `ROW_SPLIT` table must be a *list* of flowables. ReportLab's in-row split treats a bare flowable (the nested claim table, a lone `Paragraph`) as no content, so the row cannot split.
    - Keep `splitInRow` tiny. It is also the minimum height of either half of a split, so at 40 a claim overflowing the page by less than 40pt raised `LayoutError`.

### Antecedent resolution rules

- **Error vs warning.** `MISSING_ANTECEDENT` is an error only when nothing in the claim chain could be the antecedent. When something plausibly could, `resolver._possible_antecedent` makes it `POSSIBLY_MISSING_ANTECEDENT`, a warning that names the candidate. A different ordinal is never a candidate. Don't turn warnings back into errors, or errors into silence, to fix a single document.
- **Alternative readings.** Where `_collect_phrase` has to guess a phrase boundary, it returns the other readings as `alternatives`, and they reach `Occurrence.readings`. An introduction matches through any reading. A reference matches only through its full or a longer reading, never a shortened one (`resolver._reference_readings`), so a guess can't hide a real error.
- **Measure changes on granted patents.** Measure any change to the antecedent module with `tools/antecedent_eval/` (see `docs/antecedent-evaluation.md`), not only on the documents at hand. Compare false errors per claim, and planted errors reported, against the numbers recorded there.

## Reference material

- **Ground truth for §I–III** is the real ClaimMaster report for MID101312US: `MID101312US - Draft (1).docx` and `MID101312US - Draft (1) - cm report.docx`, both in `~/Downloads`, outside the repo. Current output matches it exactly: 20 claims with independents 1/9/15, §II empty, and §III with **11** findings, all limiting preamble — four on claim 1, four on claim 9, three on claim 15. Keep it matching.
  - This file previously recorded 12 findings, "11 limiting preamble plus 1 singular/plural, on claim 5". The real report has no claim 5 row. The extra finding came from `plural_checker` measuring a claim against the whole claim set: claim 5 depends on claim 1, which recites only "a primary suction conduit", while the plural "suction conduits" belongs to claims 4, 9, 13 and 19, none of which claim 5 inherits from. A claim is measured against its own dependency chain.
- **Second ground truth**: ClaimMaster's report on the tracked-changes draft 50OR570, `~/Downloads/50OR570US - Draft - QCed - 5-Aug-2026 - cm report.docx`. It has 20 claims (1→2–15, 16→17–19, 20 independent); §II flags claims 1, 2, 12, 15, 16 and 20 as amended without a status identifier; §III has one missing antecedent (claim 15, "the features").
- **`docs/antecedent-basis-spec.md` is the target spec for the antecedent module.** It covers ClaimMaster categories, severity tiers, the output contract and a build order. The code does not follow it yet:
  - Finding types are named `MISSING_ANTECEDENT`/`POSSIBLY_MISSING_ANTECEDENT`/`REVERSE_ANTECEDENT`/`LIMITING_PREAMBLE`/`SINGULAR_PLURAL`, not `*_AB`/`NUMBER_MISMATCH`.
  - Reverse antecedents are ERROR here; the spec says an optional WARNING.
  - `AMBIGUOUS_AB` is implemented as `AMBIGUOUS_ANTECEDENT` (`app/analysis/antecedent/ambiguity.py`), ERROR tier. The spec's own detection sketch — count introductions per head noun, flag once the count reaches two — is not what the code does: it would flag "the first wheel" after "a first wheel" and "a second wheel". A reference is ambiguous when two or more introductions *support* it (`term_match.supports`, the same test used everywhere else), and it is not ambiguous when it says which one it means — an ordinal, the introduction's own wording, a plural covering the group, a distributive ("each of the faces"), a deictic ("the respective face"), or a dependent claim's opening back-reference.
  - Inherent features: `lexicon.RELATIONAL_NOUNS` and `ABSTRACT_NOUNS` need no antecedent. A part of an introduced element ("the end segments of the outer ply") is a possibly-missing warning.
  - **Limiting preamble — resolved.** The spec and the ground truths were read as disagreeing, but they answer two different questions. *What is raised* follows the ground truth: every preamble introduction, as both ClaimMaster reports do, not only terms re-referenced in the body. *What it is worth* follows the spec: `Severity.INFO`. So MID101312US's eleven preamble findings are all raised and the banner reads "11 notes found", not eleven warnings. Don't reopen this without a ground-truth report that shows otherwise.
- **`docs/us12677034.fixture.json`** holds regression expectations for that spec: 0 missing-antecedent errors, 3 `AMBIGUOUS_AB`, 2 `POSSIBLY_MISSING_AB`, plus `must_not_flag` terms and known PDF-extraction corruption. It contains no claim text, and the source document is not in the repo.
