# 多模型·多机器人群聊工具：开源方案调研报告

> 调研日期：2026-09-16。Stars、最近提交时间等数据为当日通过 GitHub API 实测，License 以各仓库声明为准。

## TL;DR（直接回答）

有成熟方案，但要分两层看：

1. **开箱即用层**：你的需求描述（建群组、配置机器人角色、提出问题让多个机器人讨论）与 **botgroup.chat**（GitHub 1.7k stars，MIT，React + Cloudflare Pages 一键部署）几乎完全一致，是功能匹配度最高的现成产品；**SillyTavern**（3.3 万 stars，AGPL）的"角色卡 + 群聊"模式也完整覆盖该场景，但偏角色扮演定位。如果你只需要"一个问题同时发给多个模型并排看答案"（机器人之间不互相讨论），**ChatALL**（1.6 万 stars，Apache-2.0）是这个品类的代表。
2. **框架层**：多机器人"互相讨论"在工程上的标准解法是 **GroupChat 模式**，由微软 AutoGen 首创，现由社区分叉 **AG2** 和其继任者 **Microsoft Agent Framework** 承接；**CrewAI**（角色制团队）、**AgentScope**（阿里通义，自带 Web UI 和 MsgHub 消息路由）也是主流选项。框架没有现成聊天界面，需要自己写前端或对接第三方 UI。

**最务实的落地路径**：先用 botgroup.chat 直接部署验证产品形态；若要自研产品，用 AG2 / AgentScope 做编排后端 + 自建 Web 前端，或基于 LibreChat / LobeChat 这类成熟聊天前端二次开发。

---

## 一、需求拆解与方案地图

你的需求可以拆成五个功能点，不同方案对它们的覆盖差异很大，这是选型的关键：

| 功能点 | 说明 | 实现难度 |
|---|---|---|
| ① 在线聊天工具 | Web 界面、流式输出、Markdown 渲染 | 低（大量成熟前端） |
| ② 配置多个模型 | 接入 OpenAI / Claude / 国产模型 / 本地模型，统一切换 | 低（OpenAI 兼容 API 已是事实标准） |
| ③ 后台配置机器人、设定角色 | 机器人 = 模型 + 系统提示词（人格）+ 头像等元数据 | 低 |
| ④ 建群组、拉入不同机器人 | 群作为容器，管理成员机器人 | 中 |
| ⑤ 提出问题后机器人互相讨论 | **核心难点**：需要发言调度（谁先谁后、何时停止）、上下文共享、成本控制的编排引擎 | 高 |

⑤ 是分水岭：绝大多数开源聊天前端（LobeChat、Open WebUI、LibreChat、Dify）只做到 ①②③，对话形态是"一个用户 ↔ 一个机器人"；而"机器人之间互相讨论"需要多智能体编排能力，这正是 AutoGen GroupChat、CrewAI、AgentScope MsgHub 这类框架解决的问题。两类方案的交集——既有 Web 群聊界面又内置讨论编排——就是 botgroup.chat 和 SillyTavern。

---

## 二、开箱即用产品层

### 2.1 botgroup.chat：需求匹配度最高

