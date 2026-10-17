# QwenSci × PhAI 风格产品化网页设计与实现方案

**版本**：v1.0  
**日期**：2026-10-16  
**适用项目**：`WebApp-V2`（React + TypeScript + Vite）与 `src/webapp`（FastAPI）  
**交付内容**：产品官网、QwenSci 交互式产品预览、真实科研工作台入口，以及实现所需的前端、后端、数据和运行能力说明

## 阅读方式

本文分为两部分。第一部分定义产品叙事、信息架构、视觉系统和交互规则；第二部分把设计拆成文件、组件、接口、任务队列、数据模型和验收项。文中“现有能力”只指仓库中已经存在并有测试或实现支撑的能力；“待新增”指需要代码、数据或运行基础设施补齐的能力。

参考方向：

- PhAI 首页与产品页：<https://phai-labs.com/>、<https://phai-labs.com/products/>
- 本仓库现有前端：`WebApp-V2/src/App.tsx`、`WebApp-V2/src/api.ts`、`WebApp-V2/app/styles.css`、`WebApp-V2/src/workspace.css`
- 本仓库现有控制面：`src/webapp/api.py`、`src/webapp/schemas.py`、`src/webapp/run_service.py`
- 已加载的本地设计技能：`ui-ux-pro-max`、`impeccable`、`frontend-design`、`design-taste-frontend`、`extract-design-system`

# 第一部分：网页设计方案

## 1. 产品定位

QwenSci 应被呈现为“有证据边界的科研操作系统”，而不是泛化的聊天机器人或单一写作工具。官网负责解释研究闭环，产品页负责让访客看到真实工作台，`/app` 负责进入可恢复、可审计、可授权的研究运行。

核心承诺是：

> 从科学问题开始，沿着证据、模型、实验和写作走到可交付成果；每一步都能追溯、暂停、审阅和恢复。

主要受众分为三类：

| 受众 | 进入动机 | 首屏需要看到的证据 |
| --- | --- | --- |
| 研究者 | 把一个课题推进到综述、实验设计或论文草稿 | 阶段状态、材料边界、成果索引 |
| 课题组/实验室 | 统一研究流程、降低重复整理和交接成本 | 可恢复运行、日志、权限、可审计动作 |
| 方法与平台负责人 | 把模型调用放进安全、可验证的科学流程 | API 契约、人工批准、证据来源和失败处理 |

产品官网的主 CTA 是“打开 QwenSci 预览”，工作台的主 CTA 是“启动研究”。两个入口都指向真实产品能力，营销页面不能用虚构的实时状态冒充运行中的后端。

## 2. PhAI 参考拆解与转译原则

### 2.1 保留的视觉结构

PhAI 的有效之处在于它把研究机构做成了一个有叙事节奏的产品页面：顶部导航很轻，首屏用大号衬线标题建立立场，黑色背景让蓝紫色科研图形成为焦点，琥珀色 CTA 给出明确行动，随后用线性研究路径解释能力来源。

QwenSci 采用同一套节奏，但把“研究机构的抽象能力”换成“可进入的科研工作台”：

1. 黑色底层承载长期研究与证据的语气。
2. 靛蓝轨道、粒子和路径表示模型、工具与数据之间的关系。
3. 琥珀色只承担启动、确认和继续三个高价值动作。
4. 细弱分隔线把页面分成章节，而不是把所有内容切成同规格卡片。
5. 产品预览直接展示 QwenSci 的真实阶段、材料和成果结构。

### 2.2 需要避免的复制

QwenSci 不应复制 PhAI 的品牌标识、文案或图形资产。轨道球体、星点和蓝色光晕只作为“证据流”和“研究系统入口”的抽象视觉；可用已有代表性研究产物作为产品内容，而不是把外部网站的图片当作产品截图。

页面也不采用通用 SaaS 的浅色大圆角卡片、紫蓝渐变、三列功能卡和假数据仪表盘。所有状态都要标明是示例、代表性成果或真实运行，避免混淆。

## 3. 当前 QwenSci 界面问题

`WebApp-V2` 目前优先解决了科研运行控制，但它的视觉和信息架构仍然是内部控制台：浅蓝背景、白色卡片、圆角面板、顶部控制导航和较密集的状态信息都适合已有用户，却不能承担面向新用户的产品叙事。

需要解决的具体问题：

