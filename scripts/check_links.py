#!/usr/bin/env python3
"""链接巡检：检查论文链接和数据集主页是否可访问，并核对标为 arXiv 的论文是否已正式发表。

    python3 scripts/check_links.py --output report.md

GitHub 仓库的可用性由 refresh_github.py 负责，这里不重复检查。
结果写成 Markdown 报告；由 .github/workflows/check-links.yml 每周运行并汇总到一个 issue。
外部网站偶尔抖动，所以本脚本不作为 PR 的必过检查，默认退出码总是 0（--strict 时有失效链接返回 1）。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datalib  # noqa: E402

UA = "Mozilla/5.0 (compatible; uav-papers-with-code-linkcheck; +https://github.com/voilalz/uav-papers-with-code)"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{}?fields=venue,year,journal,publicationVenue,externalIds"
BROKEN = {404, 410}
# 出版社常对脚本返回这些状态码，无法据此判断链接是否失效
BLOCKED = {401, 403, 418, 429, 999}


def probe(url, timeout=20):
    """返回 (状态, 说明)。状态：ok | broken | blocked | error。"""
    last = ""
    for attempt in range(2):
        for method in ("HEAD", "GET"):
            req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "*/*"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return "ok", str(resp.status)
            except urllib.error.HTTPError as err:
                last = f"HTTP {err.code}"
                if err.code in BROKEN and method == "GET":
                    return "broken", last
                if err.code in BLOCKED and method == "GET":
                    return "blocked", last
                # HEAD 被拒绝时改用 GET 再试
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                last = str(getattr(err, "reason", err))
                break
        if attempt == 0:
            time.sleep(3)
    return "error", last


def s2_venue(arxiv_id):
    req = urllib.request.Request(S2_API.format(arxiv_id), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            info = json.load(resp)
    except Exception:
        return None
    venue = (info.get("publicationVenue") or {}).get("name") or (info.get("journal") or {}).get("name") or info.get("venue")
    if venue and "arxiv" not in venue.lower():
        doi = (info.get("externalIds") or {}).get("DOI")
        return venue + (f"（DOI {doi}）" if doi else "")
    return None


def collect(papers):
    targets = []
    for p in papers:
        targets.append((p["id"], "论文", p["paper"]))
        if p.get("site"):
            targets.append((p["id"], "数据集主页", p["site"]))
    return targets


def report(results, published, total):
    lines = ["# 链接巡检报告", ""]
    broken = [r for r in results if r[3] == "broken"]
    error = [r for r in results if r[3] == "error"]
    blocked = [r for r in results if r[3] == "blocked"]
    lines.append(f"共检查 {total} 个链接：失效 {len(broken)}，无法连接 {len(error)}，"
                 f"被网站拒绝（多为反爬，需人工确认）{len(blocked)}。")
    for title, rows in (("失效链接", broken), ("无法连接", error), ("被网站拒绝，需人工确认", blocked)):
        if rows:
            lines += ["", f"## {title}", "", "| 论文 id | 类型 | 链接 | 结果 |", "|---|---|---|---|"]
            lines += [f"| `{pid}` | {kind} | {url} | {msg} |" for pid, kind, url, _, msg in rows]
    if published:
        lines += ["", "## 标为 arXiv、但可能已正式发表", "",
                  "来源 Semantic Scholar，请核实后更新 papers.yaml 的 `venue`、`year`、`ids.doi`。", "",
                  "| 论文 id | 可能的发表处 |", "|---|---|"]
        lines += [f"| `{pid}` | {venue} |" for pid, venue in published]
    return "\n".join(lines) + "\n", bool(broken or error or published)


def main(argv=None, probe_fn=probe, venue_fn=s2_venue):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", help="报告写入的文件")
    ap.add_argument("--strict", action="store_true", help="有失效链接时返回非零退出码")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    papers = datalib.load_papers()
    targets = collect(papers)
    with ThreadPoolExecutor(args.workers) as pool:
        probed = list(pool.map(lambda t: probe_fn(t[2]), targets))
    results = [(pid, kind, url, status, msg) for (pid, kind, url), (status, msg) in zip(targets, probed)]

    published = []
    for p in papers:
        if p["venue"] == "arXiv" and p.get("ids", {}).get("arxiv"):
            venue = venue_fn(p["ids"]["arxiv"])
            if venue:
                published.append((p["id"], venue))
            time.sleep(1.1 if venue_fn is s2_venue else 0)   # Semantic Scholar 未登录限速约 1 次/秒

    text, problems = report(results, published, len(targets))
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"problems={'true' if problems else 'false'}\n")
    if args.strict and any(r[3] == "broken" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
