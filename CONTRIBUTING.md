# 参与贡献

欢迎推荐论文或修正数据。不熟悉 Git 的话，直接用 [推荐论文](../../issues/new?template=recommend-paper.yml) 表单提 issue 即可；下面是直接提 PR 的做法。

## 收录标准

- **有公开的代码或数据**：代码仓库在 GitHub 上可访问；数据集可以只有主页。
- **与无人机直接相关**：方法在无人机上验证过，或是无人机研究中被广泛使用的基础工作（如通用 VIO、LIO、规划框架）。
- **有代表性或被广泛使用**：发表在主流期刊或会议，或在社区中被大量使用。预印本可以收，发表后需更新 venue。
- **优先官方代码**：只有第三方实现时也可收录，但须标为 `official: false`。
- 已归档或停止维护的仓库仍可收录，页面会显示提示。

## 目录结构

```
data/
├── papers.yaml              # 论文条目：人工维护，唯一的事实来源
├── taxonomy.yaml            # 大方向、细分方向、条目类型、venue 词表
└── generated/
    ├── repo_stats.json      # Star 数等统计：由脚本生成，请勿手改
    └── repo_signals.json    # ROS/Docker/CUDA 等环境的自动检测结果：由脚本生成，请勿手改
schema/paper.schema.json     # papers.yaml 的格式定义
templates/index.html         # 页面模板
index.html                   # 生成的网站，请勿手改
scripts/
├── datalib.py               # 共用的读写函数
├── validate.py              # 校验：格式、词表、唯一性与查重
├── build.py                 # 由 data/ 和模板生成 index.html，同步 README 中的数字
├── refresh_github.py        # 刷新仓库统计（每周自动运行）
├── scan_repos.py            # 扫描仓库文件，推测运行环境（每周自动运行）
├── check_links.py           # 链接巡检（每周自动运行，结果汇总到 issue）
└── add_paper.py             # 按 arXiv 编号生成条目草稿
tests/                       # 脚本的单元测试
```

## 新增论文

```bash
pip install -r requirements.txt

# 1. 生成草稿（自动填标题、作者、年份、链接，并尝试找到 GitHub 仓库）
python3 scripts/add_paper.py 2307.05263 --subs sim --zh "一句话中文简介" --append

# 2. 打开 data/papers.yaml 检查末尾的新条目，补全 TODO，确认 venue 和仓库

# 3. 校验并重新生成页面
python3 scripts/validate.py
python3 scripts/build.py

# 4. 提交 data/papers.yaml、index.html、README.md
```

没有 arXiv 版本的论文请参照已有条目手写。新仓库的 Star 数会在合并后由 GitHub Actions 自动补上，在此之前页面显示“Star 待刷新”。

## 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 稳定主键，见下文 ID 规则 |
| `kind` | 是 | `method` 方法 / `dataset` 数据集 / `simulator` 仿真平台 / `tool` 工具与软件 |
| `name` | 是 | 方法或项目名，页面上的大标题 |
| `title` | 是 | 论文英文标题 |
| `authors` | 是 | 一位或两位作者写全名，三位及以上写“第一作者 等” |
| `venue` | 是 | 发表处简称，必须在 `taxonomy.yaml` 的 `venues` 中；新 venue 需同时在那里补全称和类型 |
| `year` | 是 | 发表年份 |
| `paper` | 是 | 论文链接，优先 arXiv 等开放版本 |
| `ids` | 否 | 外部标识：`arxiv`（如 `"2307.05263"`）、`doi`。论文链接是 arXiv 或 doi.org 时必须填写对应项，用于查重和修复失效链接 |
| `repos` | 二选一 | 代码仓库列表：`{name: owner/repo, official: true}`；第一个官方仓库的 Star 数用于排序 |
| `site` | 二选一 | 数据集或项目主页；没有代码仓库时必填 |
| `subs` | 是 | 细分方向代码，见 `taxonomy.yaml` 的 `subs`，可多选 |
| `tags` | 否 | 补充关键词，参与搜索，如 `[事件相机]` |
| `note` | 否 | 页面上的提示，如“已停止维护，新项目建议用 X”；仓库归档的提示会自动生成，无需填写 |
| `zh` | 是 | 一句话中文简介，10–120 字 |
| `evaluated_on` | 否 | 在哪些已收录的数据集上做了评测，填数据集条目的 id，如 `[euroc-mav-2016]`；数据集条目上会反向显示"用于评测" |
| `datasets` | 否 | 随论文发布、且已收录的数据集，填数据集条目的 id |
| `real_flight` | 否 | `data` 公开了真实飞行数据 / `experiment` 有真机飞行实验但未公开数据 / `none` 没有真机飞行 |
| `added` | 是 | 收录日期，`"YYYY-MM-DD"` |

