---
name: s28-customer-feedback-opportunity-analyzer
description: 从会议转写或沟通记录中提取客户反馈，完成分类分级、满意度标记和商机识别；飞书相关执行统一委派给 feishu-bitable、feishu-doc-writer、feishu-wiki、feishu-im、feishu-card 等独立 Skills
metadata: '{"openclaw":{"skillKey":"s28-customer-feedback-opportunity-analyzer","emoji":"📣","homepage":"https://github.com/MetaInFLow/metainflow-skills/tree/main/OpenClaw/s28-customer-feedback-opportunity-analyzer"}}'
---

# S28 Customer Feedback Opportunity Analyzer

## 任务定位

本 Skill 只负责业务判断和执行编排，不再内置任何飞书脚本。

**本 Skill 负责**：
- 反馈提取与结构化
- 分类分级与满意度标记
- 商业机会识别与风险判断
- 责任人、处理时限、改进建议生成
- 组织写回多维表、更新 Account Plan、发送通知所需的数据载荷

**飞书执行统一委派给独立 Skills**：
- `feishu-bitable`：客户查询、反馈回写、商机回写
- `feishu-doc-writer`：云文档创建、追加写入 Account Plan
- `feishu-wiki`：文档挂载到 Wiki 节点
- `feishu-card`：构造交互卡片
- `feishu-im`：发送文本或交互卡片消息

不要再调用 `scripts/feishu_bitable.py`、`scripts/feishu_doc.py`、`scripts/feishu_message.py`，也不要在本 Skill 内重新封装飞书 SDK。

## 触发条件

- 用户发送会议转写/沟通记录要求提取反馈
- 用户报告客户投诉或不满
- 用户需要识别商机信号
- 用户需要收集客户满意度信息

## 当前运行配置

先读取 [references/runtime_configuration.md](references/runtime_configuration.md)。

当前已确认的最小可用配置是客户反馈多维表：
- `app_token`: `LygubYc0pakvrHs4u6ucIkWcnJf`
- `lead_table_id`: `tblOOFAs2f22JXF1`（`1- 线索管理表`，也是你提供的共享链接所在表）
- `lead_view_id`: `vewAErGSTc`
- `feedback_table_id`: `tbliFS6wrDfThjCl`（`客户反馈表`）
- `customer_table_id`: `tbl9pOa5H0YcTRrx`（`公司-客户档案池`）
- `opportunity_table_id`: `tbl1r1jqPH9GpDB0`（`2- 商机主表`）

`App Secret` 不写入 Skill 文件，只允许运行时从环境变量读取。

## 执行模式

- **最小模式**：完成反馈提取、分类分级、商机判断，并写入 `客户反馈表`
- **扩展模式**：当前实例已经具备客户表、商机表、交付表等核心表 ID；补齐 `WIKI_SPACE_ID`、归档目录和接收人 ID 后，再执行文档归档、Account Plan 更新和消息通知

如果缺少执行某一步所需的飞书配置，就输出结构化草案并停止在确认阶段，不要伪造写回结果。

## 执行原则

1. 先完成抽取和判断，再做任何飞书副作用操作。
2. 默认先给用户确认；只有用户明确要求“直接写回”时才跳过确认。
3. 高敏感反馈可以建议即时通知，但仍需用户确认或明确授权。
4. 客户、项目、责任人、飞书接收人 ID 缺失时，不要猜测。
5. 多维表日期字段默认按 13 位毫秒时间戳写入。

## 操作步骤

### Step 1: 输入整理

先补齐最小上下文：
- 客户名称
- 沟通来源：会议/微信/电话/邮件/手动输入
- 沟通日期
- 业务阶段：售前/售中/交付/售后
- 项目编号或关联版本（如用户提供）

若客户名称或上下文缺失且无法从原文判断，先向用户确认，不要直接进入写回。

### Step 2: 反馈提取

从输入中识别所有评价、意见、建议、不满、肯定，并拆成最小可处理条目。

每条反馈至少要有：
- 原文
- 反馈来源
- 涉及主题
- 是否需要后续动作

**输出格式**：
```
反馈条目列表：
1. [原文] "报价偏高，竞品低30%"
2. [原文] "政策匹配能力专业"
3. [原文] "明年想申请专精特新"
```

---

### Step 3: 反馈分类

为每条反馈标记类型。

**分类选项**：
- 价格
- 方案质量
- 服务能力
- 交付进度
- 新需求
- 沟通效率
- 合同条款
- 售后支持
- 其他

**规则参考**：详见 [references/feedback_classification_rules.md](references/feedback_classification_rules.md)

---

### Step 4: 敏感度分级与满意度标记

判断反馈的重要程度和紧急程度。

**分级标准**：
| 等级 | 触发条件 | 处理时限 |
|---|---|---|
| 高 | 含竞品比价、威胁终止、投诉升级、法律风险关键词 | 24h |
| 中 | 方案修改、进度不满、新需求/商机信号 | 3工作日 |
| 低 | 随口建议、正面肯定、非关键改进 | 下次跟进前 |

