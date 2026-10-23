# 论文伴读

本地双栏论文阅读器：左侧是关联页码的 Markdown 解读，右侧是 PDF 原文。支持论文库管理、解析编辑、导入导出、公式渲染和阅读进度保存。React + PDF.js 前端，FastAPI + SQLite 后端。

源码仓库不附带论文、个人笔记、数据库、API Key 或预先构建的前端。首次安装后是空文献库，从“导入 PDF”开始使用；原有安装中的论文、缓存和阅读进度不会因更新源码被清空。

## 主要功能

- 双栏阅读：页码关联解析，Markdown / LaTeX 渲染，阅读进度保存。
- 文献库：分类、标签、元信息编辑，导入时识别 PDF / XMP 元数据，可选 DOI 查询。
- 解析管理：手工编辑、JSON / Markdown 导入导出，免费准备助手精读任务。
- API 精读：单篇分阶段生成、草稿预览、确认追加。
- DeepSeek 翻译：模型与推理强度选择、缓存、当前页重译、原文段落定位高亮。
- 费用控制：先估算再确认、单次及累计预算、真实账户余额查询、用量记账，不自动重试收费请求。

## 首次安装

推荐 Windows、Python 3.12+、Node.js 22.18+ 和 pnpm。普通阅读不要求 API Key，只有调用翻译或 API 精读时才需要配置。

```powershell
git clone https://github.com/WhiteCai2022/paper-reader.git
cd paper-reader
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launch.ps1
```

`setup.ps1` 创建 Python 虚拟环境、安装依赖并构建前端，需要联网。之后可双击 `启动阅读器.cmd`；默认打开 `http://127.0.0.1:8765`。未使用 Windows 启动器时可按下文开发命令手动运行后端和前端。

更详细的操作顺序见 [快速开始](docs/QUICKSTART.md)，项目目录与维护说明见 [项目说明](docs/PROJECT.md)。

## 打开与停止

在 Windows 中双击本目录的 `启动阅读器.cmd`，程序会在后台启动并打开浏览器。默认地址 `http://127.0.0.1:8765`；该端口被占用时自动选择后续空闲端口，以启动器显示的地址为准。

双击 `停止阅读器.cmd` 可以关闭本程序的后台进程。重复启动会复用已经运行的实例。

也可在 PowerShell 中运行：

```powershell
./launch.ps1
./launch.ps1 -NoBrowser
./stop.ps1
```

从 GitHub 下载或迁移到新机器后，需要先运行 `setup.ps1`；依赖、虚拟环境和构建产物不随源码上传。正常阅读不需要外部 CDN。

## 阅读与编辑

1. 在论文库中选择论文。解析章节关联 PDF 的起止页，点击章节可转到对应原文。
2. 选择全部解析或当前页解析；页码按 PDF 文件第一页计数，不是期刊印刷页码。
3. 在解析编辑器中填写标题、页码范围、类型和 Markdown 正文。正文支持表格和数学公式。
4. 阅读位置与缩放自动保存；完成标记和解析内容保存到本地数据库。

最初的个人安装导入过“第一批文献”，这些原文及个人导读不随源码发布。对于已有安装，文献库以当前保留条目为准，已删除条目不会重新加入；旧的批量简要导读并不等于逐篇精读稿。解析关联相关页码范围，不代表每一页都有逐段解析。后续精读不含自测、练习或参考答案。

## 添加下一篇论文

1. 点击右上角“导入 PDF”，选择新论文。窗口会自动读取元数据并预填标题、作者、出版信息、年份和 DOI；可核对、修改后再导入。上传只接受可解析且未加密的 PDF，最大 100 MB。上传完成后选中该论文，此时还没有自动生成解析。
2. 点击论文标题右侧的“精读任务”，可填写本次阅读重点，复制任务后发到当前助手对话，或将下载的任务文件交给助手。这一步只在本地准备原 PDF 路径、目标论文 ID、输出格式和完整精读标准，不调用 DeepSeek、不扣费，也不会改动已有解析。
3. 助手读取这一篇原文，按 [精读标准](docs/精读标准.md)逐节核验，生成 JSON / Markdown。也可直接告诉助手：“精读我刚导入的《论文标题》，不要自测，按单篇精读标准生成解析并导入阅读器。”
4. 在目标论文的左栏工具栏点击“导入解析”，选择生成的 `.json` / `.md`，或由助手调用本机导入 API。解析页码必须处于该 PDF 的有效范围。只有确认导入成功后，解析才会出现在左侧。

