#!/usr/bin/env python3
"""根据 arXiv 编号生成 papers.yaml 条目草稿：自动填标题、作者、年份、论文链接，并从摘要/备注里找 GitHub 仓库。

    python3 scripts/add_paper.py 2307.05263 --subs sim --zh "一句话中文简介"
    python3 scripts/add_paper.py https://arxiv.org/abs/2307.05263 --name "Pegasus Simulator" --append

默认只打印草稿；加 --append 追加到 data/papers.yaml 末尾。
没给出的字段写成 TODO，validate.py 会拦下来，提醒补全后再提交。
"""
import argparse
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datalib  # noqa: E402

ARXIV_API = "https://export.arxiv.org/api/query?id_list={}"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?(?=[\s/)\].,;]|$)")


def parse_arxiv_id(text):
    m = re.search(r"(\d{4}\.\d{4,5})", text)
    if not m:
        sys.exit(f"无法识别 arXiv 编号：{text}")
    return m.group(1)


def fetch_arxiv(arxiv_id):
    req = urllib.request.Request(ARXIV_API.format(arxiv_id), headers={"User-Agent": "uav-papers-with-code"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return parse_atom(resp.read())


def parse_atom(xml_bytes):
    entry = ET.fromstring(xml_bytes).find("a:entry", NS)
    if entry is None or entry.find("a:title", NS) is None:
        sys.exit("arXiv 没有返回这篇论文，请检查编号")
    text = lambda tag: " ".join((entry.findtext(tag, "", NS) or "").split())  # noqa: E731
    return {
        "title": text("a:title"),
        "authors": [" ".join(a.findtext("a:name", "", NS).split()) for a in entry.findall("a:author", NS)],
        "year": int(text("a:published")[:4]),
        "summary": text("a:summary"),
        "comment": text("arxiv:comment"),
        "journal_ref": text("arxiv:journal_ref"),
        "doi": text("arxiv:doi"),
    }


def guess_repo(meta):
    for src in (meta["comment"], meta["summary"]):
        m = GITHUB_RE.search(src)
        if m:
            return m.group(1).rstrip(".")
    return None


def q(v):
    """YAML 标量：简单值原样输出，其余用双引号（JSON 字符串也是合法的 YAML）。"""
    import json
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_./-]*", v) and v.lower() not in ("null", "true", "false", "yes", "no", "on", "off"):
        return v
    return json.dumps(v, ensure_ascii=False)


def draft(meta, arxiv_id, args, today):
    name = args.name or (meta["title"].split(":")[0].strip() if ":" in meta["title"] else "TODO")
    authors = meta["authors"]
    author_text = ", ".join(authors) if len(authors) <= 2 else f"{authors[0]} 等"
    repo = args.repo or guess_repo(meta)
    lines = [
        f"- id: {datalib.slugify(name, meta['year']) if name != 'TODO' else 'TODO'}",
        f"  kind: {args.kind}",
        f"  name: {q(name)}",
        f"  title: {q(meta['title'])}",
        f"  authors: {q(author_text)}",
        f"  venue: {q(args.venue or 'arXiv')}",
        f"  year: {meta['year']}",
        f"  paper: {q('https://arxiv.org/abs/' + arxiv_id)}",
    ]
    ids = [f"arxiv: {q(arxiv_id)}"] + ([f"doi: {q(meta['doi'])}"] if meta["doi"] else [])
    lines.append("  ids: {" + ", ".join(ids) + "}")
    if repo:
        lines += ["  repos:", f"    - {{name: {q(repo)}, official: {q(not args.third_party)}}}"]
    lines.append("  subs: [" + (", ".join(args.subs.split(",")) if args.subs else "TODO") + "]")
    lines.append(f"  zh: {q(args.zh or 'TODO：一句话中文简介')}")
    lines.append(f"  added: {q(today)}")
    notes = []
    if meta["journal_ref"]:
        notes.append(f"arXiv 记录的发表信息：{meta['journal_ref']}，请据此填写 venue（须在 taxonomy.yaml 词表中）")
    if not repo:
        notes.append("没有在摘要或备注里找到 GitHub 仓库，请用 --repo 指定，或手动补 repos")
    elif not args.repo:
        notes.append(f"仓库 {repo} 是从摘要/备注里自动找到的，请确认是否为官方代码")
    return "\n".join(lines) + "\n", notes


def main(argv=None, fetch=fetch_arxiv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("arxiv", help="arXiv 编号或链接")
    ap.add_argument("--name", help="方法名（默认取标题冒号前的部分）")
    ap.add_argument("--subs", help="细分方向，逗号分隔，如 vio,map")
    ap.add_argument("--zh", help="一句话中文简介")
    ap.add_argument("--venue", help="发表处简称，须在 taxonomy.yaml 中；默认 arXiv")
    ap.add_argument("--kind", default="method", help="method | dataset | simulator | tool")
    ap.add_argument("--repo", help="GitHub 仓库 owner/name")
    ap.add_argument("--third-party", action="store_true", help="代码不是论文作者发布的")
    ap.add_argument("--append", action="store_true", help="追加到 data/papers.yaml")
    args = ap.parse_args(argv)

    arxiv_id = parse_arxiv_id(args.arxiv)
    papers = datalib.load_papers()
    for p in papers:
        if p.get("ids", {}).get("arxiv") == arxiv_id:
            sys.exit(f"已收录：{p['id']}")
    meta = fetch(arxiv_id)
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    text, notes = draft(meta, arxiv_id, args, today)
    repo_keys = {datalib.repo_key(r["name"]) for p in papers for r in p.get("repos", [])}
    m = re.search(r"- \{name: ([^,}]+)", text)
    if m and datalib.repo_key(m.group(1).strip('"')) in repo_keys:
        notes.append(f"仓库 {m.group(1)} 已被其他条目使用，请确认不是重复收录")

    if args.append:
        with open(datalib.PAPERS, "a", encoding="utf-8") as f:
            f.write("\n" + text)
        print(f"已追加到 data/papers.yaml：\n\n{text}")
    else:
        print(text)
    for n in notes:
        print(f"提示：{n}", file=sys.stderr)
    print("下一步：补全 TODO，运行 python3 scripts/validate.py 和 python3 scripts/build.py", file=sys.stderr)


if __name__ == "__main__":
    main()
