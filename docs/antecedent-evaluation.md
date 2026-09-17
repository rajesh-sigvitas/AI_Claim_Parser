# Antecedent module: evaluation on granted US patents

A parser that is only checked against the documents someone happens to upload gets fixed
one phrasing at a time. This evaluation measures it on patents nobody chose.

## Method

`tools/antecedent_eval/` holds the two scripts.

1. **Corpus.** `fetch.py` draws random granted US patents (numbers 10,000,000 to
   12,400,000, seeded) from Google Patents and writes each one's claims in document
   order, one line per claim element.
2. **False errors.** A granted patent has been examined, so almost every
   `MISSING_ANTECEDENT`/`REVERSE_ANTECEDENT` error on one is the parser's mistake.
   `evaluate.py` runs the Claim Master pipeline on every patent and writes each error
   with its context, so the causes can be reviewed and grouped.
3. **Missed errors.** In each patent `evaluate.py` plants one real error. It picks a body
   introduction "a X" that the claim refers back to and has no other introduction, and
   turns it into "the X". It then checks that the module reports that term in that claim.

```bash
PYTHONPATH=. ./venv/bin/python tools/antecedent_eval/fetch.py 200 /tmp/corpus
PYTHONPATH=. ./venv/bin/python tools/antecedent_eval/evaluate.py /tmp/corpus /tmp/eval.json
```

To compare against an older version on the same corpus, run the second command with
`PROJECT=<git worktree of the old commit>`.

## Results: 200 patents, 3,230 claims (15-16 Sep 2026)

| | Committed code (`ede5a5a`) | 15 Sep | 16 Sep (verb forms) |
|---|---|---|---|
| Errors on granted patents | 3,390 (1.06 per claim) | 472 (0.146 per claim) | **447 (0.138 per claim)** |
| "Possibly missing" warnings | – (tier did not exist) | 1,103 (0.341 per claim) | 1,079 (0.334 per claim) |
| Planted errors reported | 189 / 192 | 186 / 192 (129 error, 57 warning) | **186 / 192** (129 error, 57 warning) |

The 16 Sep column re-ran the same seeded corpus against a tree with only that day's
changes reverted, which reproduced the 15 Sep numbers exactly, so the two columns are
comparable.  Recall is unchanged -- the same 129 planted errors are still reported as
errors and the same 186 are still reported at all -- so the precision came from reading
claim language better, not from reporting less.

Not all of the remaining errors are false. A hand review of 40 of the 15 Sep set of 472
found real drafting errors in granted patents:

- "the first capacitive voltage divider", never introduced in its claim chain;
- "the first second plane", a typo;
- "the power loss", used in claim 1 without an introduction.

About a third of the sample was undecidable without reading the whole claim tree, so the
figure in the table is an upper bound on the false-error rate, not a count of mistakes.

## What changed, and why it is general

Each change addresses a way claims are written, found as a recurring cause across many
patents rather than in one document. Each has a regression case in
`tests/test_claim_language.py` or `tests/test_reference_matching.py`, paired with a case
that must still be reported.

- **Two tiers (ClaimMaster, spec 3.1/3.2).**
  - `MISSING_ANTECEDENT` (error) is reported only when nothing in the claim chain could
    be the antecedent.
  - `POSSIBLY_MISSING_ANTECEDENT` (warning) names the possible antecedent and the
    reason. The reasons are:
    - the same head noun with other wording;
    - the word used only as a modifier ("the collection" / "a collection opening");
    - an act recited as a verb ("the change" / "changing", "the extrusion" /
      "extruding", "the initial production" / "initially producing");
    - a part of an introduced element (MPEP 2173.05(e));
    - the reference without its last words;
    - a nominalised act ("the treatment of plants").
  - A different ordinal is never a candidate.
- **Alternative readings.** Where the phrase reader has to guess a boundary (at a
  participle, an `-able` word, a word before a determiner), it keeps the other reading
  too. An introduction may match through any reading. A reference may match through its
  full or a longer reading, but never a shortened one: "an image" must not supply "the
  image processing device".
