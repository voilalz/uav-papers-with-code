#!/usr/bin/env python3
"""校验 data/ 下的数据：格式、词表、唯一性与查重、链接与外部 ID 一致性。

    python3 scripts/validate.py

有错误时退出码为 1；在 GitHub Actions 中会输出带行号的注解，直接标在 PR 的文件上。
警告（如新仓库还没有统计数据、仓库已改名）不影响退出码。
"""
import json
import os
import re
import sys

import jsonschema

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datalib  # noqa: E402

ARXIV_URL = re.compile(r"^https://arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$")
DOI_URL = re.compile(r"^https://(?:dx\.)?doi\.org/(10\.\S+)$")
ROS1_DISTROS = {"indigo", "kinetic", "melodic", "noetic"}


def check_repro(repro):
    """repro 中各字段之间的一致性；返回错误消息列表。"""
    if not repro:
        return []
    msgs = []
    ros, distros = repro.get("ros"), repro.get("ros_distro", [])
    if distros and ros in (None, "none"):
        msgs.append("填了 ros_distro，ros 应为 ros1 / ros2 / both")
    for d in distros:
        if ros == "ros1" and d not in ROS1_DISTROS or ros == "ros2" and d in ROS1_DISTROS:
            msgs.append(f"ROS 发行版 {d} 与 ros: {ros} 不符")
    if repro.get("cuda_version") and repro.get("cuda") in (None, "none"):
        msgs.append("填了 cuda_version，cuda 应为 required 或 optional")
    if repro.get("px4_version") and not repro.get("px4"):
        msgs.append("填了 px4_version，px4 应为 true")
    return msgs


