"""Merge data/*.json into template.html -> system-design-tradeoffs.html, with sanity checks."""
import collections
import glob
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


PROBLEM_NAMES = {
    "tail-latency": "尾延遲 / P99", "cascading-failure": "級聯故障與重試風暴", "overload": "過載保護",
    "cache-hotspot": "快取故障與熱點", "db-scaling-migration": "資料庫擴展與遷移",
    "change-induced": "部署與設定變更事故", "multi-region-dr": "多區域與災難復原", "capacity-peaks": "容量與流量尖峰",
    "data-integrity": "資料正確性與資料遺失", "resource-exhaustion": "資源耗盡與隱性上限",
    "third-party-dependency": "外部依賴故障", "time-clock": "時間與時鐘", "security-availability": "攻擊造成的可用性事件",
    "llm-serving": "LLM / AI 服務",
}


def load_incidents(data, problems):
    """Load data/inc-*.json in PROBLEM_NAMES order, then any extra types (named via inc file's 'problemName')."""
    paths = sorted(glob.glob(os.path.join(HERE, "data", "inc-*.json")))
    by_type = {}
    for path in paths:
        part = load(os.path.basename(path))
        by_type[part["problem"]] = part
    order = [p for p in PROBLEM_NAMES if p in by_type] + [p for p in by_type if p not in PROBLEM_NAMES]
    incidents, names = [], []
    for pid in order:
        part = by_type[pid]
        names.append([pid, PROBLEM_NAMES.get(pid) or part.get("problemName", pid)])
        for x in part["incidents"]:
            x["problem"] = pid
            x["topics"] = [t for t in x.get("topics", []) if t in TOPIC_IDS]
            flagged = [n for n in x.get("numbers", []) if SECOND_HAND.search(n)]
            if flagged:
                problems.append(f"incident {x['id']}: dropped second-hand numbers {flagged}")
                x["numbers"] = [n for n in x["numbers"] if n not in flagged]
            if not x.get("sources"):
                problems.append(f"incident {x['id']}: no sources")
        incidents += part["incidents"]
        data["quiz"] += [dict(q, topic=pid) for q in part.get("quiz", [])]
    dup = [k for k, v in collections.Counter(x["id"] for x in incidents).items() if v > 1]
    problems += [f"duplicate incident id {k}" for k in dup]
    return incidents, names


def apply_number_checks(items, problems):
    """Use verify_numbers.py output (+ manual review) to drop unsupported figures and flag unreadable ones."""
    check_path = os.path.join(HERE, "data", "number-check.json")
    if not os.path.exists(check_path):
        return
    review_path = os.path.join(HERE, "data", "number-review.json")
    review = {(r["id"], r["figure"]): r for r in json.load(open(review_path))} if os.path.exists(review_path) else {}
    status = {}
    for r in json.load(open(check_path)):
        status[(r["id"], r["figure"])] = r["status"]
    by_id = {x["id"]: x for x in items}
    for (iid, fig), st in status.items():
        x = by_id.get(iid)
        if not x or fig not in x.get("numbers", []):
            continue
        if st == "unreadable":
            x["numbersUnverified"] = True
        elif st == "not_found":
            r = review.get((iid, fig))
            verdict = r["verdict"] if r else "unsupported"
            if verdict == "wrong" and r.get("fix"):
                x["numbers"] = [r["fix"] if n == fig else n for n in x["numbers"]]
            elif verdict not in ("supported", "derived"):
                x["numbers"] = [n for n in x["numbers"] if n != fig]
                problems.append(f"{iid}: removed unsupported figure {fig[:50]}")


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
    incidents, problem_types = load_incidents(data, problems)
    data["incidents"] = incidents
    data["problems"] = problem_types
    dup = [k for k, v in collections.Counter(m["id"] for m in mechanisms).items() if v > 1]
    problems += [f"duplicate mechanism id {k}" for k in dup]
    data["mechanisms"] = mechanisms
    apply_number_checks(mechanisms + incidents, problems)
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
