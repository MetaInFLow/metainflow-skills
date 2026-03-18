---
name: s27-document-archive-manager
description: S27文档归档管理，实现文档智能解析、客户项目匹配、版本冲突检测、标准化命名与飞书执行计划生成；支持 OpenClaw 本地/联调烟测；当用户需要归档拜访纪要/方案/报价/合同/交付物/验收单、检查项目文档完整性、查询归档状态或处理版本冲突时使用。
dependency:
  system:
    - metainflow-studio-cli
---

# S27 文档归档管理

## 任务目标
- 本 Skill 用于：文档归档全流程管理，从文档解析到飞书执行计划生成
- 能力包含：文档解析、字段抽取、客户/项目匹配、版本冲突检测、标准命名、执行计划生成、完整性检查
- 触发条件：用户发送归档指令、上传文件需归档、要求完整性检查、或主控调度归档任务

## 前置准备
- 服务器需预装 `metainflow-studio-cli` 命令行工具（用于文档解析）
- 配置文件已包含在 `config/` 目录（字段映射、命名规则、飞书技能映射）
- 输出目录将自动创建，包含会话状态和执行计划

## OpenClaw 测试快速开始

用于 OpenClaw 测试时，优先走 smoke 脚本，避免手动拼参数。

### 本地模式（不依赖远端 Agent）
```bash
bash scripts/smoke_openclaw_local.sh /tmp/openclaw-s27-local
```

### Feishu 测试环境联调（走 s27 Agent）
```bash
bash scripts/smoke_openclaw_feishu_test.sh /tmp/openclaw-s27-feishu-test
```

### 本地直连飞书 E2E（prepare + finalize + 执行写表）
```bash
bash scripts/smoke_openclaw_local_feishu_e2e.sh /tmp/openclaw-s27-local-feishu-e2e
```

可选环境变量：
- `S27_ACTION=save_as_new_version|overwrite|confirm`
- `S27_OPENCLAW_AGENT_MODE=--agent s27|--local`（默认 `--agent s27`）
- `S27_EXEC_TIMEOUT=420`、`S27_EXEC_RETRIES=2`
- `S27_SKIP_EXECUTE=true`（只生成计划，不执行飞书写入）

### 最低验收标准
- 输出目录下存在 `prepare_result.json`、`card_payload.json`、`feishu_skill_plan.preview.json`
- `prepare_result.json.status` 为 `ready_for_confirmation` 或 `needs_confirmation`
- 若存在冲突，`version_check.json` 中应包含明确的推荐动作（`overwrite` 或 `save_as_new_version`）

## 运行模式

本 Skill 支持三种运行模式，通过 `--stage` 参数控制：

| 模式 | 触发场景 | 核心产出 |
|------|----------|----------|
| prepare | 用户发送文件或归档指令 | 预览计划 + 确认卡片 |
| finalize | 用户确认/覆盖/新版本/取消 | 可执行的最终计划 |
| completeness-check | 用户要求检查归档完整性 | 缺失清单 + 提醒卡片 |

## 操作步骤

### 模式一：prepare（预览计划）

**步骤 1：文档解析与字段抽取**
- 调用 `scripts/run_pipeline.py --stage prepare` 处理输入文档
- 脚本使用 metainflow-studio-cli 解析输入，提取：文档类型、客户名、项目编号、日期、版本号
- 参数说明：
  ```bash
  python3 scripts/run_pipeline.py \
    --stage prepare \
    --source <文件路径/URL/文本> \
    --source-type file|url|text \
    --operator-id <操作人ID> \
    --operator-name <操作人姓名> \
    --thread-id <会话ID> \
    --output-dir ./output/<会话ID>
  ```

**步骤 2：客户/项目匹配**
- 脚本以飞书多维表为主数据源匹配客户档案表和项目总表
- 若主控已传入 `customer_name` 和 `project_id` 则直接使用，否则进行模糊匹配
- 置信度不足时标记 `status=needs_confirmation`

**步骤 3：版本冲突检测**
- 查询归档索引表和 Drive 目录，检测同名文件或同版本记录
- 有冲突时标记 `blocking_conflict=true`，推荐处理动作

