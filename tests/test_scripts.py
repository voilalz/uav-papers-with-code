"""脚本的单元测试，不访问网络：python3 -m unittest discover -s tests"""
import copy
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import add_paper  # noqa: E402
import build  # noqa: E402
import check_links  # noqa: E402
import datalib  # noqa: E402
import refresh_github  # noqa: E402
import validate  # noqa: E402

with open(datalib.SCHEMA, encoding="utf-8") as f:
    SCHEMA = json.load(f)
TAXONOMY = datalib.load_taxonomy()


def paper(**kw):
    p = {
        "id": "demo-2024", "kind": "method", "name": "Demo", "title": "Demo: A Test Paper",
        "authors": "Ann Lee 等", "venue": "ICRA", "year": 2024,
        "paper": "https://arxiv.org/abs/2401.00001", "ids": {"arxiv": "2401.00001"},
        "repos": [{"name": "lab/demo", "official": True}], "subs": ["vio"],
        "zh": "用于测试的示例条目，不是真实论文。", "added": "2026-10-05",
    }
    p.update(kw)
    return p


def stats(**repos):
    return {"schema_version": 1, "generated_at": "2026-10-05", "repos": repos}


def run_check(papers, st=None):
    return validate.check(papers, TAXONOMY, st if st is not None else stats(), SCHEMA)


class RealDataTest(unittest.TestCase):
    def test_repository_data_is_valid(self):
        errors, _ = validate.check(datalib.load_papers(), TAXONOMY, datalib.load_stats(), SCHEMA)
        self.assertEqual(errors, [])

    def test_issue_form_matches_taxonomy(self):
        form = datalib.load_yaml(os.path.join(datalib.ROOT, ".github", "ISSUE_TEMPLATE", "recommend-paper.yml"))
        [field] = [b for b in form["body"] if b.get("id") == "subs"]
        expected = [f"{s['label']} ({s['id']})" for s in TAXONOMY["subs"]] + ["其他"]
        self.assertEqual(field["attributes"]["options"], expected)

    def test_ids_are_stable_slugs(self):
        for p in datalib.load_papers():
            self.assertRegex(p["id"], r"^[a-z0-9-]+-\d{4}$")


class ValidateTest(unittest.TestCase):
    def test_valid_entry(self):
        errors, warnings = run_check([paper()], stats(**{"lab/demo": {"full_name": "lab/demo"}}))
        self.assertEqual((errors, warnings), ([], []))

    def test_schema_errors_stop_further_checks(self):
        p = paper()
        del p["zh"]
        errors, _ = run_check([p])
        self.assertEqual(len(errors), 1)
        self.assertIn("zh", errors[0][1])

    def test_unknown_vocabulary(self):
        errors, _ = run_check([paper(subs=["nope"], venue="Nowhere", kind="poem")])
        msgs = " ".join(m for _, m in errors)
        for word in ("nope", "Nowhere", "poem"):
            self.assertIn(word, msgs)

    def test_duplicates(self):
        a = paper()
        b = paper(id="demo-copy-2024", title="DEMO — a test paper!")
        errors, _ = run_check([a, b])
        msgs = " ".join(m for _, m in errors)
        self.assertIn("arXiv 2401.00001", msgs)
        self.assertIn("lab/demo", msgs)
        self.assertIn("标题", msgs)

    def test_repo_duplicate_ignores_case(self):
        b = paper(id="other-2024", title="Other", ids={"arxiv": "2401.00002"}, paper="https://arxiv.org/abs/2401.00002",
                  repos=[{"name": "LAB/Demo", "official": True}])
        errors, _ = run_check([paper(), b])
        self.assertTrue(any("LAB/Demo" in m for _, m in errors))

    def test_paper_link_must_match_ids(self):
        errors, _ = run_check([paper(ids={"arxiv": "2401.99999"})])
        self.assertTrue(any("ids.arxiv" in m for _, m in errors))
        errors, _ = run_check([paper(paper="https://doi.org/10.1109/X.1", ids={"arxiv": "2401.00001"})])
        self.assertTrue(any("ids.doi" in m for _, m in errors))

    def test_needs_repo_or_site(self):
        p = paper()
        del p["repos"]
        self.assertTrue(run_check([p])[0])
        self.assertFalse(run_check([dict(p, site="https://example.org/data")])[0])

    def test_stats_warnings(self):
        _, w = run_check([paper()])
        self.assertTrue(any("还没有统计数据" in m for _, m in w))
        _, w = run_check([paper()], stats(**{"lab/demo": {"full_name": "lab/demo-v2"}}))
        self.assertTrue(any("改名" in m for _, m in w))
        _, w = run_check([paper()], stats(**{"lab/demo": {"full_name": "lab/demo"}, "old/gone": {}}))
        self.assertTrue(any("old/gone" in m for _, m in w))

    def test_duplicate_yaml_keys_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("- id: a-2020\n  name: A\n  name: B\n")
        try:
            with self.assertRaises(Exception):
                datalib.load_papers(f.name)
        finally:
            os.unlink(f.name)