**强制规则**：含"竞品""终止""投诉""起诉""换供应商"等关键词 → 敏感度强制标高

**标记选项**：
- 满意
- 中性
- 不满意

**判断依据**：
- 正面评价词 + 肯定语气 → 满意
- 负面评价词 + 不满语气 → 不满意
- 建议性表述/中性描述 → 中性

**规则参考**：详见 [references/feedback_classification_rules.md](references/feedback_classification_rules.md)

---

### Step 5: 商业机会识别

判断反馈中是否包含商业机会信号。

**信号类型**：
| 信号类型 | 触发语义 | 输出动作 |
|---|---|---|
| 新资质申报 | "想申请""打算认定""专精特新""高新" | 商机表新建 + Account Plan 追加 + 通知方案部 |
| 增购/加项 | "还能不能做""追加""多加一个" | 商机表新建 + 通知销售 |
| 续约 | "明年继续""下一期""长期合作" | 商机表新建 + Account Plan 标记 |
| 转介绍 | "推荐给""介绍朋友""同行也需要" | 商机表新建（新线索）+ 通知销售 |
| 不满转机会 | "如果能解决就继续" | 高敏感反馈 + 条件性商机 |

**规则参考**：详见 [references/opportunity_identification_rules.md](references/opportunity_identification_rules.md)

**Step 5a - 机会结构化**（识别到机会时执行）：
输出：
- 机会描述
- 预估价值（如有信息）
- 建议行动
- 关联政策/资质

---

### Step 6: 客户匹配与上下文补全

**匹配逻辑**：
1. 用户已给出明确客户名称时，直接沿用
2. 若已配置 `CUSTOMER_TABLE_ID`，委派 `feishu-bitable` 进行企业名称模糊匹配
3. 返回尽可能多的上下文：客户名称、项目编号、方案/报价/合同版本、Account Plan 链接
4. 未匹配或多条命中 → 停下来让用户确认

**字段映射参考**：详见 [references/bitable_field_mapping.md](references/bitable_field_mapping.md)

---

### Step 7: 生成改进建议与处理建议

为每条反馈生成具体的改进方向和处理动作。

**智能体执行**：
1. 结合反馈内容、客户历史、项目阶段生成具体建议
2. 改进建议：长期改进方向
3. 处理建议：具体动作 + 时限

**示例**：
- 改进建议：重新评估报价策略，对比竞品区间
- 处理建议：48h内输出调整方案，同步主管

---

### Step 8: 生成执行包

把前面的判断结果整理成可执行载荷，至少包含以下四类：

1. `feedback_records`
   当前明确会写入客户反馈表的记录集合
2. `opportunity_records`
   仅当识别出商机且商机表配置齐全时才会执行
3. `account_plan_update`
   需要追加到 Account Plan 的 Markdown 内容
4. `notifications`
   需要发送给责任人/主管的消息卡片数据

**推荐结构**：
```json
{
  "feedback_records": [
    {
      "客户名称": "深圳市同步齿科医疗股份有限公司",
      "业务阶段": "售前",
      "反馈类型": "价格",
      "敏感度": "高",
      "满意度": "不满意",
      "原文摘要": "报价偏高，竞品低30%"
    }
  ],
  "opportunity_records": [],
  "account_plan_update": {
    "title": "20260315_反馈记录_深圳市同步齿科医疗股份有限公司",
    "sections": ["新增机会", "风险提示", "行动项"]
  },
  "notifications": [
    {
      "receiver_role": "销售负责人",
      "sensitivity": "高",
      "card_type": "feedback_alert"
    }
  ]
}
```

---

### Step 9: 用户确认

在执行任何飞书写回前，默认展示：
1. 提取出的反馈条目
2. 分类、敏感度、满意度
3. 客户匹配结果
4. 商机识别结果
5. 待执行的飞书动作列表

**示例输出**：
```
已提取 3 条反馈：
1. [价格|高|不满意] 报价偏高，竞品低30%
2. [服务能力|低|满意] 政策匹配能力专业
3. [新需求|中|中性] 明年想申请专精特新

客户匹配：深圳市同步齿科医疗股份有限公司（QF-P-0078）
商机识别：专精特新申报意向
待执行动作：
- 客户反馈表写入 3 条
- 商机表新增 1 条
- Account Plan 追加 1 段
- 通知责任人 1 人

请确认是否正确？如需修改请告知。
```

---

### Step 10: 委派飞书相关执行

#### 10a. 多维表写回

委派 `feishu-bitable`：
- 写入客户反馈表
- 若 `CUSTOMER_TABLE_ID` 已配置，执行客户模糊匹配
- 若 `OPPORTUNITY_TABLE_ID` 已配置且识别到商机，创建商机记录

