# pet-hospital-mcp

把现有 **Go 宠物医院 REST API** 暴露给 AI 代理的无状态 **MCP（Model Context Protocol）服务**。

- **SDK**：`mcp==2.0.0`（官方 Python SDK 2.x，`MCPServer`，**不是** FastMCP）
- **协议**：`2026-07-28`（Streamable HTTP，**无状态**：无握手、无 `initialize`、无 `Mcp-Session-Id`）
- **传输**：无状态 Streamable HTTP，单一 HTTP 端点 `/mcp`；另有独立健康检查端点 `/health`
- **阶段一范围**：只暴露**一个工具** `list_pets`（严格适配 `GET /api/v1/pets`）

---

## 1. 功能一览

| 能力 | 说明 |
|---|---|
| 工具 | `list_pets`：列表查询，支持关键词、过滤、排序、分页、费用区间 |
| 输入校验 | 严格：后端允许值枚举、`page>=1`、`1<=pageSize<=500`、`min/max` 非负有限且 `min<=max`、拒绝未知字段/类型错误 |
| 统一错误 | 所有无效输入与上游异常都返回 `{"error": {"code", "message", "details"}}` |
| 错误码 | `VALIDATION_ERROR` / `BACKEND_TIMEOUT` / `BACKEND_UNAVAILABLE` / `BACKEND_API_ERROR` / `BACKEND_INVALID_RESPONSE` / `INTERNAL_ERROR` |
| 后端调用 | 仅经 HTTP 访问 Go REST API；统一超时 + 有限重试（仅瞬时错误）；4xx/5xx 不重试 |
| 日志 | JSON 结构化；`ownerPhone` / `ownerAddr` / `chipNo` 及其 snake_case 写法递归脱敏 |
| 健康检查 | `GET /health`，不依赖 MCP 语义 |
| 测试 | 全部离线模拟后端（respx / MockTransport / 真实模拟后端），绝不访问真实 Go 服务 |

---

## 2. 环境要求

- Python **3.11+**（开发验证环境：3.12）
- Go 宠物医院 REST API 运行于 `http://127.0.0.1:8080`（默认值，可配置）

## 3. 安装与启动

```bash
cd pet_hospital_mcp

# 1) 创建虚拟环境并安装（含开发依赖）
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2) 启动（默认 127.0.0.1:8000，后端默认 http://127.0.0.1:8080）
.venv/bin/python -m pet_hospital_mcp
# 等价方式：
# .venv/bin/uvicorn pet_hospital_mcp.server:app --host 127.0.0.1 --port 8000
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

## 4. 快速验证

```bash
# 健康检查
curl http://127.0.0.1:8000/health
# → {"status":"ok","service":"pet-hospital-mcp","version":"0.1.0","protocol":"2026-07-28"}

# 协议发现（无会话、无握手）
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Method: server/discover" \
  -H "Mcp-Protocol-Version: 2026-07-28" \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{},"io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"}}}}'

# 调用工具（无会话）
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Method: tools/call" \
  -H "Mcp-Name: list_pets" \
  -H "Mcp-Protocol-Version: 2026-07-28" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_pets","arguments":{"params":{"species":"cat","page":1,"pageSize":20}},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{},"io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"}}}}'
```

## 5. `list_pets` 工具契约

### 入参（`params` 对象，字段与 Go API 查询参数一致，全部可选）

| 参数 | 类型 | 约束 |
|---|---|---|
| `q` | string | 全局关键词搜索 |
| `name` / `ownerName` / `ownerPhone` / `doctor` / `disease` | string | 精确过滤 |
| `species` | string | 允许值：`cat` `dog` `bird` `rabbit` `fish` `reptile` `other` |
| `status` | string | 允许值：`admitted` `in_treatment` `hospitalized` `discharged` `recovered` |
| `min` / `max` | number | 费用区间，非负有限数，且 `min <= max` |
| `sortBy` | string | 允许值：`id` `name` `ownerName` `species` `doctor` `disease` `status` `totalCost` `createdAt` |
| `order` | string | `asc` / `desc` |
| `page` | integer | `>= 1`，默认 `1` |
| `pageSize` | integer | `1..500`，默认 `20` |

### 成功输出（对应 Go API 响应中的 `data`）

```json
{
  "items": [ { "id": 1, "name": "Mimi", "species": "cat",
               "records": null, "charges": null } ],
  "total": 1, "page": 1, "pageSize": 20, "totalPages": 1, "totalCost": 12.5
}
```

- `records` / `charges` 兼容 Go 的 `null` 或数组两种真实表现；
- 后端未来新增字段不会导致校验失败（`extra="allow"` 透传）。

### 统一错误结构

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "Invalid input parameters", "details": { "errors": [{"loc": ["species"], "msg": "…", "type": "literal_error"}] } } }
```

