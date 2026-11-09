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

#command-palette {
    width: 1fr;
    border: round $accent;
    background: $surface;
    color: $text;
    padding: 0 1;
    height: auto;
    max-height: 12;
}

#prompt {
    border: tall $accent;
    background: $boost;
}

#mcp-info {
    color: $text-muted;
    margin: 0 0 1 0;
}

.mcp-server {
    color: $accent;
    text-style: bold;
}

.mcp-tool {
    color: $text-muted;
}

.mcp-error {
    color: $error;
}

#status {
    height: 1;
    background: $panel;
    color: $text-muted;
    padding: 0 2;
}

#status.status-warning {
    color: $warning;
    text-style: bold;
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

.warning-message {
    color: $warning;
    text-style: bold;
    margin: 1 0 0 0;
}

CompactionScreen {
    align: center middle;
}

#compaction-dialog {
    width: 94%;
    height: 90%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}

#compaction-title {
    color: $accent;
    text-style: bold;
}

#compaction-meta {
    color: $text-muted;
    margin: 0 0 1 0;
}

#compaction-panes {
    height: 1fr;
}

.compaction-pane {
    width: 1fr;
    height: 1fr;
    border: round $panel;
    margin: 0 1;
}

.compaction-pane-title {
    color: $accent;
    text-style: bold;
    padding: 0 1;
}

#compaction-original-scroll,
#compaction-summary-scroll {
    height: 1fr;
    padding: 0 1;
}

.compaction-content {
    width: 100%;
    height: auto;
}

#compaction-actions {
    height: auto;
    align: right middle;
    margin-top: 1;
}

SessionResumeScreen {
    align: center middle;
}

#resume-dialog {
    width: 70%;
    max-width: 90;
    height: 60%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}

#resume-title {
    color: $accent;
    text-style: bold;
}

#resume-hint {
    color: $text-muted;
    margin: 0 0 1 0;
}

#resume-empty {
    color: $text-muted;
    margin: 1 0;
}

#resume-list-scroll {
    height: 1fr;
    border: round $panel;
}

#resume-list {
    height: auto;
}

#resume-actions {
    height: auto;
    align: right middle;
    margin-top: 1;
}

ConfigNoticeScreen {
    align: center middle;
}

#config-notice-dialog {
    width: 76%;
    max-width: 100;
    height: auto;
    border: thick $warning;
    background: $surface;
    padding: 2 3;
}

#config-notice-title {
    color: $warning;
    text-style: bold;
    margin-bottom: 1;
}

#config-notice-body {
    color: $text;
    margin-bottom: 1;
}

#config-notice-hint {
    color: $text-muted;
    margin-bottom: 1;
}
"""


__all__ = ["APP_CSS"]
