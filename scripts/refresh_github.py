#!/usr/bin/env python3
"""刷新 data/generated/repo_stats.json：每个仓库的 Star 数、主要语言、许可证、最近提交日期。

由 .github/workflows/refresh-stats.yml 每周运行一次，也可以在本地运行：
    GITHUB_TOKEN=xxx python3 scripts/refresh_github.py && python3 scripts/build.py

只写统计文件，不改 papers.yaml；请求失败的仓库保留上次的值。
仓库改名或迁移时记录新地址（页面随之使用新地址），validate.py 会提示把 papers.yaml 也改掉。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datalib  # noqa: E402

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# GitHub 的语言名 → 页面上显示的名字；网站/文档类语言不显示
LANG_MAP = {"Jupyter Notebook": "Jupyter", "Cuda": "CUDA"}
HIDDEN_LANGS = {"HTML", "CSS", "SCSS", "Sass", "Less", "TeX", "Markdown"}


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


def fetch_repo(name, old=None, get=api_get):
    """抓取单个仓库，返回新的统计记录；仓库不存在时抛出 Missing。"""
    info = get("/repos/" + name)
    full_name = info["full_name"]
    lang = LANG_MAP.get(info.get("language"), info.get("language"))
    lic = (info.get("license") or {}).get("spdx_id")
    rec = {
        "full_name": full_name,
        "stars": info["stargazers_count"],
        "lang": None if lang in HIDDEN_LANGS else lang,
        "license": None if lic in (None, "NOASSERTION") else lic,
        "updated": (old or {}).get("updated"),
        "archived": bool(info.get("archived")),
    }
    branch = urllib.parse.quote(info["default_branch"], safe="")
    try:
        commits = get(f"/repos/{full_name}/commits?sha={branch}&per_page=1")
        if commits:
            rec["updated"] = commits[0]["commit"]["committer"]["date"][:10]
    except Missing:
        pass                                 # 空仓库：保留原日期
    return rec


def main(get=api_get, today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    papers = datalib.load_papers()
    old = datalib.load_stats().get("repos", {})

    names = {}
    for p in papers:
        for r in p.get("repos", []):
            names.setdefault(datalib.repo_key(r["name"]), r["name"])

    repos, failed, moved, star_delta = {}, [], [], 0
    for key, name in sorted(names.items()):
        prev = old.get(key)
        # 已知改名的仓库直接请求新地址，省一次跳转
        target = (prev or {}).get("full_name") or name
        try:
            rec = fetch_repo(target, prev, get)
        except Missing as err:
            failed.append(f"{name}（{err}）")
            if prev:
                repos[key] = dict(prev, missing=str(err))
            continue
        except Exception as err:            # 单个仓库失败不影响其余条目
            failed.append(f"{name}（{err}）")
            if prev:
                repos[key] = prev
            continue
        if datalib.repo_key(rec["full_name"]) != key:
            moved.append(f"{name} → {rec['full_name']}")
        star_delta += rec["stars"] - ((prev or {}).get("stars") or 0)
        repos[key] = rec

    if len(failed) > len(names) // 2:
        print("\n".join(failed))
        sys.exit(f"超过一半的仓库请求失败（{len(failed)}/{len(names)}），本次不写入。")

    datalib.save_stats({"schema_version": datalib.STATS_SCHEMA_VERSION, "generated_at": today, "repos": repos})
    print(f"已刷新 {len(names) - len(failed)}/{len(names)} 个仓库，Star 合计变化 {star_delta:+d}，数据日期 {today}")
    for line in moved:
        print(f"::notice::仓库已改名，请同步修改 data/papers.yaml：{line}")
    for line in failed:
        print(f"::warning::未能刷新：{line}")


if __name__ == "__main__":
    main()