## 6. 项目结构

```
pet_hospital_mcp/
├── pyproject.toml            # 依赖（mcp==2.0.0 精确锁定）、pytest 配置
├── README.md
├── UPGRADE_PROMPT.md         # 阶段二扩展指引
├── src/pet_hospital_mcp/
│   ├── __init__.py
│   ├── __main__.py           # python -m pet_hospital_mcp 启动入口
│   ├── config.py             # pydantic-settings 配置（环境变量覆盖）
│   ├── errors.py             # 统一错误结构（ErrorCode / ErrorEnvelope / build_error）
│   ├── logging_config.py     # JSON 结构化日志 + 敏感字段递归脱敏
│   ├── rest_client.py        # Go REST API HTTP 客户端：超时、有限重试、错误翻译
│   ├── server.py             # MCPServer 装配：/health、工具注册、ASGI app
│   └── tools/
│       ├── __init__.py
│       └── list_pets.py      # 唯一工具：输入模型、输出模型、register()
└── tests/
    ├── conftest.py           # 夹具：进程内 Client、respx、FakeGoBackend、uvicorn
    ├── test_rest_client.py   # 客户端：参数转发、超时、重试、错误映射
    ├── test_input_model.py   # 模型级：NaN/Infinity/未知字段/类型等严格拒绝
    ├── test_list_pets.py     # 工具：参数转发、校验失败、后端异常映射、输出兼容
    ├── test_server_registration.py  # 注册/名称/schema/健康检查
    ├── test_http_protocol.py # HTTP 端到端：无状态连接流程、无会话、discover
    └── test_logging.py       # 日志脱敏
```

## 7. 测试

```bash
.venv/bin/python -m pytest -q        # 59 个用例全通过
```

覆盖范围（对应需求文档「测试」清单）：

1. **正常调用**：确认请求路径与全部过滤/排序/分页参数原样转发；
2. **输入校验失败**：枚举、范围、未知字段、类型、`min>max`、非对象输入 → 统一 `VALIDATION_ERROR`；
3. **Go API 4xx/5xx** → `BACKEND_API_ERROR`（含 status 与后端 message）；
4. **超时与连接异常** → `BACKEND_TIMEOUT` / `BACKEND_UNAVAILABLE`（含有限重试与退避）；
5. **非法 JSON / 不符合数据模型** → `BACKEND_INVALID_RESPONSE`；
6. **工具注册**：唯一工具、snake_case 名称、JSON Schema、`/health`；
7. **SDK 2.x 无状态连接流程**（HTTP 端到端）：不发送旧 `initialize`（自动模式走 `server/discover`、钉定模式零协商流量）、不要求/不返回 `Mcp-Session-Id`、2026-07-28 发现/调用方式、`/health` 可用、工具可被发现与调用。

> 说明：测试使用 pytest-asyncio（自动模式）管理异步用例；进程内 MCP 客户端由测试在自身任务内 `async with` 进入（pytest-asyncio 对 anyio 上下文管理器在异步生成器 fixture 中跨任务退出有限制）。HTTP 端到端测试用 `FakeGoBackend`（真实 HTTP 服务器）模拟 Go 后端，避免 respx 拦截测试自身请求。

## 8. 已知假设（需对照真实 Go 服务校准）

仓库根目录未提供 Go 宠物医院源码，以下契约来自任务文档，并在代码中集中标注：

1. **后端允许值**（`species` / `status` / `sortBy` / `order`）：采用教学默认值，集中定义于
   `src/pet_hospital_mcp/tools/list_pets.py` 顶部常量（`Species` / `Status` / `SortBy` / `Order`），
   对照真实后端一次性校准即可；
2. **成功响应信封**：假定为 `{"code": …, "message": …, "data": {…}}`，工具提取 `data` 并校验；
3. **`min`/`max`**：假定为费用区间过滤（响应含 `totalCost`），类型为 number。

## 9. 阶段二扩展（详见 `UPGRADE_PROMPT.md`）

新增工具只需在 `tools/` 下新建模块并实现 `register(mcp, rest_client)`，
复用 `RestClient` / `errors` / `logging_config`，由 `server.py` 统一装配。
