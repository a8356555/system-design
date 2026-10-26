"""Check every source URL in data/mech-*.json; write data/url-status.json {url: status}."""
import concurrent.futures
import glob
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def status(url):
    out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-L", "-m", "20", "-A", UA, "-w", "%{http_code}", url],
                         capture_output=True, text=True)
    return url, out.stdout.strip() or "000"


def main():
    urls = set()
    for path in glob.glob(os.path.join(HERE, "data", "mech-*.json")):
        for m in json.load(open(path))["mechanisms"]:
            urls |= {s["url"] for s in m.get("sources", []) if s.get("url")}
    with concurrent.futures.ThreadPoolExecutor(12) as pool:
        result = dict(pool.map(status, sorted(urls)))
    json.dump(result, open(os.path.join(HERE, "data", "url-status.json"), "w"), indent=1)
    bad = {u: c for u, c in result.items() if not c.startswith(("2", "3"))}
    print(f"{len(result)} urls, {len(bad)} not 2xx/3xx")
    for u, c in sorted(bad.items()):
        print(c, u)


if __name__ == "__main__":
    main()
