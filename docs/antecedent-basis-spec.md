Antecedent Basis Module — Specification

Authority: MPEP 2173.05(e) (35 U.S.C. 112(b)). Reference implementation for category naming: ClaimMaster Antecedent Basis Browser.

1. Core model

A claim introduces elements and later makes references to them.

Introduction = first recitation of an element.
Reference = a later mention preceded by the or said.
Antecedent basis = the introduction that a reference resolves to.

A reference must resolve to an introduction in:

the same claim, at an earlier position, OR
any claim in its dependency chain (transitively, to the root independent claim).
2. Introduction rules (THIS IS WHERE THE CURRENT BUG IS)

An element is introduced when it appears WITHOUT the / said. Do not require an indefinite article. All of the following are valid introductions:

Pattern	Example	Note
Indefinite article	a processor, an overlay	obvious case
Bare mass/uncountable noun	telecommunication data, first content, mitigation information	NO article, still valid
Ordinal-modified bare noun	second content, third content	NO article, still valid
Inside an alternative branch	... second content ..., or third content ...	both branches introduce
Quantified	one or more synonyms, at least one sensor, a plurality of pins	sets number = indeterminate or plural
Preamble recitation	A system for processing a signal, comprising: introduces signal	valid antecedent for the body
Gerund of a recited act	automatically adjusting a parameter supports later the adjusting	weak support; warning tier only
Inherent features — suppress, do not flag

Per MPEP 2173.05(e): inherent components of a recited element have antecedent basis in the element itself. the outer surface of said sphere needs no separate introduction.

Suppression list (configurable): surface, side, end, edge, top, bottom, interior, exterior, portion, section, perimeter, axis, length, width, height, thickness, diameter.

Non-identical wording still counts

Per Ex parte Porter: a controlled stream of fluid provides antecedent basis for the controlled fluid. Match on head noun, not on exact string.

3. Issue categories

Mirror ClaimMaster's five categories. Emit a severity on every finding.

3.1 MISSING_AB — severity: ERROR

Definite reference with no resolvable introduction anywhere in the dependency chain.

Example:

1. A device comprising a housing; and a motor mounted to the shaft.
                                                         ^^^^^^^^^ no "a shaft"
3.2 POSSIBLY_MISSING_AB — severity: WARNING

An introduction with the same head noun exists, but modifiers differ. Human confirms.

General -> specific is genuinely suspect (MPEP: a lever then said aluminum lever is indefinite). Weight this higher.
Specific -> general is usually fine (an aluminum lever then the lever). Weight lower.

Also use this tier for gerund references (the adjusting) where exactly one matching act was recited.

3.3 AMBIGUOUS_AB — severity: ERROR

Two or more distinct elements share a head noun, and a later reference does not disambiguate.

Per MPEP: if two different levers are recited, said lever is unclear.

a sensor on the door ... a sensor on the window ... the sensor transmits
                                                    ^^^^^^^^^^ which one?

Detection: maintain a count per normalized head noun. If count >= 2 when a bare definite reference is parsed, emit AMBIGUOUS_AB.

3.4 LIMITING_PREAMBLE — severity: INFO

An element is introduced in the preamble and referenced in the body. This is not an error. It signals the preamble may be claim-limiting ("breathes life and meaning"), which narrows scope. Strategic note for the drafter.

Note the reverse is explicitly fine per MPEP: body elements absent from the preamble do NOT render a claim indefinite. Never flag that direction.

3.5 NUMBER_MISMATCH — severity: WARNING

Introduced plural, referenced singular, or vice versa.

a plurality of pins ... wherein the pin is metal

Treat one or more X and at least one X as number = indeterminate; they match both singular and plural references.

3.6 REVERSE_AB — severity: WARNING (optional, non-standard)

the X appears at an earlier position than a X within the same claim. NOT a ClaimMaster category. Keep it if useful, but do not count it as an ERROR and do not present it as standard practice.

4. Output contract
json
{
  "document": "string",
  "claim_count": 0,
  "summary": {
    "errors": 0,
    "warnings": 0,
    "info": 0
  },
  "findings": [
    {
      "id": "F001",
      "claim": 1,
      "type": "MISSING_AB",
      "severity": "ERROR",
      "term": "the shaft",
      "normalized": "shaft",
      "char_span": [120, 129],
      "message": "No antecedent basis for \"the shaft\" in claim 1.",
      "suggested_fix": "Introduce the element first (e.g. \"a shaft\"), or change the reference to an element already recited.",
      "resolved_from": null
    }
  ]
}

Hard requirements:

suggested_fix is populated on EVERY finding, not just the first.
summary counts must be tiered. Never sum ERROR + WARNING + INFO into one "errors found" headline.
Never report a claim as having errors when all its findings are INFO.
5. Parsing prerequisites
Normalize input text before analysis. PDF extraction corrupts claim text. Known failure modes from the US12677034 extraction:
missing spaces: usercharacteristic, ofthe
semicolons rendered as colons: by the first user: should be ;
hyphenation and line-wrap artifacts If limitations are split on ; and :, a stray colon silently changes scope boundaries and produces asymmetric false positives.
Segment claims into: claim number, preamble, transition (comprising / consisting of / consisting essentially of), body limitations.
Resolve dependency from The X of claim N / of any of claims N-M. Build the full transitive chain before resolving references.
Term grouping is the hardest part. packet receiving device driver may split into packet + device driver. Ship a user-configurable dictionary:
force-group: list the full phrase so the parser keeps it whole
truncate: server system // controls groups server system only
ignore: exclude a phrase from parsing entirely Do not attempt to make the parser perfect without an override mechanism.
6. Build order
Fix introduction rules (section 2). Biggest precision win.
Add the severity tier to the output contract and the report template.
Implement AMBIGUOUS_AB.
Implement NUMBER_MISMATCH and LIMITING_PREAMBLE.
Add inherent-feature suppression.
Add the term-grouping override dictionary.

> **Implementation note (16 Sep 2026).** Section 4's tiering is implemented:
> `Severity` carries INFO/WARNING/ERROR, `DEFAULT_SEVERITY` in
> `app/analysis/models.py` maps each finding type to its tier, and
> `AntecedentAnalysisResult.severity_summary` reports the three counts separately.
> `LIMITING_PREAMBLE` is INFO as section 3.4 asks, but it is raised for every
> preamble introduction rather than only where the term is re-used in the body,
> because both ClaimMaster ground-truth reports do that. Section 3.3 is implemented
> as `AMBIGUOUS_ANTECEDENT`, but not by the counting sketch this section gives --
> see `docs/antecedent-evaluation.md`. Section 5's term-grouping overrides are
> implemented in `app/analysis/antecedent/overrides.py`, configured by
> `TERM_OVERRIDES_PATH` and inert when unset. Finding types keep the repository's
> names (`MISSING_ANTECEDENT`, not `MISSING_AB`), and `REVERSE_ANTECEDENT` stays
> ERROR rather than the optional WARNING of 3.6.
