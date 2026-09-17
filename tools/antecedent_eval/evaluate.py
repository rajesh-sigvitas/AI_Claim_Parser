"""
Accuracy of the antecedent module on granted US patents.

Precision: a granted patent was examined, so every MISSING/REVERSE finding on it is a
candidate false positive; each is written out with its context for review.
Recall: plant a real error -- turn a body introduction "a X" that is referenced later as
"the X" into "the X" -- and check the module reports that term in that claim.

usage (from the repo root):
    PYTHONPATH=. ./venv/bin/python tools/antecedent_eval/fetch.py 200 CORPUS_DIR
    PYTHONPATH=. ./venv/bin/python tools/antecedent_eval/evaluate.py CORPUS_DIR OUT.json

Every MISSING/REVERSE error on a granted patent is written to OUT.json with its context.
Most are the parser's mistakes, but examiners do miss some -- review a sample by hand
before concluding.  PROJECT=<path> evaluates another checkout (e.g. a git worktree of
the previous commit) against the same corpus, for a before/after comparison.
"""
import glob, json, os, random, re, sys
from loguru import logger
logger.remove()
sys.path.insert(0, os.environ.get("PROJECT", os.getcwd()))
from app.report.service import report_service
from app.analysis.antecedent.analyzer import AntecedentAnalyzer
from app.analysis.antecedent.claim_walker import iter_claim_blocks

HERE = None  # set from argv
ERR = ("MISSING_ANTECEDENT", "REVERSE_ANTECEDENT")
WARN = ("POSSIBLY_MISSING_ANTECEDENT",)


def findings_of(text):
    rep = report_service.build(text.encode(), "p.txt")
    return rep, [f for f in rep.antecedents.findings]


def context(f):
    loc = f.location
    t = (loc.element_text or "") if loc else ""
    if loc and loc.char_start is not None:
        return t[max(0, loc.char_start - 70):loc.char_start] + "[[" + t[loc.char_start:loc.char_end] + "]]" + t[loc.char_end:loc.char_end + 50]
    return t[:160]


def plant(text, rng):
    """One mutation per patent: 'a X' -> 'the X' for a body introduction referenced later."""
    rep = report_service.build(text.encode(), "p.txt")
    doc = rep.claim_document
    if not doc:
        return None
    reg, _ = AntecedentAnalyzer().build_registry(doc)
    candidates = []
    for c, occs in reg.occurrences_by_claim.items():
        for o in occs:
            if o.kind != "INTRODUCTION" or o.is_implicit or o.block_index < 0:
                continue
            if o.determiner not in ("a", "an"):
                continue
            later = [r for r in occs if r.kind == "REFERENCE" and r.normalized_term == o.normalized_term
                     and r.sort_key > o.sort_key]
            others = [i for i in occs if i is not o and i.kind == "INTRODUCTION"
                      and i.normalized_term == o.normalized_term]
            inherited = reg.inherited_introductions(c, o.normalized_term)
            if later and not others and not inherited:
                candidates.append(o)
    if not candidates:
        return None
    o = rng.choice(candidates)
    surface = o.surface_form
    mutated_surface = re.sub(r"^(a|an)\b", "the", surface, flags=re.I)
    # replace this exact occurrence in the claim's text: find the claim line by number
    claims = re.split(r"(?m)^(?=\d+\. )", text.split("What is claimed is:\n", 1)[1])
    for idx, block in enumerate(claims):
        if block.startswith(f"{o.claim_number}. ") and surface in block:
            claims[idx] = block.replace(surface, mutated_surface, 1)
            return ("What is claimed is:\n" + "".join(claims), o.claim_number, o.normalized_term)
    return None


def main(corpus, out):
    global HERE
    HERE = corpus
    rng = random.Random(7)
    files = sorted(glob.glob(os.path.join(HERE, "US*.txt")))
    result = {"patents": 0, "claims": 0, "findings": [], "by_type": {}, "recall": []}
    for path in files:
        pid = os.path.basename(path)[:-4]
        text = open(path).read()
        try:
            rep, fs = findings_of(text)
        except Exception as e:
            result["findings"].append({"patent": pid, "type": "CRASH", "term": repr(e)[:200]})
            continue
        result["patents"] += 1
        result["claims"] += len(rep.claim_document.claims) if rep.claim_document else 0
        for f in fs:
            result["by_type"][f.type.value] = result["by_type"].get(f.type.value, 0) + 1
            if f.type.value in ERR + WARN:
                result["findings"].append({"patent": pid, "claim": f.claim_number, "type": f.type.value,
                                           "term": f.term, "context": context(f)})
        try:
            planted = plant(text, rng)
        except Exception as e:
            planted = None
        if planted:
            mtext, claim, term = planted
            _, mfs = findings_of(mtext)
            matched = [f for f in mfs if f.claim_number == claim
                       and term in (f.evidence or {}).get("normalized_term", "")
                       and f.type.value in ERR + WARN]
            hits = [f.type.value for f in matched]
            reasons = [(f.evidence or {}).get("reason", "") + ": " +
                       str((f.evidence or {}).get("possible_antecedent", "")) for f in matched
                       if f.type.value in WARN]
            result["recall"].append({"patent": pid, "claim": claim, "term": term,
                                     "caught": any(h in ERR for h in hits), "reported": bool(hits),
                                     "reasons": reasons})
    json.dump(result, open(out, "w"), indent=1)
    n_err = len([f for f in result["findings"] if f["type"] in ERR])
    n_warn = len([f for f in result["findings"] if f["type"] in WARN])
    caught = sum(r["caught"] for r in result["recall"])
    reported = sum(r["reported"] for r in result["recall"])
    print(f"patents={result['patents']} claims={result['claims']} by_type={result['by_type']}")
    print(f"error findings on granted patents: {n_err}  ({n_err / max(1, result['claims']):.3f} per claim)")
    print(f"possibly-missing warnings on granted patents: {n_warn}  ({n_warn / max(1, result['claims']):.3f} per claim)")
    print(f"planted errors caught as error: {caught}/{len(result['recall'])}, reported at all: {reported}/{len(result['recall'])}")
    crashes = [f for f in result["findings"] if f["type"] == "CRASH"]
    if crashes: print("crashes:", crashes[:5])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
