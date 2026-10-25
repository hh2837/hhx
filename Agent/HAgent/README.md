# xAgent —— 核心与界面分离的多端 Agent 框架

由 [`Agent/practice02/chat_file.py`](../practice02/chat_file.py) 改造而来：把"脚本"
拆成**可复用的业务内核（core）**与**可替换的前端（tui / web / desktop / mobile）**。

当前提供 **Textual 终端界面（TUI）**，核心层不依赖任何界面框架，未来新增前端时
无需改动业务代码。

---

## 1. 设计目标

| 目标 | 落地方式 |
|---|---|
| 核心与界面分离 | `core/` 不 import 任何 UI 框架；`tui/` 只依赖 `core` 的公共 API |
| 业务模块化 | 工具按域拆分（`core/tools/datetime_tools.py`、`file_tools.py`），通过注册表装配 |
| 层级化 | `config → models/events → llm/tools → agent → frontend`，依赖只能向下 |
| 多端复用 | 前端之间零耦合；核心通过**事件流**把状态变化推送给任意前端 |
| 可测试 | 核心层 33 个离线用例，不需要启动界面、不需要真实模型服务 |

---

## 2. 目录结构

```
xAgent/
├── main.py                     # 统一启动入口（参数解析 + 装配）
├── config.ini                  # 本地配置（已被 .gitignore 忽略，不入库）
├── config.example.ini          # 配置模板（入库）
├── pyproject.toml              # 依赖与 pytest 配置
├── requirements.txt
│
├── core/                       # ★ 业务内核：零 UI 依赖
│   ├── __init__.py             # 公共 API 出口（前端只从这里导入）
│   ├── config.py               # 配置层：ini / 环境变量 / .env → 强类型配置
│   ├── errors.py               # 统一异常体系（XAgentError 为根）
│   ├── models.py               # 领域模型：Message / ToolCall
│   ├── events.py               # 事件定义：核心 ↔ 前端的唯一契约
│   ├── factory.py              # 装配工厂：build_agent / build_client / build_tools
│   ├── llm/                    # 大模型接入层
│   │   ├── client.py           #   LLMClient 抽象 + StreamChunk
│   │   ├── openai_client.py    #   OpenAI 兼容实现（SSE 流式 + function calling）
│   │   └── sse.py              #   SSE 解析
│   ├── tools/                  # 工具层
│   │   ├── base.py             #   ToolSpec / ToolResult
│   │   ├── registry.py         #   工具注册表 + JSON Schema 自动生成
│   │   ├── datetime_tools.py   #   时间工具
│   │   └── file_tools.py       #   文件系统工具（沙箱限制）
│   └── agent/                  # 编排层
│       ├── agent.py            #   模型 ⇄ 工具 主循环 + 事件产出
│       └── session.py          #   会话持久化（JSON）
│
├── tui/                        # ★ 终端前端（Textual）
│   ├── __init__.py
│   ├── __main__.py             #   python -m tui
│   ├── app.py                  #   App 装配、事件 → 界面调度
│   ├── controller.py           #   事件翻译器（不依赖 Textual，可单测）
│   ├── theme.py                #   样式
│   └── widgets/                #   对话区 / 输入框 / 侧边栏 / 状态栏
│
└── tests/                      # 离线单元测试 + TUI 集成测试
```

> 未来新增前端时，只需在同级目录新建 `web/`、`desktop/`、`mobile/`，并保持
> "只依赖 `core` 公共 API"的约束即可，无需修改 `core/` 任何代码。

---

## 3. 依赖方向

```
        ┌───────────────────────────────────────────────┐
        │  前端层（可替换、可并存）                        │
        │  tui/    web/    desktop/    mobile/           │
        └───────────────────┬───────────────────────────┘
                            │ 只依赖 core 的公共 API
                            │ 通过 Event 流接收状态变化
        ┌───────────────────▼───────────────────────────┐
        │  核心层 core/（与界面完全无关）                 │
        │  agent/ → tools/ 、 llm/                       │
        │  事件：RunStarted / AssistantDelta /           │
        │        ToolCallRequested / ToolCallFinished … │
        └───────────────────┬───────────────────────────┘
                            │
                 ┌──────────▼──────────┐
                 │ OpenAI 兼容 HTTP 服务 │
                 └─────────────────────┘
```

**单向依赖**：`tui → core → (标准库 / requests)`。核心层**不允许** import
`textual` 或任何前端模块；前端之间也互不依赖。

---

## 4. 核心设计

### 4.1 事件流：核心与前端之间的唯一契约

核心层不知道界面长什么样，只负责"发生了什么"，通过 `EventEmitter` 推送事件：

| 事件 | 含义 |
|---|---|
| `RunStarted` | 一轮对话开始 |
| `UserMessageEcho` | 用户输入已写入历史 |
| `AssistantMessageStarted` | 助手开始输出（前端据此创建消息气泡） |
| `AssistantDelta` | 流式增量片段 |
| `AssistantMessage` | 本轮回答结束 |
| `ToolCallRequested` / `ToolCallFinished` | 工具调用请求 / 结果 |
| `ErrorOccurred` / `RunFinished` | 错误 / 本轮结束 |

新增前端只需实现 `ChatViewPort` 协议（见 `tui/controller.py`）即可复用全部业务能力。

### 4.2 工具层

