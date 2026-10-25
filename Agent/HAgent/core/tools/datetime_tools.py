"""时间相关的内置工具。"""

from __future__ import annotations

from datetime import datetime

from .registry import ToolRegistry

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def get_date_time() -> str:
    """返回当前日期时间（可单独测试的纯函数）。"""
    now = datetime.now()
    return f"{now.strftime('%Y-%m-%d %H:%M:%S')} {_WEEKDAYS[now.weekday()]}"


def is_leap_year(year: int) -> str:
    """判断年份是否为闰年（可单独测试的纯函数）。"""
    year = int(year)
    if year % 400 == 0:
        return f"{year}年是闰年"
    if year % 100 == 0:
        return f"{year}年不是闰年"
    if year % 4 == 0:
        return f"{year}年是闰年"
    return f"{year}年不是闰年"


def register_datetime_tools(registry: ToolRegistry) -> ToolRegistry:
    """把时间工具注册到注册表。"""

    @registry.tool()
    def getdate() -> str:
        """获取当前电脑的日期和时间。"""
        return get_date_time()

    @registry.tool()
    def isLeapYear(year: int) -> str:
        """计算输入的年份是否是闰年。

        Args:
            year: 要计算的年份，例如 2024
        """
        return is_leap_year(year)

    return registry


__all__ = ["get_date_time", "is_leap_year", "register_datetime_tools"]
