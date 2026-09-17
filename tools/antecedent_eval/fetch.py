"""
Fetches the claims of random granted US patents from Google Patents.

usage: fetch.py [COUNT] [CORPUS_DIR]

Each patent's page is cached under CORPUS_DIR/html and its claims are written, in
document order, to CORPUS_DIR/<number>.txt ("What is claimed is:" then one line per
claim element).  The sample is seeded, so the same command gives the same corpus.
One request per second.
"""
import json, os, random, re, subprocess, sys, time
from lxml import html as LH

WANT = int(sys.argv[1]) if len(sys.argv) > 1 else 200
OUT = sys.argv[2] if len(sys.argv) > 2 else "antecedent_corpus"
os.makedirs(os.path.join(OUT, "html"), exist_ok=True)
rng = random.Random(20260915)


def fetch(num):
    for kind in ("B2", "B1"):
        cache = os.path.join(OUT, "html", f"US{num}{kind}.html")
        if os.path.exists(cache):
            return f"US{num}{kind}", open(cache, "rb").read()
        url = f"https://patents.google.com/patent/US{num}{kind}/en"
        r = subprocess.run(["curl", "-s", "--max-time", "30", "-A", "Mozilla/5.0", "-w", "%{http_code}", url],
                           capture_output=True)
        body, code = r.stdout[:-3], r.stdout[-3:].decode()
        time.sleep(1.0)
        if code == "200":
            open(cache, "wb").write(body)
            return f"US{num}{kind}", body
    return None, None


def _walk(el, out):
    is_div = isinstance(el.tag, str) and el.tag == "div"
    if is_div:
        out.append("\n")
    if el.text:
        out.append(el.text)
    for ch in el:
        _walk(ch, out)
        if ch.tail:
            out.append(ch.tail)
    if is_div:
        out.append("\n")


def claims_text(body):
    tree = LH.fromstring(body)
    sec = tree.xpath('//section[@itemprop="claims"]')
    if not sec:
        return None
    blocks = []
    for claim in sec[0].xpath('.//div[@id and starts-with(@id, "CLM-")]'):
        out = []
        _walk(claim, out)
        lines = [re.sub(r"[ \t\r\f\v]+", " ", l).strip() for l in "".join(out).split("\n")]
        lines = [l for l in lines if l]
        if lines:
            blocks.append("\n".join(lines))
    if not blocks:
        return None
    return "What is claimed is:\n" + "\n".join(blocks) + "\n"


if __name__ == "__main__":
    index, tried = {}, 0
    while len(index) < WANT and tried < WANT * 3:
        num = rng.randint(10_000_000, 12_400_000)
        tried += 1
        pid, body = fetch(num)
        if not pid:
            continue
        text = claims_text(body)
        if text and re.match(r"What is claimed is:\n1\.", text):
            open(os.path.join(OUT, pid + ".txt"), "w").write(text)
            index[pid] = len(text)
            print(len(index), pid, len(text), flush=True)
    json.dump(index, open(os.path.join(OUT, "index.json"), "w"), indent=1)
    print("done", len(index), "of", tried)