class BuildTest(unittest.TestCase):
    def test_page_entries_merge_stats(self):
        p = paper(repos=[{"name": "fork/demo", "official": False}, {"name": "lab/demo", "official": True}])
        st = stats(**{"lab/demo": {"full_name": "Lab/Demo-New", "stars": 42, "lang": "C++", "updated": "2026-01-01", "archived": True},
                      "fork/demo": {"full_name": "fork/demo", "stars": 5}})
        [e] = build.page_entries([p], TAXONOMY, st)
        self.assertEqual(e["stars"], 42)                      # 取官方仓库
        self.assertEqual(e["repos"][1]["name"], "Lab/Demo-New")  # 跟随改名
        self.assertEqual(e["note"], build.ARCHIVED_NOTE)
        self.assertEqual(e["venue_full"], TAXONOMY["venues"]["ICRA"]["full"])

    def test_render_escapes_script_end(self):
        tpl = '<script id="data">{{DATA}}</script><script id="taxonomy">{{TAXONOMY}}</script>{{DATA_DATE}} {{PAPER_COUNT}}'
        html = build.render([paper(zh="危险的 </script> 文本，用于测试转义。")], TAXONOMY, stats(), tpl)
        self.assertEqual(html.count("</script>"), 2)
        self.assertIn('"2026-10-05" 1', html)

    def test_readme_counts(self):
        out = build.render_readme("收录 1 篇论文、1 个代码仓库，3 个细分方向，截至 2020-01-01", [paper(), paper()], TAXONOMY, stats())
        self.assertIn("收录 2 篇论文、2 个代码仓库", out)
        self.assertIn(f"{len(TAXONOMY['subs'])} 个细分方向", out)
        self.assertIn("截至 2026-10-05", out)

    def test_committed_index_is_current(self):
        with mock.patch("sys.stdout"):
            build.main(["--check"])