- 首屏直接进入控制台，访客看不到产品定位、研究闭环和六类入口。
- `App.tsx` 将运行列表、研究编排、量化审阅、材料和产物全部组合在一个工作台，营销页面无法复用其中的独立产品能力。
- 当前已有 `representative` 数据和真实产物预览，但缺少一个明确的“QwenSci 产品预览”层来承接产品介绍。
- 轻度研究、绘图、润色、翻译和研究偏好没有独立的入口、状态模型或结果交付协议。
- 现有状态文字较多，缺少面向公众的简短副标题、证据说明和下一步动作。

## 4. 首页信息架构

首页使用“研究命题 → 研究闭环 → 产品入口 → 可操作预览 → 可信证据 → 进入工作台”的单向叙事。

```text
/
├── Hero：把科研流程变成可恢复的研究系统
├── Research loop：问题 → 证据 → 模型 → 实验 → 写作
├── Products：六类产品能力
├── QwenSci product preview：可点击的代表性运行预览
├── Evidence and trust：真实 API、审阅节点、产物和日志
├── Nature skill workflow map：能力与现有科研工作流的映射
├── CTA：打开预览 / 启动研究
└── Footer：文档、API、运行边界和版本信息
```

### 4.1 Hero

推荐文案：

- 眉题：`QWENSCI / EVIDENCE-BOUND RESEARCH SYSTEM`
- 主标题：`让每一个科学问题，都有一条可追溯的路径`
- 说明：`从课题、材料和文献开始，进入综述、Idea、实验设计与写作；每个阶段都能审阅、暂停和恢复。`
- 主 CTA：`打开 QwenSci 预览`
- 次 CTA：`查看研究闭环`

右侧显示 `QwenOrbitVisual`：一个由 Qwen 标记、三条轨道和少量粒子组成的静态或低速运动视觉。左侧标题保持两行以内，右侧视觉不承担文字信息。

### 4.2 Research loop

用一条横向路径替代三列功能卡：

```text
[科学问题] ── [证据登记] ── [模型与工具] ── [实验与审阅] ── [论文成果]
     ↓              ↓                ↓                ↓
   topic          materials        actions          artifacts
```

每个节点都显示一个真实的产品字段：课题、材料 scope、受控 action、artifact stage。滚动到节点时只改变线条和节点亮度，不让页面变成动画演示。

### 4.3 Products

六个入口采用纵向章节布局，每章由左侧能力标题、中央一句判断、右侧一个状态或成果片段组成。入口名称保持用户语言：

1. **全流程科研**：从课题到 Author 的完整研究运行。
2. **轻度研究**：只推进 Survey 或 Survey + Idea，适合快速判断方向。
3. **科研绘图**：从数据、脚本和图表意图生成论文级图形及可编辑源文件。
4. **语言润色**：保留证据边界的段落级修订和导出。
5. **论文翻译**：保留图、表、公式和页级结构的双语交付。
6. **研究偏好**：保存语言、学科、期刊、引用、模型、隐私和网络权限。

每章都必须有明确的“当前可用 / 需要接入 / 设计中”状态，避免把 skill 说明误写成已经上线的产品功能。

### 4.4 QwenSci 产品预览

产品预览不是 GIF 或假仪表盘，而是一个可点击的“公开样本运行”：

- 左侧：六类入口切换。
- 中央：阶段时间线、当前节点、下一步动作。
- 右侧：材料、证据、产物或结果片段。
- 底部：`查看真实工作台`、`复制预览课题`、`查看 API 约束`。

预览默认读取 `GET /api/representative` 的代表性项目；如果服务端不可用，展示明确的静态说明“这是产品结构预览”，不显示运行中、完成百分比或伪造的在线状态。点击某个入口后，预览可以切换到预置的静态 fixture；进入工作台时再切换到真实 `run_id`。

建议的六个预览状态：

| 入口 | 预览内容 | 点击后的真实动作 |
| --- | --- | --- |
| 全流程科研 | Survey → Idea → ExperimentDesign → Author 路径 | 跳转 `/app/full-research`，复用创建运行和动作 API |
| 轻度研究 | 只到 Survey 或 Idea 的短路径 | 跳转 `/app/light-research`，创建运行时传递终点 |
| 科研绘图 | 图形意图、数据文件、图像和源文件状态 | 跳转 `/app/figure`，提交绘图任务 |
| 语言润色 | 原文、修订 diff、风格和期刊配置 | 跳转 `/app/polish`，创建润色任务 |
| 论文翻译 | 页缩略图、双语文本、公式/图表保留状态 | 跳转 `/app/translate`，提交翻译任务 |
| 研究偏好 | 语言、学科、引用、模型和权限 | 跳转 `/app/preferences`，读取或保存偏好 |

