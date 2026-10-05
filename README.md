# UAV Papers with Code

无人机视觉（CV）、导航（NAV）、制导与控制（G&C）方向的开源论文索引，收录 123 篇论文、121 个代码仓库。

在线访问：https://voilalz.github.io/uav-papers-with-code/

- 视觉、导航、制导与控制、平台与数据四大方向，17 个细分方向
- 支持关键词搜索、按方向筛选，按 Star 数、发表年份或最近提交排序
- 每篇附论文链接（优先 arXiv 等开放版本）、GitHub 仓库、Star 数与最近提交日期
- Star 数与提交日期截至 2026-10-05，每周一自动刷新

## 文件

- `index.html`：整个网站，单文件，无需构建。论文数据内嵌在文件末尾的 `<script id="data">` 中，每条一个 JSON 对象。
- `scripts/refresh_stats.py`：通过 GitHub API 刷新每个仓库的 Star 数、主要语言和最近提交日期；仓库改名或迁移时自动改用新地址。
- `.github/workflows/refresh-stats.yml`：每周一 09:17（北京时间）运行上面的脚本，有变化就提交并重新发布网站。也可以在 Actions 页面点 Run workflow 手动运行。
- `.nojekyll`：让 GitHub Pages 直接发布静态文件。

## 增补论文

在数据块里追加一个对象即可，字段：`name`（方法名）、`title`、`authors`、`venue`、`year`、`paper`（论文链接）、`repo`（`owner/repo`，数据集可为 `null`）、`subs`（细分方向代码，如 `vio`、`lio`、`plan`、`det`）、`zh`（一句话中文简介）、`stars`、`lang`、`updated`（最近提交日期），可选 `site`、`note`、`tags`。