当前默认反馈表配置见 [references/runtime_configuration.md](references/runtime_configuration.md) 和 [references/bitable_field_mapping.md](references/bitable_field_mapping.md)。

#### 10b. 文档归档与 Account Plan 更新

委派 `feishu-doc-writer`，必要时再委派 `feishu-wiki`：
- 原文归档成云文档
- 将“新增机会 / 风险提示 / 行动项”追加到 Account Plan
- 若需要挂载到 Wiki，再使用 `feishu-wiki`

优先使用 Markdown 转换接口，不要手写 Block JSON，除非有飞书特有块需求。

#### 10c. 通知责任人

先按 [references/notification_template.md](references/notification_template.md) 生成卡片数据，再：
- 用 `feishu-card` 组织交互卡片
- 用 `feishu-im` 发送卡片或文本消息

**通知规则**：
- 高敏感 → 责任人 + 主管（即时）
- 中敏感 → 责任人
- 低敏感 → 只写入表，不主动推送

**责任人匹配规则**：
- 价格 → 销售负责人
- 方案质量 → 方案部
- 服务能力 → 客户成功
- 交付进度 → 交付经理
- 售后支持 → 售后团队

---

### Step 11: 主动跟踪（异步）

多维表自动化功能负责超时提醒。

**跟踪机制**：
- 处理时限字段写入后，由飞书多维表自动化功能发送提醒
- 24h 未处理 → 自动提醒责任人
- 48h 未处理 → 升级主管
- 标记"已处理" → 闭环

## 资源索引

### 外部 Skill 路由
| 场景 | 使用 Skill |
|---|---|
| 客户查询 / 反馈回写 / 商机回写 | `feishu-bitable` |
| 原文归档 / Account Plan 追加 | `feishu-doc-writer` |
| Wiki 节点挂载 | `feishu-wiki` |
| 卡片结构编排 | `feishu-card` |
| 消息发送 | `feishu-im` |

### 参考文档
| 文档 | 用途 | 阅读时机 |
|---|---|---|
| [references/runtime_configuration.md](references/runtime_configuration.md) | 当前飞书运行配置与降级规则 | 开始执行前 |
| [references/feedback_classification_rules.md](references/feedback_classification_rules.md) | 反馈分类分级规则 | Step 2, Step 3, Step 4 |
| [references/opportunity_identification_rules.md](references/opportunity_identification_rules.md) | 商业机会识别规则 | Step 5 |
| [references/notification_template.md](references/notification_template.md) | 飞书消息卡片模板 | Step 10c |
| [references/bitable_field_mapping.md](references/bitable_field_mapping.md) | 多维表字段映射说明 | Step 6, Step 10a |

## 注意事项

1. **密钥管理**：`App Secret` 不得写入 `SKILL.md`、参考文档或脚本，只能从环境变量读取。
2. **配置降级**：当前实例已确认线索表、客户表、商机表、交付表、反馈表；Wiki、归档目录和接收人 ID 未配置时，文档和通知动作只生成草案不执行。
3. **责任人映射**：需结合实际组织架构，把“角色”落到真实 `open_id`、`user_id` 或 `chat_id`。
4. **敏感度判断**：含竞品、终止、投诉等关键词必须标高敏感。
5. **商业机会**：宁多勿漏，但写回前要让用户确认，尤其是“条件性商机”。
6. **日期格式**：写多维表时，日期字段优先按 13 位毫秒时间戳处理。

## 使用示例

### 示例1：拜访后反馈提取

**用户输入**：
```
刚拜访完深圳市同步齿科，客户反馈：
1. 上次方案报价偏高，竞品低30%
2. 政策匹配能力专业
3. 明年想申请专精特新
```

**Skill 执行流程**：
1. 提取 3 条反馈
2. 分类分级：价格(高/不满意)、服务能力(低/满意)、新需求(中/中性)
3. 识别商机：专精特新申报
4. 匹配客户：深圳市同步齿科医疗股份有限公司
5. 生成改进建议和处理建议
6. 向用户展示待执行动作
7. 确认后委派 `feishu-bitable` 写入客户反馈表
8. 若商机表和文档配置齐全，再继续委派外部飞书 Skills 执行扩展动作

### 示例2：投诉处理

**用户输入**：
```
客户投诉：交付进度太慢，说要换供应商了
```

**Skill 执行流程**：
1. 提取反馈，识别关键词"换供应商"
2. 敏感度强制标高
3. 生成紧急处理建议
4. 经用户确认后委派 `feishu-card` + `feishu-im` 即时通知责任人和主管

### 示例3：商机识别

**用户输入**：
```
客户说可以推荐给同行朋友
```

**Skill 执行流程**：
1. 识别转介绍信号
2. 生成商机记录草案
3. 若 `OPPORTUNITY_TABLE_ID` 已配置，则委派 `feishu-bitable` 新建商机
4. 若接收人已配置，则委派 `feishu-im` 通知销售跟进
