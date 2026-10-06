#!/usr/bin/env python3
"""扫描各代码仓库的文件，推测运行环境，写入 data/generated/repo_signals.json。

推测项：ROS1/ROS2 与发行版、Ubuntu 版本、CUDA、PX4/ArduPilot、Docker、launch/config、
标定文件、Jetson、预训练模型。结果只是根据文件名和 README 的推测，页面上标为"自动检测"。

由 .github/workflows/refresh-stats.yml 在刷新 Star 数之后运行，也可以在本地运行：
    GITHUB_TOKEN=xxx python3 scripts/scan_repos.py && python3 scripts/build.py

每个仓库最多请求 5 次（文件树 + README + 至多 2 个 package.xml + 1 个 Dockerfile）。
最近提交日期没变、检测规则也没变的仓库直接沿用上次结果；单次运行有请求上限，
没扫到的仓库下次继续。
"""
import base64
import os
import posixpath
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datalib  # noqa: E402
from refresh_github import Missing, api_get  # noqa: E402

# 检测规则有改动时加一，所有仓库会在下次运行时重新扫描
SCANNER_VERSION = 1
MAX_REQUESTS = int(os.environ.get("SCAN_MAX_REQUESTS", "600"))
MAX_FILE_BYTES = 200_000

ROS1_DISTROS = {"indigo": "14.04", "kinetic": "16.04", "melodic": "18.04", "noetic": "20.04"}
ROS2_DISTROS = {"foxy": "20.04", "galactic": "20.04", "humble": "22.04", "iron": "22.04", "jazzy": "24.04"}

LAUNCH_RE = re.compile(r"\.launch(\.py|\.xml|\.yaml)?$")
CONFIG_DIRS = {"launch", "config", "configs", "cfg", "param", "params"}
CALIB_RE = re.compile(r"calib|kalibr|camchain|extrinsic|intrinsic", re.I)
# 标定只认参数文件，不认标定算法的源代码
CALIB_EXT_RE = re.compile(r"\.(ya?ml|txt|json|xml|launch|cfg|csv)$", re.I)
NOT_CALIB_RE = re.compile(r"cmakelists\.txt$|requirements.*\.txt$|readme|package\.xml$", re.I)
WEIGHT_RE = re.compile(r"\.(pth|pt|ckpt|onnx|engine|weights|h5|caffemodel|tflite)$", re.I)
PX4_PATH_RE = re.compile(r"(^|/)(px4|px4_msgs|px4-autopilot|mavros)(/|$|[_-])", re.I)

README_ROS1_RE = re.compile(r"\broslaunch\b|\brosrun\b|\bcatkin[_ ](make|build|tools)\b|catkin_ws", re.I)
README_ROS2_RE = re.compile(r"\bros2 (launch|run)\b|\bcolcon build\b", re.I)
UBUNTU_RE = re.compile(r"ubuntu[\s:_-]*v?(1[468]|2[024])\.04", re.I)
CUDA_VER_RE = re.compile(r"cuda[\s:_-]*(?:toolkit[\s-]*)?(?:version[\s:]*)?v?(1[0-3]\.\d)\b", re.I)
CUDA_IMAGE_RE = re.compile(r"nvidia/cuda:(\d{2}\.\d)", re.I)
CUDA_WORD_RE = re.compile(r"\bcuda\b", re.I)
PX4_RE = re.compile(r"\bpx4\b", re.I)
PX4_VER_RE = re.compile(r"\bpx4(?:[\s_-]*autopilot)?[\s:_-]*v?(1\.\d{1,2})(?:\.\d+)?\b", re.I)
ARDUPILOT_RE = re.compile(r"\bardu(pilot|copter)\b", re.I)
JETSON_RE = re.compile(r"\bjetson\b|\bxavier\b|\bagx orin\b|\borin nx\b|\borin nano\b|\btx2\b", re.I)
PRETRAINED_RE = re.compile(r"pre-?trained|checkpoints?\b|model weights|\bweights\b|预训练|权重", re.I)
WEIGHT_HOST_RE = re.compile(r"huggingface\.co|drive\.google\.com|/releases/download/|pan\.baidu\.com|dropbox\.com|onedrive|1drv\.ms|zenodo\.org", re.I)


