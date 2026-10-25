# mini-swe-agent 源码研读笔记（第二讲：交互状态机、HITL 机制与通用配置穿透）

## 目录
1. [InteractiveAgent 继承与扩展全景](#1-interactiveagent-继承与扩展全景)
2. [人机协作（HITL）四大防御机制（由易到难）](#2-人机协作hitl四大防御机制由易到难)
3. [输入收敛网关与斜杠命令系统](#3-输入收敛网关与斜杠命令系统)
4. [动态 Prompt 模板引擎（Jinja2 系统）](#4-动态-prompt-模板引擎jinja2-系统)
5. [通用命令行配置穿透机制（config_spec 揭秘）](#5-通用命令行配置穿透机制config_spec-揭秘)
6. [测试工程学：如何用自动化代码测试人机交互](#6-测试工程学如何用自动化代码测试人机交互)
7. [互动精要与代码排查四步心法](#7-互动精要与代码排查四步心法)

---

## 1. InteractiveAgent 继承与扩展全景

`mini-swe-agent` 在不修改基类 `DefaultAgent` 原有逻辑的前提下，通过面向对象继承派生了面向终端用户的 `InteractiveAgent`：

```python
class InteractiveAgent(DefaultAgent):
```

### 核心覆写方法矩阵

| 覆写的方法 | `DefaultAgent`（父类批处理基线） | `InteractiveAgent`（子类交互增强） | 工程意图 |
| :--- | :--- | :--- | :--- |
| **`add_messages`** | 仅存入内存 `self.messages` 列表 | **Rich 富文本终端着色打印** | 红/绿色区分模型思考、动作与观察 |
| **`step`** | 纯粹执行 `execute_actions(query())` | **画水平分割线 `Rule()` 并捕获 `KeyboardInterrupt`** | UI 视觉隔离每一步，防止 Ctrl+C 导致进程退出 |
| **`execute_actions`** | 拿到模型命令直接交给沙箱执行 | **安全门神确认与收尾拦截** | 执行前让用户按 Enter 把关，拦截 `Submitted` 异常 |
| **`query`** | 纯粹向大模型 API 发起网络请求 | **人类驾驶模式拦截** | 若处于 `human` 模式，直接读取人类手敲命令，不调模型 |

---

## 2. 人机协作（HITL）四大防御机制（由易到难）

`InteractiveAgent` 构建了由浅入深的人机干预防护网：

```
[难度一：命令守门] ──► 每次模型出招，人类按 Enter 放行或输入驳回
        │
[难度二：收尾验收] ──► 模型打印暗号交卷，拦截 Submitted 异常，允许人类追加新需求
        │
[难度三：运行突发] ──► 模型陷入死循环或胡言乱语，人类按 Ctrl+C 紧急打断
        │
[难度四：控制反转] ──► 彻底屏蔽大模型，人类接管驾驶，命令伪装成 Action 喂给环境
```

### 难度一：动作执行前“守门员”（`_ask_confirmation_or_interrupt`）
* **触发位置**：`interactive.py` 第 138 行，在调用 `self.env.execute(action)` 的前一毫秒。
* **核心代码**：
  ```python
  match user_input := self._prompt_and_handle_slash_commands(prompt).strip():
      case "" | "/y":
          pass  # 【放行】：按回车或 /y，函数正常结束，代码滑到下一行 env.execute
      case _:
          # 【驳回】：输入了拒绝理由，抛出异常，阻止命令执行！
          self._interrupt(f"Commands not executed. The user rejected with: {user_input}", itype="UserRejection")
  ```

### 难度二：任务收尾的“防偷懒验收”（`_check_for_new_task_or_submit`）
* **触发位置**：`interactive.py` 第 143 行，捕获沙箱环境抛出的 `Submitted` 异常。
* **核心代码**：
  ```python
  def _check_for_new_task_or_submit(self, e: Submitted) -> NoReturn:
      if self.config.confirm_exit:
          user_input = self._prompt_and_handle_slash_commands("Agent wants to finish...").strip()
          if user_input:
              # 用户追加了新任务（如："别急着交卷，先跑 pytest！"），强制续命
              self._interrupt(f"The user added a new task: {user_input}", itype="UserNewTask")
      raise e  # 仅当用户敲回车时，才真正把 Submitted 重新抛出收工
  ```

### 难度三：运行中的“紧急红按钮”（`KeyboardInterrupt`）
* **触发位置**：`interactive.py` 第 112 行，在 `step()` 外部包装 `try...except`。
* **核心机制**：用户按 `Ctrl+C` 不会崩溃退出，而是被捕获，并在终端弹窗询问人类要给模型补充什么指示，将键盘中断平滑转化为一条 `UserInterruption` 上下文提示。

### 难度四：架构级控制反转（`human` 模式）
* **触发位置**：`interactive.py` 第 58 行，在 `query()` 内部拦截。
* **核心代码**：
  ```python
  if self.config.mode == "human":
      command = self._prompt_and_handle_slash_commands("> ")
      msg = {
          "role": "user",
          "content": f"User command: \n```bash\n{command}\n```",
          "extra": {"actions": [{"command": command}]},  # 伪造成动作结构！
      }
      self.add_messages(msg)
      return msg  # 直接返回，欺骗下游的 execute_actions！
  ```
* **控制反转精髓**：下游沙箱根本不知道这个 Action 来自人类还是大模型。它忠实执行并将终端输出追加为 Observation，实现了人类与大模型在同一个对话历史中无缝交替驾驶。

---

## 3. 输入收敛网关与斜杠命令系统

为了避免在每个需要人类输入的地方重复编写 `input()` 和命令解析，代码采用了**控制收敛模式**：

```
1. query()               ───┐
2. _ask_confirmation()   ───┼──► _prompt_and_handle_slash_commands() ──► 统一拦截 /c, /y, /u, /h, /m
3. KeyboardInterrupt     ───┤
4. _check_for_new_task() ───┘
```

* **支持的动态模式切换**：
  * `/y` $\to$ 切换为 `yolo`（全自动，不再确认）
  * `/c` $\to$ 切换为 `confirm`（每步确认）
  * `/u` $\to$ 切换为 `human`（人类手敲命令）
  * `/h` $\to$ 打印当前帮助菜单
  * `/m` $\to$ 开启多行输入模式（Multiline Prompt）

---

## 4. 动态 Prompt 模板引擎（Jinja2 系统）

在 `DefaultAgent` 中，Prompt 并非静态文本，而是由 Jinja2 模板在每一步动态渲染产生。

### 变量大一统级联合并（`get_template_vars`）
```python
def get_template_vars(self, **kwargs) -> dict:
    return recursive_merge(
        self.config.model_dump(),   # Agent 静态配置
        self.env.get_template_vars(), # 操作系统信息（system == "Darwin", uname）
        self.model.get_template_vars(),
        {
            "n_model_calls": self.n_calls,
            "model_cost": self.cost,
            "elapsed_seconds": int(time.time() - self._start_time),
        },
        self.extra_template_vars,   # 用户当前 task 文本
        kwargs,
    )
```

### 防御性渲染（`StrictUndefined`）
```python
Template(template, undefined=StrictUndefined).render(**self.get_template_vars())
```
* **工业意义**：常规 Jinja2 遇到未定义变量会静默替换为空字符串。使用 `StrictUndefined` 强制校验，模板里一旦拼错变量名立即抛出异常，绝不给大模型喂残缺的提示词。

### 自适应与防溢出设计实战（`mini.yaml`）
1. **OS 自适应**：
   ```jinja2
   {%- if system == "Darwin" -%}
   You are on MacOS. Use `sed -i ''` instead of `sed -i`.
   {%- endif -%}
   ```
2. **长输出熔断截断（防止 Context Window 溢出）**：
   ```jinja2
   {%- if output.output | length < 10000 -%}
     "output": {{ output.output | tojson }}
   {%- else -%}
     "output_head": {{ output.output[:5000] | tojson }},
     "output_tail": {{ output.output[-5000:] | tojson }},
     "warning": "Output too long. Elided {{ output.output | length - 10000 }} chars."
   {%- endif -%}
   ```

---

## 5. 通用命令行配置穿透机制（config_spec 揭秘）

当在 CLI 中输入：
```bash
mini -c mini.yaml -c other.yaml -c "agent.cost_limit=10.0"
```

### 内部经历的三级演化：

#### 1. Typer CLI 收集（原始字符串列表）
```python
config_spec = ["mini.yaml", "other.yaml", "agent.cost_limit=10.0"]
```

#### 2. Spec 展开与点分语法解析（`get_config_from_spec`）
* 若无等号：读取并解析 YAML 文件为字典。
* 若含等号（`_key_value_spec_to_nested_dict`）：按点号拆分为多层嵌套字典：
  `"agent.cost_limit=10.0"` $\to$ `{"agent": {"cost_limit": 10.0}}`

#### 3. 递归合并（`recursive_merge` 法则）
> **“Later dictionaries take precedence over earlier ones. Nested dictionaries are merged recursively.”**

排在后面的字典拥有最高优先级，精准覆盖前面字典的同名 key，而保留未冲突的字段。
* **架构价值**：无需为每个内部配置编写 CLI 参数，底层所有参数均可通过 `-c key.subkey=value` 无缝穿透覆盖。

---

## 6. 测试工程学：如何用自动化代码测试人机交互

在 `tests/agents/test_interactive.py` 中，展示了工业级测试三大核心手法：

1. **`unittest.mock.patch` 模拟人类按键**：
   ```python
   with mock_prompts(["User rejected", "", ""]):  # 模拟人类先驳回、再确认、最后退出的敲键盘序列
       agent.run("task")
   ```
2. **`DeterministicModel` 0 成本确定性模型**：
   预定义模型返回的文字与工具调用，不花 API 费，毫秒级运行，输出完全可预测。
3. **Mock 突发异常**：
   通过 `patch.object(agent, "query", side_effect=KeyboardInterrupt)` 模拟人类突然按下 Ctrl+C。

---

## 7. 互动精要与代码排查四步心法

### Q1：为什么必须写 `return super().step()` 而不能写 `step()` 或 `self.step()`？
* **写 `step()`**：报 `NameError`，因为当前作用域没有叫 `step` 的独立全局函数。
* **写 `self.step()`**：报 `RecursionError`（无限递归爆栈），因为正在 `InteractiveAgent.step` 内部，调 `self.step` 属于调用自己。
* **写 `super().step()`**：跳过当前类的实现，执行父类 `DefaultAgent` 里的真实 ReAct 核心逻辑，同时保留子类的 `Rule()` 划线和键盘打断防护（经典的面向对象方法增强模式）。

### Q2：排查未知配置参数（如 `whitelist_actions`）的“四步导航心法”

```
遇到源码中的 self.config.foo
      │
      ├── 1. 点进 Config 类 ──────► 查类型、默认值（如 []）与 docstring
      │
      ├── 2. 全局搜索 "foo" ──────► 查源码消费点（re.match 过滤）
      │
      ├── 3. 点进 tests/ ────────► 看测试用例最权威的真实示范（如 [r"echo.*"]）
      │
      └── 4. 查 CLI 的 -c / spec ──► 确认它是通过通用点分语法注入的
```