## 5. 导航与路由

官网与工作台保持同一品牌，但通过路由和导航层级明确分开：

| 路由 | 页面角色 | 数据来源 |
| --- | --- | --- |
| `/` | 产品官网首页 | 产品 registry、代表性项目、静态叙事 |
| `/products` | 六类能力总览 | 产品 registry、能力状态 |
| `/products/qwensci` | QwenSci 产品介绍与可点击预览 | representative fixture、产品能力接口 |
| `/app` | 真实科研工作台入口 | health、runs、disciplines、SSE |
| `/app/full-research` | 全流程科研 | `/api/runs`、`/api/runs/{run_id}/actions` |
| `/app/light-research` | 轻度研究 | 同上，增加研究深度字段或终点参数 |
| `/app/figure` | 科研绘图 | 待新增 figure job API |
| `/app/polish` | 语言润色 | 待新增 polish job API |
| `/app/translate` | 论文翻译 | 待新增 translation job API |
| `/app/preferences` | 研究偏好 | 待新增 preferences API |

导航只保留三个全局动作：`Products`、`QwenSci preview`、`Open workspace`。进入工作台后才出现运行、流程、量化和成果导航。

## 6. 六类产品能力设计

### 6.1 全流程科研

定位：给需要完整推进课题的研究者使用，范围覆盖 Survey、Idea、ExperimentDesign 和 Author。

界面重点：顶部显示运行 ID 和持久化状态；中央时间线显示阶段、尝试次数、失败信息和下一步；右侧显示受控材料、证据和产物；任何高风险动作都先显示输入、来源和确认条件。

当前可复用：`POST /api/runs`、`GET /api/runs/{run_id}`、`POST /api/runs/{run_id}/materials`、`POST /api/runs/{run_id}/actions`、`GET /api/runs/{run_id}/events`、`GET /api/runs/{run_id}/logs`、`GET /api/runs/{run_id}/artifacts/{artifact_id}`。

### 6.2 轻度研究

定位：让用户在几分钟内获得结构化 Survey 或 Idea，而不要求立刻进入完整实验设计。

界面重点：减少配置项，只保留课题、学科、语言、材料和终点；结果页把“可继续的证据”和“尚未验证的空白”并列显示。

当前可以临时复用 `until=survey` 或 `until=idea`；产品化时新增 `research_depth: "light" | "full"`，由后端记录用户意图，避免前端把终点推断成产品类型。

### 6.3 科研绘图

定位：把数据、图表意图和论文规范连接成可审阅的图形产物。

界面重点：左侧是数据与变量，中央是图形草稿和统计说明，右侧是字体、颜色、图例、单位、导出格式和可访问性检查。结果必须区分 PNG/SVG/PDF 与可编辑的 Python/R 源文件。

当前状态：仓库有 `nature-figure`、`cumcm-paper-figures` 等技能参考和代表性图片资产，但没有明确的专用 Web API、任务队列或用户级产物模型；不能直接把技能存在写成产品已上线。

### 6.4 语言润色

定位：在不改变事实、数值、术语和证据边界的前提下，提供段落级修订、风格选择和导出。

界面重点：原文与修订并排；每段显示变更原因、保留的术语和需要作者确认的句子；目标期刊、中文/英文、语气和压缩强度在顶部设置；导出前显示修订统计与未解决标记。

当前状态：可参考 `nature-polishing` 和 `academic-humanizer`，但缺少文本/文档上传、差异存储、版本和 DOCX/PDF 导出 API。

### 6.5 论文翻译

定位：把论文 PDF 变成结构保真的中英文对照或中文阅读版。

界面重点：左侧页缩略图，中央双栏文本，右侧显示图、表、公式和 OCR 状态；每页标记是否为原生文本、OCR 文本或需要人工复核；下载前显示页数、语言和产物格式。

当前状态：可参考 `nature-reader`、`nature-paper-trans` 和 PDF 技能，但缺少 PDF 解析、OCR、版面结构、翻译任务状态和页级产物 API。

### 6.6 研究偏好

定位：把重复的研究设置保存为用户级或项目级偏好，减少每次启动运行的配置成本。

字段建议：语言、学科、目标期刊、引用风格、模型、输出格式、默认研究深度、网络访问、远程视觉分析、隐私策略和默认材料 scope。

