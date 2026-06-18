# DeepSeek + Xiaomi MiMo-V2.5 Vision Bridge AgentSkill

这个 AgentSkill 的作用是：让 DeepSeek 继续负责文本推理、计划、综合回答；让小米 MiMo-V2.5 负责图像、截图、图表、表格、技术图纸、OCR、多图对比等视觉理解。

## 为什么这样设计

DeepSeek 的 Tool Calls 机制允许模型调用外部工具增强能力；MiMo-V2.5 的图像理解接口支持通过图片 URL 或 Base64/data URL 输入图片。因此最稳的架构是：

```text
用户问题 + 图片
      ↓
DeepSeek 判断是否需要视觉能力
      ↓ tool call
mimo_visual_analyze
      ↓
MiMo-V2.5 读取图片并输出结构化视觉结果
      ↓ tool result
DeepSeek 综合视觉结果 + 用户问题，生成最终答案
```

## 文件结构

```text
deepseek_mimo_vision_skill/
├── SKILL.md
├── README.md
├── requirements.txt
├── .env.example
├── tools/
│   ├── mimo_vision.py
│   └── deepseek_agent_loop.py
└── examples/
    └── run_image_query.py
```

## 安装

```bash
cd deepseek_mimo_vision_skill
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

然后在 `.env` 里填写：

```bash
MIMO_API_KEY=你的_MiMo_API_Key
DEEPSEEK_API_KEY=你的_DeepSeek_API_Key
MIMO_MODEL=mimo-v2.5
DEEPSEEK_MODEL=deepseek-v4-pro
```

> 说明：DeepSeek 模型名请按你账号实际可用模型填写。MiMo 图像理解建议用 `mimo-v2.5`。

## 直接测试 MiMo 视觉工具

```bash
python tools/mimo_vision.py \
  --image ./test.png \
  --task "请识别图片中的文字，并说明画面内容" \
  --schema ocr
```

也可以用公网图片 URL：

```bash
python tools/mimo_vision.py \
  --image "https://example.com/image.png" \
  --task "请描述这张图" \
  --schema detailed
```

## 测试 DeepSeek 自动调用 MiMo

```bash
python tools/deepseek_agent_loop.py \
  --question "这张截图报错是什么意思？下一步该怎么处理？" \
  --image ./error_screenshot.png
```

## 给 DeepSeek 注册的工具

工具名：`mimo_visual_analyze`

输入：

```json
{
  "images": [
    {"type": "path", "value": "./screenshot.png", "mime_type": "image/png"}
  ],
  "task": "提取截图中的错误信息，并说明界面当前状态",
  "output_schema": "ui",
  "language": "zh-CN"
}
```

输出：

```json
{
  "ok": true,
  "model": "mimo-v2.5",
  "visual_result": {
    "summary": "...",
    "visible_text": ["..."],
    "objects": ["..."],
    "layout": "...",
    "details": ["..."],
    "uncertainties": ["..."],
    "answer": "..."
  },
  "raw_text": "...",
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "image_tokens": 0,
    "total_tokens": 0
  }
}
```

## 推荐的 DeepSeek 系统提示词

```text
你是一个以 DeepSeek 为主推理模型的智能体。你可以调用外部视觉工具 mimo_visual_analyze。

重要规则：
1. 只要用户的问题依赖图片、截图、图表、表格、图纸、UI、OCR 或多图对比，就必须先调用 mimo_visual_analyze。
2. 不要凭空猜测图片内容。
3. 工具返回后，把视觉结果作为证据，再用你的推理能力给出最终答案。
4. 如果视觉结果里有 uncertainties，不要把不确定内容说成确定事实。
5. 默认使用中文回答。
```

## 典型场景映射

| 用户任务 | output_schema |
|---|---|
| 描述图片内容 | detailed |
| 识别图片文字 | ocr |
| 看截图错误 | ui |
| 分析曲线图/柱状图 | chart |
| 提取表格 | table |
| 分析工程图/图纸 | drawing |
| 对比两张图 | compare |

## 注意事项

1. MiMo API 对本地文件不是“直接上传文件”，本 skill 会把本地图片转成 `data:{mime};base64,...` 后发送。
2. 单张图片不要超过 MiMo 图像理解接口限制；过大的截图建议先裁剪或压缩。
3. 涉及隐私图片时，确认用户确实要进行视觉分析。
4. DeepSeek 最终回答必须基于 MiMo 返回的可见事实，不能自行脑补图片内容。