- **Introductions:**
  - a bare noun after any preposition;
  - after "having / has / contains / comprises";
  - after "thereon / therein …" ("a memory having stored thereon instructions");
  - ordinal shorthand ("first and second electrodes", "a first and a second clutch",
    "first- and second-wheel assemblies");
  - parenthetical acronyms, including their ordinal and chained forms ("(PHY) protocol
    data unit (PPDU)");
  - superlatives ("the strongest available signal").
- **Term boundaries:**
  - hyphen = space;
  - trailing adverbs and adjectives ("rearwards", "adjacent", "nearest", "here",
    "downstream");
  - a trailing past participle ("instructions stored thereon");
  - a plural head followed by a base-form verb ("the beams define");
  - adverbs and participles before the head ("two oppositely arranged plates", "the
    modified mapping");
  - "respective" is never the head.
- **No antecedent needed:**
  - boilerplate ("the following …", "the step of …", Markush "the group consisting of");
  - sequence listings;
  - proper names ("the Internet");
  - bare property nouns of something ("the time of the interruption", "the size of …",
    "the difference between …", "the operational status of a module");
  - "the selected gateway" after "selecting a gateway".
- **Two forms of one verb (16 Sep).** Relating a noun to a verb the claim recites is
  what lets "the selected gateway" rest on "selecting a gateway" and "the change" on
  "changing".  The stemmer behind it produced roots that did not line up whenever the
  spelling changed -- `applied`/`applying` gave "appli"/"apply", `production`/`producing`
  gave "product"/"produc", `extrusion`/`extruding` gave "extru"/"extrud" -- so both rules
  silently failed on every `-tion`/`-sion` nominalisation and every y/i participle.  A
  word now yields a *set* of plausible roots, because the same ending is ambiguous
  ("action" is "act"+"ion", "production" is "produc"+"tion"), and two words are related
  when their sets meet.  Irregular past participles ("wound" / "winding") come from a
  short table that leaves out participles which are ordinary claim nouns ("ground",
  "cast", "set").
- **An act noun with a qualifier (16 Sep).** "the initial production" is "initially
  producing".  A word in front of the act noun is allowed only when it is another form
  of a word the claim recites, so "the base station" is still not "based".
- **The object of "of" (16 Sep).** "a mixing of individual components" recites the
  components, so they are registered as an introduction of their own; otherwise the
  later "the individual components" had only the whole phrase to match, whose head is
  "mixing".  Not after a bare quantifier ("a first pair of cameras", "the number of
  times"), where "of" belongs to the counting phrase, and never when the object repeats
  what the phrase already normalizes to ("the group of PbF2" normalizes to "pbf2", and
  registering it again read as a reverse antecedent).
- **"resulting" (16 Sep).** "the resulting mixture" is "the mixture": the word points
  back at what the previous step produced instead of narrowing the element.
- **Number agreement is chain-scoped (16 Sep).** `plural_checker` measured a claim
  against the whole claim set, so a sibling claim's "a plurality of suction conduits"
  put MID101312US claim 5 in the wrong even though claim 5 depends on claim 1. It now
  asks which numbers the claim's own chain *introduced*: a reference disagrees only when
  its number was never introduced there. A chain that recites the set and names a member
  of it ("a primary suction conduit of the plurality of suction conduits") offers both
  and contradicts neither. "each container" introduces the singular without being able
  to disagree, a dependent claim's opening back-reference recites nothing, and "lens",
  "gas" and "series" are singular nouns that merely end in -s. Together these took
  singular/plural findings on the corpus from 229 to 199 and made MID101312US match its
  ClaimMaster report exactly at eleven findings.
- **Ambiguous antecedent basis (16 Sep).** Spec 3.3, the last unimplemented category.
  Its detection sketch -- count introductions per head noun, flag a definite reference
  once the count reaches two -- gives 1,712 errors on the corpus, 0.53 per claim, because
  it cannot tell one element mentioned twice from two elements. What decides ambiguity is
  not how many elements share a head noun but how many of them *answer to this
  reference*, which `term_match.supports` already decides everywhere else. Five rules for
  a reference that does say which element it means took that to 53, 0.016 per claim:
  an ordinal ("the first wheel"), the introduction's own wording ("a semiconductor
  material" for "the semiconductor material"), a plural covering the group ("the ring
  oscillators"), a distributive or deictic reference ("each of the faces", "the
  respective face"), and a dependent claim's opening back-reference. What remains reads
  as genuine: "the housing" after "a bottom housing" and "a top housing", "the stator"
  after a thrust, an electric and a fluid stator.
- **Term-grouping overrides (16 Sep).** Spec section 5, the escape hatch: `force_group`,
  `truncate` and `ignore`, read from the JSON file named by `TERM_OVERRIDES_PATH` and
  applied where a phrase boundary is decided, not scattered through the rules. Unset by
  default, and the corpus numbers above are measured with none configured, so they
  measure the rules rather than a word list. Reach for an override only when a phrasing
  resists a general rule -- every figure in this document came from finding the rule
  instead.
- **Claim boundaries.** A line-initial number far out of sequence ("…a viscosity of /
  4300. cP") is claim text, not claim 4300.

## Known limits

- The act and part rules downgrade some real errors to warnings. They are still
  reported; 57 of the 192 planted errors land in the warning tier, mostly because
  another element shares the head noun (spec 3.2 asks for exactly that).
- Coordinated adjectives ("the stabilizing and equalizing system", "the second positive
  and negative contacts") and slash alternatives ("epicardium/myocardium") are not
  expanded.
- `AMBIGUOUS_ANTECEDENT` does not catch two elements introduced in *identical* words
  ("a sensor on the door ... a sensor on the window ... the sensor"), the example the
  spec gives. Both normalize to the same term, and so does the reference, so nothing
  distinguishes them from one element recited twice -- which is far commoner and which
  the deduplication by wording is there to suppress. Telling them apart needs the
  prepositional complement the term reader currently drops.
- The ambiguity count on granted patents is not comparable to the missing/reverse figure
  above. That metric rests on a granted patent having been examined; examiners let
  ambiguity through far more often, so the 53 are not all false.
- A Markush group written "selected from the group of A, B and C" -- without
  "consisting" -- is still reported.  The rule that excuses Markush groups matches a
  term starting "group", but that phrasing normalizes to its first alternative instead.