“精读任务”现在可选“助手任务”和“API 精读”。默认的助手模式仍然免费；API 模式会在确认费用后生成分阶段的单篇精读草稿，完成后先预览，再明确确认追加到解析。上传论文、打开任务、估算费用均不调用收费接口，不会自动覆盖已有解析。API 草稿不等于已核验的精读，格式校验或长篇输出不能保证内容正确。

### API 精读

在“精读任务 → API 精读”中选择已绑定 Key 对应的 DeepSeek Flash / V4 Pro、推理强度和阅读重点，查看请求阶段、预计费用和保守费用上限。默认 Flash、关闭推理，单次预算 2 元；点击“生成草稿”后还需确认调用。精读与翻译共用 API Key、真实账户余额查询及本程序累计支出上限，所有费用统一记账；有 API 任务进行中时不能更换绑定。同一篇论文不能同时运行翻译与精读。

单篇流程为“全文索引与研究问题 → 每批最多 3 页/约 18000 字符的逐节详解 → 全文综合与证据审查”。初始索引和最终审查读取全文；详解带有索引上下文，避免把整篇论文压成一段摘要。精读标准、页码约束、模型和推理强度冻结在估算单内，单次及累计预算不足时不派发；估算单有效 15 分钟，论文或提示发生变化后必须重估。后端使用 JSON 输出模式，校验文档结构、页码、类型、最低篇幅并排除自测；这些检查不替代学术内容核验。

索引阶段只生成两条导航和研究问题笔记，具体推导留给逐节详解。关闭推理时，索引/详解/综合审查的输出上限分别为 8192/16384/12288 token；开启低/高/最高推理时，每阶段分别为 32768/65536/131072 token，包含推理和最终 JSON，并非两份独立额度。估算显示每阶段上限，费用按最大输出保守预留、按返回的实际用量记账；提高上限不代表必然用完，但会提高确认前的费用预留。上限策略变化会使旧估算失效，须重新估算、确认预算，程序不会自动降低推理或提高预算。关闭/低/高与最高推理的单次请求超时分别为 180/300/600 秒。

若返回 `finish_reason=length`，任务停止且不自动重试，保留此前有效草稿并记录本次用量；界面显示失败阶段、输出量和上限，零条有效草稿时明确提示。诊断只保存 token 数和结果长度，不保存模型推理正文。旧版失败记录可从原有用量账本显示阶段与总输出量，不推测无法追溯的推理 token 数。输出上限仍然有限，不能保证任意论文和推理强度都不会截断。

API 有时会在 JSON 字符串内直接写入 Markdown 换行或制表符。阅读器使用标准 JSON 解码器兼容这类空白并记录 `json_string_whitespace` 诊断，不猜测缺失括号、不替换公式反斜杠、不修补未知转义。页码、每条至少 200 字符、字段类型及禁用自测等检查保持不变；退格、换页等异常控制字符仍拒绝，避免错误的 LaTeX 转义被默默接收。提示词也明确要求换行及 LaTeX 的 JSON 转义。

校验失败会显示具体阶段、解析条目和字段/错误位置，保存 API 的最终正文，可通过“下载未通过结果”查看；不保存推理正文，不把无效结果导入解析。旧版本未保留的被拒绝正文无法事后恢复。删除文献时关联的被拒绝正文一并清除。

