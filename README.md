# UAV Papers with Code

无人机视觉（CV）、导航（NAV）、制导与控制（G&C）方向的开源论文索引，收录 123 篇论文、121 个代码仓库。

在线访问：https://voilalz.github.io/uav-papers-with-code/

- 视觉、导航、制导与控制、平台与数据四大方向，17 个细分方向
- 支持关键词搜索、按方向筛选，按 Star 数、发表年份或最近提交排序
- 每篇附论文链接（优先 arXiv 等开放版本）、GitHub 仓库、Star 数与最近提交日期
- 每篇都有固定链接，形如 `#vins-mono-2018`
- Star 数与提交日期截至 2026-10-06，每周一自动刷新

## 数据与文件

- `data/papers.yaml`：论文条目，人工维护，唯一的事实来源；格式由 `schema/paper.schema.json` 定义。
- `data/taxonomy.yaml`：大方向、细分方向、条目类型和 venue 词表。
- `data/generated/repo_stats.json`：各仓库的 Star 数、语言、许可证与最近提交日期，由脚本生成。
- `templates/index.html` → `index.html`：页面模板和由 `scripts/build.py` 生成的网站（单文件，无需服务器）。
- `scripts/`：校验、生成、刷新统计、链接巡检、按 arXiv 编号生成条目草稿，说明见 [CONTRIBUTING.md](CONTRIBUTING.md)。
- `.github/workflows/`：PR 数据校验；每周一刷新统计并重新发布网站；每周三巡检链接并汇总到 issue。

## 增补论文

可以用 [推荐论文](../../issues/new?template=recommend-paper.yml) 表单提 issue，也可以直接提 PR：

```bash
pip install -r requirements.txt
python3 scripts/add_paper.py <arXiv 编号> --subs vio --zh "一句话中文简介" --append
python3 scripts/validate.py && python3 scripts/build.py
```

收录标准、字段说明和 ID 规则见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可

代码 [MIT](LICENSE)，数据 [CC BY 4.0](data/LICENSE)。