当前状态：没有持久化接口；设计时先做表单和本地未保存态，正式产品必须增加认证、用户/项目边界和 `GET /api/preferences`、`PUT /api/preferences`。

## 7. 深色视觉系统

### 7.1 色彩 token

```css
:root {
  --color-bg: #0a0a0b;
  --color-surface: #101012;
  --color-surface-raised: #151518;
  --color-ink: #f0eee8;
  --color-ink-muted: rgba(240, 238, 232, .68);
  --color-ink-subtle: rgba(240, 238, 232, .44);
  --color-ink-faint: rgba(240, 238, 232, .26);
  --color-rule: rgba(240, 238, 232, .12);
  --color-rule-soft: rgba(240, 238, 232, .07);
  --color-primary: #9ba7ff;
  --color-primary-hover: #aab4ff;
  --color-primary-deep: #5d6bd6;
  --color-primary-ink: #3a45a8;
  --color-primary-glow: rgba(155, 167, 255, .20);
  --color-cta: #d29c52;
  --color-cta-hover: #e0ae66;
  --color-success: #5fd6a0;
  --color-warning: #d29c52;
  --color-danger: #f26b7a;
}
```

使用规则：背景和表面占绝大多数面积；靛蓝承担链接、焦点、研究路径和产品图形；琥珀只用于主 CTA、确认和少量关键状态；成功、警告、错误状态必须同时有文字或图标，不能只靠颜色。

### 7.2 字体与层级

| 用途 | 字体 | 建议规格 |
| --- | --- | --- |
| 英文大标题 | Plex Serif 或可授权的衬线替代 | 56–88 px，行高 0.98–1.08 |
| 中文大标题 | Noto Serif SC | 44–72 px，行高 1.12 |
| 正文与导航 | Plex Sans / Noto Sans SC | 15–18 px，行高 1.55–1.75 |
| 数据、运行 ID、API | Plex Mono / JetBrains Mono | 12–14 px，行高 1.4 |
| 眉题与标签 | Sans + 小号字距 | 11–12 px，避免连续大写堆叠 |

标题使用 sentence case，中文标题不强行加入英文全大写标签。所有正文文字保持左对齐，只有 Hero 的单句产品主张可以在宽屏上形成较宽的左栏。

### 7.3 网格、间距与形状

- 最大内容宽度：`1200px`；Hero 和产品预览可扩展到 `1440px`。
- 页面左右内边距：桌面 `clamp(24px, 5vw, 80px)`，移动端 `20px`。
- 基础间距：`4 / 8 / 12 / 20 / 32 / 48 / 72 / 120px`。
- 分隔线使用 `1px` 的 `--color-rule`；卡片只在需要承载交互状态时使用 `1px` 边框。
- 官网章节避免统一圆角；产品预览可使用 `12px`，工作台面板保持原有层级但改为近黑表面。
- 阴影优先使用表面和边框对比，不使用大面积柔和灰色投影。

### 7.4 响应式

| 断点 | 布局 |
| --- | --- |
| `< 640px` | Hero 单列；产品章节改为上下堆叠；预览右栏折叠为底部抽屉；轨道视觉减小并降低粒子数量 |
| `640–1023px` | 两列产品预览；研究闭环保持横向但允许换行；导航折叠为菜单 |
| `>= 1024px` | 12 列网格；Hero 左 5 列、右 7 列；产品章节使用 3 区结构；工作台恢复三栏 |

## 8. Qwen Logo 与右侧科研视觉

建议新增 `WebApp-V2/assets/qwen-mark.svg` 和 `WebApp-V2/src/components/QwenOrbitVisual.tsx`。使用已授权的 Qwen 标志或字形资产，不重新绘制可能产生品牌误差的商标。

视觉分三层：

1. 主标记：`opacity: .86`，作为焦点。
2. 轨道残影：`opacity: .28`，连接问题、证据和工具。
3. 环境粒子与外圈：`opacity: .08`，只提供空间感。

轨道可以用 SVG path 或 Canvas 绘制，运动速度保持低，默认不自动旋转；如果开启运动，只让轨道和少数粒子缓慢移动。`prefers-reduced-motion: reduce` 时保留静态轨道、去掉闪烁和自动播放。右侧视觉需要有可访问的文本替代：“QwenSci 研究闭环：问题、证据、模型、实验和成果沿轨道连接”。

## 9. 动效、交互与无障碍

动效只服务于方向感和状态反馈：