当前 API 模式发送的是提取的 PDF 文本与阅读重点，不上传密钥给其他服务、不调用联网检索，也没有自动视觉识图。所有生成笔记标注“API 精读草稿，尚未人工核验”；图表数值、复杂公式、双栏顺序或缺失证据必须人工对照原文，不声称已复现或完成视觉核验。单篇最多 80 页、提取文本最多 400000 UTF-8 字节；无足够可提取文字的页面需先 OCR 或改用助手阅读。

后台进度及每阶段草稿持久保存，可关闭窗口后重新打开查看生成记录。停止只阻止后续阶段，正在执行的请求仍可能收费；截断、格式错误、网络异常或重启不自动重试。已返回有效用量的失败按实际用量记账，用量不确定时按该次保守上限记账；保留之前已完成的草稿，可导出 JSON / Markdown。重新生成是新的收费任务，不自动复用未完成任务。完整草稿必须经“追加到解析 → 确认追加”才写入文献，重复确认同一份草稿不会重复追加，原解析、完成状态和元信息不变。删除文献会清除关联草稿和源文计划，但不会清零费用记录。

API 精读接口（本机 `/api/docs` 可直接调试）：

| 方法与路径 | 用途 |
|---|---|
| `POST /api/papers/{id}/reading/estimate` | `{"model":"deepseek-flash","reasoning_effort":"none","focus":"推导与实验"}`，仅本地估算 |
| `GET /api/papers/{id}/reading/jobs` | 最近 20 份草稿记录及共享费用设置 |
| `POST /api/papers/{id}/reading/jobs` | `{"quote_id":"...","max_cost_cny":2}`，确认并派发；同一估算单幂等 |
| `GET /api/reading/jobs/{job_id}` | 阶段进度、错误及已完成草稿 |
| `POST /api/reading/jobs/{job_id}/cancel` | 停止后续阶段 |
| `POST /api/reading/jobs/{job_id}/import` | 完整草稿幂等追加，不覆盖现有解析 |
| `GET /api/reading/jobs/{job_id}/export?format=json` | 导出可导入 JSON；也支持 `format=markdown`，未完成草稿可导出 |
| `GET /api/reading/jobs/{job_id}/rejected-output` | 下载未通过结果的最终正文（纯文本），不包含推理内容 |

### 导入元数据

选择文件后，程序在本机读取 PDF 文档信息和 XMP（包括 Dublin Core、PRISM 中的标题、完整作者列表、期刊名、卷期、页码、出版日期与 DOI）。信息缺失时会尝试首页标题、期刊页眉和 DOI，并明确提示候选信息；仍不能识别的字段留空，标题最后才退回文件名。PDF 的创建日期、修改日期不会直接当成出版年份。扫描件尚不支持 OCR，首页识别不能保证适用所有排版。

元数据预览不建立文献记录，临时副本读取后立即删除，也不调用 DeepSeek。识别异步完成时不会覆盖用户已修改的字段。导入时保存的是最终确认的字段，包括手工清空的作者、出版信息或年份；原有分类选择仍然有效。

若本地信息不完整，可在 DOI 旁点击查询图标，从 [Crossref 公开 REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)补全。此操作仅在用户点击时联网，只向固定的 `api.crossref.org` 发送 DOI，不上传 PDF、全文或 DeepSeek 密钥，不使用大模型余额。未找到、网络超时或记录不匹配时保留当前内容，不自动重试；也不会覆盖查询期间的人工编辑。无 DOI 或无法联网时仍可手工填写并导入。

DOI 会和其他文献信息一起存入本地数据库，可在“文献信息”中修改，并随解析 JSON / Markdown 元信息导入导出。旧文献不会被批量重写，升级只补一个默认为空的 DOI 字段。

元数据 API：

| 方法与路径 | 用途 |
|---|---|
| `POST /api/papers/metadata` | multipart 字段 `file`，只预览本地 PDF 元数据、来源、警告及页数，不导入 |
| `POST /api/metadata/doi` | JSON `{"doi":"10.xxxx/xxxxx"}`，显式请求 Crossref 补全 |