[botgroup.chat](https://github.com/maojindao55/botgroup.chat) 是一个基于 React 和 Cloudflare Pages 的开源多人 AI 聊天应用，支持多个 AI 角色同时参与对话，提供类似微信群聊的交互体验（[GitHub](https://github.com/maojindao55/botgroup.chat)）。它的功能清单与你的描述几乎逐条对应：支持多个 AI 角色同时对话、可自定义 AI 角色的名称/性格/模型/头像、群组管理（添加、删除角色）、AI 角色禁言（相当于群主控场）、实时流式响应、Markdown 与 KaTeX 数学公式渲染、移动端响应式适配（[GitHub Issue](https://github.com/ruanyf/weekly/issues/6133), [百度经验类介绍](https://www.kdjingpai.com/en/botgroupchatshizhiai/)）。

技术架构上，前端是 React，后端用 Cloudflare Pages Functions 做 Serverless，通过环境变量管理各家模型的 API Key（千问、混元、豆包、DeepSeek 等），角色配置存储在配置文件中；项目还提供了一键 Docker 部署的服务器版本 botgroup.chat-server（Go 语言），并且最新桌面版可以把 CLI Agent（如 Codex、Claude Code）拉进群聊做协同开发（[NPM](https://libraries.io/npm/@botgroup%2Fopenclaw-chat), [造物雷达](https://zaowujuzhen.com/maker/radar/github/repos/maojindao55/botgroup.chat)）。实测数据：**1,684 stars，MIT 协议，TypeScript 为主，最近提交 2026-06**。

需要注意的短板：项目规模较小（1.7k stars），个人开发者维护，角色配置改的是配置文件而非真正的"后台管理界面"，没有完善的多用户/权限体系。它适合验证产品形态和中小团队内部使用，要做成正式产品仍需在其基础上开发用户系统与后台管理。

### 2.2 SillyTavern：角色群聊的"老炮"

[SillyTavern](https://github.com/SillyTavern/SillyTavern) 是 TavernAI 的分支，由 Cohee、RossAscends 及 200 多名社区贡献者维护，核心是**角色卡系统**：每张角色卡定义性格、背景故事、对话示例，然后可以建"群聊"把多张角色卡拉进一个房间，让它们轮流或按活跃度发言、互相接话（[百度百科](https://baike.baidu.com/item/SillyTavern/67315725)）。它兼容 Claude、OpenAI 及几乎所有主流模型接口（通过 OpenAI 兼容 API 可接国产模型和 Ollama 本地模型），还有 WorldInfo 世界设定、扩展插件、TTS、图像生成等丰富周边。

实测数据：**33,411 stars，AGPL-3.0 协议，JavaScript，最近提交 2026-09-14**，非常活跃。它的局限在于定位是"角色扮演/同人创作"工具，UI 和术语都是 RP 向的；另外 **AGPL-3.0 协议对商业化 SaaS 二开有传染性约束**（修改后对外提供服务也必须开源），如果打算商用需要特别注意。

### 2.3 ChatALL：并行问答，不是"讨论"

[ChatALL（齐叨）](https://github.com/ai-shifu/ChatALL) 是"一次提问、多模型并排作答"品类的开创者，作者孙志岗（哈工大前副教授），支持 ChatGPT、Claude、Gemini、文心一言、讯飞星火等数十个模型，回答并排展示、可高亮优选，历史记录保存在本地（[阿里云开发者社区](https://developer.aliyun.com/article/1215262), [CSDN](https://blog.csdn.net/lovechris00/article/details/147356685)）。实测数据：**16,493 stars，Apache-2.0，最近提交 2026-09-11**，仍在维护，且已有在线浏览器版（[chatall.io](https://chatall.io/zh/all-in-one-ai-chatbot/)）。

但要明确：**ChatALL 的机器人之间不互相看见对方的回答**，它是"广播 + 汇总"模式，没有讨论、反驳、接龙能力。如果你的真实诉求是"博采众长选最佳答案"，它够用；如果是"让 AI 互相辩论出更深结论"，它不满足 ⑤。

### 2.4 主流聊天前端的适配度：LibreChat / LobeChat / Open WebUI / Dify

这四个是"自建 AI 聊天入口"的四大主流开源项目，都完美覆盖 ①②③，但都不原生支持"机器人互相讨论"：

| 项目 | Stars（实测） | License | 机器人/角色配置 | 多机器人讨论 |
|---|---|---|---|---|
| [LibreChat](https://github.com/danny-avila/LibreChat) | 44,008 | MIT | Agents 系统最成熟：无代码自定义助手、MCP 工具、Code Interpreter、Agent 市场 | 无（Agent 与用户单聊），但多用户/权限/审计/SSO 是企业级最完整的（[agentlist](https://www.agentlist.top/zh/articles/chat-ui-platform-comparison/), [freelamp](https://freelamp.com/articles/2026-08-08_librechat-oss-value/)） |
| [LobeChat](https://github.com/lobehub/lobe-chat) | 82,516 | 自定义（非 OSI 标准） | 助手（Assistant）+ 插件市场，消费级 UI 最精致 | 无 |
| [Open WebUI](https://github.com/open-webui/open-webui) | 152,248 | 自定义（含品牌条款） | 自定义模型（Model = 模型 + 系统提示词） | 无；本地模型/Ollama、RAG 最强（[TrueFoundry](https://www.truefoundry.com/blog/librechat-vs-open-webui)） |
| [Dify](https://github.com/langgenius/dify) | 155,909 | 自定义（附加条款） | 后台配置 Bot、编排工作流、知识库 RAG，最像"机器人后台" | 无原生群聊讨论，需用工作流编排模拟 |

一个现实的二开思路是：**用 LibreChat 做用户体系、模型接入和后台管理的底座，把"群聊讨论"作为一个自研模块嵌入**——LibreChat 2025 年 11 月被 ClickHouse 收购后承诺保持 MIT 开源，且其 Agents + MCP + 多用户的组合在自托管包中最完整（[TrueFoundry](https://www.truefoundry.com/blog/librechat-vs-open-webui), [freelamp](https://freelamp.com/articles/2026-08-08_librechat-oss-value/)）。而 LobeChat / Open WebUI / Dify 的 License 都带自定义附加条款（品牌、多租户 SaaS 限制等），商用前要逐条读。

### 2.5 小众/玩具类

- **[MultiBot Chat](https://github.com/gptzm/multibot-chat)**（56 stars，GPL-3.0，Streamlit）：有"对话模式"（并排比较）和"群聊模式"（多机器人接龙讨论、可设定角色专长），功能概念完全对口，但规模太小，最后提交 2025-03，适合参考实现思路不适合直接投产。
- **[llm-debate-arena](https://github.com/shibing624/llm-debate-arena)**（新项目，Apache-2.0）：AI 辩论竞技场，任意两个模型 PK、ELO 排位、多裁判投票、5 种辩论性格注入，React + Tailwind 界面，如果你的"讨论"偏对抗辩论场景可以参考。
- **Legend Talk / AI Roundtable** 类：让多个历史名人/数百个模型围绕话题圆桌讨论的工具，概念验证性质，可体验其交互设计（[80aj](https://www.80aj.com/2026/03/25/ai-models-debate/)）。

---

## 三、框架层：实现"机器人互相讨论"的标准解法

如果你要自研产品，群聊讨论引擎建议直接站在这些框架上。2026 年的共识是：**按协调模式选框架，而不是按品牌**（[Zylos Research](https://zylos.ai/research/2026-05-23-swarm-intelligence-multi-agent-coordination-patterns/)）。

### 3.1 AG2 / AutoGen / Microsoft Agent Framework：GroupChat 的嫡系

**GroupChat 模式是你要的功能的"官方学名"**：多个 Agent 在一个共享对话里，由一个 GroupChatManager 决定谁下一个发言（支持 `auto`（LLM 自动选择）、`round_robin`（轮流）、`manual`（人工指定）、`random` 等策略），用户以 UserProxyAgent 身份参与讨论，直到达成共识或达到最大轮次（[51CTO](https://blog.51cto.com/u_16213681/14766282), [bytezonex](https://www.bytezonex.com/archives/GIU6Z2oB.html)）。

谱系要理清：微软研究院 2023 年 9 月发布 AutoGen，2024 年底 0.4 版推倒重写，之后**微软已将 AutoGen 并入 Semantic Kernel 形成继任者 Microsoft Agent Framework（MAF），原 AutoGen 进入维护模式**；社区把 GroupChat 语义保存在了分叉项目 AG2 中（[aispectrum](https://aispectrum.io/agent-harnesses), [wxul.top](https://wxul.top/archive/flue-astro-agent-harness-framework/)）。实测：microsoft/autogen 61,006 stars（仓库声明 CC-BY-4.0）；AG2 4,930 stars、Apache-2.0、提交活跃（2026-09-16）；microsoft/agent-framework 13,545 stars、MIT、同样活跃。新项目建议在 AG2 与 MAF 之间评估，不要再基于老 AutoGen 开工。

### 3.2 CrewAI：角色制团队，上手最快

CrewAI 用"角色（Role）+ 目标（Goal）+ 背景故事（Backstory）"定义 Agent，多个 Agent 组成 Crew 按顺序/层级/并行流程协作，50 行 Python 即可跑通一个多智能体系统，是三巨头中学习曲线最平缓的（[callsphere](https://callsphere.ai/blog/langchain-1-million-github-stars-agent-framework-wars-intensify), [uvik](https://uvik.net/blog/python-ai-agent-frameworks/)）。实测 **58,641 stars、MIT、提交活跃**。它的抽象是"任务委派"而非"自由讨论"：如果你的群聊讨论是结构化的（研究员 → 分析师 → 评审 → 总结），CrewAI 很合适；如果要"自由辩论、随时插话"，AG2 的 GroupChat 更贴切（[coderfile](https://coderfile.io/blog/ai-agents-framework-comparison-2026)）。

### 3.3 AgentScope（阿里通义）：自带服务化和 Web UI 的国产选项

AgentScope 是阿里通义实验室开源的多智能体框架，Apache-2.0，实测 **31,780 stars、提交活跃**。两个点对你特别有价值：其一，它的 **MsgHub** 就是"多智能体消息路由/广播"原语，配合 pipeline 可以很方便地实现群聊讨论，并且支持动态增删参与者——正好对应"建群、拉人、踢人"（[51CTO](https://www.51cto.com/aigc/7890.html)）；其二，它提供开箱即用的**智能体服务**（基于 FastAPI 的多租户后端 + 预构建 Web UI），还有 AgentScope Studio 可视化监控、飞书/钉钉/Discord 消息渠道接入，是框架里离"产品"最近的（[GitHub README](https://github.com/agentscope-ai/agentscope/blob/main/README_zh.md)）。中文文档、国产模型（DashScope/通义）一等支持也是实际优势。

### 3.4 其他框架简评

- **LangGraph**（41,744 stars，MIT）：图状态机编排，生产成熟度、可观测性（LangSmith）、检查点回滚最强，但学习曲线最陡，适合审批流、复杂状态机，而不是自由讨论（[skill-sprinters](https://skill-sprinters.de/blog/tools/crewai-vs-autogen-vs-langgraph-2026-was-passt-fuer-kmu/)）。
- **MetaGPT**（70,417 stars，MIT，最近提交 2026-01，活跃度明显下降）：把软件公司 SOP（产品经理/架构师/工程师/QA）编码进框架，专注自动化软件研发，不适合通用群聊讨论（[guigiagi](https://guijiagi.com/tags/autogen/)）。
- **OpenAI Agents SDK**：handoff 模式显式交接，绑定 OpenAI 生态，多模型自由度低。
- **ChatDev / CAMEL**：学术/垂直场景（软件开发、角色扮演研究），工程产品化弱。

---

## 四、横向对比与项目活跃度

![相关开源项目 GitHub Star 对比](assets/stars对比.png)

> 数据为 2026-09-16 通过 GitHub API 实测。注意 Stars 反映的是"通用热度"而非"与本需求的匹配度"——botgroup.chat 只有 1.7k stars，但功能上是对口度最高的。

**按你需求的匹配度重排**（①~⑤对应第一章功能点）：

| 方案 | 类型 | ①在线聊天 | ②多模型 | ③角色配置 | ④群组 | ⑤互相讨论 | 协议 | 适合 |
|---|---|---|---|---|---|---|---|---|
| botgroup.chat | 产品 | ✅ | ✅ | ✅ | ✅ | ✅（接龙式） | MIT | 直接部署/借鉴 |
| SillyTavern | 产品 | ✅ | ✅ | ✅✅（角色卡最强） | ✅ | ✅（轮流/活跃度触发） | AGPL-3.0 | RP 向场景 |
| ChatALL | 产品 | ✅ | ✅✅ | 部分 | ❌ | ❌（仅并行） | Apache-2.0 | 答案对比 |
| LibreChat | 产品 | ✅✅ | ✅ | ✅（Agents） | ❌ | ❌ | MIT | 二开底座 |
| AG2 / MAF | 框架 | 需自建 | ✅ | 代码配置 | GroupChat | ✅✅（最正宗） | Apache-2.0 / MIT | 自研引擎 |
| CrewAI | 框架 | 需自建 | ✅ | ✅（Role/Goal） | Crew | ✅（结构化委派） | MIT | 流程化讨论 |
| AgentScope | 框架 | 自带Web UI | ✅ | 代码/配置 | MsgHub | ✅✅ | Apache-2.0 | 自研+国产化 |

---

## 五、选型建议

**路径 A：最快验证（1 天内）**——直接部署 botgroup.chat（Cloudflare Pages 免费一键部署，或 botgroup.chat-server 的 Docker 版），把你要的"配置角色 → 建群 → 提问讨论"流程跑一遍，验证产品假设。它的代码量小、结构清晰，后续自研时其发言调度逻辑也是很好的参考实现。

**路径 B：自研产品（推荐）**——编排引擎选 **AG2**（自由讨论/辩论场景）或 **AgentScope**（要国产模型、要自带服务化后端和 Web UI 时）；前端与账户体系基于 **LibreChat**（MIT、多用户、SSO、审计、Agent 市场都现成）二次开发，把"群聊"做成一个新的会话类型。这样 ①②③ 零重复造轮子，研发精力集中在 ④⑤ 这个差异化功能上。

**路径 C：结构化协作而非自由讨论**——如果实际业务是"一群专家 Agent 按流程产出结论"（如 AI 评审团），**CrewAI** 或 **LangGraph** 更可控、更容易调试和审计。

**成本与工程提醒**：多智能体群聊是 token 消耗大户——5 个 Agent 讨论一个问题，每轮每个 Agent 都要带完整对话历史调用一次 LLM，token 用量可达单 Agent 方案的 10–50 倍，成本建模必须前置（[Kunal Ganglani](https://www.kunalganglani.com/blog/autogen-vs-crewai), [autolearningagents](https://www.autolearningagents.com/open-source-ai-agents/)）。此外建议给讨论设置硬性轮次上限与"主持人总结"角色，避免机器人之间无限客套或跑题。

---

*本报告为技术与选型参考信息，所引数据以各项目官方仓库及注明来源为准，开源协议条款请在商用前以官方 License 文件原文为准。*
