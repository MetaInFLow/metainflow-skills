# S27 数据契约

## 目录
- [概述](#概述)
- [核心数据结构](#核心数据结构)
  - [ExtractedDocument](#extracteddocument)
  - [MatchResult](#matchresult)
  - [VersionCheckResult](#versioncheckresult)
  - [NamingResult](#namingresult)
  - [PrepareResult](#prepareresult)
  - [TableSchemaRequirement](#tableschemarequirement)
  - [FinalizeResult](#finalizeresult)
  - [FeishuSkillPlan](#feishuskillplan)
- [配置规范](#配置规范)
  - [字段映射配置](#字段映射配置)
  - [命名规则配置](#命名规则配置)
  - [飞书技能映射配置](#飞书技能映射配置)
- [使用示例](#使用示例)

---

## 概述

本文档定义 S27 文档归档管理 Skill 的核心数据结构和契约规范，包括：
- 输入输出数据的字段定义和约束
- 配置文件的格式规范
- 典型使用示例

---

## 核心数据结构

### ExtractedDocument

**用途**：文档解析后的结构化事实提取结果

**字段定义**：

| 字段名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `document_type` | string | 是 | 文档类型：拜访纪要、方案、报价、合同、交付物、验收单、其他 |
| `customer_name` | string | 否 | 客户名称（从文档中提取） |
| `project_id` | string | 否 | 项目编号（格式：QF-P-XXXX） |
| `project_name` | string | 否 | 项目名称 |
| `document_date` | string | 否 | 文档日期（ISO 格式：YYYY-MM-DD） |
| `version_label` | string | 否 | 版本标签（如：v1、v2） |
| `status_label` | string | 否 | 状态标签（如：终稿、待审、签署版） |
| `contract_id` | string | 否 | 合同编号（格式：QF-HT-XXXX） |
| `deliverable_name` | string | 否 | 交付物名称 |
| `participants` | array | 否 | 参会人列表 |
| `summary` | string | 否 | 文档摘要 |
| `requirements` | array | 否 | 需求列表 |
| `decision_chain` | array | 否 | 决策链记录 |
| `risks` | array | 否 | 风险项列表 |
| `action_items` | array | 否 | 行动项列表 |
| `evidence_refs` | array | 否 | 证据引用列表 |
| `operator_id` | string | 是 | 操作人 ID（由调用方注入） |
| `operator_name` | string | 是 | 操作人姓名（由调用方注入） |
| `thread_id` | string | 是 | 会话 ID（由调用方注入） |

**示例**：
```json
{
  "document_type": "拜访纪要",
  "customer_name": "深圳某科技",
  "project_id": "QF-P-0078",
  "project_name": "深圳某科技高企项目",
  "document_date": "2026-03-17",
  "participants": ["张三", "李四"],
  "summary": "讨论项目进度和下一步计划",
  "action_items": ["完成方案终稿", "提交报价"],
  "operator_id": "user-001",
  "operator_name": "演示用户",
  "thread_id": "thread-s27-demo"
}
```

---

### MatchResult

**用途**：客户/项目匹配结果

**字段定义**：

| 字段名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `status` | string | 是 | 匹配状态：matched、ambiguous、unmatched |
| `customer` | object | 否 | 匹配到的客户对象 |
| `project` | object | 否 | 匹配到的项目对象 |
| `candidates` | array | 否 | 候选列表（ambiguous 时返回） |
| `notes` | array | 否 | 匹配过程备注 |
| `enterprise_lookup` | object | 否 | 企业查询结果 |

**示例**：
```json
{
  "status": "matched",
  "customer": {
    "customer_id": "QF-C-0042",
    "customer_name": "深圳某科技",
    "aliases": ["深圳某科技公司", "某科技"]
  },
  "project": {
    "project_id": "QF-P-0078",
    "project_name": "深圳某科技高企项目",
    "project_status": "售前"
  },
  "notes": ["命中 feishu-bitable 预读取缓存"]
}
```

---

### VersionCheckResult

**用途**：版本冲突检测结果

**字段定义**：

| 字段名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `blocking_conflict` | boolean | 是 | 是否存在阻塞冲突 |
| `conflict_type` | string | 否 | 冲突类型：index_conflict、drive_conflict |
| `existing_records` | array | 否 | 已存在的记录列表 |
| `recommended_actions` | array | 否 | 推荐处理动作 |
| `notes` | array | 否 | 检测过程备注 |

**示例**：
```json
{
  "blocking_conflict": true,
  "conflict_type": "index_conflict",
  "existing_records": [
    {
      "record_id": "doc_001",
      "version_label": "v2",
      "file_name": "QF-P-0078_v2_终稿"
    }
  ],
  "recommended_actions": ["overwrite", "save_as_new_version"]
}
```

---

### NamingResult

**用途**：标准化命名与归档路径结果

**字段定义**：

| 字段名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `normalized_name` | string | 是 | 标准化文件名 |
| `folder_segments` | array | 是 | 目录路径段列表 |
| `folder_path` | string | 是 | 完整归档路径 |
| `file_key` | string | 否 | 文件唯一标识 |
| `resolved_version` | string | 否 | 解析后的版本号 |

**示例**：
```json
{
  "normalized_name": "QF-P-0078_v2_终稿",
  "folder_segments": ["客户文档库", "深圳某科技", "02_售前", "方案"],
  "folder_path": "客户文档库/深圳某科技/02_售前/方案",
  "resolved_version": "v2"
}
```

---

### PrepareResult

**用途**：prepare 阶段的完整输出结果

**字段定义**：

| 字段名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `status` | string | 是 | 状态：ready_for_confirmation、needs_confirmation、failed |
| `session_id` | string | 是 | 会话 ID |
| `output_dir` | string | 是 | 输出目录路径 |
| `confirmation_token` | string | 是 | 确认令牌（20 字符哈希） |
| `extracted_document` | object | 是 | 文档提取结果 |
| `match_result` | object | 是 | 匹配结果 |
| `version_check` | object | 是 | 冲突检测结果 |
| `naming_result` | object | 是 | 命名结果 |
| `table_update_plan` | array | 是 | 表更新计划列表 |
| `account_plan_append` | object | 否 | Account Plan 追加项 |
| `card_payload` | object | 是 | 确认卡片 payload |
| `feishu_skill_plan_preview` | object | 是 | 飞书技能计划预览 |
| `prepare_hash` | string | 是 | prepare 阶段数据哈希 |

---

### TableSchemaRequirement

**用途**：多维表写入前的结构校验需求

**字段定义**：

| 字段名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `table_name` | string | 是 | 表名称 |
| `app_token` | string | 是 | 多维表应用 token |
| `table_id` | string | 是 | 表 ID |
| `key_field` | string | 是 | 主键字段名 |
| `operation` | string | 是 | 操作类型：upsert、update、append |
| `required_fields` | array | 是 | 必需字段列表 |
| `record_lookup_fields` | array | 是 | 记录查找字段列表 |
| `update_fields` | array | 是 | 更新字段列表 |

**约束**：
- `required_fields` 必须基于 materialized 后的真实写入字段生成
- 空值字段不进入 `record_lookup_fields` / `update_fields`

---

### FinalizeResult

**用途**：finalize 阶段的执行结果

**字段定义**：

| 字段名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `status` | string | 是 | 状态：ready_for_feishu_skill_execution、cancelled、failed |
| `written_targets` | array | 是 | 已写入目标列表 |
| `skipped_targets` | array | 是 | 跳过目标列表 |
| `warnings` | array | 是 | 警告信息列表 |
| `audit_log` | object | 是 | 审计日志 |
| `resolved_naming` | object | 否 | 最终命名结果 |

---

### FeishuSkillPlan

**用途**：飞书技能调用计划

**字段定义**：

| 字段名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `status` | string | 是 | 状态：planned |
| `stage` | string | 是 | 阶段：prepare、finalize |
| `action` | string | 否 | 动作（finalize 时必需） |
| `business_skill` | string | 是 | 业务技能标识 |
| `sub_agent` | string | 是 | 子代理名称 |
| `skill_calls` | array | 是 | 技能调用列表 |

**skill_calls 元素结构**：

| 字段名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `call_id` | string | 否 | 调用 ID（用于依赖引用） |
| `skill` | string | 是 | 技能名称 |
| `intent` | string | 是 | 意图名称 |
| `reason` | string | 是 | 调用原因说明 |
| `depends_on` | array | 否 | 依赖的前置调用 ID 列表 |
| `inputs` | object | 是 | 输入参数 |

---

## 配置规范

### 字段映射配置

**文件**：`config/field_mapping.json`

**用途**：定义飞书多维表字段映射、归档结构和完整性检查规则

**核心结构**：
```json
{
  "tables": {
    "<表名>": {
      "app_token": "<应用token>",
      "table_id": "<表ID>",
      "key_field": "<主键字段>",
      "lookup_field_aliases": {},
      "field_aliases": {},
      "static_fields": {}
    }
  },
  "archive_structure": {
    "<文档类型>": ["目录层级1", "目录层级2"]
  },
  "completeness": {
    "required_document_types": ["方案", "拜访纪要", "报价", "合同", "交付物", "验收单"]
  }
}
```

### 命名规则配置

**文件**：`config/naming_rules.json`

**用途**：定义不同文档类型的命名模板

**核心结构**：
```json
{
  "rules": {
    "<文档类型>": {
      "template": "{变量1}_{变量2}_{变量3}",
      "auto_version": true|false
    }
  }
}
```

**可用变量**：
- `{项目编号}`、`{客户名称}`、`{日期}`
- `{版本}`、`{状态}`
- `{合同编号}`、`{交付物名称}`

### 飞书技能映射配置

**文件**：`config/feishu_skill_mapping.json`

**用途**：定义飞书根节点和技能映射

**核心结构**：
```json
{
  "roots": {
    "customer_document_root": "<飞书文档库根token>",
    "customer_wiki_root": "<飞书知识库根token>"
  },
  "skills": {
    "feishu-contact": "feishu-contact",
    "feishu-bitable": "feishu-bitable",
    "feishu-drive": "feishu-drive",
    "feishu-doc-writer": "feishu-doc-writer",
    "feishu-wiki": "feishu-wiki",
    "feishu-im": "feishu-im",
    "feishu-card": "feishu-card"
  }
}
```

---

## 使用示例

### 示例1：拜访纪要归档

**输入**：
- 文件：`examples/visit_minutes_sample.txt`
- 类型：file

**prepare 阶段输出**：
```json
{
  "status": "ready_for_confirmation",
  "session_id": "s27-abc123def456",
  "confirmation_token": "a1b2c3d4e5f6g7h8i9j0",
  "extracted_document": {
    "document_type": "拜访纪要",
    "customer_name": "深圳某科技",
    "project_id": "QF-P-0078"
  },
  "naming_result": {
    "normalized_name": "2026-03-17_拜访纪要_深圳某科技",
    "folder_path": "客户文档库/深圳某科技/02_售前/拜访纪要"
  }
}
```

### 示例2：版本冲突处理

**场景**：方案已存在 v2 版本，用户选择保存为新版本

**finalize 输入**：
```bash
--action save_as_new_version
```

**输出**：
```json
{
  "status": "ready_for_feishu_skill_execution",
  "resolved_naming": {
    "normalized_name": "QF-P-0078_v3_终稿",
    "resolved_version": "v3"
  }
}
```

### 示例3：完整性检查

**输入**：
```bash
--project-hint QF-P-0078
```

**输出**：
```json
{
  "project_id": "QF-P-0078",
  "archived_types": ["方案", "拜访纪要", "报价"],
  "missing_types": ["合同", "交付物", "验收单"],
  "blocking_status": "合同签署前无法完成交付物归档"
}
```
