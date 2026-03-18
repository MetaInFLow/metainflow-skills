---
name: customer-profile-generator
description: 从客户名称、客户记录、S4/S5方案结果或S28反馈出发，协同企业查询、网页搜索和 openclaw-lark 飞书能力创建或增量更新标准化 Account Plan；当需要生成客户计划、更新 Account Plan、刷新客户档案、同步客户等级/商机/跟进策略时使用
---

# 客户计划生成器

## 定位

`customer-profile-generator` 是 S11 的执行 Skill。目标不是产出零散画像片段，而是生成或更新一份可落在飞书知识库的 **Account Plan**，并同步客户档案表与商机表。

默认支持四种结果：
- 从零创建 Account Plan
- 在已有 AP 上增量更新
- 仅预览拟更新内容
- 在无法写飞书时输出符合模板的 Markdown 草稿

## 何时触发

以下情况应触发本 Skill：
- 用户明确说：`生成客户计划`、`更新 Account Plan`、`刷新客户档案`、`客户一页纸`、`客户计划`
- 上游回调：S4/S5 完成方案后、S27 归档拜访纪要后、S28 识别商机/风险后
- 已知客户名称或客户记录，需要补全企业概览、资质、政策机会、决策链、价值评估、风险与跟进策略

以下情况不要强行使用本 Skill：
- 只是在会议转写中提取反馈，优先用 `customer-feedback-collection`
- 只是做项目申报规划，优先用 `proposal-generator`

## 必要输入

至少满足以下之一：
- 客户全称
- 客户 `record_id`
- `document_id + record_id`（S4/S5 自动触发）
- `record_id + JSON`（S28 回调触发）

可选补充：
- 用户补充的决策链、预算、竞争情报
- 已有 AP 文档链接或原文
- 明确要求：仅预览 / 仅草稿 / 指定更新章节

如果客户名称是简称或模糊片段，先用 `metainflow-enterprise-query` 做模糊搜索；多候选时先让用户确认，不自动猜测目标企业。

## 依赖路由

优先使用 `openclaw-lark` 插件暴露的飞书 Skill / Tool，不要混用旧版命名：

| 场景 | 优先 Skill / Tool |
|---|---|
| 客户档案、项目、商机、反馈、方案、合同查询与回写 | `feishu-bitable` |
| 搜索客户目录、已有 AP、方案、纪要、反馈文档 | `feishu_search_doc_wiki`、`feishu_drive_file` |
| 定位知识库节点、解析 wiki 链接 | `feishu_wiki_space_node` |
| 读取已有 AP 或其他飞书文档 | `feishu-fetch-doc` |
| 创建新 AP 文档 | `feishu-create-doc` |
| 增量更新已有 AP | `feishu-update-doc` |
| 工商信息、资质证书、企业全称确认 | `metainflow-enterprise-query` |
| 公司近期动态、政策窗口补充验证 | `metainflow-web-search` |

## 执行模式

| 模式 | 适用情况 | 结果 |
|---|---|---|
| 创建模式 | 未找到已有 AP | 新建 AP 文档并挂载 |
| 更新模式 | 已找到已有 AP | 追加式更新，不覆盖历史 |
| 预览模式 | 用户只想先看拟更新内容 | 返回执行计划和关键发现，不写外部系统 |
| 草稿模式 | 无法写飞书或用户明确要文稿 | 输出 Markdown 草稿，结构必须匹配模板 |

## 工作流

### Step 1：客户定位与模式判定

1. 识别输入来源：用户指令 / S4/S5 / S27 / S28 / 手动补充
2. 用 `feishu-bitable` 查询客户档案表，拿到客户编号、等级、标签、负责人、历史更新时间
3. 客户名不稳定时，用 `metainflow-enterprise-query` 校验企业全称
4. 判断是创建、更新、预览还是草稿模式

### Step 2：基础信息刷新

1. 用 `metainflow-enterprise-query` 刷新工商、资质、股东与处罚等企业信息
2. 用 `metainflow-web-search` 补充近期动态；只有涉及“最新窗口 / 最新新闻 / 近期变化”时才搜索
3. 把“事实”与“待验证线索”分开记录，不把搜索摘要直接当确定事实

### Step 3：多维表汇总

至少查询以下表：
- 客户档案表：客户等级、标签、负责人、最近 AP 更新日期
- 项目总表：项目状态、金额、阶段
- 商机表：状态、预估价值、是否存在重复机会
- 客户反馈表：满意度、未闭环项、竞品/风险信息
- 方案管理表：版本、状态、最近完成时间
- 合同管理表：合同金额、状态、到期时间

### Step 4：知识库与历史文档检索