- 页面进入：标题和轨道从低透明度过渡，不使用大幅缩放。
- 滚动：研究路径按节点进入视口亮起；节点状态由文字同步说明。
- 预览切换：入口切换使用 180–240ms 的淡入和位移，保留键盘焦点。
- 工作台：SSE 更新时只更新对应阶段、事件和提示，不整页闪烁。
- 错误：说明发生了什么、下一步怎么修复，并保留可复制的技术详情。

无障碍验收：

- 所有按钮、入口、标签页和时间线节点可用键盘访问，焦点环使用 `--color-primary`。
- 正文和控件达到 WCAG AA 对比度；低透明度文字只用于辅助信息。
- 状态不能只靠颜色；必须有文本、图标或 `aria-live` 播报。
- 产品预览的动态区域有 `aria-selected`、`aria-controls` 和明确的 tab 顺序。
- 上传、解析、翻译和绘图任务分别有进行中、成功、失败和可重试状态。
- `prefers-reduced-motion`、窄屏和 200% 页面缩放都保持内容可读。

## 10. 内容文案建议

首页的文案要解释产品能做什么，不要用“重新定义”“下一代”“智能化赋能”等空泛表达。建议文案：

| 位置 | 文案 |
| --- | --- |
| Hero | `让每一个科学问题，都有一条可追溯的路径` |
| Research loop | `把问题、证据、模型、实验和写作放进同一条可恢复的运行` |
| 产品预览 | `先看研究怎样推进，再决定从哪里开始` |
| 证据区 | `每个结论都有来源，每个动作都有边界` |
| 工作台 CTA | `启动研究` |
| 轻度研究 CTA | `先做 Survey` |
| 绘图 CTA | `创建图形任务` |
| 润色 CTA | `比较修订` |
| 翻译 CTA | `上传论文` |
| 偏好 CTA | `保存研究设置` |

## 11. 官网与工作台的视觉衔接

官网使用更宽的留白、较少的状态字段和较大的衬线标题；工作台使用同一套深色 token、字体和分隔线，但把信息密度提高，把每个操作绑定到真实 API。

过渡规则：

- 官网的 `打开 QwenSci 预览` 进入 `/products/qwensci`，不直接创建运行。
- 预览中的 `进入真实工作台` 携带入口类型和可选的示例课题，打开 `/app/{module}`。
- 工作台顶部保留 QwenSci 标记和产品名称，去掉营销语句，直接显示运行和连接状态。
- 官网中的“代表性成果”只来自 `/api/representative` 或静态已标注样本；工作台成果只来自具体 `run_id` 的 artifact index。

## 12. Nature skill 能力映射

这些 skill 可作为产品流程、文案和验收标准的参考，但 skill 存在不等于 QwenSci 已提供对应 API。

| QwenSci 入口 | 可复用的科研工作流参考 | 需要在产品中落地的对象 |
| --- | --- | --- |
| 全流程科研 | `nature-writing`、`nature-academic-search`、`nature-paper-card`、`nature-reviewer` | 运行阶段、证据、审阅、作者交接 |
| 轻度研究 | `nature-paper-card`、`nature-academic-search`、`nature-social-science` | 短路径研究运行和缺口输出 |
| 科研绘图 | `nature-figure`、`cumcm-paper-figures` | 图形任务、数据、脚本、导出产物 |
| 语言润色 | `nature-polishing`、`academic-humanizer` | 段落 diff、术语锁定、版本和导出 |
| 论文翻译 | `nature-reader`、`nature-paper-trans`、`pdf` | PDF 页结构、OCR、双语和复核标记 |
| 研究偏好 | `nature-data`、`nature-experiment-log`、`nature-statistics` | 用户/项目偏好、隐私、数据和日志策略 |

# 第二部分：代码、接口与能力缺口

## 13. 代码仓库现状

当前可直接复用的前端入口：

- `WebApp-V2/src/App.tsx`：真实运行加载、运行选择、材料上传、动作提交、SSE 刷新和工作台组合。
- `WebApp-V2/src/api.ts`：同源 `/api` 请求封装、材料、产物和量化参数检索。
- `WebApp-V2/src/types.ts`：`ResearchRun`、`Artifact`、`RunEvent`、量化状态和动作契约。
- `WebApp-V2/src/components/ResearchComposer.tsx`：创建运行、学科解析、终点选择和材料草稿。
- `WebApp-V2/src/components/WorkflowTimeline.tsx`：阶段和事件流展示。
- `WebApp-V2/src/components/QuantitativeReviewWorkspace.tsx`：Q1/Q2 审批、计划和结果资格审查。
- `WebApp-V2/src/components/MaterialTray.tsx`、`ArtifactInspector.tsx`、`RunLogsPanel.tsx`：材料、产物和日志查看。