**步骤 4：标准命名与目录映射**
- 参考命名规则配置（`config/naming_rules.json`）生成标准文件名
- 根据文档类型映射到目标目录（参考 `config/field_mapping.json`）

**步骤 5：生成执行计划预览**
- 组装 `feishu_skill_plan.preview.json`，包含：
  - drive 上传操作
  - doc-writer 创建操作
  - wiki 挂载操作
  - bitable 写入操作
  - card+im 确认卡片

**步骤 6：输出产物**
- `prepare_result.json`：包含 session_id、status、confirmation_token
- `version_check.json`：冲突检测结果
- `card_payload.json`：确认卡片 payload
- `feishu_skill_plan.preview.json`：预览计划（不可直接执行）

**智能体任务**：
- 向用户展示匹配结果和冲突检测结果
- 若匹配失败或存在冲突，请求用户确认处理方式
- 保存 confirmation_token 用于后续 finalize 阶段

### 模式二：finalize（确认执行）

**步骤 1：校验确认令牌**
- 调用 `scripts/run_pipeline.py --stage finalize`
- 校验 `confirmation_token` 有效且匹配会话状态

**步骤 2：根据 action 处理**
- `confirm`：输出最终计划（无冲突或冲突已处理）
- `overwrite`：覆盖已有文件，更新索引版本
- `save_as_new_version`：版本递增，保留旧版
- `cancel`：不生成计划，记录取消日志

**步骤 3：输出最终产物**
```bash
python3 scripts/run_pipeline.py \
  --stage finalize \
  --session-dir ./output/<会话ID> \
  --confirmation-token <token> \
  --confirmed-by <操作人ID> \
  --action confirm|overwrite|save_as_new_version|cancel
```

输出：
- `feishu_skill_plan.json`：可执行计划（由 OpenClaw 调度执行）
- `finalize_result.json`：执行状态与审计日志

**智能体任务**：
- 验证 confirmation_token 匹配
- 若存在冲突且用户未选择 overwrite/save_as_new_version，阻断执行
- 将 `feishu_skill_plan.json` 交付给 OpenClaw 调度执行

### 模式三：completeness-check（完整性检查）

**步骤 1：查询应归档清单**
- 基于客户/项目的业务阶段查询应归档文档清单
- 必需文档类型：方案、拜访纪要、报价、合同、交付物、验收单

**步骤 2：比对归档索引**
- 比对归档索引表，输出缺失项清单和阻塞状态

**步骤 3：生成提醒计划**
```bash
python3 scripts/run_pipeline.py \
  --stage completeness-check \
  --project-hint <项目编号或关键词> \
  --customer-hint <客户名称或关键词> \
  --operator-id <操作人ID> \
  --operator-name <操作人姓名> \
  --thread-id <会话ID> \
  --output-dir ./output/completeness-<项目编号>
```

输出：
- `completeness_check_result.json`：缺失文档清单和建议
- `feishu_skill_plan.json`：提醒卡片发送计划

## 输入输出说明

### 主控调度时的输入映射

| 主控传入字段 | S27 参数 | 说明 |
|-------------|----------|------|
| upstream_data.file_token | --source | 飞书文件 token 或本地路径 |
| upstream_data.file_type | --source-type | file / url / text |
| upstream_data.customer_name | 内部匹配用 | 优先使用，跳过模糊匹配 |
| upstream_data.project_id | 内部匹配用 | 优先使用，跳过模糊匹配 |
| context.operator_id | --operator-id | 当前操作人 |
| context.operator_name | --operator-name | 操作人姓名 |
| context.thread_id | --thread-id | 会话 ID |

### archive_summary 结构

供 S11 消费的归档摘要格式：
```json
{
  "document_type": "方案",
  "file_name": "QF-P-0078_v2_终稿.xlsx",
  "archive_path": "客户文档库/深圳市同步齿科/02_售前/方案/",
  "wiki_node_url": "https://xxx.feishu.cn/wiki/...",
  "file_url": "https://xxx.feishu.cn/drive/...",
  "version": "v2",
  "archived_at": "2026-03-18T14:30:00+08:00"
}
```

