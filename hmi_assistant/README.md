# Siemens HMI 画面助手

基于 **大模型 + TIA Portal Openness** 的 HMI 画面自动绘制工具。用中文描述画面需求，大模型生成结构化画面，再经 SimaticML 一键导入博途，自动绘制符号 IO 域、文本 IO 域、按钮（含 VBS 脚本）、指示灯（圆 + 变量动画），并自动链接变量。

> 这是 SCL 代码生成工具的姊妹工具，沿用同样的深色 + 青绿配色风格。

---

## 一、它能做什么

| 画面对象 | 实现方式 |
|---|---|
| **符号 IO 域** | 绘制 + 链接文本列表 + 链接变量 |
| **文本 IO 域** | 绘制 + 链接变量（支持输入/输出/输入输出模式） |
| **按钮** | 绘制 + 导入 VBS 脚本（动画、登录界面等） |
| **指示灯** | 用基本对象「圆」链接变量，靠颜色动画 + 闪烁实现状态显示 |
| **静态文本** | 标签 / 说明文字 |

核心流水线：

```
中文需求 + 图片/PDF
   ↓ 大模型（流式 + 可调思考深度，思考过程一并展示）
结构化中间表示 IR（JSON）
   ↓ 校验 + 归一化
SimaticML（XML）
   ↓ Openness 一键导入
博途 HMI 画面（自动绘制 + 变量链接 + 可选编译）
```

之所以中间隔一层 IR，是为了把「大模型输出」「XML 生成」「Openness 导入」三件事解耦：大模型只需产出规范的 JSON，XML 细节和版本差异都在生成器里处理，便于按博途版本微调。

---

## 二、安装

需要 **Python 3.10 ~ 3.12**。

```bash
cd hmi_assistant
pip install -r requirements.txt
```

`pythonnet`（Openness 用）仅在 Windows 上安装。**在 Mac / Linux 上也能正常启动**，只是 Openness 进入「诊断模式」无法真正连接博途——这样方便你先在任意机器上调好前端和大模型，再到装了博途的 Windows 机器上做导入。

---

## 三、运行

```bash
python app.py
```

浏览器打开 **http://127.0.0.1:5000**

首次运行会在项目根目录自动生成 `config.yaml`。

### 配置大模型 API Key

两种方式任选其一：

1. **界面里配**：点右上角 ⚙️ 设置 → 填 Base URL / API Key / 模型名 → 保存（推荐，可点「测试连接」验证）。
2. **直接改 `config.yaml`**：在 `llm.providers.deepseek.api_key` 填入你的 Key。

默认走 DeepSeek（OpenAI 兼容接口）。换其它供应商时把 `active_provider` 指向 `openai_compatible`，或在「设置」里切换。**思考深度**「低/中/高」会优先用带原生推理的 reasoner 模型（如 `deepseek-reasoner`）；「关闭」用普通 chat 模型。

---

## 四、使用流程

1. 左侧文本框用中文描述画面需求（参考占位示例：*「一个电机启停控制画面，带启动/停止按钮、运行指示灯、故障指示灯，并显示当前转速」*）。
2. 需要的话拖入**图片或 PDF**（例如手绘草图、工艺说明），会作为附加上下文。
3. 选思考深度，点**生成**。右侧实时流式显示：**思考过程**（可折叠）→ **AI 输出** → 解析出的 **IR**。
4. 切到**画面预览**标签，看 IR 渲染成的 SVG 草图（IO 域、按钮、闪烁指示灯等）确认布局。
5. 确认无误后，点底部**生成 XML**得到 SimaticML 文件（落在 `exports/`）。
6. 右上角点**连接**附加到正在运行的博途实例 → 点**导入到博途**，自动绘制并链接变量。

---

## 五、Openness 使用前提（Windows）

真正导入到博途，需要满足：

