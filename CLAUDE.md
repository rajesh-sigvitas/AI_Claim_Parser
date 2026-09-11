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
- Settings come from `.env` via `app/core/config.py`. Generated PDFs go to `OUTPUT_DIR`, default `/tmp/claim_parser/outputs`.

## Architecture

Two pipelines share one claim parser.

**1. Claim parsing** (`/parse`, `/parse/pdf`) — `app/services/parser_service.py`:

- `FileTypeDetector` (python-magic) → extractor from `app/extractor/factory.py`:
  - Word is converted to PDF by LibreOffice, then read by PyMuPDF.
  - Scanned PDFs fall back to Tesseract, then Groq.
  - USPTO XML is parsed structurally by `extractor/xml.py` and skips the steps below.
- `app/normalizer/engine.py` merges wrapped lines. It must keep claim-start lines intact, including amendment forms `[12.]` and `12.[13.]`.
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
    - Then `resolver` (missing/reverse), `preamble_checker` and `plural_checker`.
    - `analyze(errors_only=True)` returns missing/reverse only; the standalone `/analyze/antecedents` routes use this. The CM report runs all four checks.
- `report/cm_report_generator.py` renders a `CMReport`:
  - `generate()` produces the full report.
  - `generate_antecedent_report()` produces the standalone antecedent PDF: §III only, no contents page or section numbering.
  - Sections IV–VIII (specification checks) are not implemented yet and render as "Not analysed".

### Invariants that span files

- **Finding locations** are a block index plus character offsets into the text from `iter_claim_blocks`. Block -1 is the header; body elements are numbered depth-first. Every renderer must walk claims through that same function, or highlights land on the wrong words.
- **Headerless claims:** the first markerless top-level element is drawn on the claim number's line, not below it (`PDFGenerator._opens_claim_line`). `AnnotatedPDFGenerator` and the CM claim cells mirror this rule.
- **Amendment markup:**
  - Cancelled claims (`[12.]`) are left out of `ClaimDocument.claims` and listed in `metadata["cancelled_claims"]`. Their numbers collide with the live claims renumbered into them.
  - Renumbered claims keep `metadata["old_number"]`.
- **Dependencies:** `claim.metadata["parent_claims"]` holds the full parent list ("claims 1 and 2", ranges) and is authoritative. `claim.parent_claim` is only the first parent.
- **CM report conventions:**
  - Every section opens with a status banner: green "No errors found for this section." versus red or amber with a breakdown.
  - "Not analysed" is kept distinct from a clean result.
  - An explanation prints once per issue type.
  - §III table rows split within the row (`ROW_SPLIT`). Splitting between rows raises `LayoutError` on tall claims and repeats headers mid-page.

## Reference material

- **Ground truth for §I–III** is the real ClaimMaster report for MID101312US. The input `MID101312US - Draft (1).docx` and `MID101312US - Draft - CM Report.pdf` are in `~/Downloads`, outside the repo. Current output matches it exactly: 20 claims with independents 1/9/15, §II empty, and §III with 12 findings (11 limiting preamble plus 1 singular/plural, on claim 5). Keep it matching.
- **`docs/antecedent-basis-spec.md` is the target spec for the antecedent module.** It covers ClaimMaster categories, severity tiers, the output contract and a build order. The code does not follow it yet:
  - Finding types are named `MISSING_ANTECEDENT`/`REVERSE_ANTECEDENT`/`LIMITING_PREAMBLE`/`SINGULAR_PLURAL`, not `*_AB`/`NUMBER_MISMATCH`.
  - Reverse antecedents are ERROR here; the spec says an optional WARNING.
  - `AMBIGUOUS_AB` and `POSSIBLY_MISSING_AB` do not exist.
  - Inherent-feature suppression is only `lexicon.RELATIONAL_NOUNS`.
  - The spec rates limiting preamble INFO, raised only when the preamble term is re-referenced in the body. The MID ground truth flags every preamble introduction, and that is what the code does. Resolve this conflict deliberately rather than silently.
- **`docs/us12677034.fixture.json`** holds regression expectations for that spec: 0 missing-antecedent errors, 3 `AMBIGUOUS_AB`, 2 `POSSIBLY_MISSING_AB`, plus `must_not_flag` terms and known PDF-extraction corruption. It contains no claim text, and the source document is not in the repo.