`POST /api/papers` 不提供元信息时同样会本地识别；仍兼容旧的 `title`、`short_title` 表单字段。新客户端可用 multipart `metadata` 字段提交 JSON（符合 `MetadataPatch`），覆盖自动识别值；字段显式置空或 `year: null` 会保留清空结果。优先级为 `metadata` JSON、旧表单字段、本地识别结果。非法 JSON、无效 DOI 或越界年份会整体拒绝，不注册文献或残留上传副本。

导入默认追加。选择替换会替换该论文当前的解析；确认前可先导出备份。导入会先整体验证，某条数据有误不会只导入一半或先清空旧解析。

默认阅读与解析管理不调用大模型。左栏新增“译文”视图，确认翻译范围和费用后才调用 DeepSeek；也可继续让助手生成解析后导入，或由自己的程序调用 API 写入。

### 精读深度

每篇须讲清研究问题与贡献、系统模型与假设、关键符号和公式推导、算法的实际执行过程、理论保证的条件、核心图表和实验设置、局限与复现障碍；结合用户研究方向时单独标记延伸设想。关键判断附 PDF 页码及公式/图表编号，区分作者结论与解读者推断，未核验处如实标注。没有自测，不把每项一两句的提纲称为精读。测量型、系统型、理论型论文按实际内容调整，具体要求保存在 `docs/精读标准.md`，也会完整写入每份精读任务。

原始阅读笔记文件作为历史资料保留，不因本次调整删除；种子生成脚本不再把其中的自测写入阅读器。旧数据库可运行 `python -m scripts.upgrade_reading_notes` 预览、加 `--apply` 执行迁移。迁移前会把受影响文献的全部解析备份为可导入 JSON 到 `data/backups/`，仅标记未被修改的原始导读，不覆盖用户编辑。

## 文献分类

- 左侧文献库新增分类目录，初始文献和没有自建分类的文献均显示在“默认分类”；“全部文献”始终包含文献库中的所有论文。
- 点击分类标题旁的文件夹加号可新建分类。分类可重命名、删除，同名分类会被拒绝；默认分类不能重命名或删除。
- 点击文献条目右侧的归类图标，可勾选一个或多个分类。取消全部自建分类后自动回到默认分类；分类与原有主题标签互不影响。
- 选中一个自建分类后，点击文献列表上方“管理分类文献”图标，可从现有文献中批量勾选加入或取消勾选移除。此操作仅改变该分类，不清除文献的其他分类。
- 导入 PDF 时可以直接选择分类，也可在导入窗口中临时新建分类。当前正在查看自建分类时，导入窗口默认勾选该分类；在默认分类或全部文献中导入则默认不勾选自建分类。
- 从分类移除文献、删除分类都不会删除 PDF、解析、译文或阅读进度。仅“删除文献及全部解析”才会删除论文记录，分类功能不会触发模型调用。

分类持久化保存在原有 SQLite 数据库中的 `categories`、`paper_categories` 表，升级只新增表，不改动现有文献和笔记。论文响应增加 `category_ids` 数组：空数组表示默认分类，自建分类使用真实 ID。解析导入导出仍专注于论文信息与笔记，不会覆盖分类关系。

分类 API：

| 方法与路径 | 用途 |
|---|---|
| `GET /api/categories` | 列出默认分类、自建分类及各自的文献数量 |
| `POST /api/categories` | 新建分类，JSON `{"name":"研究一"}` |
| `PATCH /api/categories/{id}` | 重命名，JSON `{"name":"新名称"}` |
| `DELETE /api/categories/{id}` | 删除自建分类，保留所有文献及其他分类关系 |
| `PUT /api/papers/{id}/categories` | 设置单篇文献的全部分类，JSON `{"category_ids":["分类ID"]}`；传空数组返回默认分类 |
| `PUT /api/categories/{id}/papers` | 设置该自建分类的文献集合，JSON `{"paper_ids":["文献ID"]}`；不修改其他分类 |

