# hhx — MCP 实践项目集

个人 MCP（Model Context Protocol）实验仓库，收录若干把**既有业务系统**接入 **AI Agent** 的服务实现。

当前包含两个子项目，分别对应两类典型场景：

| 子项目 | 目录 | 场景 | 技术栈 |
|---|---|---|---|
| **Pet Hospital MCP Server** | [`pet_hospital_mcp/`](pet_hospital_mcp/) | 把已有的 **Go 宠物医院 REST API** 通过 MCP 暴露给 AI 代理 | Python · `mcp==2.0.0` · Streamable HTTP |
| **AnythingLLM MCP Server** | [`AnythingLLMMCP/`](AnythingLLMMCP/) | 把 **AnythingLLM** 工作区的 RAG 检索/问答能力暴露为 MCP 工具 | Python · `mcp>=2.0.0` · Streamable HTTP |
| AnythingLLM 文档上传助手 | [`AnythingLLMSever/`](AnythingLLMSever/) | 浏览器内一键把文档上传并嵌入 AnythingLLM 工作区 | 单文件 HTML + Fetch API |

---

## 1. 整体架构

```
                        ┌───────────────────────────────┐
                        │        AI Agent / MCP 客户端    │
                        │ (Claude Desktop、Cursor、…)     │
                        └───────────────┬───────────────┘
                                        │ MCP (Streamable HTTP)
                    ┌───────────────────┴───────────────────┐
                    │                                       │
        ┌───────────▼────────────┐            ┌─────────────▼──────────────┐
        │  pet_hospital_mcp      │            │  AnythingLLM MCP Server     │
        │  :8000  (无状态)        │            │  :8100  (无状态)            │
        │  tool: list_pets       │            │  tool: query_workspace      │
        └───────────┬────────────┘            └─────────────┬──────────────┘
                    │ HTTP (httpx, 超时+重试)                 │ HTTP (urllib)
        ┌───────────▼────────────┐            ┌─────────────▼──────────────┐
        │ Go 宠物医院 REST API    │            │  AnythingLLM Server :3001   │
        │ :8080  /api/v1/pets    │            │  向量库 + LLM 编排           │
        └────────────────────────┘            └────────────────────────────┘
```

两个 MCP 服务都基于**官方 Python SDK 2.x**（`MCPServer`，FastMCP 已更名），
以**无状态 Streamable HTTP** 方式提供服务：没有握手、没有 `initialize`、不返回
`Mcp-Session-Id`，单个 HTTP 端点即可完成发现与调用。

---

## 2. Pet Hospital MCP Server

> 详细文档见 [`pet_hospital_mcp/README.md`](pet_hospital_mcp/README.md)，
> 扩展指引见 [`pet_hospital_mcp/UPGRADE_PROMPT.md`](pet_hospital_mcp/UPGRADE_PROMPT.md)。

把现有 **Go 宠物医院 REST API** 暴露给 AI 代理的无状态 MCP 服务。

- **协议**：`2026-07-28`，Streamable HTTP，无状态
- **端点**：`POST /mcp`（MCP 协议）、`GET /health`（纯 HTTP 健康检查）
- **工具（阶段一）**：`list_pets` —— 列表查询，支持关键词、过滤、排序、分页、费用区间
- **健壮性**：严格入参校验、统一错误信封、超时 + 仅对瞬时错误的有限重试、JSON 结构化日志与敏感字段递归脱敏

### 环境要求

- Python **3.11+**（开发验证环境：3.12）
- Go 宠物医院 REST API 运行于 `http://127.0.0.1:8080`（默认值，可配置）

### 安装与启动

