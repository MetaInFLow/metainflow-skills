---
name: s27-document-archive-manager
description: S27 文档归档管理。接收会议转写/文件/归档指令后，完成信息提取、客户/项目匹配、版本冲突检测、标准命名、飞书执行计划（bitable/drive/doc/wiki/card/im）生成，并支持 finalize 与完整性检查。
---

# S27 Document Archive Manager

一句话：
先用服务器本地 `metainflow-studio-cli` 解析文档与企业线索，再生成 S27 结构化结果和 `Feishu_Skills` 调用计划，确认后再执行 `finalize`。

## 适用范围

- 输入类型：`file | url | text`
- 文档类型：`拜访纪要 | 方案 | 报价 | 合同 | 交付物 | 验收单`
- 运行依赖：
  - 服务器已安装 `metainflow-studio-cli`
  - OpenClaw 已接入 `openclaw-lark` / `Feishu_Skills`

## 目录结构

- `scripts/run_pipeline.py`：主入口（`prepare/finalize/completeness-check`）
- `scripts/common.py`：CLI 调用与通用工具
- `scripts/extract_document_facts.py`：文档解析与字段抽取
- `scripts/match_customer_project.py`：客户/项目匹配
- `scripts/check_version_conflict.py`：版本冲突检测
- `scripts/normalize_naming.py`：标准命名与目录映射
- `scripts/build_card_payload.py`：卡片 payload 组装
- `scripts/update_account_plan.py`：Account Plan 追加 patch
- `scripts/write_prepare_state.py`：prepare 产物落盘
- `scripts/smoke_openclaw_feishu_test.sh`：测试环境冒烟脚本（通过 openclaw-lark 执行 Feishu_Skills）
- `config/field_mapping.json`：字段映射与主数据配置
- `config/naming_rules.json`：命名规则
- `config/feishu_skill_mapping.json`：Feishu_Skills 编排映射

## 阶段定义

1. `prepare`
   - 解析输入并抽取文档事实
   - 客户/项目匹配（以飞书主数据为真相源）
   - 版本冲突检测（索引冲突 + 同名文件冲突）
   - 标准化命名与目录映射
   - 生成表更新计划、Account Plan patch、确认卡片
   - 输出 `feishu_skill_plan.preview.json`
2. `finalize`
   - 校验 `confirmation_token` 与会话状态
   - 接收动作：`confirm | overwrite | save_as_new_version | cancel`
   - 生成最终 `feishu_skill_plan.json`
3. `completeness-check`
   - 对照应归档清单输出缺失项与阻塞状态
   - 生成检查写入计划和提醒卡片计划

## 输入参数约束

- `prepare` 必填：
  - `--source`
  - `--source-type`
  - `--operator-id`
  - `--operator-name`
  - `--thread-id`
  - `--output-dir`
- `finalize` 必填：
  - `--session-dir`
  - `--confirmation-token`
  - `--confirmed-by`
  - `--action`
- `completeness-check` 推荐至少提供其一：
  - `--customer-id | --project-id | --customer-hint | --project-hint`

## 关键输出契约

- `prepare_result.json`
  - `session_id`
  - `status`: `ready_for_confirmation | needs_confirmation | failed`
  - `confirmation_token`
- `version_check.json`
  - `blocking_conflict`
  - `conflict_type`
  - `conflict_records`
- `card_payload.json`
  - 用于 `feishu-card` 的确认卡片 payload
- `feishu_skill_plan.preview.json`
  - 仅预览，不应直接执行写入动作
- `finalize_result.json`
  - `status`: `ready_for_feishu_skill_execution | cancelled | failed`
  - `audit_log`
- `feishu_skill_plan.json`
  - 可执行的飞书技能调用计划

## Feishu 执行边界

- S27 自身不直接调用飞书 HTTP API
- S27 只输出计划，由 OpenClaw 调度以下技能：
  - `feishu-contact`
  - `feishu-bitable`
  - `feishu-drive`
  - `feishu-doc-writer`
  - `feishu-wiki`
  - `feishu-card`
  - `feishu-im`

## 测试模式与生产模式

- 测试模式：
  - 只允许写测试多维表/测试目录
  - 禁止写正式业务表
  - 建议在提示词里显式声明“仅测试表写入”
- 生产模式：
  - 允许执行 `feishu_skill_plan.json` 中的正式写入
  - 必须经过 `prepare -> 用户确认 -> finalize`

## 测试环境约束

- 本 Skill 的飞书能力统一通过 `openclaw-lark` 执行，不允许业务代码直连飞书 HTTP API。
- `prepare` 阶段只做预判和计划生成；正式查询/写入由 `feishu-bitable/drive/doc-writer/wiki/card/im` 在执行阶段完成。
- 测试环境联调建议使用 `scripts/smoke_openclaw_feishu_test.sh`，并显式指定测试 `session-id / output-dir`。

## 命令示例

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

## 失败与阻断规则

- 找不到 `metainflow` 且模块回退也失败时，返回环境错误
- 文档类型、客户或项目未达到最低匹配条件时，不直接允许提交
- 冲突未被显式处理时，`finalize` 阻断
- `action=cancel` 时不得产生正式写入计划
