"""``python -m pet_hospital_mcp`` 启动入口。"""

from __future__ import annotations

import uvicorn

from .config import Settings
from .server import create_server


def main() -> None:
    settings = Settings()
    bundle = create_server(settings)
    uvicorn.run(
        bundle.app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