class RefreshTest(unittest.TestCase):
    def fake_get(self, responses):
        def get(path):
            r = responses[path]
            if isinstance(r, Exception):
                raise r
            return r
        return get

    def test_fetch_repo(self):
        get = self.fake_get({
            "/repos/lab/demo": {"full_name": "Lab/Demo", "stargazers_count": 7, "language": "Jupyter Notebook",
                                "license": {"spdx_id": "MIT"}, "archived": False, "default_branch": "main"},
            "/repos/Lab/Demo/commits?sha=main&per_page=1": [{"commit": {"committer": {"date": "2026-09-30T01:02:03Z"}}}],
        })
        rec = refresh_github.fetch_repo("lab/demo", None, get)
        self.assertEqual(rec, {"full_name": "Lab/Demo", "stars": 7, "lang": "Jupyter", "license": "MIT",
                               "updated": "2026-09-30", "archived": False})

    def test_main_keeps_old_values_on_failure_and_drops_orphans(self):
        tmp = tempfile.mkdtemp()
        papers = os.path.join(tmp, "papers.yaml")
        st_path = os.path.join(tmp, "stats.json")
        with open(papers, "w", encoding="utf-8") as f:
            f.write("- id: a-2020\n  repos: [{name: ok/one, official: true}]\n"
                    "- id: b-2020\n  repos: [{name: gone/two, official: true}]\n"
                    "- id: c-2020\n  repos: [{name: ok/three, official: true}]\n")
        old = stats(**{"gone/two": {"full_name": "gone/two", "stars": 3}, "orphan/x": {"stars": 1}})
        datalib.save_stats(old, st_path)
        ok = lambda n: {"full_name": n, "stargazers_count": 1, "language": "C", "default_branch": "main"}  # noqa: E731
        get = self.fake_get({
            "/repos/ok/one": ok("ok/one"), "/repos/ok/one/commits?sha=main&per_page=1": [],
            "/repos/ok/three": ok("ok/three"), "/repos/ok/three/commits?sha=main&per_page=1": [],
            "/repos/gone/two": refresh_github.Missing("HTTP 404"),
        })
        orig_load, orig_save = datalib.load_papers, datalib.save_stats
        with mock.patch.object(datalib, "load_papers", lambda: orig_load(papers)), \
                mock.patch.object(datalib, "load_stats", lambda: copy.deepcopy(old)), \
                mock.patch.object(datalib, "save_stats", lambda s: orig_save(s, st_path)), \
                mock.patch("sys.stdout"):
            refresh_github.main(get=get, today="2026-10-06")
        new = datalib.load_stats(st_path)
        self.assertEqual(new["generated_at"], "2026-10-06")
        self.assertEqual(set(new["repos"]), {"ok/one", "gone/two", "ok/three"})
        self.assertEqual(new["repos"]["gone/two"]["missing"], "HTTP 404")
        self.assertEqual(new["repos"]["gone/two"]["stars"], 3)


class CheckLinksTest(unittest.TestCase):
    def test_report(self):
        results = [("a-2020", "论文", "https://x/1", "broken", "HTTP 404"),
                   ("b-2020", "论文", "https://x/2", "blocked", "HTTP 403"),
                   ("c-2020", "论文", "https://x/3", "ok", "200")]
        text, problems = check_links.report(results, [("d-2020", "ICRA")], 3)
        self.assertTrue(problems)
        self.assertIn("失效 1", text)
        self.assertIn("`d-2020` | ICRA", text)
        _, problems = check_links.report(results[1:], [], 2)
        self.assertFalse(problems)              # 被反爬拒绝的不算问题


class AddPaperTest(unittest.TestCase):
    ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
    <entry><title>FooNet:  Fast
     Things</title><published>2025-03-01T00:00:00Z</published>
    <summary>Code at https://github.com/foo-lab/FooNet.</summary>
    <author><name>Ann Lee</name></author><author><name>Bo Li</name></author><author><name>C D</name></author>
    <arxiv:comment>ICRA 2025</arxiv:comment></entry></feed>"""

    def test_parse_and_draft(self):
        meta = add_paper.parse_atom(self.ATOM)
        self.assertEqual(meta["title"], "FooNet: Fast Things")
        self.assertEqual(add_paper.guess_repo(meta), "foo-lab/FooNet")
        args = add_paper.argparse.Namespace(name=None, kind="method", repo=None, third_party=False,
                                            venue="ICRA", subs="det", zh="一句话中文简介，用于测试。")
        text, _ = add_paper.draft(meta, "2503.00001", args, "2026-10-05")
        entry = datalib.yaml.load(text, Loader=datalib.UniqueKeyLoader)[0]
        self.assertEqual(entry["id"], "foonet-2025")
        self.assertEqual(entry["authors"], "Ann Lee 等")
        self.assertEqual(entry["repos"], [{"name": "foo-lab/FooNet", "official": True}])
        errors, _ = run_check([entry])
        self.assertEqual(errors, [])

    def test_parse_arxiv_id(self):
        self.assertEqual(add_paper.parse_arxiv_id("https://arxiv.org/abs/2307.05263v2"), "2307.05263")
        self.assertTrue(re.fullmatch(r"\d{4}\.\d{5}", add_paper.parse_arxiv_id("arXiv:2307.05263")))


if __name__ == "__main__":
    unittest.main()
