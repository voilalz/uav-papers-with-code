#!/usr/bin/env python3
"""刷新 index.html 中内嵌的 GitHub 数据：Star 数、主要语言、最近提交日期。

由 .github/workflows/refresh-stats.yml 每周运行一次，也可以在本地运行：
    GITHUB_TOKEN=xxx python3 scripts/refresh_stats.py

只改动数据块、页面的数据日期和 README 中的日期；请求失败的仓库保留原值。
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
README = os.path.join(ROOT, "README.md")
API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# GitHub 的语言名 → 页面上显示的名字；网站/文档类语言不显示
LANG_MAP = {"Jupyter Notebook": "Jupyter", "Cuda": "CUDA"}
HIDDEN_LANGS = {"HTML", "CSS", "SCSS", "Sass", "Less", "TeX", "Markdown"}
ARCHIVED_NOTE = "仓库已归档"

DATA_RE = re.compile(r'(<script type="application/json" id="data">)(.*?)(</script>)', re.S)
DATE_RE = re.compile(r'var DATA_DATE = "\d{4}-\d{2}-\d{2}";')
README_DATE_RE = re.compile(r"(截至 )\d{4}-\d{2}-\d{2}")


class Missing(Exception):
    """仓库不存在、已删除或为空。"""


def api_get(path):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "uav-papers-with-code-refresh",
    }
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    req = urllib.request.Request(API + path, headers=headers)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code in (404, 409, 410, 451):
                raise Missing(f"HTTP {err.code}")
            limited = err.code == 429 or (err.code == 403 and err.headers.get("X-RateLimit-Remaining") == "0")
            if limited and attempt < 3:
                reset = err.headers.get("Retry-After")
                if not reset and err.headers.get("X-RateLimit-Reset"):
                    reset = max(1, int(err.headers["X-RateLimit-Reset"]) - int(time.time()))
                time.sleep(min(int(reset or 30), 120))
                continue
            if err.code >= 500 and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def refresh_entry(entry, get=api_get):
    """更新单个条目，返回改动过的字段名列表。"""
    before = dict(entry)
    info = get("/repos/" + entry["repo"])
    full_name = info["full_name"]
    if full_name != entry["repo"]:          # 仓库改名或迁移后跟随新地址
        entry["repo"] = full_name
    entry["stars"] = info["stargazers_count"]

    lang = LANG_MAP.get(info.get("language"), info.get("language"))
    entry["lang"] = None if lang in HIDDEN_LANGS else lang

    if info.get("archived"):
        entry.setdefault("note", ARCHIVED_NOTE)
    elif entry.get("note") == ARCHIVED_NOTE:
        del entry["note"]

    branch = urllib.parse.quote(info["default_branch"], safe="")
    try:
        commits = get(f"/repos/{full_name}/commits?sha={branch}&per_page=1")
        if commits:
            entry["updated"] = commits[0]["commit"]["committer"]["date"][:10]
    except Missing:
        pass                                 # 空仓库：保留原日期
    return [k for k in set(before) | set(entry) if before.get(k) != entry.get(k)]


def main(get=api_get, today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    html = open(INDEX, encoding="utf-8").read()
    match = DATA_RE.search(html)
    if not match:
        sys.exit("index.html 里没有找到数据块 <script id=\"data\">")
    data = json.loads(match.group(2))

    repos = [e for e in data if e.get("repo")]
    failed, moved, star_delta = [], [], 0
    for entry in repos:
        old_repo, old_stars = entry["repo"], entry.get("stars") or 0
        try:
            refresh_entry(entry, get)
        except Missing as err:
            failed.append(f"{old_repo}（{err}）")
            continue
        except Exception as err:            # 单个仓库失败不影响其余条目
            failed.append(f"{old_repo}（{err}）")
            continue
        if entry["repo"] != old_repo:
            moved.append(f"{old_repo} → {entry['repo']}")
        star_delta += (entry["stars"] or 0) - old_stars

    if len(failed) > len(repos) // 2:
        print("\n".join(failed))
        sys.exit(f"超过一半的仓库请求失败（{len(failed)}/{len(repos)}），本次不写入。")

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = html[: match.start(2)] + payload + html[match.end(2):]
    html = DATE_RE.sub(f'var DATA_DATE = "{today}";', html, count=1)
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(html)

    if os.path.exists(README):
        readme = open(README, encoding="utf-8").read()
        with open(README, "w", encoding="utf-8") as f:
            f.write(README_DATE_RE.sub(lambda m: m.group(1) + today, readme))

    print(f"已刷新 {len(repos) - len(failed)}/{len(repos)} 个仓库，Star 合计变化 {star_delta:+d}，数据日期 {today}")
    for line in moved:
        print(f"::notice::仓库地址已更新：{line}")
    for line in failed:
        print(f"::warning::未能刷新：{line}")


if __name__ == "__main__":
    main()
