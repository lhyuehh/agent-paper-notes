# mini-swe-agent 源码研读笔记（第七讲：现代 Python 打包规范、PEP 621、Entrypoints 与沙箱环境部署）

## 目录
1. [现代打包大一统：从 setup.py 到 pyproject.toml](#1-现代打包大一统从-setuppy-到-pyprojecttoml)
2. [__version__ 的本质、生命周期与 GitHub Release 映射](#2-version-的本质生命周期与-github-release-映射)
3. [终端快捷命令的诞生机理：Entrypoints 与 Typer app](#3-终端快捷命令的诞生机理entrypoints-与-typer-app)
4. [mini-extra 辅助工具箱与别名设计](#4-mini-extra-辅助工具箱与别名设计)
5. [src 布局与 package-data 静态资源打包避坑](#5-src-布局与-package-data-静态资源打包避坑)
6. [可编辑安装（pip install -e .）原理](#6-可编辑安装pip-install--e-原理)
7. [互动精要复盘](#7-互动精要复盘)

---

## 1. 现代打包大一统：从 setup.py 到 pyproject.toml

在现代 Python 标准（PEP 517 / 518 / 621）下，项目的所有元数据、依赖分组、构建配置完全汇聚于根目录的 `pyproject.toml`。

```toml
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "mini-swe-agent"
dynamic = ["version"]
requires-python = ">=3.10"
dependencies = [
    "pyyaml", "pydantic >= 2.0", "tenacity", "rich", "typer",
    "litellm >= 1.75.5, != 1.82.7, != 1.82.8", # 排除特定安全漏洞版本
]

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "ruff", ...]
modal = ["modal", "boto3"]
full = ["mini-swe-agent[dev]", "mini-swe-agent[modal]", ...]
```

### 可选依赖（Optional Dependencies）哲学：
* 普通用户安装：`pip install mini-swe-agent`，仅下载核心轻量依赖；
* 贡献者与评测者按需加载：`pip install "mini-swe-agent[dev]"` 或 `[modal]`，防止无用依赖膨胀。

---

## 2. __version__ 的本质、生命周期与 GitHub Release 映射

### 1. 代码本质
在 `src/minisweagent/__init__.py` 中定义的标准 SemVer 字符串（如 `"2.4.6"`）。

### 2. 影响范围
* **单一事实来源（Single Source of Truth）**：通过 `dynamic = ["version"]` 映射，打包工具直接读取该字符串，保证源码内部与 PyPI 发布包版本号完全一致。
* **轨迹溯源**：写入 `trajectory.json` 里的 `mini_version` 字段，确保评测记录可精确定位到具体的代码演进阶段。

### 3. GitHub 物理映射
* **Git Tag**：发布时对应 Git 标签（`v2.4.6`）。
* **GitHub Releases**：触发 GitHub Actions CI/CD 自动化构建流程，自动将对应版本的 Wheel 包与更新日志同步推送到 PyPI。

---

## 3. 终端快捷命令的诞生机理：Entrypoints 与 Typer app

### 配置语法（`pyproject.toml:80`）：
```toml
[project.scripts]
mini = "minisweagent.run.mini:app"
mini-swe-agent = "minisweagent.run.mini:app"
```

* **左边 `mini`**：注册到操作系统的可执行命令名。
* **右边 `minisweagent.run.mini:app`**：
  * 模块路径：`minisweagent.run.mini`；
  * 执行目标：`app`（即 `typer.Typer()` 实例对象）。

### 物理底层发生了什么？
当执行 `pip install` 时，pip 会在当前 Python 虚拟环境的 `bin/` 目录下（如 `.venv/bin/mini`）自动生成一个同名的可执行 Shell 包装脚本：
```python
#!/usr/bin/env python
from minisweagent.run.mini import app
app()
```
因为该 `bin/` 目录位于系统的 `$PATH` 环境变量中，所以在全局任何路径下输入 `mini` 都能瞬间被操作系统捕获并启动。

---

## 4. mini-extra 辅助工具箱与别名设计

```toml
[project.scripts]
mini-extra = "minisweagent.run.utilities.mini_extra:main"
mini-e = "minisweagent.run.utilities.mini_extra:main"
```

* **别名机制**：`mini-e` 是 `mini-extra` 的极简别名，提升高频使用者的键盘效率。
* **多功能分发中枢（`mini_extra.py`）**：
  * `mini-extra config`：管理全局 API Key 与环境变量；
  * `mini-extra inspect`（或 `mini-e i`）：启动终端 Textual TUI 交互式回放 Agent 运行轨迹；
  * `mini-extra swebench`：批量运行学术评测。

---

## 5. src 布局与 package-data 静态资源打包避坑

```toml
[tool.setuptools.packages.find]
where = ["src"]
include = ["minisweagent*"]

[tool.setuptools.package-data]
minisweagent = ["config/**/*"]
```

1. **`src/` 布局优势**：避免本地开发根目录中的源码意外遮蔽安装目录中的包，保证开发与测试环境的高度真实性。
2. **`package-data` 避坑关键**：Python 默认只打包 `.py` 代码。Prompt 模板 `mini.yaml` 是静态文本文件，必须显式声明打包规则，否则他人 `pip install` 后会触发 `FileNotFoundError`。

---

## 6. 可编辑安装（pip install -e .）原理

在本地进行源码调试与二次开发时，使用：
```bash
pip install -e .
```
* **原理**：`--editable` 模式不在 `site-packages` 中拷贝源码文件，而是写入一条指向本地开发目录的 `.pth` 符号引用。
* **效果**：在 `src/` 目录下对代码的任何修改，无需重新执行 build 或 install，再次运行终端命令 `mini` 即可毫秒级直接生效。

---

## 7. 互动精要复盘

* **Q1：如何新增一个命令 `mini-test` 调用 `tests/test_init.py` 的 `main()`？**
  * **解答**：在 `[project.scripts]` 下添加：`mini-test = "tests.test_init:main"`。
* **Q2：为什么新增了 `.txt` 提示词模板后，不改配置会导致别人报 `FileNotFoundError`？**
  * **解答**：Python 打包默认只包含 `.py` 文件，非代码的静态数据文件必须在 `[tool.setuptools.package-data]` 中显式声明包含，否则打包时会被自动剔除。