```bash
cd pet_hospital_mcp

# 创建虚拟环境并安装（含开发依赖）
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"     # Windows
# .venv/bin/pip install -e ".[dev]"       # macOS / Linux

# 启动（默认 127.0.0.1:8000）
.venv\Scripts\python -m pet_hospital_mcp
# 等价方式：
# .venv\Scripts\uvicorn pet_hospital_mcp.server:app --host 127.0.0.1 --port 8000
```

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MCP_HOST` | `127.0.0.1` | MCP 服务监听地址 |
| `MCP_PORT` | `8000` | MCP 服务监听端口 |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | 上游 Go REST API 地址 |
| `BACKEND_TIMEOUT_SECONDS` | `10.0` | 单次后端调用超时（秒） |
| `BACKEND_MAX_RETRIES` | `2` | 瞬时失败最大重试次数（总尝试 = 1 + 重试数） |
| `LOG_LEVEL` | `INFO` | 日志级别 |

### 快速验证

```bash
# 健康检查
curl http://127.0.0.1:8000/health
# → {"status":"ok","service":"pet-hospital-mcp","version":"0.1.0","protocol":"2026-07-28"}

# 调用工具（无会话、无握手）
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Method: tools/call" \
  -H "Mcp-Name: list_pets" \
  -H "Mcp-Protocol-Version: 2026-07-28" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_pets","arguments":{"params":{"species":"猫","page":1,"pageSize":20}},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{},"io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"}}}}'
```

### 测试

```bash
cd pet_hospital_mcp
.venv\Scripts\python -m pytest -q     # 59 passed
```

测试**全部离线**：进程内用例用 `respx` 拦截 httpx，HTTP 端到端用例用
`FakeGoBackend`（真实 HTTP 服务器替身），绝不访问真实 Go 服务。

### Windows 一键启动 / 开机自启

| 脚本 | 用途 |
|---|---|
| `启动宠物医院MCP.bat` | 前台启动：先拉起 Go 后端，再在当前窗口运行 MCP 服务 |
| `启动宠物医院MCP自启.vbs` | 无窗口方式调用 `start-services.ps1`（放到 Windows 启动文件夹） |
| `start-services.ps1` | 由计划任务在用户登录时调用；**先探测 8080 / 8000 端口监听状态，未监听才拉起**，避免重复启动 |

> 这三个脚本中的路径为部署机上的绝对路径（`E:\pet\windows\...`），按需修改。

---

## 3. AnythingLLM MCP Server

把 **AnythingLLM** 工作区的 RAG 能力封装成一个 MCP 工具：Agent 可以直接对工作区
里已嵌入的私有文档提问，并拿到答案与引用来源标题。

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ANYTHINGLLM_BASE_URL` | `http://localhost:3001/api` | AnythingLLM API 根地址 |
| `ANYTHINGLLM_API_KEY` | *(必填)* | AnythingLLM API Key，**请通过环境变量注入，不要写进代码** |
| `ANYTHINGLLM_WORKSPACE` | *(可选)* | 目标工作区 slug；不设置则自动取唯一的工作区 |
| `ANYTHINGLLM_MCP_PORT` | `8100` | MCP 服务监听端口 |

### 安装与启动

```bash
cd AnythingLLMMCP
pip install -r requirements.txt

# PowerShell 示例
$env:ANYTHINGLLM_API_KEY = "<your-api-key>"
$env:ANYTHINGLLM_WORKSPACE = "default"
python server.py
```

### 工具契约

| 工具 | 参数 | 返回 |
|---|---|---|
| `query_workspace` | `question: string` | `{"answer": "...", "sources": ["标题1", "标题2"]}` |

服务以 `stateless_http=True` + `json_response=True` 运行在 `127.0.0.1:8100`。

---

## 4. AnythingLLM 文档上传助手

[`AnythingLLMSever/anythingllm-upload.html`](AnythingLLMSever/anythingllm-upload.html)
是一个零依赖的单文件网页工具，用浏览器直接调用 AnythingLLM API 完成三步操作：

1. 拉取工作区列表，取第一个工作区；
2. 上传本地文档（`POST /api/v1/document/upload`）；
3. 触发嵌入（`POST /api/v1/workspace/{slug}/update-embeddings`）。

