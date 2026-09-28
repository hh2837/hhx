"""工具注册包。

每个工具一个模块，提供 ``register(mcp, rest_client)`` 入口；
``server.py`` 负责统一装配。
"""

from __future__ import annotations