def check(papers, taxonomy, stats, schema):
    """返回 (errors, warnings)，每项为 (论文 id 或 None, 消息)。"""
    errors, warnings = [], []

    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(papers), key=lambda e: list(e.path)):
        path = list(err.path)
        pid = None
        if path and isinstance(path[0], int) and path[0] < len(papers) and isinstance(papers[path[0]], dict):
            pid = papers[path[0]].get("id")
        field = ".".join(str(p) for p in path[1:]) or "条目"
        errors.append((pid, f"{field}：{err.message}"))
    if errors:                     # 结构不对时后面的检查没有意义
        return errors, warnings

    kinds = set(taxonomy["kinds"])
    venues = set(taxonomy["venues"])
    subs = {s["id"] for s in taxonomy["subs"]}
    cats = {c["id"] for c in taxonomy["categories"]}
    for s in taxonomy["subs"]:
        if s["cat"] not in cats:
            errors.append((None, f"taxonomy.yaml：细分方向 {s['id']} 的大方向 {s['cat']} 不存在"))

    seen = {"id": {}, "arxiv": {}, "doi": {}, "repo": {}, "title": {}}

    def unique(kind, key, pid, label):
        other = seen[kind].get(key)
        if other:
            errors.append((pid, f"{label} 与 {other} 重复"))
        else:
            seen[kind][key] = pid

    for p in papers:
        pid = p["id"]
        unique("id", pid, pid, f"id {pid}")
        if not pid.endswith(f"-{p['year']}"):
            warnings.append((pid, f"id 的年份后缀与 year {p['year']} 不一致（id 创建后不改，确认无误可忽略）"))
        if p["kind"] not in kinds:
            errors.append((pid, f"kind {p['kind']!r} 不在 taxonomy.yaml 的 kinds 中"))
        if p["venue"] not in venues:
            errors.append((pid, f"venue {p['venue']!r} 不在 taxonomy.yaml 的 venues 词表中"))
        for s in p["subs"]:
            if s not in subs:
                errors.append((pid, f"细分方向 {s!r} 不在 taxonomy.yaml 中"))
        if p["kind"] == "dataset" and "data" not in p["subs"]:
            warnings.append((pid, "kind 为 dataset，但 subs 里没有 data"))

        ids = p.get("ids", {})
        if "arxiv" in ids:
            unique("arxiv", ids["arxiv"], pid, f"arXiv {ids['arxiv']}")
        if "doi" in ids:
            unique("doi", ids["doi"].lower(), pid, f"DOI {ids['doi']}")
        m = ARXIV_URL.match(p["paper"])
        if m and ids.get("arxiv") != m.group(1):
            errors.append((pid, f"论文链接是 arXiv {m.group(1)}，ids.arxiv 应填 \"{m.group(1)}\""))
        m = DOI_URL.match(p["paper"])
        if m and ids.get("doi", "").lower() != m.group(1).lower():
            errors.append((pid, f"论文链接是 DOI {m.group(1)}，ids.doi 应填 {m.group(1)}"))

        unique("title", datalib.norm_title(p["title"]), pid, "标题")
        for r in p.get("repos", []):
            unique("repo", datalib.repo_key(r["name"]), pid, f"仓库 {r['name']}")
            errors.extend((pid, f"仓库 {r['name']} 的 repro：{m}") for m in check_repro(r.get("repro")))

    # evaluated_on / datasets 只能引用已收录的数据集条目
    kind_of = {p["id"]: p["kind"] for p in papers}
    for p in papers:
        for field in ("evaluated_on", "datasets"):
            for ref in p.get(field, []):
                if ref == p["id"]:
                    errors.append((p["id"], f"{field} 不能引用自己"))
                elif ref not in kind_of:
                    errors.append((p["id"], f"{field} 中的 {ref} 不是已收录条目的 id"))
                elif kind_of[ref] != "dataset":
                    errors.append((p["id"], f"{field} 中的 {ref} 不是数据集条目（kind 为 {kind_of[ref]}）"))

    # 与机器生成的统计数据对照
    stat_repos = stats.get("repos", {})
    if stats.get("schema_version") != datalib.STATS_SCHEMA_VERSION:
        errors.append((None, f"repo_stats.json 的 schema_version 应为 {datalib.STATS_SCHEMA_VERSION}"))
    for key, pid in seen["repo"].items():
        st = stat_repos.get(key)
        name = next(r["name"] for p in papers if p["id"] == pid for r in p.get("repos", []) if datalib.repo_key(r["name"]) == key)
        if not st:
            warnings.append((pid, f"仓库 {name} 还没有统计数据，下次刷新后补上（或本地运行 refresh_github.py）"))
        elif st.get("full_name") and datalib.repo_key(st["full_name"]) != key:
            warnings.append((pid, f"仓库已改名为 {st['full_name']}，请把 papers.yaml 中的 {name} 改为新地址"))
        elif st.get("missing"):
            warnings.append((pid, f"仓库 {name} 已无法访问（{st['missing']}），请核实后更换或删除"))
    for key in stat_repos:
        if key not in seen["repo"]:
            warnings.append((None, f"repo_stats.json 中的 {key} 已不在 papers.yaml 里，下次刷新时会移除"))

    return errors, warnings


def main():
    try:
        papers = datalib.load_papers()
        taxonomy = datalib.load_taxonomy()
    except Exception as err:              # YAML 语法错误、重复键
        print(f"::error file=data/papers.yaml::{err}" if os.environ.get("GITHUB_ACTIONS") else err)
        sys.exit(1)
    with open(datalib.SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)
    errors, warnings = check(papers, taxonomy, datalib.load_stats(), schema)

    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    lines = datalib.id_lines()
    for level, items in (("error", errors), ("warning", warnings)):
        for pid, msg in items:
            if gha:
                loc = f" file=data/papers.yaml,line={lines[pid]}" if pid in lines else ""
                print(f"::{level}{loc}::{pid + '：' if pid else ''}{msg}")
            else:
                tag = "错误" if level == "error" else "警告"
                where = f"[{pid}] " if pid else ""
                print(f"{tag} {where}{msg}")

    print(f"校验完成：{len(papers)} 篇，{len(errors)} 个错误，{len(warnings)} 个警告")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
