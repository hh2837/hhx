import json
import os
import urllib.request

from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("ANYTHINGLLM_BASE_URL", "http://localhost:3001/api")
API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "V100P7Z-1GYMTE0-P3VRHB6-ZCT8DEZ")
WORKSPACE = os.environ.get("ANYTHINGLLM_WORKSPACE")

_slug = None


def _call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_slug() -> str:
    global _slug
    if _slug:
        return _slug
    if WORKSPACE:
        _slug = WORKSPACE
    else:
        workspaces = _call("GET", "/v1/workspaces").get("workspaces", [])
        if len(workspaces) != 1:
            raise RuntimeError(
                f"Expected exactly 1 workspace, found {len(workspaces)}. "
                "Set ANYTHINGLLM_WORKSPACE to the workspace slug or name."
            )
        _slug = workspaces[0]["slug"]
    return _slug


mcp = MCPServer("anythingllm")


@mcp.tool()
def query_workspace(question: str) -> str:
    """Answer a question using knowledge extracted from the AnythingLLM workspace.

    Retrieves relevant context from the workspace vector store and returns the
    AI answer together with the cited source titles.
    """
    result = _call(
        "POST",
        f"/v1/workspace/{resolve_slug()}/chat",
        {"message": question, "mode": "query"},
    )
    if result.get("error"):
        raise RuntimeError(f"AnythingLLM error: {result['error']}")
    return json.dumps(
        {
            "answer": result.get("textResponse", ""),
            "sources": [s.get("title") for s in result.get("sources", [])],
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=int(os.environ.get("ANYTHINGLLM_MCP_PORT", "8100")),
        stateless_http=True,
        json_response=True,
    )