完整 Schema 参考：[数据契约](references/s27_data_contracts.md)

## 资源索引

### 核心脚本
- `scripts/run_pipeline.py`：归档流程主入口
- `scripts/common.py`：CLI 调用与通用工具函数
- `scripts/extract_document_facts.py`：文档解析与字段抽取
- `scripts/match_customer_project.py`：客户/项目匹配逻辑
- `scripts/check_version_conflict.py`：版本冲突检测
- `scripts/normalize_naming.py`：标准化命名与目录映射
- `scripts/build_card_payload.py`：确认卡片 payload 构建
- `scripts/smoke_openclaw_local_feishu_e2e.sh`：本地联调飞书一键 E2E 校验

### 配置文件
- `config/field_mapping.json`：飞书多维表字段映射与主数据配置
- `config/naming_rules.json`：文档命名规则模板
- `config/feishu_skill_mapping.json`：飞书技能映射与根节点配置

### 参考文档
- `references/s27_data_contracts.md`：数据契约定义（输入输出结构规范）

### 测试样例
- `examples/visit_minutes_sample.txt`：OpenClaw smoke test 默认输入样例

## 与其他 Skill 的分工

| 场景 | S27 职责 | 其他 Skill 职责 |
|------|----------|----------------|
| S4 生成 Excel 后 | 归档半成品 Excel | S11 创建/更新 AP |
| S5 生成终版后 | 归档终版 Excel，版本递增 | S11 更新 AP 需求章节 |
| 用户主动归档文件 | 识别类型、归档、写索引 | S11 追加 AP 归档记录 |
| 会议转写同时触发 S27+S28 | 归档纪要文档本身 | S28 归档反馈原文、S11 更新 AP |
| 完整性检查 | 输出缺失清单和提醒 | 无联动 |

## 职责边界

### 做什么
- ✅ 解析输入文档，抽取类型、客户、项目等关键字段
- ✅ 匹配飞书多维表中的客户与项目记录
- ✅ 检测版本冲突（索引冲突 + 同名文件冲突）
- ✅ 按命名规则生成标准文件名与目标目录
- ✅ 生成飞书执行计划
- ✅ 在输出中包含归档摘要，供 S11 更新 Account Plan
- ✅ 支持用户确认后 finalize 写入
- ✅ 支持归档完整性检查

### 不做什么
- ❌ 不直接调用飞书 HTTP API（统一由 OpenClaw 执行）
- ❌ 不修改文档内容（只归档，不编辑）
- ❌ 不写入或修改 Account Plan（AP 统一由 S11 负责）
- ❌ 不归档 S28 产生的反馈原文（反馈原文归档由 S28 自行处理）

## Feishu 执行边界

**重要**：本 Skill **不直接调用飞书 HTTP API**。只输出计划 JSON，由 OpenClaw 调度以下 Feishu_Skills 执行：
- feishu-contact：用户信息查询
- feishu-bitable：多维表操作
- feishu-drive：文件上传
- feishu-doc-writer：文档创建
- feishu-wiki：知识库挂载
- feishu-card：卡片消息
- feishu-im：消息发送

## 异常处理

| 异常 | 处理方式 |
|------|----------|
| CLI 不可用 | 返回环境错误，不生成计划 |
| 文档类型无法识别 | 标记"其他"，提示用户确认 |
| 客户匹配失败 | 列候选项，status=needs_confirmation |
| 冲突未处理 | finalize 阻断 |
| action=cancel | 不生成写入计划 |
| Drive 上传失败 | 重试一次，仍失败则中止 |

## 注意事项

- 仅在需要时读取参考文档，保持上下文简洁
- 生成的执行计划 JSON 需由主控调度执行，不直接调用飞书 API
- archive_summary 字段必须完整，供 S11 更新 Account Plan
- 版本冲突时需用户明确选择 overwrite 或 save_as_new_version
- 确认令牌有效期建议设置为 30 分钟
- 测试模式通过环境变量 `S27_ALLOW_DEMO_FEISHU_ROOTS=true` 允许使用 demo 根节点