**使用方式**：直接用浏览器打开该文件，填写 API Base URL 与 API Key，选择文件后点击
「上传并嵌入」，下方黑色控制台会实时打印每一步结果。

---

## 5. 在 MCP 客户端中接入

两个服务都是无状态 Streamable HTTP 服务，在 Claude Desktop / Cursor 等客户端的
MCP 配置中添加 HTTP 类型的服务器即可：

```json
{
  "mcpServers": {
    "pet-hospital": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    },
    "anythingllm": {
      "type": "http",
      "url": "http://127.0.0.1:8100/mcp"
    }
  }
}
```

---

## 6. 目录结构

```
.
├── README.md                          # 本文件：仓库总览
├── pet_hospital_mcp/                  # Go 宠物医院 REST API 的 MCP 网关
│   ├── pyproject.toml                 # 依赖（mcp==2.0.0 精确锁定）与 pytest 配置
│   ├── README.md                      # 子项目详细文档
│   ├── UPGRADE_PROMPT.md              # 阶段二扩展指引（新增工具的正确姿势）
│   ├── start-services.ps1             # 端口探测式自启脚本
│   ├── 启动宠物医院MCP.bat              # 前台一键启动
│   ├── 启动宠物医院MCP自启.vbs           # 无窗口自启入口
│   ├── src/pet_hospital_mcp/
│   │   ├── __main__.py                # python -m pet_hospital_mcp 入口
│   │   ├── config.py                  # pydantic-settings 配置（环境变量覆盖）
│   │   ├── errors.py                  # 统一错误信封与错误码
│   │   ├── logging_config.py          # JSON 结构化日志 + 敏感字段递归脱敏
│   │   ├── rest_client.py             # 上游 HTTP 客户端：超时、重试、错误翻译
│   │   ├── server.py                  # MCPServer 装配：/health + 工具注册
│   │   └── tools/list_pets.py         # 唯一工具：输入/输出模型 + register()
│   └── tests/                         # 59 个离线用例
├── AnythingLLMMCP/                    # AnythingLLM 的 MCP 网关
│   ├── server.py                      # 工具 query_workspace
│   └── requirements.txt
└── AnythingLLMSever/                  # AnythingLLM 文档上传网页助手
    └── anythingllm-upload.html
```

---

## 7. 设计与实现要点

- **SDK 2.x 语义**：`from mcp.server import MCPServer`（不是 `FastMCP`），
  协议 `2026-07-28` 无握手无会话，发现走 `server/discover`。
- **统一错误结构**：所有对客户端可见的错误都返回
  `{"error": {"code", "message", "details"}}`，错误码集合见
  [`errors.py`](pet_hospital_mcp/src/pet_hospital_mcp/errors.py)。
- **只走 HTTP**：MCP 服务不直连数据库或进程内逻辑，一律经 HTTP 调用上游服务，
  便于替换后端与端到端测试。
- **重试策略**：只对超时 / 连接失败等瞬时错误重试并退避；4xx/5xx 属确定性失败，不重试。
- **隐私保护**：日志对 `ownerPhone` / `ownerAddr` / `chipNo`（含 snake_case 写法）递归脱敏。
- **不引入适配器私有参数**：工具入参与上游 REST 查询参数逐字段对应，降低契约漂移风险。

---

## 8. 安全须知

- **不要把 AnythingLLM API Key 提交到仓库**。请通过环境变量
  `ANYTHINGLLM_API_KEY` 注入；若历史提交中已包含真实 Key，请立即在 AnythingLLM
  后台轮换该 Key。
- 两个服务默认只监听 `127.0.0.1`，不对外暴露。若需远程访问，请自行加反向代理与鉴权。
- `pet_hospital_mcp/*.log`、`*.egg-info/`、`.venv/` 属于本地运行产物，**不应**入库。

---

## License

MIT
