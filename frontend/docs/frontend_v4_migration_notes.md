# V4.0 前端迁移审计报告

## 当前架构

| 项目 | 当前状态 |
|------|---------|
| 框架 | Flask + Jinja2 模板渲染（非 SPA） |
| 前端语言 | 原生 JavaScript (ES6+)，无 TypeScript |
| 状态管理 | 全局变量 + CONFIG 对象，无 Pinia/Vuex |
| UI 组件库 | 无，纯手写 HTML/CSS |
| 路由 | 无前端路由，后端 Flask 路由 |
| 打包工具 | 无 Vite/Webpack |
| CSS | 手写 CSS，深色青绿主题 |
| HTTP 库 | 原生 fetch API，无 axios |

## 现有文件结构

```
templates/
  index.html          # 单页 HTML 模板（465行）
static/
  css/
    style.css         # 全部样式（595行）
  js/
    app.js            # 全部前端逻辑（1067行）
```

## 现有功能清单

1. ✅ 自然语言输入区域 + 示例标签
2. ✅ SSE 流式生成（含思考过程展示）
3. ✅ AI 输出/思考过程折叠面板
4. ✅ 画面预览（SVG 渲染 IR）
5. ✅ MiMo 视觉审查流水线进度 UI
6. ✅ 配置管理（表单 + 原始 YAML）
7. ✅ 模型与接口设置模态框
8. ✅ TIA 连接/断开/诊断
9. ✅ HMI 能力信息展示条
10. ✅ 模板导出对话框
11. ✅ 文件上传（图片/PDF）
12. ✅ 生成模式选择（auto/unified/classic/simaticml）
13. ✅ 经典模板/Unified/默认模板配置
14. ✅ 沉浸式深色/浅色主题切换

## V4.0 缺失功能

1. ❌ 统一的变量表（VariableTable）展示
2. ❌ 统一的控件绑定表（BindingTable）展示
3. ❌ 部署计划 Timeline 展示
4. ❌ 部署状态面板（DeploymentStatusPanel）
5. ❌ 编译结果面板（CompileResultPanel）
6. ❌ 验证结果面板（VerificationResultPanel）
7. ❌ 统一诊断面板（DiagnosticsPanel）
8. ❌ 目标设备选择器（TargetSelector）
9. ❌ 能力矩阵面板（CapabilityPanel）
10. ❌ 模板上传/分析/原型展示
11. ❌ Dry-Run / 真实部署 安全保护
12. ❌ NOT_CONNECTED 状态正确展示
13. ❌ 部署前二次确认
14. ❌ 模块化 JS 架构（单文件 1067 行）
15. ❌ 前端测试

## 迁移策略

**方案选定：原生 JS 模块化扩展**

不引入 Vue/Vite 等重型框架，理由：
- 当前用户已熟悉现有界面
- Flask 模板渲染是成熟的架构选择
- 引入 Vue SPA 需要完全重写，风险高
- 原生 JS 模块化可逐步演进

**实施方案：**
1. 创建 `static/js/modules/` 目录存放模块化 JS
2. 创建 `static/js/api/` 目录存放 API 封装
3. 创建 `static/js/adapters/` 目录存放数据适配器
4. 扩展现有 `templates/index.html` 添加新 UI 组件
5. 扩展 `static/css/style.css` 添加新样式
6. 保持 `app.js` 向后兼容，新增功能通过模块注入

## 验收状态

- ✅ 不删除旧页面
- ✅ 不删除旧 API
- ✅ 能正常启动当前前端
- ✅ 新增 `frontend/docs/frontend_v4_migration_notes.md`
- ✅ 明确当前架构：Flask + 原生 JS + 无状态管理 + fetch API
