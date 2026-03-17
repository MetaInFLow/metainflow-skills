---
name: s27-document-archive-manager
description: 收到会议转写、文件或归档指令后，自动完成文档信息提取、客户/项目匹配、版本冲突检测、标准化命名、归档执行计划生成、Account Plan 追加计划和飞书确认卡片 payload 生成。适用于“归档这个文件”“整理拜访纪要并归档”“检查某客户归档完整性”“合同/方案/报价/交付物归档”等场景。
---

# S27 Document Archive Manager

一句话定义：

先用服务器本地安装的 `metainflow-studio-cli` 做文档解析和企业查询，再基于 S27 的规则生成标准化归档计划、飞书卡片和 `Feishu_Skills` 编排计划；只有确认后才进入 `finalize`。

## 适用范围

- 输入可以是：
  - 本地文件
  - URL
  - 纯文本
- 支持文档类型：
  - 拜访纪要
  - 方案
  - 报价
  - 合同
  - 交付物
  - 验收单
- 运行依赖：
  - 服务器已安装 `metainflow-studio-cli`
  - OpenClaw 已安装 `openclaw-lark`

## 目录结构

- `scripts/run_pipeline.py`: 总入口，支持 `prepare`、`finalize`、`completeness-check`
- `scripts/common.py`: CLI 调用、JSON 工具、日期与命名辅助函数
- `scripts/extract_document_facts.py`: 调用 `metainflow parse-doc` 并抽取结构化字段
- `scripts/match_customer_project.py`: 根据抽取结果匹配客户和项目
- `scripts/check_version_conflict.py`: 查询索引快照，识别版本冲突
- `scripts/normalize_naming.py`: 生成标准文件名与目录
- `scripts/build_card_payload.py`: 生成确认卡片 payload
- `scripts/update_account_plan.py`: 生成 Account Plan 追加 patch
- `scripts/write_prepare_state.py`: 汇总并落盘 `prepare` 状态
- `config/field_mapping.json`: 表结构、目录和示例主数据映射
- `config/naming_rules.json`: 文档命名规则与版本策略
- `config/feishu_skill_mapping.json`: `Feishu_Skills` 能力映射与调用计划模板

## 默认工作流

1. `prepare`
   - 调 `metainflow parse-doc --output json`
   - 抽取文档类型、客户、项目、日期、版本等
   - 匹配客户/项目
   - 检查索引冲突
   - 生成标准命名、表更新计划、Account Plan 追加计划
   - 输出卡片 payload 与 `Feishu_Skills` 调用计划预览
2. `finalize`
   - 校验 `confirmation_token`
   - 根据确认动作更新最终命名或冲突动作
   - 输出最终 `feishu_skill_plan.json`
3. `completeness-check`
   - 对照应归档清单输出缺失项
   - 生成检查表写入计划和提醒卡片 payload

## 命令示例

macOS / Linux:

```bash
python3 ./scripts/run_pipeline.py \
  --stage prepare \
  --source ./examples/visit_minutes_sample.txt \
  --source-type file \
  --operator-id demo-user \
  --operator-name 演示用户 \
  --thread-id thread-s27-demo \
  --output-dir ./output/s27-demo
```

```bash
python3 ./scripts/run_pipeline.py \
  --stage finalize \
  --session-dir ./output/s27-demo \
  --confirmation-token <prepare_result中的token> \
  --confirmed-by demo-user \
  --action confirm
```

```bash
python3 ./scripts/run_pipeline.py \
  --stage completeness-check \
  --project-hint QF-P-0078 \
  --customer-hint 深圳某科技 \
  --operator-id demo-user \
  --operator-name 演示用户 \
  --thread-id thread-s27-demo \
  --output-dir ./output/s27-completeness
```

## `Feishu_Skills` 使用约定

- 本 skill 不直接访问飞书 HTTP API
- 本 skill 不再暴露底层 `lark.*` 原子动作
- `prepare` 输出 `feishu_skill_plan.preview.json`
- `finalize` 与 `completeness-check` 输出 `feishu_skill_plan.json`
- OpenClaw 运行时应按该计划调用对应的 `Feishu_Skills` 完成：
  - `feishu-contact`
  - `feishu-bitable`
  - `feishu-drive`
  - `feishu-doc-writer`
  - `feishu-wiki`
  - `feishu-card`
  - `feishu-im`

## 输出约定

- `prepare` 必产出：
  - `prepare_result.json`
  - `card_payload.json`
  - `session_state.json`
  - `feishu_skill_plan.preview.json`
- `finalize` 必产出：
  - `finalize_result.json`
  - `feishu_skill_plan.json`
- `completeness-check` 必产出：
  - `completeness_check_result.json`
  - `feishu_skill_plan.json`

## 失败处理

- 找不到 `metainflow` 且模块回退也失败时，返回环境错误
- 文档类型、客户或项目未达到最低匹配条件时，不直接允许提交
- 冲突未显式处理时，`finalize` 会阻断