当前可直接复用的后端控制面：

- `GET /api/health`
- `GET /api/disciplines`、`POST /api/disciplines/resolve`
- `GET /api/runs`、`POST /api/runs`、`GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/materials`、`GET|DELETE /api/runs/{run_id}/materials/{material_id}`
- `POST /api/runs/{run_id}/actions`
- `GET /api/runs/{run_id}/events`（SSE）
- `GET /api/runs/{run_id}/logs`、`GET /api/runs/{run_id}/logs/{log_id}`
- `GET /api/runs/{run_id}/artifacts/{artifact_id}`
- `GET /api/representative`、`GET /api/representative/{project_id}/files/{file_id}`
- 量化参数检索、检索结果读取和来源选择接口

## 14. 建议新增与修改的文件

### 14.1 前端新增文件

```text
WebApp-V2/src/marketing/MarketingApp.tsx
WebApp-V2/src/marketing/marketing.css
WebApp-V2/src/marketing/content.ts
WebApp-V2/src/marketing/productRegistry.ts
WebApp-V2/src/components/QwenOrbitVisual.tsx
WebApp-V2/src/components/ResearchLoop.tsx
WebApp-V2/src/components/ProductModuleGrid.tsx
WebApp-V2/src/components/QwenSciPreview.tsx
WebApp-V2/src/components/CapabilityStatus.tsx
WebApp-V2/src/components/AccessibleTabs.tsx
WebApp-V2/src/app/AppShell.tsx
WebApp-V2/src/app/routes.tsx
WebApp-V2/src/app/moduleTypes.ts
WebApp-V2/src/modules/figure/FigureWorkspace.tsx
WebApp-V2/src/modules/polish/PolishWorkspace.tsx
WebApp-V2/src/modules/translate/TranslationWorkspace.tsx
WebApp-V2/src/modules/preferences/PreferencesWorkspace.tsx
WebApp-V2/src/styles/tokens.css
WebApp-V2/src/styles/marketing.css
WebApp-V2/src/styles/workspace-dark.css
WebApp-V2/src/assets/qwen-mark.svg
```

### 14.2 前端需要修改的文件

| 文件 | 修改目标 |
| --- | --- |
| `WebApp-V2/src/main.tsx` | 从单一 `App` 入口切换为路由或轻量 pathname dispatcher，保留同源部署 |
| `WebApp-V2/src/App.tsx` | 拆成 `WorkspaceApp`，只负责真实工作台，不再承载官网 Hero 和产品营销内容 |
| `WebApp-V2/src/api.ts` | 增加 product registry、figure、polish、translation、preferences 的请求封装；统一错误和取消请求 |
| `WebApp-V2/src/types.ts` | 增加模块状态、任务状态、偏好、文件产物、diff 和页面级翻译类型 |
| `WebApp-V2/app/styles.css` | 迁移或清理旧的浅色控制台 token，避免与新 token 冲突 |
| `WebApp-V2/src/workspace.css` | 使用深色工作台 token，保留信息密度但统一焦点、状态和响应式规则 |
| `WebApp-V2/vite.config.ts` | 检查多路由 history fallback、静态资源路径和构建输出 |
| `WebApp-V2/index.html` | 增加主题色、字体预加载、描述和 reduced-motion 兼容的基础 meta |
| `src/webapp/api.py` | 注册新增产品 registry、任务和偏好路由；继续保持同源托管 |
| `src/webapp/schemas.py` | 增加严格的请求/响应 schema，所有新增字段默认拒绝未知字段 |
| `WebApp-V2/README.md` | 补充官网、产品预览和各模块启动/能力边界说明 |

## 15. 产品 registry 与路由代码缺口

官网需要一个可审计的产品能力 registry，不能把组件名称散落在 JSX 中。建议先用静态版本，再切换为服务端版本：

```ts
export type ProductModuleId =
  | "full-research"
  | "light-research"
  | "figure"
  | "polish"
  | "translate"
  | "preferences";

export type CapabilityStatus = "available" | "partial" | "planned";

export interface ProductModule {
  id: ProductModuleId;
  title: string;
  summary: string;
  status: CapabilityStatus;
  previewRoute: string;
  workspaceRoute: string;
  evidence: string[];
}
```