`POST /api/papers` 的 multipart 上传也支持重复的 `category_ids` 字段，每个字段一个分类 ID；不提供该字段即进入默认分类。上传或更新时会先验证所有 ID，分类或文献不存在时拒绝整个操作，不会导入一半或残留无效 PDF 副本。

## DeepSeek 论文翻译

在左栏选择“译文”，右侧 PDF 与左侧中文译文使用同一页码。可翻译当前页、指定范围或整篇论文，也可以展开“原文文本”查看提取的文字，并导出已完成页的中英对照 Markdown。

译文工具栏的循环箭头为“重新翻译当前页”，始终可直接打开当前页的费用确认窗口，固定范围为这一页且忽略缓存；确认后才重新收费。成功并返回可靠段落锚点后替换当前模型/推理强度的缓存，失败保留旧译文，不自动重试。

新译文按原文块生成 Markdown 标题、段落、列表及公式，并保存稳定的原文锚点。鼠标悬停或键盘聚焦译文段落时，右侧对应原文会高亮；定位图标可固定高亮，手机上点击会切换到原文。翻页、切换模型或论文时清除旧高亮，缩放与调整栏宽后重新计算位置。定位使用 PDF.js 文字层，关闭文字选择仍可高亮；不可靠的匹配只提示无法精确定位，不猜测位置。复杂分栏、图表、公式和扫描页可能无法精确匹配；这不是版面重建或 OCR。

当前使用第二版自然段识别：本地读取 PDF 文字坐标，结合首行缩进、行距、字号、空行和分栏位置确定段落，不再按 12 行、1100 字符或句号强行截断。摘要标签与摘要正文、首字下沉与后续正文会保持在同一段；翻译提示明确要求一个原文自然段对应一个译文段落，不额外调用段落识别大模型。版面坐标无法可靠对应原文时退回空行/独立标题分段，保留全部原文。仍按页翻译，跨页段落不会自动合并；复杂公式和跨栏浮动图表可能需要核对。

已有付费缓存不会自动重译。无段落锚点的旧译文标为“整页对照”，悬停仅标示整页范围；“更新对照”会打开当前页的重新翻译费用确认窗口。只有确认后才收费，成功返回完整段落锚点才替换旧译文；失败、截断或锚点不全时保留原缓存，并按实际返回用量或不确定请求的预留上限记账，不自动重试。默认翻译继续优先使用缓存。浏览译文及悬停高亮完全本地运行，不调用 DeepSeek。

第一版带锚点的译文也会原样保留，并继续使用原来的锚点高亮，标为“旧版分段”；可手动“更新对照”切换到自然段识别，更新前仍需确认费用。段落算法、实际发送内容或系统提示发生变化时，旧费用估算单会失效，必须重新估算后才能启动，避免按旧上限发送新请求。

翻译界面及费用确认窗口均可选择 `deepseek-flash` / `deepseek-v4-pro`，推理强度提供关闭、低、高、最高（`none` / `low` / `high` / `max`），会记住本浏览器的选择。默认仍为 Flash、关闭推理。每页只发送提取的文字；扫描 PDF 需要先做 OCR。机器翻译保留页边界，复杂表格与公式仍应核对右侧原 PDF。

- 默认单次预算为 0.50 元，本机累计预算为 5 元，可在费用确认窗口和翻译设置中调整。
- 估算和读取译文免费；缓存按论文、页码、原文内容指纹、模型和推理强度分别保存。切回已有配置直接读取对应译文，旧版 Flash 非思考译文自动保留。
- 开启推理后，推理 token 计入输出费用与输出上限；强度越高，预留的输出预算越大。切换配置会重新估算，最终请求使用估算单中固定的配置。
- 任务按页串行处理，使用输出 token 上限，并在开始前预留整批保守费用上限；预算不足时不会开始。
- “停止后续页”会保留已经完成的内容；正在调用的一页仍可能计费。
- 不自动重试收费请求。超时、中断或缺少用量时，按该页预留上限保守记账，保留提示供核对官方账单。
- 本机费用不会因删除论文而清零，也不包含此 Key 在其他程序中的使用。服务重启不会自动继续未完成任务，已缓存页可跳过后继续翻译。