def _text(blob):
    if blob.get("size", 0) > MAX_FILE_BYTES:
        return ""
    return base64.b64decode(blob.get("content") or "").decode("utf-8", "replace")


def _shallow(paths):
    return sorted(paths, key=lambda p: (p.count("/"), p))


def detect(paths, readme="", package_xmls=(), dockerfile=""):
    """根据文件路径列表和少量文件内容推测运行环境；返回 (结果, 依据)。纯函数，便于测试。"""
    sig, why = {}, {}
    names = {p: posixpath.basename(p) for p in paths}
    docs = readme + "\n" + dockerfile

    # ROS：package.xml 的构建工具最可靠，其次是 launch 文件格式，最后看 README 中的命令
    ros1 = any(re.search(r"<buildtool_depend>\s*catkin", x) for x in package_xmls)
    ros2 = any(re.search(r"<buildtool_depend>\s*ament_", x) for x in package_xmls)
    if ros1 or ros2:
        why["ros"] = "package.xml 使用 " + "、".join(n for n, f in (("catkin", ros1), ("ament", ros2)) if f)
    else:
        ros1 = any(n.endswith(".launch") for n in names.values())
        ros2 = any(n.endswith(".launch.py") for n in names.values())
        if ros1 or ros2:
            why["ros"] = "含 " + "、".join(n for n, f in ((".launch", ros1), (".launch.py", ros2)) if f) + " 文件"
        else:
            ros1, ros2 = bool(README_ROS1_RE.search(docs)), bool(README_ROS2_RE.search(docs))
            if ros1 or ros2:
                why["ros"] = "README 中有 " + "、".join(n for n, f in (("roslaunch/catkin", ros1), ("ros2/colcon", ros2)) if f) + " 命令"
    sig["ros"] = "both" if ros1 and ros2 else "ros1" if ros1 else "ros2" if ros2 else "none"

    distros = []
    if sig["ros"] != "none":
        table = {**(ROS1_DISTROS if ros1 else {}), **(ROS2_DISTROS if ros2 else {})}
        distros = [d for d in table if re.search(r"\b" + d + r"\b", docs, re.I)]
    sig["ros_distro"] = distros

    ubuntu = set(m + ".04" for m in UBUNTU_RE.findall(docs))
    if ubuntu:
        why["ubuntu"] = "README / Dockerfile 中写明"
    elif distros:
        ubuntu = {(ROS1_DISTROS | ROS2_DISTROS)[d] for d in distros}
        why["ubuntu"] = "由 ROS 发行版推断"
    sig["ubuntu"] = sorted(ubuntu)

    cu_files = any(n.endswith((".cu", ".cuh")) for n in names.values())
    image = CUDA_IMAGE_RE.search(dockerfile)
    sig["cuda"] = bool(cu_files or image or CUDA_WORD_RE.search(docs))
    if sig["cuda"]:
        why["cuda"] = "含 .cu 源文件" if cu_files else "Dockerfile 基于 nvidia/cuda" if image else "README 中提到 CUDA"
    versions = sorted(set(([image.group(1)] if image else []) + CUDA_VER_RE.findall(docs)), key=lambda v: [int(x) for x in v.split(".")])
    sig["cuda_version"] = versions

    px4_dep = any(re.search(r"<(build_|exec_|run_)?depend>\s*(px4_msgs|mavros)", x) for x in package_xmls)
    px4_path = any(PX4_PATH_RE.search(p) for p in paths)
    sig["px4"] = bool(px4_dep or px4_path or PX4_RE.search(readme))
    if sig["px4"]:
        why["px4"] = "package.xml 依赖 px4_msgs/mavros" if px4_dep else "含 PX4 相关目录" if px4_path else "README 中提到 PX4"
    sig["px4_version"] = sorted(set(PX4_VER_RE.findall(docs)))
    sig["ardupilot"] = bool(ARDUPILOT_RE.search(readme))

    docker = sorted(p for p, n in names.items() if n.startswith("Dockerfile") or n.lower().startswith("docker-compose") or n.endswith(".dockerfile"))
    docker += [p for p in paths if p.startswith(".devcontainer/")][:1]
    sig["docker"] = bool(docker)
    if docker:
        why["docker"] = docker[0]

    launch = [p for p, n in names.items() if LAUNCH_RE.search(n)]
    cfg = [p for p in paths if set(p.split("/")[:-1]) & CONFIG_DIRS]
    sig["launch_config"] = bool(launch or cfg)
    if sig["launch_config"]:
        why["launch_config"] = (launch or cfg)[0]

    calib = [p for p, n in names.items() if CALIB_RE.search(p) and CALIB_EXT_RE.search(n) and not NOT_CALIB_RE.match(n)]
    sig["calibration"] = bool(calib)
    if calib:
        why["calibration"] = _shallow(calib)[0]

    sig["jetson"] = bool(JETSON_RE.search(readme))
    if sig["jetson"]:
        why["jetson"] = "README 中提到 " + JETSON_RE.search(readme).group(0)

    weights = [p for p, n in names.items() if WEIGHT_RE.search(n)]
    linked = bool(PRETRAINED_RE.search(readme) and WEIGHT_HOST_RE.search(readme))
    sig["pretrained"] = bool(weights or linked)
    if sig["pretrained"]:
        why["pretrained"] = weights[0] if weights else "README 中有权重下载链接"

    return sig, why