路由层需要把产品页和工作台隔开：

```tsx
<Routes>
  <Route path="/" element={<MarketingApp />} />
  <Route path="/products" element={<ProductsPage />} />
  <Route path="/products/qwensci" element={<QwenSciPreview />} />
  <Route path="/app/*" element={<AppShell />} />
</Routes>
```

如果暂时不引入路由库，至少在 `main.tsx` 中使用 pathname 映射，并为未知路径提供可回到 `/` 或 `/app` 的错误页；不能让营销组件和工作台组件依赖同一个大组件状态。

## 16. 需要新增的 API

### 16.1 产品能力

```text
GET /api/product/modules
GET /api/product/capabilities
GET /api/product/preview/{module_id}
```

响应需要包含 `id`、`status`、`route`、`evidence`、`last_verified_at` 和 `data_source`。`data_source` 用于区分静态 registry、代表性项目和真实运行，禁止把静态 preview 标成 live。

### 16.2 研究深度

为轻度研究补充：

```text
POST /api/runs
  research_depth: "light" | "full"
  until: "survey" | "idea" | "exp_design" | "author"
```

服务端在 run metadata 中保存 `research_depth`，前端从返回的 `allowed_actions` 和 `stages` 判断能否继续，不自行推断。

### 16.3 科研绘图任务

```text
POST /api/figure/jobs
GET  /api/figure/jobs
GET  /api/figure/jobs/{job_id}
POST /api/figure/jobs/{job_id}/actions
GET  /api/figure/jobs/{job_id}/events
GET  /api/figure/jobs/{job_id}/artifacts/{artifact_id}
```

最小请求字段：数据文件、变量映射、图表类型、统计说明、目标期刊/模板、语言、导出格式。服务端需要校验 CSV/TSV/XLSX/Parquet 等格式、记录数据 hash、运行 Python/R worker，并登记 PNG、SVG、PDF、源代码和日志。

### 16.4 语言润色任务

```text
POST /api/polish/jobs
GET  /api/polish/jobs/{job_id}
GET  /api/polish/jobs/{job_id}/revisions
POST /api/polish/jobs/{job_id}/actions
GET  /api/polish/jobs/{job_id}/artifacts/{artifact_id}
```

任务需要保存原文快照、目标语言、期刊和风格、术语锁定表、段落级 diff、作者接受/拒绝记录和导出版本。模型输出不能覆盖原始文本，也不能把“建议”写成“已验证事实”。

### 16.5 论文翻译任务

```text
POST /api/translation/jobs
GET  /api/translation/jobs/{job_id}
GET  /api/translation/jobs/{job_id}/pages/{page_number}
POST /api/translation/jobs/{job_id}/actions
GET  /api/translation/jobs/{job_id}/artifacts/{artifact_id}
```

任务需要保存 PDF hash、页数、文本/OCR来源、图表和公式块、页级双语结构、人工复核状态和最终 PDF/Markdown/图片产物。扫描件必须显式标为 OCR，解析失败要给出页码和重试动作。

### 16.6 研究偏好

```text
GET /api/preferences?scope=user
PUT /api/preferences
GET /api/preferences/schema
```

```json
{
  "scope": "user",
  "language": "zh-CN",
  "disciplines": ["Materials Science"],
  "target_journal": "",
  "citation_style": "numeric",
  "model_profile": "balanced",
  "default_output": "markdown",
  "network_access": "ask",
  "remote_perception": false,
  "privacy_mode": "controlled-materials"
}
```

正式接口需要认证、用户或项目归属、版本号和并发更新策略；没有身份边界前，只能作为本地未保存表单。

## 17. 后端任务与数据模型缺口

### 17.1 任务队列与事件

绘图、润色和翻译都可能超过一次 HTTP 请求的生命周期。需要统一 `TaskRecord`：

```python
class TaskRecord(TypedDict):
    task_id: str
    kind: Literal["figure", "polish", "translation"]
    owner_id: str
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    progress: int | None
    input_artifacts: list[str]
    output_artifacts: list[str]
    error_code: str | None
    created_at: str
    updated_at: str
```

需要一个可持久化队列或 worker supervisor，支持重试、取消、幂等 key、事件追加和日志分片；前端使用 SSE 或轮询读取同一套状态。

### 17.2 文件处理

需要统一文件登记服务：文件大小、MIME、sha256、来源、敏感数据标记、解析器版本、保留期限和可下载权限。PDF、DOCX、XLSX、CSV、图像和源代码都要以 artifact 形式索引，不能把本地路径传给浏览器或模型。