价格按 [DeepSeek 官方人民币高峰价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)保守计算，核对日期为 2026-10-22：Flash 每百万输入 token 为 2 元、输入缓存命中为 0.04 元、输出为 8 元；V4 Pro 分别为 9 元、0.30 元、27 元。实际账单可能因空闲时段折扣而更低；价格变化后需要更新后端价格常量。

页面右上角“设置”可绑定、更换或解除 DeepSeek API Key。点击“验证并绑定”时，后端先查询官方账户余额；验证成功后才保存，验证失败会保留原绑定。翻译或精读 API 任务进行中不能更换绑定，防止同一任务跨账户扣费。

Windows 下，密钥使用当前用户的 DPAPI 加密，保存在 `data/translation.local.json`，不进入前端构建、接口响应或导出文件；设置只显示末四位。界面绑定的密钥优先；尚未配置本机绑定时支持后端环境变量 `DEEPSEEK_API_KEY`。主动解除绑定后不会自动恢复环境变量中的旧 Key。将程序迁移到另一用户或机器时，请重新配置密钥。

“API 账户余额”来自 [DeepSeek 官方余额接口](https://api-docs.deepseek.com/api/get-user-balance/)，包含当前 Key 所属账户可用的充值余额和赠送余额，并保留官方返回的 CNY / USD 币种。成功结果缓存 30 秒，点击刷新按钮可立即重新查询；查询失败显示“暂不可用”，不会用本机预算或 0 元替代。

翻译确认窗口已使用真实 API 账户余额。原有本程序累计支出上限可在“设置 → 费用控制”中调整，它用于限制本程序的累计支出，与账户余额分别计算。更换 Key 后，旧的付费估算单需要重新估算；已有缓存译文仍可直接读取。

翻译 API 已纳入 `/api/docs`：

| 方法与路径 | 用途 |
|---|---|
| `GET /api/translation/settings` | 配置状态、价格、累计预算和本机用量，不返回密钥 |
| `PATCH /api/translation/settings` | 更新 `api_key` 或 `total_budget_cny` |
| `GET /api/translation/balance?refresh=false` | 查询当前绑定账户的官方余额；`refresh=true` 立即刷新 |
| `GET /api/papers/{id}/translations` | 已翻译页和最近任务 |
| `GET /api/papers/{id}/translations/pages/{page}` | 本页文字及缓存译文，不收费 |
| `POST /api/papers/{id}/translations/estimate` | 提交 `{"pages":[1,2]}` 获取 15 分钟有效的估算单 |
| `POST /api/papers/{id}/translations` | 提交 `quote_id`、`max_cost_cny`，返回后台任务；同一估算单重复提交返回同一任务 |
| `GET /api/translation/jobs/{job_id}` | 查看状态、完成页数和费用 |
| `POST /api/translation/jobs/{job_id}/cancel` | 停止后续页 |
| `GET /api/papers/{id}/translations/export` | 导出已完成页的中英对照 Markdown |

从自己的程序调用时，先估算，再提交任务，最后轮询状态。可参考 `examples/translate_pages.py`；该示例默认只估算，必须显式加 `--run` 才会产生翻译调用。

页接口增加 `source_blocks: [{id, source_text}]`、`alignment: "blocks" | "page"` 和 `segments: [{id, source_text, content}]`。只有译文包含全部、同序、非空且与当前原文匹配的锚点时，才返回段落级 `segments`；旧译文或无效锚点返回整页模式。原始锚点随 Markdown 缓存保存，对外 `translation.content` 和 Markdown 导出会移除内部标记。费用估算将锚点与结构化提示词的开销计入上限。

`alignment_version` 为 `2` 时表示当前自然段锚点，`1` 表示兼容的旧分块锚点，`0` 表示无有效段落锚点。新版锚点前缀为 `p`，旧版 `s` 锚点的识别规则冻结保留，不改变已有译文的原文绑定关系或原文校验摘要。

估算接口可显式提交 `{"pages":[1],"refresh_cache":true}`，忽略所选页缓存并预留重新翻译费用；标志冻结在估算单中，仍需通过原任务启动接口及单次/累计预算校验。默认 `false`，仅估算或读取页面不会收费，重新翻译也不会清除历史费用记录。

估算请求可增加 `model` 和 `reasoning_effort`，例如 `{"pages":[1],"model":"deepseek-v4-pro","reasoning_effort":"high"}`。查询缓存汇总、本页译文和导出时，将同样的配置作为 URL 查询参数传入，例如 `?model=deepseek-v4-pro&reasoning_effort=high`；省略时兼容原有 Flash、关闭推理的配置。

## JSON 接口格式

可以从 `examples/解析导入示例.json` 开始。最小文档如下：

```json
{
  "schema_version": 1,
  "notes": [
    {
      "title": "研究问题",
      "page_start": 1,
      "page_end": 1,
      "kind": "concept",
      "content": "这篇论文要解决的问题是……\n\n$$T=T_l+D/B+T_c$$",
      "sort_order": 0,
      "completed": false
    }
  ]
}
```

新解析的 `kind` 使用：`guide` 导读、`concept` 概念、`method` 方法、`experiment` 实验、`critique` 评读、`note` 笔记。`exercise` 仅作为旧文件兼容值保留，编辑器不再提供新增入口，新的精读稿不得使用。新增笔记的 ID 由服务器生成，不必自己填写。

支持可选的 `paper` 元信息字段；导入时会同步更新其中提供的标题、作者等信息。不想变更目标论文的信息时，请省略 `paper` 字段。也可以单独使用论文元信息 PATCH 接口更新。导出再导入会创建新的笔记记录，服务端生成 ID。

## Markdown 接口格式

使用二级标题标注页码：

```markdown
## [p. 1] 研究问题

这一节的解析正文。

## [p. 3-5] 系统模型

这里写公式、假设和自己的理解。

$$T=T_l+D/B+T_c$$
```

没有页码标题的 Markdown 将作为一条第 1 页笔记导入。程序导出的 Markdown 包含用于保留类型和完成状态的元数据注释；保留这些注释可以更完整地往返导入导出。普通手写 Markdown 不要求这些注释。

## REST API

服务启动后打开 `/api/docs` 可直接查看和调试完整接口；OpenAPI 规范位于 `/api/openapi.json`。所有地址相对于本地服务根路径。

| 方法与路径 | 用途 |
|---|---|
| `GET /api/health` | 服务状态 |
| `GET /api/papers` | 列出论文、元信息与阅读进度 |
| `POST /api/papers` | multipart 上传 PDF，字段 `file`，可选 `title`、`short_title` |
| `GET /api/papers/{id}` | 论文详情和全部解析 |
| `GET /api/papers/{id}/reading-task` | 准备单篇精读任务；可选 `focus`（最多 2000 字符）、`format=json\|markdown`，不调用外部 API |
| `PATCH /api/papers/{id}` | 更新标题、作者、期刊、年份、标签和状态 |
| `DELETE /api/papers/{id}` | 从论文库删除论文记录及其解析 |
| `GET /api/papers/{id}/pdf` | 获取原文，支持 PDF.js 读取 |
| `PATCH /api/papers/{id}/progress` | 保存 `page`、`zoom`、`active_note_id` 或 `status` |
| `POST /api/papers/{id}/notes` | 新增解析 |
| `PUT /api/papers/{id}/notes/{note_id}` | 更新解析或完成状态 |
| `DELETE /api/papers/{id}/notes/{note_id}` | 删除解析 |
| `POST /api/papers/{id}/import` | multipart 导入，字段 `file` 和 `mode=append/replace` |
| `GET /api/papers/{id}/export?format=json` | 导出 JSON |
| `GET /api/papers/{id}/export?format=markdown` | 导出 Markdown |

例如，从另一个 Python 程序添加解析：

```python
import json
from urllib.request import Request, urlopen

base = "http://127.0.0.1:8765"
note = {
    "title": "我的补充理解",
    "page_start": 1,
    "page_end": 1,
    "kind": "note",
    "content": "需要进一步核对的假设……",
}
request = Request(
    f"{base}/api/papers/PAPER_ID/notes",
    data=json.dumps(note).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request) as response:
    print(json.load(response))
```

上传示例，PowerShell 使用 `curl.exe` 避免命令别名差异：

```powershell
curl.exe -X POST http://127.0.0.1:8765/api/papers -F "file=@D:/papers/new-paper.pdf" -F "title=新论文"
curl.exe -X POST http://127.0.0.1:8765/api/papers/PAPER_ID/import -F "file=@D:/papers/notes.json" -F "mode=append"
```

接口返回的 `id` 才是后续调用使用的论文 ID。接口校验与错误详情以当前 OpenAPI 文档为准。

## 数据位置和备份

- `data/papers.sqlite3`：论文元信息、解析、阅读进度及删除记录；`data/uploads/` 保存上传的 PDF。
- `data/` 下的日志与 `server.json`：服务日志和启动状态。
- `data/seed.json`：可选的本机初始数据，不随仓库发布；没有该文件时正常以空库启动。已有安装重启不会覆盖数据库中的编辑。
- `frontend/dist/`：已经构建好的离线前端、PDF.js 附属资源和 API 文档资源。
- `examples/`：后续导入的 JSON、Markdown 模板。

通过界面上传的 PDF 保存在程序管理的数据目录内。可选本机种子若引用外部 PDF，删除论文库记录不会删除这些外部原文件；源码不依赖某个固定磁盘目录。

完整备份请先停止服务，再备份 `data/` 和仍被引用的原 PDF 文件。单篇 JSON/Markdown 导出仅包含解析与元信息，不包含 PDF 本身。迁移到其他目录时也需要保证初始论文的原文路径可用。

服务默认仅监听 `127.0.0.1`，定位为单机阅读工具。API 没有多人账号隔离；并发编辑同一条笔记采用最后保存的版本。

## 上传与隐私

`.gitignore` 排除整个 `data/`、`tmp/`、PDF、环境配置、密钥文件、虚拟环境、依赖目录及构建产物。请勿用 `git add -f` 把这些个人资料加入仓库。备份阅读资料应单独进行，GitHub 源码仓库不等于文献库备份。

普通阅读、编辑及估算在本地运行；明确确认 API 翻译或精读后，会把所选论文的提取文本发送给 DeepSeek。DOI 出版信息查询会访问 Crossref。API 价格和模型支持可能变化，使用前应核对官方说明；本程序的费用账本不是官方账单。

本工具没有公网服务所需的用户认证、权限隔离和部署加固，不要直接暴露到公网。Windows 绑定的 Key 受当前用户 DPAPI 保护，迁移机器后需要重新绑定。

## 开发和测试

后端：

```powershell
./.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m pytest backend/tests
```

前端在 `frontend/` 中运行 `pnpm dev`，通过 Vite 将 `/api` 代理到 8765 端口；生产构建运行 `pnpm build`。API 文档和 PDF.js 的 cMaps、标准字体、WASM 在构建前自动复制到前端资源目录。

前端原文匹配单元测试在 `frontend/` 中运行 `pnpm test`（Node.js 22.18+）；覆盖连字、断词、分栏顺序、歧义匹配与字符偏移。

`scripts/build_seed.py` 是原始个人资料的迁移工具，需要自行准备其指定目录结构，并非安装必需步骤。它只生成本机初始 JSON，不修改原 PDF；已有数据库不会被种子覆盖。历史浏览器冒烟脚本也需要相应本机资料；常规自动测试请使用 `backend/tests` 和 `frontend/tests`。

使用 `PAPER_READER_DATA_DIR` 环境变量可给测试或另一套论文库指定独立数据目录，避免影响日常阅读记录。
