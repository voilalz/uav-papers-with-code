#!/usr/bin/env python3
"""由 data/（含 generated/ 下的统计与环境检测结果）和 templates/index.html 生成网站 index.html，并同步 README 中的数字与日期。

    python3 scripts/build.py           # 生成
    python3 scripts/build.py --check   # 只检查 index.html / README 是否与数据一致（CI 用）

index.html 是生成文件，请改 templates/index.html 或 data/，不要直接改它。
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datalib  # noqa: E402
import validate  # noqa: E402

ARCHIVED_NOTE = "仓库已归档"
README_COUNT_RE = re.compile(r"收录 \d+ 篇论文、\d+ 个代码仓库")
README_SUBS_RE = re.compile(r"\d+ 个细分方向")
README_DATE_RE = re.compile(r"(截至 )\d{4}-\d{2}-\d{2}")


# repo_signals.json 中页面要用的字段；值为空/false 的不写进页面，减小体积
SIGNAL_KEYS = ("ros", "ros_distro", "ubuntu", "cuda", "cuda_version", "px4", "px4_version", "ardupilot",
               "docker", "launch_config", "calibration", "jetson", "pretrained")


REPRO_SOURCES = {"readme": "README 写明", "tested": "有人实际编译运行过", "issue": "来自 issue / 社区报告"}
# 人工确认了主项、没填附属项时，丢弃自动推测的附属项（如确认 ros 后不再显示推测的发行版）
REPRO_COVERS = {"ros": ("ros", "ros_distro"), "cuda": ("cuda", "cuda_version"), "px4": ("px4", "px4_version")}


def page_signals(sig, repro=None):
    """自动检测结果与人工确认（repro）合并成页面用的紧凑结构。

    人工填写的项逐项覆盖自动结果，并记入 ok 列表（页面以实线标签显示）；
    值为空、false 或 none 的项不写进页面。两者都没有时返回 None。
    """
    if not sig and not repro:
        return None
    sig, repro = sig or {}, repro or {}
    merged = {k: sig.get(k) for k in SIGNAL_KEYS}
    why = {k: v for k, v in (sig.get("why") or {}).items() if k in merged}
    ok = []
    src = REPRO_SOURCES[repro["source"]] + f"，{repro['checked']} 核对" if repro else ""
    for k in SIGNAL_KEYS:
        if k not in repro:
            continue
        merged[k] = None if repro[k] == "none" else repro[k]
        why[k] = src
        ok.append(k)
        for c in REPRO_COVERS.get(k, ())[1:]:
            if c not in repro:
                merged[c] = None
                why.pop(c, None)
    out = {k: v for k, v in merged.items() if v and v != "none"}
    if repro.get("note"):
        why["note"] = repro["note"]
    why = {k: v for k, v in why.items() if k in out or k == "note"}
    ok = [k for k in ok if k in out]
    if why:
        out["why"] = why
    if ok:
        out["ok"] = ok
    return out


def page_entries(papers, taxonomy, stats, signals=None):
    """把论文条目、仓库统计和环境检测结果合并成页面使用的扁平结构。"""
    venues = taxonomy["venues"]
    stat_repos = stats.get("repos", {})
    sig_repos = (signals or {}).get("repos", {})
    names = {p["id"]: p["name"] for p in papers}
    used_by = {}                              # 数据集 id → 用它评测的条目
    for p in papers:
        for ref in p.get("evaluated_on", []):
            used_by.setdefault(ref, []).append(p["id"])
    out = []
    for p in papers:
        repos = []
        for r in p.get("repos", []):
            key = datalib.repo_key(r["name"])
            st = stat_repos.get(key, {})
            repo = {"name": st.get("full_name") or r["name"], "official": r["official"]}
            sig = page_signals(sig_repos.get(key), r.get("repro"))
            if sig is not None:
                repo["sig"] = sig
            repos.append(repo)
        main = datalib.primary_repo(p)
        st = stat_repos.get(datalib.repo_key(main["name"]), {}) if main else {}
        note = p.get("note")
        if not note and st.get("archived"):
            note = ARCHIVED_NOTE
        e = {
            "id": p["id"], "kind": p["kind"], "name": p["name"], "title": p["title"],
            "authors": p["authors"], "venue": p["venue"], "venue_full": venues[p["venue"]]["full"],
            "year": p["year"], "paper": p["paper"], "repos": repos, "subs": p["subs"], "zh": p["zh"],
            "stars": st.get("stars"), "lang": st.get("lang"), "updated": st.get("updated"),
        }
        for k in ("site", "tags", "real_flight"):
            if p.get(k):
                e[k] = p[k]
        for k in ("evaluated_on", "datasets"):
            if p.get(k):
                e[k] = [[ref, names[ref]] for ref in p[k]]
        if p["id"] in used_by:
            e["used_by"] = [[ref, names[ref]] for ref in used_by[p["id"]]]
        if note:
            e["note"] = note
        out.append(e)
    return out


def script_json(obj):
    """可安全放进 <script> 的紧凑 JSON。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render(papers, taxonomy, stats, template, signals=None):
    entries = page_entries(papers, taxonomy, stats, signals)
    tax = {"categories": taxonomy["categories"],
           "subs": [{"id": s["id"], "cat": s["cat"], "label": s["label"]} for s in taxonomy["subs"]]}
    values = {
        "{{DATA}}": script_json(entries),
        "{{TAXONOMY}}": script_json(tax),
        "{{DATA_DATE}}": json.dumps(stats.get("generated_at") or ""),
        "{{PAPER_COUNT}}": str(len(entries)),
    }
    html = template
    for key, val in values.items():
        if key not in html:
            raise SystemExit(f"模板中缺少占位符 {key}")
        html = html.replace(key, val)
    return html