- `@registry.tool()` 装饰器注册工具，**JSON Schema 由函数签名 + docstring 自动生成**
  （支持 Google 风格 `Args:` 与 Sphinx 风格 `:param:`），也可用 `parameters=` 显式覆盖。
- 工具执行统一返回 `ToolResult(ok, content, error)`，异常不会打断主循环。
- 文件系统工具默认**沙箱化**：路径统一归一化，越界路径直接拒绝。

内置工具：`getdate`、`isLeapYear`、`get_cwd`、`list_dir`、`file_info`、`read_file`、
`create_file`、`write_file`、`create_dir`、`delete_dir`、`delete_file`、`move_path`。

### 4.3 模型接入

`LLMClient` 是抽象基类，`OpenAICompatibleClient` 为 OpenAI 兼容协议实现
（LM Studio / Ollama / vLLM / DeepSeek 等均可直接使用），支持 SSE 流式输出与
function calling，工具调用参数按 `index` 聚合，支持分片拼接。

---

## 5. 快速开始

```bash
cd Agent/xAgent

# 1. 安装依赖
pip install -r requirements.txt

# 2. 准备配置（config.ini 不入库，请自行创建）
copy config.example.ini config.ini
#    然后编辑 [LLM] 段：base_url / api_key / model

# 3. 启动 TUI
python main.py
#    等价写法：
python -m tui
```

常用参数：

```bash
python main.py --workspace D:\work          # 指定工作目录（同时是文件沙箱根）
python main.py --model "DeepSeek V4.1 Flash" # 临时覆盖模型
python main.py --base-url http://127.0.0.1:1234/v1
python main.py --no-sidebar                  # 隐藏右侧信息栏
python main.py --list-tools                  # 查看内置工具
```

### 快捷键

| 快捷键 | 功能 |
|---|---|
| `Enter` | 发送 |
| `Ctrl+Q` | 退出 |
| `Ctrl+N` | 新会话（清空历史与界面） |
| `Ctrl+S` | 保存当前会话到 `.xagent/sessions/` |
| `Ctrl+L` | 清屏（保留历史） |

---

## 6. 配置

优先级：**内置默认值 < config.ini < 环境变量 < .env**。

| 环境变量 | 说明 |
|---|---|
| `XAGENT_CONFIG` | 指定配置文件路径 |
| `XAGENT_LLM_BASE_URL` / `XAGENT_LLM_API_KEY` / `XAGENT_LLM_MODEL` | 覆盖 `[LLM]` |
| `XAGENT_LLM_TIMEOUT` / `XAGENT_LLM_TEMPERATURE` | 覆盖超时与温度 |
| `XAGENT_MAX_TOOL_ROUNDS` | 单轮内最大工具调用轮次 |
| `XAGENT_SYSTEM_PROMPT` | 覆盖系统提示词 |
| `XAGENT_FS_ROOT` | 文件工具沙箱根目录（默认工作目录） |
| `XAGENT_WORKSPACE` | 工作目录 |
| `XAGENT_THEME` | Textual 主题名 |

`config.ini` 与 `.env` 已被 `.gitignore` 忽略，**不要把密钥提交到仓库**。

---

## 7. 测试与代码规范

```bash
cd Agent/xAgent
python -m pytest -q          # 33 passed
ruff check core tui tests    # 规范检查（规则集见 pyproject.toml）
```

测试全部离线：模型用假客户端替换，文件操作在临时目录内完成，TUI 用
Textual 的 `run_test()` 驱动。

---

## 8. 与 `practice02/chat_file.py` 的对照

| 原脚本 | 现在的位置 |
|---|---|
| `configparser` 读 `config.ini` | `core/config.py`（`ConfigLoader`，支持环境变量覆盖与强类型） |
| `getdate` / `isLeapYear` | `core/tools/datetime_tools.py` |
| `list_dir` / `read_file` / `create_file` … | `core/tools/file_tools.py`（`FileTools`，带沙箱） |
| `tools` 列表字面量 | `core/tools/registry.py`（注册表自动生成 JSON Schema） |
| `run_tool` if/elif 分发 | `ToolRegistry.execute()` + 装饰器注册 |
| `history` 列表 | `core/models.py` 的 `Message` + `core/agent/session.py` 持久化 |
| `while True` + `input()` 主循环 | `core/agent/agent.py`（事件驱动）+ `tui/app.py`（界面） |
| `print(content, end="")` 流式输出 | `AssistantDelta` 事件 → `tui/widgets/chat_view.py` |

---

## 9. 如何新增一个前端（以 Web 为例）

1. 新建 `web/` 目录与 `web/app.py`；
2. 只从 `core` 导入：`from core import Agent, build_agent, ConfigLoader, ...`；
3. 实现一个类似 `ChatViewPort` 的适配层，把 `core.events` 翻译成前端动作
   （SSE / WebSocket 推给浏览器）；
4. 在 `main.py` 中增加子命令分发。

`core/` 不需要任何改动。

---

## 10. 安全须知

- **不要提交 `config.ini` / `.env`**（含 API Key），已通过 `.gitignore` 排除。
- 文件工具默认限制在工作目录内；如需放开，可通过 `XAGENT_FS_ROOT` 显式指定，
  但请评估风险。
- 删除类工具（`delete_file` / `delete_dir`）由模型触发，建议在生产环境加人工确认。

---

## License

MIT
