# 飞书运行配置

## 当前已知配置

- 飞书 App ID：`cli_a9324b7443799cce`
- App Secret：不写入任何 Skill 文件，运行时从 `FEISHU_APP_SECRET` 读取
- 共享链接：`https://metainflow.feishu.cn/base/LygubYc0pakvrHs4u6ucIkWcnJf?table=tblOOFAs2f22JXF1&view=vewAErGSTc`
- `app_token`：`LygubYc0pakvrHs4u6ucIkWcnJf`
- `lead_table_id`：`tblOOFAs2f22JXF1`（`1- 线索管理表`）
- `lead_view_id`：`vewAErGSTc`
- `feedback_table_id`：`tbliFS6wrDfThjCl`（`客户反馈表`）
- `customer_table_id`：`tbl9pOa5H0YcTRrx`（`公司-客户档案池`）
- `opportunity_table_id`：`tbl1r1jqPH9GpDB0`（`2- 商机主表`）
- `follow_up_table_id`：`tblk4eanWvzgbX7j`（`2-1 客户跟进记录`）
- `proposal_table_id`：`tblF9IViphrnPyiV`（`3- 方案报价表`）
- `contract_table_id`：`tblEsSKlvkHhkzOh`（`4- 合同与回款情况表`）
- `delivery_table_id`：`tblEdGFiJ21k6KfO`（`产业政策交付表`）
- `document_index_table_id`：`tblDLfTnycWhIx2O`（`文档索引表`）
- `revisit_table_id`：`tblmlQtqjz79txFN`（`复访记录表`）

## 建议运行时变量

- `FEISHU_APP_ID=cli_a9324b7443799cce`
- `FEISHU_APP_SECRET=<local secret>`
- `FEEDBACK_APP_TOKEN=LygubYc0pakvrHs4u6ucIkWcnJf`
- `LEAD_TABLE_ID=tblOOFAs2f22JXF1`
- `LEAD_VIEW_ID=vewAErGSTc`
- `FEEDBACK_TABLE_ID=tbliFS6wrDfThjCl`
- `CUSTOMER_TABLE_ID=tbl9pOa5H0YcTRrx`
- `OPPORTUNITY_TABLE_ID=tbl1r1jqPH9GpDB0`
- `DELIVERY_TABLE_ID=tblEdGFiJ21k6KfO`

## 当前 Base 表总览

- `1- 线索管理表`：`tblOOFAs2f22JXF1`，线索入口和共享链接所在表
- `2- 商机主表`：`tbl1r1jqPH9GpDB0`，商机写回
- `2-1 客户跟进记录`：`tblk4eanWvzgbX7j`，跟进沉淀
- `3- 方案报价表`：`tblF9IViphrnPyiV`，版本与报价上下文
- `4- 合同与回款情况表`：`tblEsSKlvkHhkzOh`，客户历史上下文
- `4-1 回款明细表`：`tblShhkpn5KwyVxk`，合同回款明细
- `公司-客户档案池`：`tbl9pOa5H0YcTRrx`，客户匹配与 Account Plan 链接
- `📝-渠道档案表`：`tblACNhQfm4ljeVI`，线索来源上下文
- `公司归属人-联系人`：`tbleflR8h2ezLSOA`，联系人关联
- `政策知识库`：`tbloCRfmoFG7Gdgp`，方案/政策上下文
- `文档索引表`：`tblDLfTnycWhIx2O`，文档归档索引
- `政策目录表`：`tbljYsGTMWyydLqh`，政策目录
- `产品目录表`：`tblSCPkzDLerdo6J`，产品上下文
- `供应商协同表`：`tblIan9iTTHbQOh6`，交付协同
- `产业政策交付表`：`tblEdGFiJ21k6KfO`，项目编号与交付主表
- `服务产品交付表（协同））`：`tblSeGXlgkx5fRCU`，交付任务
- `复访记录表`：`tblmlQtqjz79txFN`，满意度与续单上下文
- `客户反馈表`：`tbliFS6wrDfThjCl`，反馈主写入表

## 当前实例的执行映射

1. 共享链接进入 `1- 线索管理表`，可作为线索来源和商机上下文。
2. 客户匹配优先查 `公司-客户档案池` 的 `企业名称`。
3. 反馈主记录写入 `客户反馈表`。
4. `客户反馈表.客户名称` 实际写入的是客户档案池记录关联，不是纯文本。
5. `客户反馈表.项目编号` 实际写入的是 `产业政策交付表` 记录关联。
6. 商机识别后写入 `2- 商机主表`，并回链客户/线索。
7. 客户的 Account Plan 链接来自 `公司-客户档案池.客户Account Plan（飞书云文档）`。
8. 如需做文档归档索引，可写 `文档索引表` 并关联 `产业政策交付表`。

## 全链路仍缺少的配置

- `WIKI_SPACE_ID`
- `ACCOUNT_PLAN_PARENT_NODE_ID`
- 责任人 / 主管 / 协作者的真实 `open_id`、`user_id` 或 `chat_id`

## 降级规则

1. 当前已经可以执行“反馈提取 + 客户匹配 + 商机判断 + 写入客户反馈表”。
2. 如果客户未能匹配到 `公司-客户档案池`，先让用户确认，再决定是否只写文本草案。
3. 如果商机关联客户或线索无法确定，商机只生成结构化草案，不盲写关联字段。
4. 如果文档或 Wiki 配置未补齐，Account Plan 更新和原文归档只生成 Markdown 草案。
5. 如果接收人 ID 未配置，通知卡片只生成内容，不发送消息。

## 安全规则

1. 不在 `SKILL.md`、参考文档、脚本、命令历史中保存 `App Secret` 明文。
2. 如需共享配置，只共享 `App ID`、`app_token`、`table_id` 等非密钥信息。
3. 真正执行飞书写操作前，优先让用户确认目标表、目标人和目标文档。