Star 数、主要语言、许可证、最近提交日期都来自 `data/generated/repo_stats.json`，不要写进 `papers.yaml`。

页面上的环境标签（ROS1/ROS2 与发行版、Ubuntu、CUDA、PX4、Docker、launch/config、标定文件、预训练模型、Jetson）来自 `data/generated/repo_signals.json`，由 `scan_repos.py` 根据文件树、README、`package.xml` 和 Dockerfile 推测，页面上以虚线标签显示并注明依据。判断规则见脚本中的 `detect()`；规则有改动时把 `SCANNER_VERSION` 加一，下次运行会重新扫描所有仓库。检测有误时请提 issue，不要手改该文件。

### 人工确认运行环境（`repos[].repro`）

自动检测有误或不完整时，在对应仓库下填写 `repro`。填了的项覆盖自动结果，页面上改为实线标签并在悬停提示中注明来源和核对日期；没填的项继续显示自动推测。

```yaml
  repos:
    - name: HKUST-Aerial-Robotics/VINS-Mono
      official: true
      repro: {source: readme, checked: "2026-10-07", ros: ros1, ros_distro: [kinetic], ubuntu: ["16.04"], docker: true}
```

| 字段 | 说明 |
|---|---|
| `source` | 必填。`readme` 作者在 README / 文档中写明；`tested` 有人实际编译运行过；`issue` 来自 issue 或社区报告 |
| `checked` | 必填。核对日期 `"YYYY-MM-DD"` |
| `ros` / `ros_distro` | `ros1` / `ros2` / `both` / `none`；发行版如 `[melodic, noetic]`，须与 `ros` 一致 |
| `ubuntu` | 如 `["18.04", "20.04"]`（加引号，否则会被当成数字） |
| `cuda` / `cuda_version` | `required` 必需 / `optional` 可选（如只用于 GPU 加速或仿真渲染）/ `none` 不需要；版本如 `["11.8"]` |
| `px4` / `px4_version`、`ardupilot` | 是否用到 PX4 / ArduPilot，PX4 版本如 `["1.14"]` |
| `docker`、`launch_config`、`calibration`、`pretrained`、`jetson` | `true` / `false`；`jetson: true` 表示作者写明或有人报告能在 Jetson 上运行 |
| `note` | 补充说明（≤ 60 字），显示在悬停提示里 |

只写能从 README、文档或实际运行中确认的项，拿不准的不要填。

## ID 规则

- 格式：方法名转小写，非字母数字字符换成连字符，再加 `-年份`。如 `VINS-Mono`（2018）→ `vins-mono-2018`，`SE(3) Geometric Control`（2010）→ `se3-geometric-control-2010`。`add_paper.py` 会自动生成。
- **创建后永不修改**：改名、改年份、换链接都保留原 id。页面链接 `https://voilalz.github.io/uav-papers-with-code/#vins-mono-2018` 依赖它。
- **删除后不复用**：被删除条目的 id 不再分配给其他论文。

## 自动检查

每个 PR 都会运行 `validate.py`、`build.py --check` 和单元测试：

- 必填字段、类型、URL 与 `owner/repo` 格式
- `subs`、`venue`、`kind` 是否在词表内
- `id`、arXiv 编号、DOI、仓库、标题（忽略大小写和标点）是否与已有条目重复
- 论文链接与 `ids` 是否一致
- `index.html` 是否已用最新数据重新生成

另有两个定时任务：每周一刷新仓库统计（仓库改名时会提示同步修改 `papers.yaml`），每周三巡检论文链接、并查询标为 arXiv 的论文是否已正式发表，发现问题会更新“链接巡检报告” issue。

## 数据格式版本

数据格式版本当前为 1（见 `schema/paper.schema.json` 的说明和 `data/generated/repo_stats.json` 的 `schema_version`）。字段有不兼容的改动时，递增版本号，并在同一个 PR 里迁移全部数据、更新脚本与本文档。

## 许可

网站与脚本代码使用 [MIT](LICENSE)；`data/` 下的数据使用 [CC BY 4.0](data/LICENSE)。
