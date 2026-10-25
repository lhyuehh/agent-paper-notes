# ARG-Designer 学习大纲（论文 ↔ 代码 ↔ 工程语法）

> 论文：*Assemble Your Crew: Automatic Multi-agent Communication Topology Design via Autoregressive Graph Generation*（AAAI 2026 Oral，arXiv 2507.18224）
> 目标：① 学会"带着论文读陌生仓库"的方法；② 吃透本仓库用到的工程语法；③ 沉淀一份能指导 Agent 复现本仓库的 `AGENTS.md`。

## 0. 仓库的真实面貌（先看清再学）

| 目录 | 作用 | 对应论文 |
|---|---|---|
| `mas_framework/` | MAS **执行层**：Graph / Node / Agent / LLM / 工具（源自 GDesigner） | Problem Formulation：协作图、协作协议（式 1–3） |
| `experiment/model.py` | **ARGDesigner 模型**：GRU 节点生成器 + GRU 边生成器 | Model Architecture（式 6–15）、Algorithm 1 |
| `experiment/<数据集>/cold_start_*.py` | 阶段 1：生成冷启动数据 D_exp | 式 16 |
| `experiment/<数据集>/finetune_*.py` | 阶段 2：预训练 → 生成 D_eff → 微调 | 式 17、18–21 |
| `experiment/<数据集>/evaluate_*.py` | 阶段 3：用训练好的模型生成拓扑并评测 | Inference |
| `experiment/args.py` `train_ARGDesigner.py` | 命令行配置 / 训练循环 | 式 19 |

**诚实提示**：仓库 **没有** `pyproject.toml` / `requirements.txt` / Dockerfile / shell 脚本；"打包、shell、docker"这一块我们会先看它现有的做法（`sys.path.append`、`.env`、README 里的命令），再动手补上规范版本。另外 `experiment/prompt` 与 `mas_framework/prompt` 内容重复，是代码异味，读代码时要留意。

---

## Part A：宏观架构 ——「论文主要设计 → 代码如何实现」

| 课 | 主题 | 论文对应 | 重点代码 | 要掌握的"读仓库方法" |
|---|---|---|---|---|
| **L01** | 读仓库方法论 + 三阶段流水线全景 | Fig.2b、Intro | README、`cold_start_humaneval.py`、`finetune_humaneval.py`、`evaluate_humaneval.py` | 从 README 命令行入口 → 画数据流（谁产出什么文件，谁消费） |
| **L02** | MAS 执行层：协作图、节点、协议 | 式 1–3、DAG、拓扑排序、K 轮 | `graph/graph.py`、`graph/node.py`、`agents/*`、`agent_registry.py` | 论文里的数学符号 ↔ 类/字段（V→Node，E→spatial/temporal mask） |
| **L03** | 冷启动数据 D_exp | 式 16、config c=('star',6,R) | `utils.get_kwargs`、`cold_start_*.py` | 论文"数据构造"在代码里往往是一个循环 + 过滤条件 |
| **L04** | 图 → 序列：数据表示 | 式 5 自回归分解 | `process_dataset.py`、`*_adapter.py`、`Graph_to_Adj_Matrix` | 模型输入张量的形状推导（max_prev_node、head_and_tail） |
| **L05** | 模型结构：节点生成器 | 式 6–11（task emb、GRU_prev、门控、metric-learning 选角色） | `ARGDesigner.__init__`、`forward` 前半 | 公式逐行对照；找出论文没写的实现细节 |
| **L06** | 模型结构：边生成器 + 训练损失 | 式 12–15、18–21、teacher forcing | `forward` 后半、`train_ARGDesigner.py` | 论文 NLL ↔ 代码 BCE 的等价性与差异 |
| **L07** | 推理采样 | Algorithm 1 | `ARGDesigner.sample`、`utils.generate_graph` | 论文伪代码 ↔ 真实代码里的"修补逻辑"（保底一条边、连通修复、去环） |
| **L08** | 效率微调 D_eff | 式 17：D_simple / D_pruned / D_replay | `finetune_*.py` | 课程学习：用"数据"而非"损失"实现论文思想 |
| **L09** | 评测与全链路串联 + 论文 vs 代码差异清单 | 实验章节、Ablation | `evaluate_*.py`、`ablation_variant` | 复现实验的最小路径；如何判断代码是否忠于论文 |

## Part B：细致语法与工程 —— 每课绑定本仓库的真实代码

| 课 | 主题 | 本仓库里的例子 | 练习 |
|---|---|---|---|
| **L10** | 装饰器与注册表模式 | `@LLMRegistry.register('GPTChat')`、`@classmethod`、`@staticmethod`、`@abstractmethod`、`@property` | 手写一个 `register` 装饰器 + 简易注册表 |
| **L11** | 重试装饰器与异步 | `tenacity` 的 `@retry`（`gpt_chat.py`）；`async/await`、`asyncio.gather`（`cold_start_*`、`graph.arun`） | 给一个会失败的函数加指数退避重试；并发跑 N 个协程 |
| **L12** | 日志 | `loguru`（`utils/log.py`：`configure_logging`、`swarmlog`） | 把仓库里散落的 `print` 改造成分级日志 + 文件轮转 |
| **L13** | 命令行与配置 | `argparse`（`experiment/args.py` 的 `Args` 类；各脚本 `parse_args`）、`parse_known_args` | 对比 mini-swe-agent 的 typer；给脚本加子命令/配置文件 |
| **L14** | 环境配置：`.env` 与 `sys.path` | `template.env`、`python-dotenv`、`sys.path.append(...)` | 解释为何 `cd experiment/humaneval` 才能跑；怎么消除 hack |
| **L15** | Python 打包 | （仓库缺失）补 `pyproject.toml`、`pip install -e .` | 亲手给仓库加上可安装的包结构 |
| **L16** | shell 脚本 + Docker | （仓库缺失）`run_humaneval.sh`、`Dockerfile` | 一键跑三阶段；容器里跑通 |
| **L17** | 毕业：用 Agent.md 复现仓库 | 全部 | 产出 `AGENTS.md` 并试跑 |

> 顺序可以交错：学完 L02 后穿插 L10（注册表），学完 L03 后穿插 L11（异步），随讲随学效果更好。实际顺序以我们的进度为准。

---

## 每一课的固定流程

1. **讲解**：先讲"论文怎么说"，再讲"代码怎么写"，最后讲"二者哪里不一样"。
2. **提问**：3–4 个问题（概念题 + 定位代码题 + 小推理题），你作答。
3. **点评**：我指出你答对/遗漏的点，必要时回讲。
4. **落笔**：生成本课笔记 `lessons/Lxx_*.md`，并把"这一课我们是怎么交流的"追加到 `协作思路文档.md`。

## 产出物

- `learning-notes/00_学习大纲.md`（本文件）
- `learning-notes/lessons/Lxx_*.md`：每课笔记
- `learning-notes/协作思路文档.md`：我们的交流方法 → 最终提炼为 `AGENTS.md`（用于指导 Agent 生成/复现 ARG-Designer）