### 17.3 模型调用与证据边界

需要按任务类型建立模型 profile、网络权限、提示词版本、输入快照、输出快照和人工确认节点。网络检索和远程视觉分析继续采用显式授权；润色和翻译需要保留原文与模型输出；绘图执行需要记录代码、依赖、数据 hash 和随机种子。

### 17.4 认证与权限

当前控制面按 `run_id` 工作，适合单用户受控环境。生产产品需要用户、项目、组织、角色和材料访问范围；所有新接口都要明确 owner、scope、审计事件和删除策略。

## 18. API 客户端与状态管理改造

`WebApp-V2/src/api.ts` 需要从单一运行 API 扩展为按域分组的客户端，并支持 AbortController、统一错误代码和任务事件：

```ts
export const api = {
  health,
  product: {
    modules: () => requestJson<ProductModule[]>("/product/modules"),
    capabilities: () => requestJson<CapabilityMap>("/product/capabilities"),
  },
  research: {
    runs,
    run,
    createRun,
    action,
    events,
  },
  figure: { createJob, job, actions, events },
  polish: { createJob, job, revisions, actions },
  translation: { createJob, job, page, actions },
  preferences: { get, update },
};
```

状态层按“页面域”拆分：产品 registry、预览数据、当前运行、任务状态、偏好草稿和全局错误。工作台的现有 `selected`、`busy`、`feedback` 可先保留，但新模块需要避免把所有任务状态塞进 `App.tsx`。

## 19. 测试与验收清单

### 19.1 视觉与交互

- 桌面、平板、手机三种宽度都能完整阅读 Hero、产品预览和 CTA。
- 深色背景、文字、链接、状态和焦点符合对比度要求。
- Qwen 标志使用授权资产；`prefers-reduced-motion` 下无自动旋转或闪烁。
- 键盘可以完成产品入口切换、预览 tab、文件上传、任务重试和返回工作台。
- 未连接后端时，页面明确显示静态预览，不伪造 live 状态。

### 19.2 现有科研能力回归

- `GET /api/health`、学科加载、学科解析和运行列表仍可用。
- 创建运行、材料登记/删除、启动/恢复/取消和 SSE 刷新仍可用。
- 量化参数检索、来源选择、审批、计划身份确认和结果资格审查仍受服务端状态约束。
- 产物预览、日志分片和代表性成果不泄露本地路径。

### 19.3 新模块契约

- figure/polish/translation 任务可创建、读取、取消、重试，并能通过事件流得到明确状态。
- 每个任务都记录输入 hash、模型/解析器版本、输出 artifact 和失败原因。
- 偏好读写具有 user/project scope、版本和并发冲突提示。
- 模块 registry 的 `status` 与真实 API/测试保持一致；规划中的能力不能显示为 available。

### 19.4 建议命令

```bash
npm --prefix WebApp-V2 run build
pytest tests/test_webapp_api.py tests/test_webapp_parameter_search.py
uv run python -m pytest tests/test_webapp_api.py tests/test_webapp_parameter_search.py
```

新增前端页面后，再增加浏览器级检查：真实 API 成功、API 断开、任务失败、窄屏、键盘导航和 reduced motion 各至少覆盖一个场景。绘图、润色和翻译上线前分别增加文件格式、取消/重试和产物完整性测试。

## 20. 分阶段落地顺序

1. **视觉基础**：新增深色 token、字体、`QwenOrbitVisual`、官网壳和路由；工作台先保持真实 API 行为。
2. **产品 registry 与预览**：接入 `representative`，建立六类入口和明确的 available/partial/planned 状态。
3. **全流程与轻度研究**：拆分 `App.tsx`，增加 `research_depth`，完成 `/app/full-research` 和 `/app/light-research`。
4. **偏好与公共任务协议**：先完成 preferences schema，再抽象统一任务、artifact、事件和错误模型。
5. **绘图、润色、翻译**：按数据/文档边界分别实现 worker、文件解析、审阅、导出和 API，不用一个泛化 endpoint 代替三套不同的证据与文件需求。
6. **生产前置**：认证、项目权限、审计、队列持久化、存储策略、限额、监控和删除流程完成后再开放多人使用。

完成后，用户从首页可以先理解 QwenSci 的研究闭环，再通过六类入口选择合适深度；进入工作台后看到的每个状态、材料、动作和产物都能回到现有或新增的服务端契约中。