def render_readme(readme, papers, taxonomy, stats):
    n_repos = sum(1 for p in papers if p.get("repos"))
    readme = README_COUNT_RE.sub(f"收录 {len(papers)} 篇论文、{n_repos} 个代码仓库", readme)
    readme = README_SUBS_RE.sub(f"{len(taxonomy['subs'])} 个细分方向", readme)
    if stats.get("generated_at"):
        readme = README_DATE_RE.sub(lambda m: m.group(1) + stats["generated_at"], readme)
    return readme


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只检查生成文件是否最新，不写入")
    args = ap.parse_args(argv)

    papers, taxonomy, stats = datalib.load_papers(), datalib.load_taxonomy(), datalib.load_stats()
    with open(datalib.SCHEMA, encoding="utf-8") as f:
        errors, _ = validate.check(papers, taxonomy, stats, json.load(f))
    if errors:
        sys.exit("数据未通过校验，请先运行 python3 scripts/validate.py 查看错误")

    with open(datalib.TEMPLATE, encoding="utf-8") as f:
        html = render(papers, taxonomy, stats, f.read(), datalib.load_stats(datalib.SIGNALS))
    with open(datalib.README, encoding="utf-8") as f:
        old_readme = f.read()
    readme = render_readme(old_readme, papers, taxonomy, stats)
    old_html = ""
    if os.path.exists(datalib.INDEX):
        with open(datalib.INDEX, encoding="utf-8") as f:
            old_html = f.read()

    if args.check:
        stale = [n for n, new, old in (("index.html", html, old_html), ("README.md", readme, old_readme)) if new != old]
        if stale:
            sys.exit(f"{'、'.join(stale)} 与 data/ 不一致，请运行 python3 scripts/build.py 后一并提交")
        print("index.html 与 README.md 已是最新")
        return

    with open(datalib.INDEX, "w", encoding="utf-8") as f:
        f.write(html)
    with open(datalib.README, "w", encoding="utf-8") as f:
        f.write(readme)
    print(f"已生成 index.html：{len(papers)} 篇，数据日期 {stats.get('generated_at')}")


if __name__ == "__main__":
    main()
