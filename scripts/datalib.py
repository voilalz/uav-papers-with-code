"""各脚本共用的数据读写：papers.yaml、taxonomy.yaml、generated/repo_stats.json。"""
import json
import os
import re
import unicodedata

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PAPERS = os.path.join(DATA, "papers.yaml")
TAXONOMY = os.path.join(DATA, "taxonomy.yaml")
STATS = os.path.join(DATA, "generated", "repo_stats.json")
SCHEMA = os.path.join(ROOT, "schema", "paper.schema.json")
TEMPLATE = os.path.join(ROOT, "templates", "index.html")
INDEX = os.path.join(ROOT, "index.html")
README = os.path.join(ROOT, "README.md")

STATS_SCHEMA_VERSION = 1


class UniqueKeyLoader(yaml.SafeLoader):
    """重复的键直接报错，避免 PyYAML 默认的"后者静默覆盖前者"。"""


def _construct_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"重复的键 {key!r}", key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node, deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
# 日期保持为字符串，和 JSON Schema 的 "YYYY-MM-DD" 约定一致
UniqueKeyLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=UniqueKeyLoader)


def load_papers(path=PAPERS):
    return load_yaml(path) or []


def load_taxonomy(path=TAXONOMY):
    return load_yaml(path)


def load_stats(path=STATS):
    if not os.path.exists(path):
        return {"schema_version": STATS_SCHEMA_VERSION, "generated_at": None, "repos": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_stats(stats, path=STATS):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def repo_key(name):
    """仓库在统计文件中的键：GitHub 的 owner/name 不区分大小写。"""
    return name.lower()


def primary_repo(paper):
    """用于显示 Star 数的仓库：第一个官方仓库，没有则取第一个。"""
    repos = paper.get("repos") or []
    for r in repos:
        if r["official"]:
            return r
    return repos[0] if repos else None


def slugify(name, year):
    s = unicodedata.normalize("NFKD", name.replace("²", "2").replace("³", "3"))
    s = re.sub(r"[()\[\]'’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return f"{s}-{year}"


def norm_title(title):
    return re.sub(r"[\W_]+", "", title.lower())


def id_lines(path=PAPERS):
    """论文 id → 它在 papers.yaml 中的行号，用于报错定位。"""
    lines = {}
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            m = re.match(r"-\s+id:\s*[\"']?([^\s\"']+)", line)
            if m:
                lines.setdefault(m.group(1), i)
    return lines
