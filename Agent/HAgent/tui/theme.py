"""TUI 主题与样式。

样式集中管理，避免散落在各个控件里；更换主题只需替换 :data:`APP_CSS`
或调用 Textual 内置主题切换。
"""

from __future__ import annotations

APP_CSS = """
Screen {
    background: $surface;
    layers: base overlay;
}

#body {
    height: 1fr;
}

#chat {
    width: 1fr;
    padding: 1 2;
    scrollbar-size-vertical: 1;
}

#sidebar {
    width: 42;
    border-left: solid $panel;
    padding: 0 1;
    background: $panel;
    scrollbar-size-vertical: 1;
}

.panel-title {
    color: $accent;
    text-style: bold;
    margin: 1 0 0 0;
}

#session-info {
    color: $text-muted;
    margin: 0 0 1 0;
}

#tool-log {
    height: 1fr;
    min-height: 6;
    border: round $panel;
    padding: 0 1;
}

#prompt-area {
    height: auto;
    padding: 0 2;
}

#prompt {
    border: tall $accent;
    background: $boost;
}

#status {
    height: 1;
    background: $panel;
    color: $text-muted;
    padding: 0 2;
}

.user-message {
    color: $accent;
    text-style: bold;
    margin: 1 0 0 0;
}

.tool-call {
    border: round $warning;
    color: $warning;
    padding: 0 1;
    margin: 1 0 0 0;
}

.tool-result {
    color: $text-muted;
    padding: 0 1 0 2;
}

.tool-result-error {
    color: $error;
}

.error-message {
    color: $error;
    text-style: bold;
    margin: 1 0 0 0;
}

.info-message {
    color: $text-muted;
    margin: 1 0 0 0;
}
"""


__all__ = ["APP_CSS"]
