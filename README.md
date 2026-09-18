<div align="center">
  <img src="web/public/brand/xunke-logo.svg" width="88" height="88" alt="循课 AI Logo" />
  <h1>循课 AI · Xunke AI</h1>
  <p><strong>把资料组织成课程，让学习有依据、有反馈、有下一步。</strong></p>
  <p>以课程为核心的开源学习 Agent，也是一个可以运行、拆解与扩展的 Agent 应用开发项目。</p>
  <p>
    <a href="#quick-start">快速开始</a> ·
    <a href="#agent-design">Agent 设计</a> ·
    <a href="#architecture">系统架构</a> ·
    <a href="#configuration">配置指南</a>
  </p>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" />
  <img src="https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white" alt="React 19" />
  <img src="https://img.shields.io/badge/LangGraph-Agent%20Workflow-176B58" alt="LangGraph 工作流" />
  <img src="https://img.shields.io/badge/LlamaIndex-RAG-5551BA" alt="LlamaIndex 检索集成" />
  <img src="https://img.shields.io/badge/License-MIT-176B58" alt="MIT License" />
</p>

## 目录

- [循课 AI 是什么](#循课-ai-是什么)
- [可以做什么](#可以做什么)
- [快速开始](#快速开始)
- [第一次怎样使用](#第一次怎样使用)
- [系统架构](#系统架构)
- [Agent 设计：编排、工具、上下文与执行边界](#agent-设计编排工具上下文与执行边界)
- [Agent 架构详解](#agent-架构详解)
- [配置与部署](#配置与部署)
- [个人模型与系统模型](#personal-model)
- [使用评测工作台](#使用评测工作台)
- [开发与测试](#开发与测试)
- [常见问题](#常见问题)
- [参与贡献与许可](#参与贡献与许可)

## 循课 AI 是什么

循课 AI 面向“手里有资料，却不知道如何系统学习”的个人自学场景。输入一个主题，或上传自己的资料，就能创建课程、逐课学习、围绕内容提问，再通过练习、结业检查与复习记录继续推进。

对于开发者，循课 AI 提供一套完整的 Web 实践：**用 LangGraph 组织有边界的教学多 Agent 与 RAG 工作流，用 LlamaIndex 接入可追溯检索，将教学 Skill、正文流、学习证据和模型预算连接起来。** 适合学习 Agent / RAG 应用开发、课程设计和二次开发，支持电脑与手机浏览器。

```mermaid
flowchart LR
    S["资料 / 主题"] --> C["课程纲要"]
    C --> L["逐课学习"]
    L --> Q["提问与查证"]
    Q --> P["练习与反馈"]
    P --> R["复习与下一课"]
    R --> L
    P --> F["结业检查 / 文本应用"]
    F --> N["目标结果与补学建议"]
    N --> L
```

## 可以做什么

| 能力 | 使用方式 |
| --- | --- |
| **生成自己的课程** | 输入主题即可开始，目标、基础与学习安排按需补充；默认准备第一课。教学协作就绪后可选择标准教学，由 Planner、Teacher、Reviewer 分工规划、讲解和核对，也可选择快速生成。 |
| **边学边问** | 对当前课文自由提问，解释某一段、换个例子或获取提示；保存自检回答，再按需请求反馈。 |
| **尽早看到可读内容** | 开启正文流后，课文和知识库回答可按经过基本检查的完整块提前展示；部分课内助教回答增量显示。页面区分生成中预览与正式发布内容。 |
| **基于资料查证** | 上传 PDF、DOCX、Markdown、TXT，限定资料或章节多轮问答，点击引用回到原文，还可从有依据的回答发起练习。 |
| **练习与反馈** | 产品覆盖单选、多选、判断、填空、数值、短解释六类题型；课程每课配三道客观题检查，支持继续作答与查看解析。 |
| **对照目标检验学习结果** | 课程结业检查提供客观题与文本应用任务，回答先保存、反馈可恢复；逐项目标展示待验证、需补学、已验证或旧版本证据，并说明判断依据。 |
| **持续学习** | 学习空间管理目标、资料与知识点，记录首次检查、补练、错题和复习；“今日学习”结合未完成活动与到期任务推荐下一步。生成完成或失败时，无论当前在哪个页面都会收到提醒。 |
| **独立课程书架** | 首页聚焦今日行动，“我的课程”集中管理书架；支持课程选择、手机阅读与明确进入课时后的阅读聚焦。资料问答可持续输入，并按需跳到最新消息。 |
| **使用自己的模型** | 普通用户在个人中心配置 DeepSeek、原生 Anthropic 或 OpenAI 兼容服务；个人模型调用平台不计费，管理员使用系统模型。密钥加密保存，不回显明文。 |
| **比较 RAG 方案** | 在评测工作台冻结数据和配置，比较召回、排序、引用、耗时与费用，按需启用模型 Judge；系统执行能力仅向管理员开放。 |

### 界面一览

| 学习首页：今日主行动与复习 | 课时学习：正文、自检、小结与下一步 |
| --- | --- |
| ![学习首页](assets/home-study.png) | ![课时学习](assets/lesson-reading.png) |

| 课程页：结业检查与逐项目标证据 | |
| --- | --- |
| ![结业检查与目标证据](assets/outcomes-panel.png) | 截图来自本地运行的真实界面（演示数据）；导航、书架与模型设置以当前运行版本为准。 |

<a id="quick-start"></a>

## 快速开始

准备 **Docker Desktop / Docker Engine、Docker Compose 2.24.4+ 和 Python 3.11**，下载源码后在项目根目录执行。

**1. 生成私有配置**

```shell
python deploy/init_env.py
```

脚本创建 `deploy/.env` 并生成独立随机密钥。已有该文件时直接编辑，保留现有数据库与应用密钥。

**2. 配置系统服务与注册邮箱**

编辑 `deploy/.env`，保留脚本生成的 `USER_LLM_KEY_SECRET`，并按使用场景配置下面三类服务：

| 服务 | 作用 | 配置入口 |
| --- | --- | --- |
| **系统 LLM** | 管理员的课程、问答、练习及系统评测；启用 LLM 重排时也使用系统配置 | 选择 `LLM_PROVIDER`，填写对应 API 地址、密钥和模型名 |
| **Embedding** | 资料向量化与检索；主题课程无需此项 | `DASHSCOPE_API_KEY`、模型、地址与匹配的向量维度 |
| **SMTP** | 新账号邮箱验证码注册与邮箱找回密码 | QQ / 163 SMTP 地址、发件邮箱与客户端授权码 |

**普通用户（包括 `evaluator`）的学习模型在登录后的「个人中心 → 模型设置」单独配置，不使用上述系统 LLM，也不会在缺少个人配置时自动回退。** 个人模型支持 DeepSeek、原生 Anthropic 和 OpenAI 兼容服务。

配置示例见 [模型与服务配置](#configuration)，所有参数见 [环境变量模板](deploy/env.example)。课程与综合练习在模板中已启用；未配置学习模型时仍可浏览首页、预置题目和已有内容，已有账号仍可登录，新注册需要 SMTP。

**3. 构建、迁移并启动**

```shell
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.local.yaml build
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.local.yaml up -d --wait mysql
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.local.yaml run --rm migrate
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.local.yaml up -d api rag-owner eval-scorer web
```

打开 **[http://localhost:18080](http://localhost:18080)**，通过邮箱注册并保存恢复码。普通用户先进入「个人中心 → 模型设置」保存并验证个人模型，再创建课程；管理员使用部署中的系统模型。恢复码只展示一次；万一没有保存，还可以在登录页使用「邮箱验证码找回密码」。

## 第一次怎样使用

1. 在「个人中心 → 模型设置」选择服务商，填写 API 根地址、模型名与 API key，保存后完成连接验证。**平台不计费不等于服务商免费**，连接验证本身也可能产生服务商费用；管理员显示只读系统模型，无需配置个人 key。
2. 进入「我的课程」，输入学习主题即可开始；目标、已有基础、每天学习时间和课时数可按需补充。也可以先上传资料，处理完成后选择资料或章节并预览原文。
3. 选择可用的教学方式。标准教学增加 Planner / Teacher / Reviewer 协作核对，快速生成减少审核等待。默认准备第一课；想先调整纲要标题，可取消自动准备。
4. 学习时使用段落解释和课内助教，保存自检回答，需要反馈时点击「检查我的理解」。
5. 完成三题检查，查看解析、错题与本课小结；根据页面主行动继续补练、到期复习或下一课。
6. 进入课程中的「结业检查与课程目标」，完成一组客观题及文本应用任务。按目标结果回到薄弱课时；暂定文本反馈可用于修改回答，不能当作正式掌握结论。

| 来源模式 | 内容依据 |
| --- | --- |
| **主题课程** | 基于当前 LLM 的通用知识，标明未经外部资料核验。 |
| **资料课程** | 使用选定资料的冻结版本，保留引用，材料不足的课时标明缺口。 |

资料课程与主题课程均不自动联网。当前单份文件上限为 10 MB；PDF 需含可提取文字，扫描件请先进行 OCR。

<details>
<summary>学习记录、评分与复习如何理解</summary>

- 阅读完成由用户标记；生成课文、已读、已完成检查分别记录。
- 课堂自检的保存与反馈不计正式成绩、经验值或掌握状态。
- 课程检查使用单选、多选、判断三类客观题；填空、数值、短解释使用独立的练习与评分流程。
- 短解释的模型评分在缺少有效校准时为暂定分，授权复核与自评独立保存。
- 结业检查完成与全部课程目标已验证分别判断；文本应用的当前模型反馈为暂定状态。
- 教学 Reviewer 审核内容，学习目标状态依据作答与结算证据；两者不能互相替代。
- 首次成绩与后续补练、复习分别记录。课程当前提供次日复习建议，支持明确选择提前复习。
- 生成任务可通过 SSE 展示阶段，正文预览需独立开启，均保留结果读取回退；当前采用确定性复习规则。

</details>

<a id="architecture"></a>

## 系统架构

```mermaid
flowchart LR
    subgraph 客户端
        Web["React 网页"]
    end
    subgraph 业务层
        API["FastAPI · 授权与业务"]
        Eval["独立评测 worker"]
    end
    subgraph 执行层
        W["Writer × 1"]
        G["Generation × 2"]
    end
    subgraph 存储与加速
        SQL[("MySQL · 任务 / 学习记录 / 预算")]
        Q["Qdrant"]
        R["Redis"]
        Files[("原文 / 引用 / 原始向量归档")]
    end
    PersonalLLM["个人学习 LLM · learner / evaluator"]
    SystemLLM["系统 LLM / Embedding / 重排"]
    Web <--> API
    API <--> SQL
    SQL --> W
    SQL --> G
    W -->|"构建与删除"| Q
    G -->|"只读检索"| Q
    W --> Files
    G --> Files
    W -.-> PersonalLLM
    G -.-> PersonalLLM
    W -.-> SystemLLM
    G -.-> SystemLLM
    W -.->|"提交后通知"| R
    G -.->|"提交后通知"| R
    R -.->|"唤醒"| API
    API -->|"SSE 阶段 / 私有正文预览与补读"| Web
    Eval <--> API
```

上图为 Qdrant 模式；轻量部署使用单个 RAG owner 与本地 Chroma。两种模式共用业务、证据和任务协议。

| 层次 | 技术与职责 |
| --- | --- |
| 交互 | React 19、TypeScript、Vite、TanStack Query：课程、问答、练习与任务状态 |
| 业务 | FastAPI、Pydantic、MySQL：身份、权限、数据契约、学习记录、任务与预算 |
| Agent 与模型 | RAG 与教学两张 LangGraph、Planner / Teacher / Reviewer、Teach v2 结构契约；LangChain 适配模型协议 |
| 检索与上下文 | LlamaIndex、Chroma / Qdrant、中文 BM25 / RRF、可选重排、证据契约与上下文预算 |
| 任务与加速 | MySQL 租约队列、Redis Lua / Pub/Sub、SSE 游标恢复、可选查询向量缓存 |
| 运行与评测 | 单 owner 或 writer / generation 分工，独立评测 worker，Docker Compose / Nginx |

学习 LLM 按当前账户选择：普通用户与 `evaluator` 使用个人模型，`admin` 使用系统模型；系统 Embedding、可选重排和外部 Judge 分别配置。个人配置加密存储在 MySQL，任务领取时解析，任务结束后关闭其独立模型客户端，不缓存跨用户密钥。Claude 使用原生 Anthropic 协议，也支持 DeepSeek 和 OpenAI 兼容服务。基础部署使用 Chroma；Redis 与 Qdrant 通过独立 Compose 配置启用，无需本地 GPU。已有资料切换向量后端时，请按 [迁移与回退说明](#vector-deployment) 操作。

<a id="design"></a>
<a id="agent-design"></a>

## Agent 设计：编排、工具、上下文与执行边界

循课 AI 将 Agent 应用拆成可单独理解和替换的职责。模型输出先成为内容产物，通过校验后才进入业务系统；工具执行、资料访问和状态更新都有程序约束。

| 关注点 | 当前设计 | 解决的问题 |
| --- | --- | --- |
| **LangGraph · 双工作流** | 保留 RAG 出题图；教学图组织 Planner / Teacher / Reviewer，结构修复与内容返修共享一次机会 | 让协作有实际产物、条件分支、预算和停止原因 |
| **LangChain · 模型协议** | 使用 ChatAnthropic / ChatOpenAI 适配原生 Claude 与兼容接口，统一调用包装 | 业务逻辑复用同一调用入口，便于更换服务商 |
| **LlamaIndex · 知识检索** | 管理节点与文档存储；通过自有投影接口连接 Chroma / Qdrant，再与 BM25 / RRF 配合 | 向量后端可替换，证据与权限契约保持一致 |
| **Tool Interfaces · 工具边界** | 显式注入检索、生成、语义校验和重新授权等接口，限定各任务可用能力 | 工具便于替换与隔离验证，模型不能任意写库或结算成绩 |
| **Context & Memory · 上下文与记忆** | 会话持久化，按来源范围与预算选择历史；每轮事实重新检索，课程只加载相关教学规则 | 连续对话保留意图，历史回答不冒充新一轮事实依据 |
| **Structured Output · Teach v2** | 课程目标关联讲解块、示例与自检；草稿、审核报告、学习证据分别绑定版本与身份 | 校验目标是否被教到、检查是否匹配，教学审核不替代学生成绩 |
| **Redis · 交互加速** | Lua 共享突发限流、Pub/Sub 唤醒 SSE、可选查询向量缓存；阶段流与私有正文流分别授权 | 内容可提前阅读，断线可补读，缓存命中不重复调用模型 |
| **Qdrant · 共享检索** | 原生异步 SDK，单写者和两个只读生成 worker，完整身份过滤后再 Top-K | 长生成任务可以并行，索引发布与资料权限仍由 MySQL 决定 |

### 教学多 Agent：一份计划，按课执行，有界复核

一次学习从一份轻量纲要开始。默认在纲要生成后准备第一课，其余课时进入后按需生成，已生成课文保存复用；取消自动准备后可先调整标题，首次生成课时后固定纲要，保持目标与内容一致。

教学规则作为版本化的 [Teach Skill](.agents/skills/xunke-teach/SKILL.md) 加载，使用 LangGraph 明确组织三个角色：

| 角色 | 实际职责 | 交付给下一步的内容 |
| --- | --- | --- |
| **Planner** | 根据学习目标、基础和资料范围规划课程 | 可观察的课程目标、课时顺序和前置关系，发布后跨课时复用 |
| **Teacher** | 沿用已保存计划，生成当前课时 | 与目标对应的讲解、示例、自检和来源引用 |
| **Reviewer** | 独立核对当前稿的目标、先修、示例、检查、来源与答案泄露 | 结构化问题与修改建议，绑定当前草稿、计划和规则版本 |

```mermaid
sequenceDiagram
    autonumber
    actor U as 学习者
    participant P as Planner
    participant T as Teacher
    participant R as Reviewer
    participant B as 业务层（发布事务）
    U->>P: 创建课程（标准教学）
    P-->>B: 结构化纲要 + 计划哈希，核对通过后发布
    U->>T: 进入新课时
    T->>T: 读取冻结计划，生成本课候选稿
    T->>R: 候选稿 + 冻结计划 + 来源片段
    R-->>B: 六维审核结论（绑定稿/计划/规范哈希）
    alt 审核通过
        B->>U: 原子发布正式课文
    else 存在阻断问题且返修槽可用
        R->>T: 结构化修改意见（消耗唯一返修槽）
        T->>R: 新稿（新内容哈希）并重新复核
        R-->>B: 复核通过后发布
    else 核对不可用 / 额度不足
        B->>U: 明确失败原因；旧内容保持可读
    end
```

标准教学（`guided`）对纲要和课文执行教学核对；快速生成（`fast`）默认只做基本检查。**格式修复和内容返修共用一次机会，返修后重新检查新稿，旧报告不能替新内容背书。** 审核超时、调用预算不足或复核仍有问题时，所请求的审核稿不会发布为合格内容。

角色可以使用同一个已配置模型，但各自拥有固定职责、上下文、工具白名单和调用目的。应用记录真实角色阶段与调用账本；增加 generation worker 数量只是并行执行任务，与这套教学协作分开。默认配置保留快速生成，开启教学 Agent 并确认 worker 就绪后，网页才提供标准教学。

### Teach v2：目标、讲解、示例和检查相互对应

每个课程目标都有明确的预期行为。课时通过局部目标引用说明“这一课教什么”，正文、示例与自检继续绑定这些目标；应用检查目标覆盖、引用有效性和前置顺序，再为发布后的目标分配稳定身份。旧版课程仍可读取和继续学习。

**课程内容的审核结果与用户的学习结果分别保存。** Reviewer 通过说明该稿完成了所请求的教学核对；只有符合目标类型、版本和确认条件的学习证据，才能支持目标状态变化。模型审核不能证明学习者已经掌握，也不能代替真实样本的质量评估。

### LlamaIndex + 混合 RAG：同一份证据贯穿检索与使用

资料课程、知识库问答和资料练习复用证据结构，保留文档版本、章节与原文定位。检索时先限定用户和来源范围，再取候选；引用在生成后核验，展示时继续检查资料授权。

向量与中文 BM25 分别提供语义和关键词召回，RRF 按排名融合，可选重排与父段扩展补充上下文。**检索方案可以替换，内容依据仍然可追溯。** 主题课程明确使用模型知识，资料不足则标明缺口。

LlamaIndex 承担节点与文档存储适配；向量投影可选择轻量 Chroma 或服务化 Qdrant。Qdrant 使用原生异步 SDK，通过项目自己的 Evidence 契约连接来源、上下文和引用。会话历史用于理解追问，当前授权资料提供事实依据，两者分别进入上下文管理。

### 保留 RAG LangGraph：每一次回路都有触发条件和终点

资料出题采用 LangGraph 编排。证据覆盖不足时补检索，生成结果未通过校验时有限再生成；轮次、模型调用数、时间和费用共同约束执行。

```mermaid
flowchart TB
    P["规划覆盖目标"] --> R["检索资料"]
    R --> E["组装证据"]
    E -->|"覆盖不足且仍有预算"| R
    E -->|"证据足够"| G["生成题目"]
    G --> V["结构、引用与语义校验"]
    V -->|"未通过且允许重试"| G
    V -->|"通过"| A["返回内容产物"]
    A --> B["业务层校验执行权并发布"]
    E -->|"无法满足"| X["明确失败与原因"]
    V -->|"达到上限"| X
```

图中展示严格资料出题链路；预算耗尽、超时或授权失效也会停止执行。**原有 RAG 图继续承担检索与出题，新增教学图承担课程角色协作。** 两张图保留各自的状态和条件边，共用受控执行摘要；图负责内容产物，业务层负责发布与结算。问答与综合练习继续使用各自的业务流程。

状态包含覆盖计划、候选证据、检索轮次、生成次数和校验结果；条件边读取这些状态决定下一步。当前资料出题最多两轮检索、两次生成，且受共同调用预算约束。持久恢复由外层任务与 attempt 管理，当前未配置 LangGraph Checkpointer 做逐节点续跑。

### 正文流：同一次调用，提前阅读，最终原子发布

开启 `CONTENT_EVENTS_ENABLED` 后，同一条模型流一边聚合完整产物，一边提供允许预览的内容。课文只输出结构完整、目标与来源引用通过基本检查的块；知识库回答按引用有效的块输出；主题课内的解释、举例和提示支持文本增量。提示词、工具参数、隐藏推理与私有评分依据不进入预览。

正文流与任务阶段流使用独立协议。重连按任务、执行轮次、草稿版本和游标补读；进入返修会清除旧稿预览，取消或来源失效会停止读取。**预览不写成正式课文，正文显示完也不等于发布成功。** 完整产物通过检查并提交后，页面重新读取正式结果。

一次流式生成只记录一次技术调用；仅系统调用预占和结算平台金额，个人调用保持“平台不计费”。不会为取得最终 JSON 再调用模型。不支持流式的服务保留完整响应；流中断后不会自动追加一次付费请求。Redis 可加速唤醒，正文帧仍由 MySQL 短期保存，关闭正文流也能照常生成和读取结果。

### 持久任务与预算：长任务可恢复，重复操作有边界

课程、问答和出题进入 MySQL 持久任务队列。worker 用租约与心跳维护执行权，发布前再次校验，避免旧执行结果覆盖新结果；幂等键处理重复提交，成绩结算保留收据。

同一套外呼账本记录模型来源、调用次数与 token。**个人 LLM 调用平台不计费**：金额和预留金额保持 `null`，费用状态为 `not_applicable`，不参与人民币预占与结算，但仍受调用次数、token、超时与重试限制。系统调用按配置预占与结算金额，超时且费用未知时保留预占等待对账。

混合任务按每次外呼分别归属：个人生成不计平台费用，系统 Embedding 或重排仍记录系统成本。费用预览仅展示系统部分，不包含个人服务商账单；历史账本缺少来源时保持未知，不按当前角色推断，也不把“不适用”当作零元或成本下降。**任务状态、业务结果、技术用量与系统费用各自有据可查。**

<details>
<summary>为什么当前使用 MySQL 任务队列，Redis 在这里适合做什么？</summary>

当前采用 MySQL 的行锁与 `SKIP LOCKED` 领取任务，将任务发布、学习记录和预算状态放在已有的事务体系内协调，减少需要共同维护的基础设施。数据库保存事实，租约与幂等控制有效结果；这项选择优先服务于当前部署规模和一致性需求。

Redis 承担共享突发限流和任务阶段推送：状态变更与公开事件同事务写入 MySQL，提交后才发唤醒通知。前端通过 SSE 接收阶段，并按游标补读；Redis 故障时继续使用 SQL 硬限制和状态查询。课程、助教、问答、出题与练习使用同一套事件协议。

查询 Embedding 可使用独立 Redis 缓存，按用户、来源空间、模型版本和原始查询隔离。命中时直接复用向量，不再次调用或计费；评测、文档入库和未固定模型版本的查询绕过缓存。成绩、费用、验证码消费与发信配额继续由 MySQL 事务管理。

</details>

### 索引可替换，历史依据可保留

Qdrant 的物理写入完成后，独立读客户端完整核验向量，业务事务再决定是否发布。查询先限定用户、文档版本、构建和节点范围，再执行 Top-K；生成容器只持有读 key。

迁移直接复制已有向量，保留逻辑文档与引用标识。由于 Qdrant 的 Cosine 存储会归一化向量，系统额外归档原始 float32 向量，新增资料也可据此恢复到 Chroma。删除按登记清理各后端副本；未确认的远端操作保留待恢复记录。

### 反馈、成绩与掌握状态为什么分开

自检回答可以直接保存，模型反馈按需请求；页面分别显示保存、反馈生成和结果读取状态，网络恢复后可以取回已保存内容。正式题目按题型评分，首次成绩、补练和复习记录分别保存。

结业检查把课程目标与实际题目关联起来，包含客观题和文本应用任务。客观题沿用现有判分与结算；文本应用先保存不可变回答，再生成教学反馈，当前模型反馈保留 **`provisional`（暂定、未正式确认）**。回答或反馈生成成功都不会自动变成目标已验证。

目标结果由程序依据学习记录计算，展示“待验证 / 需补学 / 已验证 / 旧版本证据”和对应原因。识别题通过只支持相应的识别目标，不能证明已经会解释或应用；帮助使用情况未知时也不会直接推断独立完成。旧课程缺少可信目标映射时保持待验证，不事后伪造关联。

“今日学习”根据未完成练习、到期复习和课程进度计算建议，查看建议无需调用模型。**该用规则判断的地方使用规则，模型集中处理讲解与生成。**

### 如何评估一次改动值不值得保留

评测冻结资料、标注和运行配置，再比较检索或生成方案。确定性检查、可选模型 Judge 和人工复核各有职责；耗时与费用和质量一起记录，帮助判断一次优化是否值得保留。

独立评分进程通过受控 API 获取任务与提交结果，部署时不持有业务数据库凭据或原始资料卷。基础评测可直接运行，外部 Judge 按需启用。

## Agent 架构详解

<details>
<summary><b>点开查看工程级细节：角色工具白名单、预算数值表、审核绑定、持久化与恢复</b></summary>


本节面向想理解或二次开发这套 Agent 的读者，给出编排层的工程细节。所有数值以代码为准（`backend/app/teaching/policy.py`、`graph.py`、`agents.py`）。

### 两种任务，两张图

| | 教学协作图（课程纲要 / 课时） | RAG 出题图（资料练习） |
| --- | --- | --- |
| 节点 | authorize → planner/teacher → validate → reviewer → repair → revalidate → recheck → finish/stop | prepare → retrieve → assemble → generate → validate → finish |
| 回路 | 共享唯一返修槽（结构错误与审核返修共用），返修后必经复核 | 覆盖不足补检索（≤2 轮）、校验失败有限再生成（≤2 次） |
| recursion_limit | 16 | 24 |
| 状态载体 | TeachingAgentState（请求/候选/审核报告/返修槽计数） | _State（覆盖计划/候选证据/轮次/校验结果） |
| 持久恢复 | 外层 MySQL 任务租约 + 质量运行检查点（无 LangGraph Checkpointer） | 同左 |

两张图**不共享状态**，各自有显式输入与终止原因；共同的只有预算组件、摘要协议与业务层的发布事务。

### 角色与工具允许列表

工具端口由 worker 按角色注入，模型没有通用文件、SQL、shell 或网络接口；越权调用在进入模型前就被拒绝：

| 角色 | 允许的工具端口 | 产物边界 |
| --- | --- | --- |
| Planner | `outline_material`、`validate_outline`、`generate_outline` | CourseDraftV2 + plan_hash；不给旧课改目标、不分配持久 ID |
| Teacher | `load_frozen_plan`、`lesson_material`、`validate_lesson`、`generate_lesson`、`preview_lesson_blocks` | LessonDraftV2 + draft_hash；复制纲要约束，不扩大来源范围 |
| Reviewer | `read_candidate`、`read_frozen_sources`、`validate_references`、`review_candidate` | 结构化 findings；不写课文、不调正式评分、不改成绩 |

Teacher 的 `preview_lesson_blocks` 用于正文流：每完成一个通过结构与引用校验的完整块即对外预览，不发送半个 JSON。

### 冻结策略与预算（数值表）

策略在任务排队时冻结（policy_hash 入库），运行中改配置不影响已排队任务：

| 冻结路径 | 初次生成 | 共享返修槽 | Reviewer（初审+复核） | LLM 重排 | LLM 总上限 |
| --- | ---: | ---: | ---: | ---: | ---: |
| fast 纲要 | 1 | ≤1 | 0 | 0 | 2 |
| fast 课时 | 1 | ≤1 | 0 | ≤1 | 3 |
| guided 纲要 | 1 | ≤1 | ≤2 | 0 | 4 |
| guided 课时 | 1 | ≤1 | ≤2 | ≤1 | 5 |

- 输入按完整消息计数（不是只算候选正文）：初稿上限 12000，Reviewer/返修 16000；输出初稿沿用纲要 3000 / 课时 4500，Reviewer 1200，重排 512。
- 时间：Reviewer 默认 60s（可配 1–120）、返修 90s、发布预留 5s；启动返修前必须同时满足"两次调用 + 125s 剩余时间"。
- 缺失 token usage 保留未知并标记估算，不视为免费；所有调用进入技术用量账本。个人模型金额标为“不适用”，只有系统调用进入平台费用合计。

### 审核如何绑定"当前这一稿"

Reviewer 的报告不是一句"通过"，而是带绑定头的结构化报告。发布时逐字段核对：

| 绑定字段 | 防止的问题 |
| --- | --- |
| `draft_hash` | 旧报告替新稿背书（改一个字哈希即变） |
| `plan_hash` | 计划改了还沿用旧审核 |
| `skill_hash` | 教学规范升级后旧审核失效 |
| `scope_fingerprint` | 来源范围变化后旧证据引用失效 |
| `criteria_revision` | 目标版本变化后对齐关系失效 |
| `policy_hash` | 用篡改的宽松策略骗取通过 |
| `artifact_hash`（发布时生成） | 公开"已核对"必须匹配当前已发布产物 |

六个维度必须各出现一次；`pass`/`fail` 缺一即报告无效。topic 课程的 `source_support` 可为 not_applicable，但保留"模型知识、未外部核验"提示。

### 终止原因、公开事件与隐私边界

- 终止原因使用**固定错误码**（`budget_exceeded`、`insufficient_evidence`、`course_quality_blocked`、`course_quality_unavailable`、`course_generation_invalid`、`source_revoked` 等），不接受模型自由文本。
- 公开 SSE 阶段白名单：`planning / teaching / reviewing / revising`，映射为"规划课程 / 编写本课 / 核对教学内容 / 根据反馈修订"；正文与审核原文走独立授权的内容流，公开事件永不出内网。
- 执行摘要（`GraphExecutionSummary`）记录节点顺序、分支、usage 增量与终止码，供本地诊断与面试演示；字段严格约束，塞入 prompt/摘录等私有字段会被 schema 拒绝。

### 持久化与恢复

| 表 | 用途 |
| --- | --- |
| `learning_teaching_quality_runs` | 每任务一条：冻结策略、候选稿私有暂存、最新报告、返修槽与 generation_revision |
| `learning_teaching_agent_steps` | 每角色调用一条：stage_slot 限 `initial/repair/review_initial/review_recheck`，外呼前占槽（崩溃遗留的槽视为已消耗，恢复时不重放未知调用） |

候选稿是私有暂存而非已发布内容：发布后清空正文只留哈希与报告；失败候选 24 小时内由 owner 维护周期分批清理；课程删除/资料撤销同步清除候选与报告正文。要求审核的路径缺少有效报告就不发布——worker 重启不会把 guided 静默降级成 fast。

### 教学质量如何被评估

结构契约（目标对齐、引用、先修）由确定性校验保证，Reviewer 与真实质量是两回事。项目为此保留三层评估入口：

1. **契约层**：增量迁移、严格 Pydantic/JSON Schema 与生成 API 类型一致检查进入 CI；
2. **评审层**：评测工作台冻结数据集运行方案，确定性指标 + 可选模型 Judge（`calibrated` 区分人工校准），已有基线与消融报告；
3. **效果层**：目标结果投影（A07）给出"已验证/需补学/待验证"证据计数，配合体验事件（首块可见耗时、重试率）与成本观察（E02），按明确分母报告——无样本如实为 null。

真实模型的抽样验收（8 个固定任务、guided/fast 对照、人工按六维盲读）在模型供应商可用时单独执行，不与模拟验收混记。


</details>

<a id="configuration"></a>

## 配置与部署

Docker 部署统一读取私有的 `deploy/.env`。初始化脚本生成数据库、应用、个人模型加密、验证码、Redis 与 Qdrant 的独立密钥；已有部署定向补充缺少的配置，保留原密钥、Compose 项目名与数据卷。系统环境配置修改后，用原 Compose 文件组合执行 `up -d` 重新创建相关容器；个人模型设置不需要重建容器。

<a id="personal-model"></a>

### 个人模型与系统模型

| 账户 / 服务 | 使用的模型 | 平台费用归属 |
| --- | --- | --- |
| 普通学习用户、`evaluator` 的学习任务 | 个人中心保存的 LLM，包括课程规划、讲解、教学核对、助教、文本应用与练习评分 | 平台不计费；服务商是否收费及其账单由用户自行确认 |
| `admin` 的学习任务及系统评测执行 | 部署配置的系统 LLM；可选外部 Judge 独立配置 | 按系统价格与预算记录 |
| 资料向量化、查询 Embedding、可选重排 | 系统 Embedding / 重排配置，与个人生成模型分离 | 独立记录系统成本，不因生成使用个人 key 而免计 |

普通用户进入「个人中心 → 模型设置」，填写服务商、API 根地址、模型名与 API key。Anthropic 使用原生协议根地址（例如 `https://api.anthropic.com`），OpenAI 兼容服务填写供应商要求的根地址（通常含 `/v1`），不要填写完整的 `/chat/completions` 或 `/messages` 路径。模型名称以服务商实际支持为准。

- 保存时会发送一次小型连接验证请求，**该请求也可能由服务商收费**；验证失败不会覆盖已有配置。
- 密钥不回填，页面只显示掩码。服务商、地址和模型都未变化且旧密钥可读时，可留空沿用；更改这些参数后需要重新填写 key。
- 删除需确认；删除、密钥不可读或未配置时，学习任务明确提示配置问题，**不回退系统模型**。并发更新会要求重新加载，避免旧表单覆盖新设置。
- 管理员个人中心显示只读系统模型，不能保存个人配置；历史个人配置不参与管理员模型选择。
- 个人 API 地址必须可从服务器访问且解析到公网。拒绝回环、内网、保留地址、URL 内嵌凭据与重定向；支持公开 HTTP / HTTPS，推荐 HTTPS。密钥使用 AES-GCM 加密并绑定账户，错误信息脱敏。

<details>
<summary>已有部署升级：加密密钥与增量迁移</summary>

1. 在现有私有 `deploy/.env` 中补充独立随机的 `USER_LLM_KEY_SECRET`，至少 32 字符，不得复用 `JWT_SECRET` 或 `EMAIL_CODE_SECRET`。不要重新生成或覆盖已有数据库、会话密钥。
2. API 与实际执行学习生成、练习评分的 worker 必须使用同一个值；仓库 Compose 的共享后端环境已传递该变量。独立 `eval-scorer` 使用系统 Judge，不接收个人密钥或此加密密钥。
3. 备份数据库和资料后，使用原 Compose 项目、文件组合及数据卷重新构建，执行 `migrate`，再重新创建应用容器。增量迁移会创建 `user_llm_configs`；迁移器按完整文件名标识记录，因此两个以 `023_` 开头的独立迁移都需保留，不手动重编号。
4. 现有普通用户仍需各自保存个人模型。`USER_LLM_KEY_SECRET` 一旦更换，旧密文将无法解密；轮换前安排重新加密方案，或通知用户重新填写并保存 API key，不能仅替换环境值后期待旧配置继续可用。

</details>

<details>
<summary>系统模型、Embedding 与注册邮箱</summary>

选择一个系统 `LLM_PROVIDER`，填写对应服务的地址、密钥和模型名。它服务于管理员学习、系统评测和启用的系统 LLM 重排，不是普通用户的模型配置入口。模型名以供应商实际支持的名称为准，外部评测 Judge 独立配置。

| `LLM_PROVIDER` | 配置项 | 地址示例 |
| --- | --- | --- |
| `anthropic` | `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL` | `https://api.anthropic.com`，使用原生 Anthropic 协议 |
| `deepseek` | `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` | `https://api.deepseek.com` |
| `openai_compatible` | `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` | 供应商提供的兼容 API 根地址，通常以 `/v1` 结尾 |

资料检索另需配置 Embedding。变量沿用 `DASHSCOPE_*` 命名，也可填写兼容服务：

```dotenv
DASHSCOPE_API_KEY=your_embedding_api_key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024
```

`EMBEDDING_DIMENSIONS` 必须匹配模型实际输出。更换模型、维度或分块方案后重建对应资料索引；已有索引不会随环境变量自动转换。`RAG_PIPELINE_ID=dense-v1` 是默认向量基线，`hybrid-v1` 启用 BM25 / RRF，重排配置见 [环境变量模板](deploy/env.example)。

在发件邮箱开启 SMTP 并获取客户端授权码，以 QQ 邮箱为例：

```dotenv
EMAIL_REGISTRATION_ENABLED=true
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_SECURITY=ssl
SMTP_USERNAME=your_account@qq.com
SMTP_PASSWORD=your_smtp_authorization_code
SMTP_FROM_EMAIL=your_account@qq.com
SMTP_FROM_NAME=循课 AI
```

163 邮箱使用 `smtp.163.com`，用户名与发件地址填写同一个邮箱。`SMTP_PASSWORD` 使用客户端授权码。SMTP 用于注册和邮箱验证码找回密码；关闭注册后，已有账号仍可登录。真实密钥仅保存在私有配置中。

</details>

<a id="timeouts"></a>

<details>
<summary>功能开关、超时与费用预算</summary>

新环境默认启用 `COURSE_ENABLED`、`PRACTICE_ENABLED` 和 `PRACTICE_SHORT_ANSWER_ENABLED`。课程与课内助教使用 `COURSE_PROVIDER_TIMEOUT_SECONDS` / `COURSE_JOB_DEADLINE_SECONDS`，通用任务使用 `PROVIDER_TIMEOUT_SECONDS` / `JOB_DEADLINE_SECONDS`，分别限制单次外呼与整项任务。

教学协作与正文预览是独立开关，模板中均为关闭。需要使用时，在私有 `deploy/.env` 中显式开启并重新创建 API 与生成 worker：

```dotenv
ENABLE_COURSE_TEACHING_AGENTS=true
CONTENT_EVENTS_ENABLED=true
COURSE_TEACHING_REVIEW_TIMEOUT_SECONDS=60
COURSE_TEACHING_REPAIR_TIMEOUT_SECONDS=90
COURSE_TEACHING_PUBLICATION_RESERVE_SECONDS=5
```

教学角色复用当前账户的学习模型配置：普通用户与 `evaluator` 使用个人模型，管理员使用系统模型，无需为三个角色分别配置模型。网页根据开关、账户配置和近期 worker 心跳判断标准教学是否就绪，这不等于已经确认外部模型可调用。已有课程和旧请求不会被自动重跑。

Reviewer 单次审核默认 60 秒，允许配置 1–120 秒；可按供应商延迟调整，例如设为 90 秒。配置只在新任务创建时冻结，旧任务继续使用原策略。审核仍需预留发布时间，整项任务仍受 `COURSE_JOB_DEADLINE_SECONDS` 限制；超时且调用结果未知时不会自动重新发起模型请求。

标准教学中，每个纲要任务最多 4 次 LLM 调用，每个课时任务最多 5 次（计入可能使用的 LLM 重排）；快速生成对应为 2 / 3 次。每个任务至多一次返修、两次 Reviewer 调用，实际正常生成通常少于上限。返修前同时预留复核与发布时间，不能通过延长超时绕过次数和费用预算。

正文流无需启用教学审核，也不强制依赖 Redis；它只改变内容可见时间，完整检查与发布条件保持一致。生产反向代理需保持 SSE 不缓冲，仓库 Nginx 配置已包含相应设置。

按系统服务商实际价格填写 `LLM_INPUT_CNY_PER_MILLION`、`LLM_OUTPUT_CNY_PER_MILLION`、`EMBEDDING_CNY_PER_MILLION` 等人民币单价，并更新 `PRICING_VERSION`。这些单价与用户、全局、评测金额预算只用于系统调用，不用于推算个人 LLM 的服务商账单。个人模型仍受技术用量限制，系统部分未知价格保持未知；涉及付费服务的系统评测需要价格配置才能执行费用上限控制。

</details>

<a id="redis-deployment"></a>

<details>
<summary>可选 Redis：共享限流、任务阶段推送与查询缓存</summary>

在 `deploy/.env` 中保留初始化生成的 `REDIS_PASSWORD`，开启以下配置，再增加 Redis 覆盖文件：

```dotenv
REDIS_ENABLED=true
REDIS_RATE_LIMIT_ENABLED=true
TASK_EVENTS_ENABLED=true
```

```shell
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.local.yaml -f deploy/compose.redis.yaml up -d
```

Redis 仅在 Compose 内网提供服务。SQL 硬限额与任务事件持续保存；Redis 不可用时，突发限流跳过附加门槛，事件通过 SQL 补读，页面保留状态查询回退。

查询向量缓存使用独立实例及 `REDIS_CACHE_PASSWORD`。设置 `QUERY_EMBEDDING_CACHE_ENABLED=true` 和供应商可确认的 `EMBEDDING_MODEL_REVISION`，然后在上述命令的 `up -d` 前追加 `-f deploy/compose.cache.yaml`。无法确认固定模型版本时留空，系统自动绕过缓存；评测与文档向量化始终绕过查询缓存。使用 Qdrant 时，把它的覆盖文件放在 Redis / cache 之后。

</details>

<a id="vector-deployment"></a>

<details>
<summary>Qdrant：启用并行生成、迁移已有资料与回退 Chroma</summary>

基础部署使用 Chroma 和单个 RAG owner。Qdrant 模式使用单个 writer 和默认两个 generation：writer 处理索引与原有写任务，generation 处理资料问答、课程纲要、课文和课内助教。只读 key 由服务端强制限制；API 与评分进程不持有向量库 key。

已有资料需先复制并核验，再启动 Qdrant 模式。准备维护窗口，等待任务结束，备份 MySQL 与资料卷，保留 Chroma 卷和原镜像。在私有配置中补齐以下值，读写 key 使用初始化脚本生成的不同随机值：

```dotenv
VECTOR_BACKEND=qdrant
VECTOR_TARGET_REVISION=qdrant-v1
VECTOR_PROJECTION_REGISTRY_REQUIRED=true
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION_PREFIX=xunke_dense
QDRANT_API_KEY=your_independent_writer_key
QDRANT_READ_ONLY_API_KEY=your_independent_reader_key
QDRANT_GENERATION_WORKERS=2
```

下面的 PowerShell 示例同时启用 Redis；仅使用 Qdrant 时可去掉 Redis 覆盖文件，并保持 Redis 开关关闭。启用查询缓存时，将 cache 覆盖文件加在 Qdrant 之前；已有 Judge 部署保留对应覆盖文件。后续管理保持相同组合。

<details>
<summary>迁移与回退完整命令（PowerShell，逐项确认后继续）</summary>

```powershell
$xunkeCompose = @('--env-file', 'deploy/.env', '-f', 'deploy/compose.yaml', '-f', 'deploy/compose.local.yaml', '-f', 'deploy/compose.redis.yaml', '-f', 'deploy/compose.qdrant.yaml')
docker compose @xunkeCompose config --quiet
docker compose @xunkeCompose build api web eval-scorer
docker compose @xunkeCompose stop api rag-owner rag-generation eval-scorer
docker compose @xunkeCompose up -d --wait mysql
docker compose @xunkeCompose run --rm --no-deps migrate
docker compose @xunkeCompose up -d --no-deps qdrant
docker compose @xunkeCompose run --rm --no-deps vector-migrate python -m scripts.migrate_vectors plan
docker compose @xunkeCompose run --rm --no-deps vector-migrate python -m scripts.migrate_vectors copy --run-id initial-qdrant-v1
docker compose @xunkeCompose run --rm --no-deps vector-migrate python -m scripts.migrate_vectors verify
docker compose @xunkeCompose run --rm --no-deps vector-migrate python -m scripts.migrate_vectors switch-check
docker compose @xunkeCompose up -d
```

逐项确认命令成功后继续；新空库也执行相同检查，清单为空时无需复制向量。旧 worker 停止后，其心跳可能需等待 90 秒退出活动窗口。维护检查会拒绝未排空的执行，保留现有数据卷。

`copy` 按原构建的模型空间初始化或核对集合，复制所有已发布历史构建，保留逻辑 manifest、引用 ID 与原始 float32 向量归档，不重新调用 Embedding。回执位于资料卷的 `rag/vector-migrations/`。相同 run ID 可复用已确认批次；崩溃遗留的未知操作需要原执行者退出证据及 `--recovery-proof`，未知 Qdrant 写入还要求在原执行者退出后重启服务并核对实际启动时间。

回退同样先排空任务并停止执行进程，再从原始归档恢复包含新增构建在内的 Chroma 副本：

```powershell
docker compose @xunkeCompose stop api rag-owner rag-generation eval-scorer
docker compose @xunkeCompose run --rm --no-deps vector-migrate python -m scripts.migrate_vectors restore-chroma --run-id rollback-qdrant-v1
docker compose @xunkeCompose run --rm --no-deps vector-migrate python -m scripts.migrate_vectors rollback-check
```

</details>

检查成功后，设置 `VECTOR_BACKEND=chroma`、`VECTOR_TARGET_REVISION=legacy-v1`，保留 `VECTOR_PROJECTION_REGISTRY_REQUIRED=true`、Qdrant 服务与读写 key，再执行：

```powershell
docker compose @xunkeCompose up -d --scale rag-generation=0
```

Chroma 恢复单 owner 执行，后续启动继续带 `--scale rag-generation=0`；保留的 Qdrant 登记副本继续参与资料删除。缺失原始归档、未核验投影或未收尾操作会阻止回退，检查命令不会自行更改服务配置。当前 Qdrant 为单节点部署，容量与吞吐需结合实际资料和模型服务测量。

</details>

<a id="deployment"></a>

<details>
<summary>服务器 HTTPS 部署与更新</summary>

服务器使用 [基础 Compose](deploy/compose.yaml)，去掉命令中的 `-f deploy/compose.local.yaml`。将 `WEB_ORIGINS` 设为实际 HTTPS Origin 的 JSON 数组，如 `["https://learn.example.com"]`；把 `fullchain.pem`、`privkey.pem` 放入 `deploy/certs/` 并确保容器内 Nginx 用户可读，默认使用 80 / 443 端口。前置代理需按实际拓扑配置受信真实 IP。

更新源码后重新构建镜像，再按“启动 MySQL → 执行增量迁移 → 启动应用”的顺序更新。保留当前项目名与卷；使用同一 Compose 组合的 `ps` 和 `logs --tail 100` 检查服务，反馈问题时提供脱敏错误。

</details>

<a id="evaluation"></a>

## 使用评测工作台

流程为 **准备资料 → 创建并标注数据集 → 冻结版本 → 运行方案 → 比较结果**。

`evaluator` 和 `admin` 均可从导航进入本人范围的工作台，但权限不同：

| 角色 | 工作台能力 |
| --- | --- |
| `evaluator` | 维护本人数据集、查看资料与记录、人工复核、导出、取消任务及费用预估；不能执行或恢复系统评测，不能发起使用系统模型的评测资料处理。其日常学习仍使用个人模型。 |
| `admin` | 在上述能力之外，允许创建、恢复系统评测，执行评测资料上传处理、重建、反馈转入评测及模型评分等受控操作。 |

执行入口、worker 与发布阶段校验当前数据库角色；管理员权限**不绕过资料所属用户限制，也不是全平台用户后台**。基础评分无需外部 Judge；需要模型判断维度时，再配置独立的 Judge 服务。各类样本使用各自适用的指标，效果结论应结合实际标注与运行结果。

<details>
<summary>管理员授权与可选 Judge</summary>

将 `123` 替换为实际**数字用户 ID**，不是邮箱；登录后的 `/api/v1/auth/session` 响应中 `data.user.id` 可查看该值。使用部署时相同的 Compose 组合运行，仅为可信账户授予所需角色，授权后重新登录。

只需要数据维护与人工复核时：

```shell
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.local.yaml exec api python scripts/admin.py --user-id 123 --role evaluator
```

需要执行系统评测时，改为授予 `admin`（该账户的学习也会改用系统模型）：

```shell
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.local.yaml exec api python scripts/admin.py --user-id 123 --role admin
```

恢复普通学习角色使用 `--role learner`。以上是部署管理员手动授权命令，不会在应用注册时自动执行。

外部 Judge 使用 [独立配置模板](evaluation/judge-config.example.json)，填写模型、协议、地址、价格和预算；在私有环境中配置 `EVAL_JUDGE_CONFIG_FILE` 与 `EVAL_JUDGE_API_KEY`，并增加 `-f deploy/compose.judge.yaml` 重建 `api`、`eval-scorer`。它不会自动继承生成模型的凭据；没有人工校准记录时保持 `calibrated=false`。

</details>

## 开发与测试

版本以 [`.python-version`](.python-version)、[`.node-version`](.node-version) 和各目录锁文件为准。[CI](.github/workflows/ci.yml) 在 push / Pull Request 时分别检查后端、独立评测环境、前端及浏览器流程；测试使用合成账号与模拟模型，不需要真实付费模型 key。

| 检查 | 覆盖 |
| --- | --- |
| 后端与 MySQL 8.4 | 非外部单元 / RAG / 数据库集成测试、鉴权、迁移、个人密钥与调用来源隔离 |
| 独立评测 core / Ragas | 各自锁定依赖环境、确定性指标、已安装适配器、数据集校验 |
| 前端 | 生成 API 类型一致性、TypeScript、Vitest、生产构建 |
| 浏览器 | Chromium 桌面 / 手机及 Firefox / WebKit，运行隔离 mock API 的用户流程 |

前端检查（项目根目录）：

```shell
npm --prefix web ci
npm --prefix web run api:check
npm --prefix web run typecheck
npm --prefix web run test:run
npm --prefix web run build
```

后端请使用独立 Python 3.11 环境，安装 `backend/requirements.lock` 及本地 `evaluation` 包，在 `backend` 目录运行 `python scripts/export_contracts.py --check` 和 `python -m pytest -m "not external" -q`。数据库集成测试需要独立 MySQL，库名必须以 `yu_ai_learn_test` 开头；具体合成环境变量和安装命令见 CI，**不要指向生产库或加载真实服务商凭据**。`evaluation/requirements-ragas.lock` 应安装到单独环境，缺少该依赖时的跳过不能替代 Ragas 检查通过。

模拟测试验证功能与隔离边界，不代表真实模型教学质量或服务商连通性已经验收；外部模型抽样验证需另行准备授权、价格和预算。

## 常见问题

**生成失败或长时间等待？**

普通用户先在「个人中心 → 模型设置」检查模型、地址、key 与服务商额度；缺少配置、密钥不可读或连接失败不会改用系统模型。管理员检查系统配置。单次调用超时和整个任务截止时间分别配置，个人模型也受技术限额约束；具体参数见 [超时与预算](#timeouts)。

**配置修改后没有生效？**

个人模型保存成功后，后续领取的学习任务使用新配置；已在执行的任务持有自己的模型客户端，不会在中途自动切换。并发修改、密钥不可读或更换模型参数时，重新加载设置并填写 key 后保存。更新系统 `deploy/.env` 则需要重新创建相关容器，仅执行 `restart` 不会重新加载环境变量。

**为什么个人模型显示「平台不计费」，任务仍有系统费用？**

这只表示平台不统计和扣算个人 LLM 金额，不表示服务商免费。资料向量化、查询 Embedding 或系统重排单独计量，混合任务仍可能产生系统费用；页面预估不包含你的个人服务商账单。

**资料上传后无法使用？**

检查可提取文字、Embedding 服务和向量维度。更换向量模型后需要重建对应资料索引。

**如何部署到服务器？**

使用 HTTPS 域名、证书与生产 Compose 配置，详见 [服务器部署](#deployment)。

## 参与贡献与许可

欢迎通过 Issue 反馈问题、讨论使用场景，或提交 Pull Request 改进教学体验、检索策略与工程实现。反馈时附上复现步骤、环境版本和脱敏后的错误信息。

项目采用 [MIT License](LICENSE)。教学 Skill 参考 Matt Pocock 的 `teach`，并增加资料来源策略、结构化课程契约和学习状态边界，来源与许可见 [第三方说明](.agents/skills/xunke-teach/THIRD_PARTY_NOTICES.md)。
