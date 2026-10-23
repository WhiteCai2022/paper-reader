# 项目说明

## 定位与技术栈

论文伴读是本机运行的论文阅读与解析工具，不是公开托管的多人知识库。前端为 React / TypeScript / Vite，PDF 渲染使用 PDF.js，Markdown 与公式使用 react-markdown / KaTeX；后端为 FastAPI / Pydantic，数据保存在 SQLite，文字及版面坐标由 pypdf 提取。

## 目录

```text
backend/                  FastAPI 服务、数据模型、文献管理、翻译与精读任务
backend/tests/            隔离数据与模拟提供方的后端测试
frontend/src/             React 阅读界面与 PDF 段落定位
frontend/tests/           原文匹配与字符偏移测试
frontend/scripts/         构建时准备 PDF.js / API 文档静态资源
docs/                     快速开始、精读标准与项目说明
examples/                 解析导入模板与翻译接口示例
scripts/                  可选的个人资料迁移及历史测试工具
setup.ps1                 安装依赖并构建前端
launch.ps1 / stop.ps1      Windows 本机服务启动和停止
data/                     运行时数据，自动创建，不上传 GitHub
tmp/                      临时文件与本机验证产物，不上传 GitHub
```

`data/seed.json` 是可选的本机初始化资料，不是源码依赖。正常的新安装没有种子文件，直接从空文献库开始。历史迁移脚本不是默认安装或测试流程。

## 接口与任务

运行后访问 `/api/docs`，OpenAPI 定义位于 `/api/openapi.json`。文献、分类、元信息、笔记、阅读进度和解析导入导出均提供 REST API。

收费任务遵循“本地估算 → 冻结模型/推理/文本/提示策略 → 确认预算 → 后台执行 → 记录用量”。翻译和精读共用 Key、串行执行器、预算控制与账本。失败不自动重试；缺少可核验用量时采用请求预留上限保守记账，需对照官方账单。

精读按全文索引、分段详解和综合审查生成草稿，只有用户确认追加后才写入解析。JSON 字符串中的原始换行可兼容读取，仍校验结构、页码、最低篇幅与类型。不能确定的公式和图表必须人工核验，不能把草稿误称为完整复现或视觉审查。

## 开发与测试

完成 `setup.ps1` 后，在项目根目录安装测试依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest backend/tests
```

前端：

```powershell
cd frontend
pnpm test
pnpm build
pnpm dev
```

前端开发服务器将 `/api` 代理到本机 `8765`。可以在另一终端运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

常规测试使用临时数据库及假 API Key，不产生付费模型请求。实际付费测试应单独授权、限定预算并写入账本，不应加入自动测试或 CI。可以通过 `PAPER_READER_DATA_DIR` 指定另一套独立数据目录。

## 安全边界与限制

- 服务仅供本机使用，没有多人认证和权限隔离，不要直接绑定公网地址。
- 仓库只保存源码、文档与模板，不保存论文、个人笔记、缓存、账本、密钥或本机测试输出。
- Windows 界面绑定的 Key 使用当前用户 DPAPI 加密；未绑定时可在后端通过 `DEEPSEEK_API_KEY` 环境变量配置。不要在源码中硬编码密钥。
- DeepSeek 会接收明确授权处理的论文提取文本。出版信息查询使用 Crossref；普通阅读不需要这些外部服务。
- 模型名称、价格和上限属于可变配置，当前后端价格不是官方账单的替代品，变更时应重新核对。
- PDF、元数据和旧笔记是待分析资料，不是可执行指令。复杂分栏、扫描文字及图表需要额外核对。

发布前请检查 `git diff --cached` 和待上传文件列表，不要强制加入 `.gitignore` 中的个人文件。项目当前未附开源许可证；不要把第三方论文或依赖的许可视为本项目自行授予。