1. **安装了 TIA Portal**（建议 V16 及以上）及对应的 **Openness** 功能。
2. **已用博途打开目标项目**（`attach_running: true` 时附加到当前实例最稳）。
3. 当前 Windows 账户已加入 **Siemens TIA Openness** 用户组（首次会弹授权确认，点允许）。
4. `config.yaml` 里 `openness` 节配置正确：
   - `tia_version`：你的博途版本（如 `V18`）。
   - `dll_path`：`Siemens.Engineering.dll` 的实际路径（版本号要对上）。
   - `hmi_device`：目标 HMI 设备名（需与项目中一致）。

不确定能不能连？点右上角**诊断**，会列出 pythonnet 是否就绪、DLL 是否找到、博途实例是否可附加等，逐项排查。

---

## 六、关于 SimaticML 的重要说明（务必阅读）

SimaticML 里**画面元素的精确标签名、属性、命名空间，会随博途版本（V16→V19）和 HMI 类型（Comfort 面板 / Unified 统一精智）不同而变化**。本工具的生成器（`backend/simaticml_generator.py`）已尽量贴合常见情况，并把每类对象拆成独立函数，但不可能覆盖所有版本组合。

**强烈建议按你的实际环境校准一次**：

1. 在博途里**手动画一个**含目标元素（IO 域、按钮、圆等）的样例画面。
2. 用 Openness 或界面 `Screen.Export()` 把它**导出为 XML**。
3. 对照导出的真实 XML，微调 `simaticml_generator.py` 里对应对象的标签/属性。

校准一次后，后续生成就能稳定匹配你的博途版本。生成器已按对象分函数，改起来定位很快。

---

## 七、项目结构

```
hmi_assistant/
├── app.py                      # Flask 主程序与所有 API 路由
├── config.yaml                 # 运行后自动生成的配置（API Key、Openness 等）
├── requirements.txt
├── backend/
│   ├── prompts.py              # ★ 内置提示词：IR 规范 + 文字/命名约定 + VBS 约定 + 示例
│   ├── config_manager.py       # config.yaml 读写与默认值
│   ├── llm_client.py           # 大模型流式客户端 + 思考深度 + JSON 抽取
│   ├── hmi_ir.py               # IR 校验与归一化、交叉引用检查
│   ├── simaticml_generator.py  # IR → SimaticML(XML)，各对象生成片段
│   └── openness_manager.py     # 附加博途 / 导入画面 / 编译（pythonnet）
├── templates/
│   └── index.html              # 主界面
├── static/
│   ├── css/style.css           # 深色青绿主题
│   └── js/app.js               # 前端逻辑：流式读取、SVG 预览、配置、导入
├── exports/                    # 生成的 XML 输出目录
└── uploads/                    # 上传文件临时目录
```

最关键的是 **`backend/prompts.py`**——它内置了约束大模型「画面输出」和「文字内容输出」的系统提示词（含 IR JSON 强约束、`LMP_/BTN_/IO_/SIO_/TXT_` 命名前缀规范、VBS 读写 SmartTags 约定，以及一个电机控制的 few-shot 示例）。需要调整生成风格或命名规范，改这里即可。

---

## 八、API 速览（前端已封装，二次开发可用）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 主界面 |
| `/api/config` | GET/POST | 读取 / 保存配置 |
| `/api/config/raw` | POST | 直接保存原始 YAML |
| `/api/generate` | POST | 大模型流式生成（SSE，支持 multipart 文件上传） |
| `/api/build` | POST | 由 IR 生成 SimaticML XML |
| `/api/openness/diagnose` | POST | 环境诊断 |
| `/api/openness/connect` | POST | 附加到博途 |
| `/api/openness/import` | POST | 导入画面到博途 |
| `/api/openness/disconnect` | POST | 断开 |

---

## 常见问题

**Q：没装博途，能用吗？**
能。前端、大模型生成、IR 预览、XML 导出都能正常用；只有「导入到博途」需要 Windows + 博途。

**Q：导入后元素位置/属性不对？**
基本是 SimaticML 版本差异，按上面**第六节**校准一次即可。

**Q：思考过程不显示？**
确认 `config.yaml` 里 `show_thinking: true`，且思考深度不为「关闭」，并使用支持推理的模型。