1. 先用 `feishu_search_doc_wiki` 按客户名搜索已有 AP、方案、纪要、报价、反馈文档
2. 若拿到 wiki 链接或 node token，用 `feishu_wiki_space_node` 解析节点和实际对象类型
3. 若需要确认目录位置或移动目标，再用 `feishu_drive_file` 查询文件夹 / 文件元数据
4. 读取已有 AP 时使用 `feishu-fetch-doc`，先判断当前版本结构是否匹配模板
5. 找到已有 AP 则进入更新模式；找不到则进入创建模式

### Step 5：证据整理

为每条事实保留：
- 来源
- 日期
- 原始对象（表记录 / 文档 / 搜索结果）
- 置信度：高 / 中 / 低

没有证据的字段写 `待补充`，不要为了表格完整而虚构内容。

### Step 6：分析生成

基于证据生成以下内容：
- 决策链：决策人 / 评估人 / 使用人 / 影响人及态度
- 政策机会：机会名称、优先级、窗口、前置条件、匹配度
- 价值评估：已服务金额、在谈金额、潜在机会价值、续约概率、LTV
- 竞争情报：仅在纪要、反馈或搜索结果中有依据时输出
- 风险与预警：未闭环反馈、合同到期、竞品威胁、关键人变化
- 跟进策略：下一步行动、优先联系人、时间窗口、30/90 天目标

明确区分：
- `事实`：可直接回溯到资料
- `判断`：基于证据的推断，必要时写明“推断”

### Step 7：政策交叉验证

只有当政策机会要进入正式 AP 或用户要求“最新窗口”时才执行：
1. 用 `feishu-bitable` 查询政策库索引表
2. 必要时用 `metainflow-web-search` 校验窗口和条件变化
3. 若线上结果互相冲突，以内部政策库为主，并标注“需复核”

### Step 8：创建或更新 Account Plan

写入前先读取 [references/template.md](references/template.md)。

创建模式：
1. 用 `feishu-create-doc` 按模板创建新文档，优先直接创建到 wiki 节点或目标文件夹
2. 若创建后仍需调整位置，用 `feishu_drive_file` 移动到 `{客户名称}/01_客户档案/`
3. 若输入是 wiki 节点，优先直接挂到对应节点，不再走旧版文档写入流程

更新模式：
1. 先用 `feishu-fetch-doc` 读取原文结构
2. 保留历史内容，不整段覆盖
3. 用 `feishu-update-doc` 对时间线、更新记录、机会、风险等章节采用 `append` 或 `replace_range` 局部更新，避免 `overwrite`
4. 每次新增内容都标注来源和日期，例如 `2026/03/17 · S28反馈回调`

### Step 9：回写与输出

1. 用 `feishu-bitable` 回写客户档案表：客户等级、标签、最近 AP 更新日期、机会摘要
2. 对新识别机会先查重，再写入或更新商机表
3. 返回：
   - AP 文档链接或 Markdown 草稿
   - 更新摘要
   - 关键发现
   - 仍待补充的信息

## 输出要求

最终输出固定包含 4 部分：
1. `文档结果`：AP 链接或 Markdown 草稿
2. `更新摘要`：新增或变更了哪些章节
3. `关键发现`：机会、风险、决策链、建议动作
4. `待补充`：缺失字段和下一步建议

如果用户要求“只看预览”，输出：
- 拟更新章节
- 每章动作：新增 / 更新 / 追加 / 无变化 / 待澄清
- 关键风险
- 是否建议继续写入飞书

## 严格规则

- 不再使用旧版 18 章节“客户一页纸”结构；统一使用 10 章节 AP 模板
- 更新模式必须保留历史，不得静默覆盖原内容
- 决策链信息不足时写 `待补充`，不虚构人物和态度
- 商机写入前必须查重；已有记录优先更新
- 企业模糊命名时先确认目标企业，再继续写入
- 最新新闻、政策窗口、工商变化属于时效信息，必须先查询再写
- 飞书文档读写统一走 `openclaw-lark` 的 `feishu-create-doc` / `feishu-update-doc` / `feishu-fetch-doc`，不要回退到旧版 `feishu-doc-writer` / `feishu-drive` / `feishu-wiki` 命名
- 禁止使用 `exec`、`python requests` 或手工 `tenant_access_token` 流程直连飞书 OpenAPI；所有飞书副作用必须通过 `~/.openclaw/extensions/openclaw-lark` 注册的 skill/tool 执行
- AI 主观措辞不作为核心输出，重点是结构化事实、判断依据和后续动作

## 参考资料

按需读取，不要一次性全部加载：
- [references/template.md](references/template.md)：正式 AP 模板
- [references/chapter-guide.md](references/chapter-guide.md)：章节填充规则、数据源映射、客户等级规则
- [references/execution-examples.md](references/execution-examples.md)：创建、更新和回调示例
