---
name: deepseek-mimo-vision-bridge
description: Let a DeepSeek-based agent use Xiaomi MiMo-V2.5 multimodal vision to understand images, screenshots, diagrams, tables, charts, PDFs rendered as images, and UI screenshots. Use this skill whenever the user asks a visual question, uploads/links images, needs OCR, chart/table interpretation, visual comparison, screenshot diagnosis, or any task where DeepSeek's text-only reasoning needs visual perception.
---

# DeepSeek + MiMo-V2.5 Vision Bridge Skill

## Purpose

DeepSeek is used as the main reasoning/planning model. MiMo-V2.5 is used as an external visual perception tool. The agent should call MiMo first whenever visual evidence is required, then pass MiMo's structured visual findings back to DeepSeek for final reasoning.

## When to use this skill

Use this skill when the input contains or references:

- One or more image files or image URLs
- Screenshots, app interfaces, code screenshots, error dialogs, UI layouts
- Photos, product images, industrial parts, drawings, charts, tables, diagrams
- Requests such as “看图”, “识别图片”, “图片里有什么”, “分析这张图”, “对比两张图”, “提取图中文字”, “判断图纸/截图问题”
- PDF pages converted to images, especially pages with figures, equations, diagrams, forms, or tables

Do not use this skill for purely text-only questions.

## Core routing rule

DeepSeek must not guess visual details. If the answer depends on visual content, call the tool `mimo_visual_analyze` and wait for its result.

## Tool contract

### Tool name

`mimo_visual_analyze`

### Input JSON

```json
{
  "images": [
    {
      "type": "path | url | base64",
      "value": "local file path, public image URL, or raw/base64 data URL",
      "mime_type": "image/png | image/jpeg | image/webp | image/gif | image/bmp"
    }
  ],
  "task": "What MiMo should inspect or extract from the image(s).",
  "output_schema": "brief | detailed | ocr | chart | table | ui | drawing | compare | custom",
  "language": "zh-CN"
}
```

### Output JSON

```json
{
  "ok": true,
  "model": "mimo-v2.5",
  "task": "...",
  "visual_result": {
    "summary": "high-level description",
    "visible_text": ["OCR text if any"],
    "objects": ["main visible objects/entities"],
    "layout": "spatial/layout notes",
    "details": ["important details"],
    "uncertainties": ["what is unclear or low confidence"],
    "answer": "direct answer to the visual task"
  },
  "raw_text": "MiMo original text output",
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "image_tokens": 0,
    "total_tokens": 0
  }
}
```

If the call fails, return:

```json
{
  "ok": false,
  "error_type": "auth | network | bad_input | api | parse",
  "message": "human-readable error",
  "retryable": true
}
```

## MiMo prompt policy

When calling MiMo, ask for structured observation, not final reasoning. MiMo should:

1. Describe only what is visible.
2. Extract text faithfully if OCR is needed.
3. Mark uncertain details explicitly.
4. Avoid inventing invisible information.
5. Use Chinese by default unless the user asks otherwise.
6. Return JSON when possible.

Recommended MiMo system prompt:

```text
You are a precise multimodal visual perception engine. Your job is to inspect images and return faithful visual observations for another reasoning model. Do not hallucinate. Separate visible facts from inferences. If something is unclear, say it is unclear. Return concise structured JSON in the requested language.
```

## DeepSeek final-answer policy

After MiMo returns visual findings, DeepSeek should:

1. Use MiMo's visual result as evidence.
2. Combine it with the user's text request.
3. Explain any uncertainty.
4. Do not claim visual facts that MiMo did not observe.
5. If MiMo result is insufficient, ask for a clearer image or perform another targeted visual call.

## Multi-image comparison policy

For multiple images, pass all images in a single MiMo request when the user asks for comparison, consistency checking, replacement, before/after analysis, or style matching. Request MiMo to label images as Image 1, Image 2, etc.

## Screenshot/UI policy

For screenshots, ask MiMo to extract:

- Visible error messages
- Button labels and menu names
- Current state of the interface
- Likely next UI action, if visually inferable
- Unclear or cropped areas

DeepSeek should provide the procedural solution after receiving these observations.

## Diagram/drawing policy

For technical drawings, ask MiMo to extract:

- Symbols, callouts, dimensions, title block, annotations
- Relationships between marked components
- Ambiguous or unreadable labels

DeepSeek should perform engineering interpretation only after visual extraction.

## Table/chart policy

For tables/charts, ask MiMo to extract:

- Axes, units, legends, labels
- Data points or approximate trends
- Table headers and cell values
- Visual anomalies

DeepSeek should not overstate exact numerical values unless MiMo clearly reads them.

## Local file policy

MiMo API accepts public URLs and Base64/data URLs. For local files, the bridge code converts the file to `data:{mime};base64,...` before sending to MiMo.

## Security and privacy

- Never log API keys.
- Do not upload private images to MiMo unless the user has provided them for analysis.
- Redact sensitive text from debug logs.
- Keep raw image data out of final responses.

## Minimal usage pattern

1. DeepSeek receives user request with image or visual reference.
2. DeepSeek emits a tool call to `mimo_visual_analyze`.
3. The host application executes `tools/mimo_vision.py`.
4. The host application appends the tool result to the DeepSeek conversation.
5. DeepSeek writes the final answer.
