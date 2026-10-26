"""Rebuild posts.md from all_posts.jsonl.

Usage: python3 build_posts.py   (run inside docs/threads-chunhao2026/)

Groups each series-tagged post with the author's same-day follow-up
posts (ordered by decoded shortcode), keeps system-design series only.
"""
import collections
import json
import re

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
KEEP = {"Tech Blog 系列", "Tool 系列", "Comparison 系列", "System Design 系列",
        "System Design Interview 系列", "Case Study 系列", "Small Quiz 系列"}
SKIP_PREFIX = ("Claude Code Workflow", "MCP vs. A2A", "Unit Test vs.", "好問題該怎麼問",
               "API vs. MCP", "Beyond code generation", "RAG", "OpenAI 如何")
ORDER = ["System Design Interview 系列", "System Design 系列", "Case Study 系列",
         "Tech Blog 系列", "Tool 系列", "Comparison 系列", "Small Quiz 系列",
         "Cross-domain 系列"]
MAX_FOLLOWUPS = 4


def media_id(code):
    n = 0
    for ch in code[:11]:
        n = n * 64 + ALPHABET.index(ch)
    return n


def load_posts():
    posts = [json.loads(line) for line in open("all_posts.jsonl")]
    posts = [p for p in posts if "text" in p]
    for p in posts:
        p["mid"] = media_id(p["url"].split("/post/")[1])
    return sorted(posts, key=lambda p: p["mid"])


def group(posts):
    groups, cur = [], None
    for p in posts:
        m = re.match(r"\s*<([^>]{2,40})>\s*(.*)", p["text"], re.S)
        if m:
            cur = {"series": m.group(1), "title": m.group(2).split("\n")[0].strip(), "posts": [p]}
            groups.append(cur)
        elif cur and p["date"] == cur["posts"][-1]["date"] and len(cur["posts"]) < MAX_FOLLOWUPS:
            cur["posts"].append(p)
        else:
            cur = None
    return groups


def wanted(g):
    if g["title"].startswith("Occam"):
        return True
    return g["series"] in KEEP and not g["title"].startswith(SKIP_PREFIX) and g["title"] != "Git"


def render(sel, total, span):
    out = ["# Threads @chunhao2026 — 系統設計相關貼文全集", "",
           f"> 來源：https://www.threads.com/@chunhao2026 ｜ 全帳號 {total} 篇（{span}）。本檔收錄系統設計相關 {len(sel)} 組，"
           "每組 = 主文 + 作者同日接續留言，原文照錄；連結含登入後收集的連結預覽卡。",
           "> 未收錄：PM / Business / UX / Podcast Blog、多數 Cross-domain 思維文、AI 工具類（Claude Code、MCP、RAG、OpenAI agents）、Git、Unit test、生活與職涯文。",
           "", "## 目錄", ""]
    by_series = {s: sorted([g for g in sel if g["series"] == s], key=lambda g: g["posts"][0]["mid"]) for s in ORDER}
    for s, gs in by_series.items():
        if gs:
            out.append(f"- **{s.replace(' 系列', '')}**：" + "、".join(g["title"][:28] for g in gs))
    out.append("")
    for s, gs in by_series.items():
        if not gs:
            continue
        out += [f"## {s.replace(' 系列', '')}（{len(gs)}）", ""]
        for g in gs:
            first = g["posts"][0]
            out += [f"### {first['date']} — {g['title']}", f"[原文]({first['url']})", ""]
            for p in g["posts"]:
                out.append("\n".join("> " + ln if ln.strip() else ">" for ln in p["text"].split("\n")))
                out.append("")
            links = sorted({u for p in g["posts"] for u in p.get("links", [])})
            if links:
                out += ["連結：" + " ｜ ".join(links), ""]
    return "\n".join(out)


def main():
    posts = load_posts()
    sel = [g for g in group(posts) if wanted(g)]
    span = f"{posts[0]['date']} ~ {posts[-1]['date']}"
    open("posts.md", "w").write(render(sel, len(posts), span))
    print(len(sel), collections.Counter(g["series"] for g in sel))


if __name__ == "__main__":
    main()
