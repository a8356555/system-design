"""Merge data/*.json into template.html -> system-design-tradeoffs.html, with sanity checks."""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = "/Users/a8356555/Projects/alan/interview/system-design/docs"
TOPIC_IDS = ("contention consistency multistep idempotency caching scaling-reads sharding scaling-writes realtime "
             "fanout async-jobs streaming blobs search geo counting rate-limiting reliability api-networking auth "
             "storage-choice id-generation").split()
# Numbers must come from a page actually read; agents sometimes keep snippet-only figures with a label.
SECOND_HAND = re.compile(r"搜尋摘要|二手|未查證|未提供|摘要所述|vendor 報告|轉述|未給出|沒有給出|無具體")
DOMAINS = ("video maps connections recsys moderation data-pipeline deploy-migration observability "
           "matching-engine gaming audio collab delivery ads email payments web-search iot classic").split()


def load(name):
    with open(os.path.join(HERE, "data", name)) as f:
        return json.load(f)


def main():
    topics = [t for i in range(1, 5) for t in load(f"topics-{i}.json")]
    cases = load("cases-1.json") + load("cases-2.json")
    data = {"topics": topics, "cases": cases, "components": load("components.json"), "quiz": load("quiz.json")}

    problems = []
    mechanisms = []
    for domain in DOMAINS:
        path = os.path.join(HERE, "data", f"mech-{domain}.json")
        if not os.path.exists(path):
            problems.append(f"mechanisms: missing {os.path.basename(path)}")
            continue
        part = load(os.path.basename(path))
        for m in part["mechanisms"]:
            m["domain"] = domain
            flagged = [n for n in m.get("numbers", []) if SECOND_HAND.search(n)]
            if flagged:
                problems.append(f"mechanism {m['id']}: dropped second-hand numbers {flagged}")
                m["numbers"] = [n for n in m["numbers"] if n not in flagged]
            m["topics"] = [x for x in m.get("topics", []) if x in TOPIC_IDS]
            if not m.get("sources"):
                problems.append(f"mechanism {m['id']}: no sources")
        mechanisms += part["mechanisms"]
        data["quiz"] += [dict(q, topic=domain) for q in part.get("quiz", [])]
    dup = [k for k, v in collections.Counter(m["id"] for m in mechanisms).items() if v > 1]
    problems += [f"duplicate mechanism id {k}" for k in dup]
    data["mechanisms"] = mechanisms
    got = {t["id"] for t in topics}
    problems += [f"missing topic {t}" for t in TOPIC_IDS if t not in got]
    problems += [f"unknown topic id {t}" for t in got - set(TOPIC_IDS)]
    for t in topics:
        if len(t.get("options", [])) < 3:
            problems.append(f"{t['id']}: only {len(t.get('options', []))} options")
        for c in t.get("cases", []):
            if not os.path.exists(os.path.join(DOCS, c["ref"])):
                problems.append(f"{t['id']}: case ref not found {c['ref']}")
    ids = collections.Counter(c["id"] for c in cases)
    problems += [f"duplicate case id {k}" for k, v in ids.items() if v > 1]
    for c in cases:
        bad = [x for x in c.get("topics", []) if x not in TOPIC_IDS]
        if bad:
            problems.append(f"case {c['id']}: bad topics {bad}")
            c["topics"] = [x for x in c["topics"] if x in TOPIC_IDS]
        if not os.path.exists(os.path.join(DOCS, c.get("file", ""))):
            problems.append(f"case {c['id']}: file not found {c.get('file')}")
    qt = collections.Counter(q.get("topic") for q in data["quiz"])
    problems += [f"quiz: topic {t} has {qt[t]} questions" for t in TOPIC_IDS if qt[t] < 2]

    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = open(os.path.join(HERE, "template.html")).read().replace("/*DATA*/null", blob)
    out = os.path.join(HERE, "index.html")
    open(out, "w").write(html)
    print(f"topics {len(topics)} cases {len(cases)} mechanisms {len(mechanisms)} "
          f"components {len(data['components'])} quiz {len(data['quiz'])}")
    print(f"size {len(html.encode()) / 1024:.0f} KB -> {out}")
    print("\n".join(problems) or "no problems")
    return 0


if __name__ == "__main__":
    sys.exit(main())
