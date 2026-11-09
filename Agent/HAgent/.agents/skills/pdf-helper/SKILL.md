---
name: pdf-helper
description: 处理 PDF 文档：读取文本内容、按页提取信息、把 PDF 转换为可编辑文本。当任务涉及 PDF 解析或内容提取时使用。
---

# PDF 处理技能

## 使用流程

1. 先用 fileOps 类工具确认 PDF 文件路径存在。
2. 按页或按整篇提取文本内容。
3. 若需要更详细的约定，加载 `references/extract-rules.md`。

## 注意事项

- 扫描版 PDF 需要 OCR，本技能不覆盖 OCR 流程。
- 输出前先向用户确认页码范围。
