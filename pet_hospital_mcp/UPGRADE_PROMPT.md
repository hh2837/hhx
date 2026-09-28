# UPGRADE_PROMPT — 阶段二扩展指引

本文档回答「如何在当前 MCP 服务上安全地新增/升级能力」，供后续开发或
自动代理直接执行时参考。阶段一之后的新增工作应遵循本指引。

---

## 1. 新增一个工具（推荐做法）

1. 在 `src/pet_hospital_mcp/tools/` 下新建模块，例如 `get_pet.py`：
   ```python
   from mcp.server import MCPServer
   from ..rest_client import RestClient

   def register(mcp: MCPServer, rest_client: RestClient) -> None:
       @mcp.tool(name="get_pet", description="…完整契约…")
       async def get_pet(params: Any) -> SomeOutputModel:
           # 1) 用 Pydantic 输入模型 model_validate 统一校验（无效输入 → VALIDATION_ERROR）
           # 2) rest_client.get("/api/v1/pets/{id}")  调用后端
           # 3) 校验响应 → 返回输出模型
   ```
2. 在 `server.py` 的 `create_server()` 中调用
   `from .tools.get_pet import register as register_get_pet` 并
   `register_get_pet(mcp, rest_client)`；
3. 复用 `errors.build_error` / `ToolError`（统一错误结构）、
   `logging_config.get_logger`（自动脱敏 JSON 日志）、`RestClient`（超时/重试）；
4. 在 `tests/` 仿照 `test_list_pets.py` 补充用例。

> 工具名一律 snake_case；参数对象与 Go API 查询/路径参数逐字段对应，
> 不新增适配器私有业务参数。

## 2. 校准后端允许值与契约（对照真实 Go 服务）

仓库根目录当前没有 Go 宠物医院源码，阶段一采用了以下**教学默认值**：

| 项 | 当前取值 | 位置 |
|---|---|---|
| `species` | cat / dog / bird / rabbit / fish / reptile / other | `tools/list_pets.py` 顶部 `Species` |
| `status` | admitted / in_treatment / hospitalized / discharged / recovered | `tools/list_pets.py` 顶部 `Status` |
| `sortBy` | id / name / ownerName / species / doctor / disease / status / totalCost / createdAt | `tools/list_pets.py` 顶部 `SortBy` |
| `order` | asc / desc | `tools/list_pets.py` 顶部 `Order` |
| 成功信封 | `{code, message, data:{items,total,page,pageSize,totalPages,totalCost}}` | `tools/list_pets.py` `_extract_data` |
| `min`/`max` | 费用区间（number） | `tools/list_pets.py` `ListPetsParams` |

拿到真实 Go 源码后，**只需修改上述常量/模型**，无需改动错误处理、
RestClient 与测试框架。校准后同步更新 README 的「已知假设」。

## 3. 已确认的 SDK 2.x 关键行为（勿回退到 1.x 习惯）

- 用 `from mcp.server import MCPServer`（FastMCP 已更名）；**禁止** `FastMCP`；
- 装配用 `mcp.streamable_http_app()`（返回 Starlette app）；自定义路由用
  `@mcp.custom_route("/health", methods=["GET"])`；
- 协议 2026-07-28：**无握手、无会话**。客户端请求在 `_meta` 中携带
  `io.modelcontextprotocol/protocolVersion` 等信封；服务端不要求也不返回
  `Mcp-Session-Id`；发现走 `server/discover`；
- 工具错误：抛 `ToolError(json)`（消息原样到达模型，其余异常会被包装成
  `Error executing tool <name>: …`）；失败标记在协议层为 `isError`，
  Python 侧读取 `result.is_error`（snake_case）；
- 工具参数声明为 `Any` 时，SDK 不做前置类型拦截，全部输入进入工具内
  Pydantic 统一校验路径（保证任何无效输入都返回统一错误结构）；
- 输入 NaN/Infinity：标准 MCP 客户端序列化时会归一化为 `null`，无法以数字
  形态到达工具；模型层仍需用 `allow_inf_nan=False` 拒绝（测试在
  `tests/test_input_model.py` 模型级覆盖）。

## 4. 测试约束（保持）

- 测试**禁止访问真实 Go 服务**；进程内用例用 respx，HTTP 端到端用例用
  `FakeGoBackend`（真实 HTTP 服务器替身）；
- 进程内 `Client` 用同步 fixture 返回未进入对象，测试内 `async with client:`
  进入（pytest-asyncio 对 anyio 上下文管理器跨任务退出有限制）；
- 新增错误码需同步更新 `errors.ErrorCode`、README 错误码表与本文件。

## 5. 常见问题

- **respx 拦截了测试自身的请求**：resp 会对未匹配请求报错；HTTP 端到端测试
  一律改用 `FakeGoBackend`，不要在同一测试里混用 respx 与真实 HTTP 客户端；
- **`Attempted to exit cancel scope in a different task`**：不要在
  pytest-asyncio 异步生成器 fixture 里 `async with Client(mcp)`；改为同步
  fixture 返回未进入的 Client，测试内进入；
- **工具参数类型**：想保留 SDK 自动类型拦截（非对象入参被前置拒绝）可用
  `dict[str, Any]`；想保证统一错误结构（任何无效输入都返回
  `VALIDATION_ERROR`）用 `Any`。阶段一选择 `Any`。
