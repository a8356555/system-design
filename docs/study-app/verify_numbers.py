"""Check that numeric figures in data/{inc,mech}-*.json appear in their cited source pages.

Fetches each source URL directly with a normal browser UA (no archives/mirrors: a blocked page is
reported as unreadable, not worked around). PDFs go through pdftotext. A figure counts as verified
when every number token in it (e.g. "3.8", "200", "99.99") appears in the text of one of its sources.

Writes data/number-check.json and prints a summary. Does not modify the data files.
"""
import concurrent.futures
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser("~/.claude/skills/harvesting-threads-posts/scripts"))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
CACHE = os.path.join(HERE, ".pagecache")
NUM = re.compile(r"\d+(?:[.,]\d+)*")
MIN_TEXT = 2000  # below this the page is a block / JS shell, not readable content


def page_text(url):
    os.makedirs(CACHE, exist_ok=True)
    key = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9]", "_", url)[:180])
    if os.path.exists(key + ".txt"):
        return open(key + ".txt").read()
    raw = key + ".raw"
    code = subprocess.run(["curl", "-s", "-L", "-m", "30", "-A", UA, "-o", raw, "-w", "%{http_code}", url],
                          capture_output=True, text=True).stdout.strip()
    text = ""
    if code.startswith("2") and os.path.exists(raw):
        head = open(raw, "rb").read(5)
        if head.startswith(b"%PDF"):
            text = subprocess.run(["pdftotext", raw, "-"], capture_output=True, text=True).stdout
        else:
            text = subprocess.run([sys.executable, os.path.expanduser(
                "~/.claude/skills/harvesting-threads-posts/scripts/html_to_text.py"), raw],
                capture_output=True, text=True).stdout
    open(key + ".txt", "w").write(text)
    return text


def normalize(s):
    return s.replace(",", "").replace(" ", " ")


def tokens(figure):
    return [t.replace(",", "") for t in NUM.findall(figure) if not re.fullmatch(r"(19|20)\d\d", t) or len(NUM.findall(figure)) == 1]


def load_items():
    items = []
    for path in sorted(glob.glob(os.path.join(HERE, "data", "inc-*.json")) + glob.glob(os.path.join(HERE, "data", "mech-*.json"))):
        d = json.load(open(path))
        for x in d.get("incidents", []) + d.get("mechanisms", []):
            urls = [s["url"] for s in x.get("sources", []) if s.get("url")]
            if x.get("numbers"):
                items.append((os.path.basename(path), x["id"], x["numbers"], urls))
    return items


def main():
    items = load_items()
    urls = sorted({u for _, _, _, us in items for u in us})
    with concurrent.futures.ThreadPoolExecutor(10) as pool:
        texts = dict(zip(urls, pool.map(page_text, urls)))
    report, stats = [], {"verified": 0, "not_found": 0, "unreadable": 0}
    for f, iid, figures, us in items:
        readable = [normalize(texts[u]) for u in us if len(texts[u]) >= MIN_TEXT]
        for fig in figures:
            toks = tokens(fig)
            if not toks:
                continue
            if not readable:
                status = "unreadable"
            elif any(all(t in txt for t in toks) for txt in readable):
                status = "verified"
            else:
                status = "not_found"
            stats[status] += 1
            report.append({"file": f, "id": iid, "figure": fig, "status": status})
    json.dump(report, open(os.path.join(HERE, "data", "number-check.json"), "w"), ensure_ascii=False, indent=1)
    print(stats)


if __name__ == "__main__":
    main()
