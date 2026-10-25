# mini-swe-agent 源码研读笔记（第五讲：企业级日志、轨迹序列化与 Python 对象底层魔术）

## 目录
1. [Python 原生 Logging 四大核心积木](#1-python-原生-logging-四大核心积木)
2. [log.py 双分流架构源码解密](#2-logpy-双分流架构源码解密)
3. [单例注册表与变量作用域闭环](#3-单例注册表与变量作用域闭环)
4. [超越纯文本日志：结构化轨迹（Trajectory JSON）](#4-超越纯文本日志结构化轨迹trajectory-json)
5. [Python 系统魔术变量（Dunder Attributes）全景](#5-python-系统魔术变量dunder-attributes全景)
6. [对象、实例与 __dict__ 的底层内存本质](#6-对象实例与-__dict__-的底层内存本质)
7. [互动精要复盘](#7-互动精要复盘)

---

## 1. Python 原生 Logging 四大核心积木

Python 原生 `logging` 模块遵循“电视台流水线模式”，解耦日志的收集、分流与排版：

```
代码层: logger.info("...")
             │
             ▼
    ┌────────────────┐
    │ 1. Logger (总台)│ ──► 入口，设定最低接收门槛（Level）
    └────────┬───────┘
             │
     ┌───────┴───────┐
     ▼               ▼
┌─────────┐     ┌─────────┐
│Handler A│     │Handler B│ ──► 2. Handler（分流渠道）：一个打屏幕，一个写文件
└────┬────┘     └────┬────┘
     ▼               ▼
┌─────────┐     ┌─────────┐
│Formatter│     │Formatter│ ──► 3. Formatter（排版）：终端要简洁色彩，文件要精确时间戳
└─────────┘     └─────────┘
```

* **Level（五级日志天梯）**：`DEBUG` < `INFO` < `WARNING` < `ERROR` < `CRITICAL`。

---

## 2. log.py 双分流架构源码解密

打开 `src/minisweagent/utils/log.py`：

```python
import logging
from pathlib import Path
from rich.logging import RichHandler

def _setup_root_logger() -> None:
    logger = logging.getLogger("minisweagent")
    logger.setLevel(logging.DEBUG)
    
    # 屏幕渠道：Rich 富文本美化
    _handler = RichHandler(
        show_path=False, show_time=False, show_level=False, markup=True
    )
    _formatter = logging.Formatter("%(name)s: %(levelname)s: %(message)s")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)

def add_file_handler(path: Path | str, level: int = logging.DEBUG, *, print_path: bool = True) -> None:
    logger = logging.getLogger("minisweagent")
    # 磁盘文件渠道：标准文件追加
    handler = logging.FileHandler(path)
    handler.setLevel(level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

_setup_root_logger()
logger = logging.getLogger("minisweagent")

__all__ = ["logger"]
```

### 双分流工程价值：
1. **面向终端人类（`RichHandler`）**：隐藏繁杂的毫秒时间戳与源码物理路径，开启 `markup=True` 支持色彩标签，提供赏心悦目的终端阅读体验。
2. **面向事后审计排查（`FileHandler`）**：记录精确到毫秒的绝对时间（`%(asctime)s`），让故障复盘和性能瓶颈分析有据可查。

---

## 3. 单例注册表与变量作用域闭环

### 核心疑问：为什么 `_setup_root_logger()` 调了一次 `getLogger`，外面又调了一次？
1. **单例注册表机制**：`logging.getLogger("minisweagent")` 并不是每次创建新对象，而是查全局单例字典。两次调用返回的是内存中**同一个物理实例**（`id` 相同）。
2. **函数作用域限制（Scope）**：函数内部的 `logger` 是局部变量，函数执行完毕后即被销毁。为了让外部能通过 `from minisweagent.utils.log import logger` 引用，必须在模块全局层重新执行一次，将单例对象绑定到模块的公共变量名上。

---

## 4. 超越纯文本日志：结构化轨迹（Trajectory JSON）

在 Agent 开发中，纯文本日志难以被机器程序自动化评测与回放。`mini-swe-agent` 将每次运行的所有维度打包为结构化快照。

### 核心实现（`default.py:148 serialize`）：
```python
def serialize(self, *extra_dicts) -> dict:
    agent_data = {
        "info": {
            "model_stats": {"instance_cost": self.cost, "api_calls": self.n_calls},
            "config": {
                "agent": self.config.model_dump(mode="json"),
                "agent_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
            },
            "mini_version": __version__,
            "exit_status": last_extra.get("exit_status", ""),
            "submission": last_extra.get("submission", ""),
        },
        "messages": self.messages, # 完整的对话历史数组
        "trajectory_format": "mini-swe-agent-1.1",
    }
    return recursive_merge(agent_data, self.model.serialize(), self.env.serialize(), *extra_dicts)
```

### 轨迹文件的工业意义：
1. **自包含快照**：一份 JSON 文件同时囊括开销、Prompt 模板、模型名称、沙箱操作系统配置以及每一步完整的输入输出。
2. **录像带回放（Inspector TUI）**：官方通过 `inspector.py` 构建了基于 Textual 的终端界面，可按步逐帧审查大模型的思考过程，彻底告别盲搜文本日志。

---

## 5. Python 系统魔术变量（Dunder Attributes）全景

前后双下划线变量 `__xxx__` 是 Python 解释器保留的系统级契约与元数据钩子：

```
                           Python 双下划线元数据
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
【阵营 1：文件与模块身份】      【阵营 2：导入与发布规范】      【阵营 3：类与对象反射】
• __name__ (身份牌)          • __all__ (导出白名单)         • __class__ (所属类型)
• __file__ (物理绝对路径)    • __version__ (版本号)         • __dict__ (属性存储字典)
• __doc__  (文档字符串)      • __package__ (所属包路径)     • __module__ (定义所在模块)
```

### 1. `__name__` 的“主角与配角”法则
* 当文件被终端直接运行（如 `python run/mini.py`）：Python 设其为 `"__main__"`。
* 当文件被外部 `import`：Python 设其为模块路径名（如 `"minisweagent.run.mini"`）。
* **`if __name__ == "__main__":` 的工程价值**：门禁保护，保证文件作为脚本直接执行时跑测试/启动命令，而被当作库导入时不产生任何意外副作用。

### 2. `__all__` 的导出白名单法则
* 当外部使用 `from module import *` 时，只有列在 `__all__ = ["logger"]` 列表中的符号才会被导出，彻底杜绝外部依赖污染调用方的命名空间。

### 3. `__file__` 与 `__doc__`
* `__file__` 记录当前文件在磁盘上的物理绝对路径，常用于相对路径查找内置静态资源（如 `mini.yaml`）。
* `__doc__` 提取模块/函数头部的 Docstring，常被 CLI 框架（如 Typer）直接抓取作为命令行帮助文档。

---

## 6. 对象、实例与 `__dict__` 的底层内存本质

### 1. 对象（Object）vs 实例（Instance）
* **对象（本体论）**：只要存在于 Python 内存中的实体都是对象（“万物皆对象”，数字、字符串、函数、类本身都是对象）。
* **实例（关系论）**：强调个体与模具的衍生关系（`isinstance(a, B)` 表示 a 是类 B 实例化出来的产物）。

### 2. 对象的本质就是字典：`__dict__`
在 Python 底层，一个对象身上所有的属性，物理上全部保存在其 **`__dict__` 哈希表** 中：
```python
obj.name = "Hanhan"     # 语法糖
obj.__dict__['name'] = "Hanhan"  # 底层真实操作
```

### 3. 函数也是对象，函数也有 `__dict__`！
* 函数对象的 `__dict__` 默认是一个空字典 `{}`。
* **工程黑科技**：框架可以在不改变函数形参的前提下，通过 `func.attr = value` 动态往函数的 `__dict__` 里注入元数据（如 Typer 路由标签、计数器、权限标记等）。

---

## 7. 互动精要复盘

* **Q1：为什么 `_setup_root_logger()` 和模块外层都写了 `logging.getLogger("minisweagent")`？**
  * **解答**：`getLogger` 是单例查表，两次拿到的是内存中同一个对象。函数内负责配置 Handler 和 Formatter，函数外负责将该单例绑定到模块级全局变量 `logger`，以便外部文件安全 `import`。
* **Q2：`if __name__ == "__main__":` 为什么能防止测试代码被外部误执行？**
  * **解答**：文件直接运行时 `__name__` 自动被赋值为 `"__main__"`，条件成立；被当作库 `import` 时 `__name__` 为模块名，条件不成立，内部逻辑自动跳过。
* **Q3：函数的 `__dict__` 有什么用途？**
  * **解答**：函数是对象，其 `__dict__` 允许装饰器或框架在函数身上动态捆绑状态（如调用次数统计）或路由元数据（如命令行 help 文档）。