def scan_repo(full_name, get=api_get):
    """抓取一个仓库的文件树和少量关键文件；返回 (结果, 依据, 请求次数)。"""
    tree = get(f"/repos/{full_name}/git/trees/HEAD?recursive=1")
    calls = 1
    blobs = {e["path"]: e for e in tree.get("tree", []) if e.get("type") == "blob"}
    paths = sorted(blobs)

    def read(path):
        nonlocal calls
        e = blobs[path]
        if e.get("size", 0) > MAX_FILE_BYTES:
            return ""
        calls += 1
        try:
            return _text(get(f"/repos/{full_name}/git/blobs/{e['sha']}"))
        except Missing:
            return ""

    readme_paths = [p for p in paths if "/" not in p and re.match(r"readme(\.(md|markdown|rst|txt))?$", p, re.I)]
    readme = read(sorted(readme_paths, key=lambda p: (not p.lower().endswith(".md"), p))[0]) if readme_paths else ""
    pkgs = [read(p) for p in _shallow(p for p in paths if posixpath.basename(p) == "package.xml")[:2]]
    dockerfiles = _shallow(p for p in paths if posixpath.basename(p).startswith("Dockerfile"))
    dockerfile = read(dockerfiles[0]) if dockerfiles else ""

    sig, why = detect(paths, readme, pkgs, dockerfile)
    if tree.get("truncated"):
        why["_note"] = "文件树过大，只扫描了部分文件"
    return sig, why, calls


def main(get=api_get, today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    papers = datalib.load_papers()
    stats = datalib.load_stats().get("repos", {})
    old = datalib.load_stats(datalib.SIGNALS).get("repos", {})

    keys = sorted({datalib.repo_key(r["name"]): r["name"] for p in papers for r in p.get("repos", [])}.items())
    out, budget, scanned, kept, failed, pending = {}, MAX_REQUESTS, 0, 0, [], 0
    for key, name in keys:
        st = stats.get(key, {})
        prev = old.get(key)
        commit = st.get("updated")
        fresh = prev and prev.get("scanner") == SCANNER_VERSION and prev.get("commit") == commit and commit
        if fresh or st.get("missing"):
            if prev:
                out[key] = prev
                kept += 1
            continue
        if budget < 5:                      # 本次请求额度用完，留到下次
            pending += 1
            if prev:
                out[key] = prev
            continue
        try:
            sig, why, calls = scan_repo(st.get("full_name") or name, get)
        except Exception as err:            # 单个仓库失败不影响其余条目
            budget -= 1
            failed.append(f"{name}（{err}）")
            if prev:
                out[key] = prev
            continue
        budget -= calls
        scanned += 1
        out[key] = dict(sig, why=why, commit=commit, scanned=today, scanner=SCANNER_VERSION)

    datalib.save_stats({"schema_version": 1, "generated_at": today, "repos": out}, datalib.SIGNALS)
    print(f"已扫描 {scanned} 个仓库，沿用 {kept} 个，用掉 {MAX_REQUESTS - budget} 次请求"
          + (f"，{pending} 个留到下次" if pending else ""))
    for line in failed:
        print(f"::warning::未能扫描：{line}")


if __name__ == "__main__":
    main()
