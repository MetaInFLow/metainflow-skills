# 本地政策库预筛指南

## 定位

本文件定义 `s4-policy-proposal-generator` 在 Step 0.8 中如何使用本地政策库 `policy_list.jsonl` 做第一轮项目筛选，并说明何时对具体政策触发联网核验。

目标不是一次性替代顾问判断，而是先把接近万条政策压缩为一份可讨论、可落表、可继续核验的候选清单。

## 输入与输出

### 输入

- 标准化企业画像：
  - `company_name`
  - `registered_capital`
  - `registration_date`
  - `employee_count`
  - `declared_projects`
  - `main_business`
  - `existing_qualifications`
  - `registered_address`
  - `intellectual_property`
  - `industry`
- 政策库文件：`references/policy_list.jsonl`

### 输出

脚本输出固定包含：

- `company_profile`
- `retained_candidates`
- `projects`

其中 `projects` 必须兼容 [scripts/generate-plan.py](../scripts/generate-plan.py) 的 `--projects` 输入结构。

## 筛选顺序

### 1. 企业主体校验

- 若 `company_name` 缺失、为 `待确认`，或当前无法确认唯一企业主体，直接停止
- 在企业主体未确认前，不应进入政策筛选，也不应生成最终规划表

### 2. 地区硬过滤

- 保留国家级、省级、深圳市级、注册地址所属区级政策
- 明确属于其他区且无跨区适用迹象的政策直接剔除
- 若地区无法完全判断，保守保留国家、省、市级政策

### 3. 主体硬过滤

- 明显只适用于个人、高校、医院、协会、科研院所等主体，且当前企业画像不支持的政策直接剔除
- 只在“明显不适配”时剔除；存在企业或法人主体适用可能时，优先保守保留

### 4. 宽松保留

- 行业、主营业务、知识产权、资质、人才、数字化、研发、场地等关键词命中即可保留
- 默认保留排序后的 `Top 30` 候选

## 状态定义

### `eligible`

- 当前证据下较明确匹配
- 企业画像与政策方向、地区、主体要求较一致
- 可直接进入落表候选

### `conditional`

- 方向匹配，但还缺少少量条件、材料或进一步核验
- 可进入落表候选，但备注需写明缺口

### `needs_review`

- 方向相关，但证据不足
- 允许落表，但备注必须显式写明 `需顾问复核`

## 排序规则

- 首先按状态排序：`eligible > conditional > needs_review`
- 同档内按以下维度降序：
  - 地区匹配度
  - 业务关键词命中度
  - 资质/知识产权相关度

## 字段映射

`projects` 结构固定映射如下：

| 输出字段 | 来源 |
|----------|------|
| `category` | 规则判断 `qualification` 或 `funding` |
| `project_name` | `title` |
| `department` | `dept_name` |
| `application_time` | 优先联网核验结果，否则 `待确认（需核验时效）` |
| `project_type` | `认定类 / 资助类 / 事前资助 / 事后资助` |
| `funding_amount` | 优先联网核验或文本提取，否则 `待确认` |
| `key_conditions` | 优先联网核验结果，否则 `conditions_preview` |
| `match_reason` | 顾问口径说明，必须带状态和待补充条件 |
| `source_link` | `detail_url` 或联网核验得到的详情链接 |

## 备注写法

不修改 Excel 生成脚本，因此状态必须写入 `match_reason`，推荐格式：

```text
匹配状态：需顾问复核
当前判断：企业所在区域和业务方向与该政策相关，但现有证据不足以确认核心门槛。
待补充条件：发明专利数量、研发投入数据、现有资质证明。
```

## 定向联网核验

### 触发条件

- 默认只核验高优先级且缺信息的项目
- 高优先级定义为排序前 `Top 12`
- 触发字段：
  - `application_time`
  - `funding_amount`
  - `key_conditions`

### 工具选择

- **已有具体 URL**：使用 [$metainflow-web-fetch](../metainflow-web-fetch/SKILL.md)
  - 命令：`metainflow web-crawl`
- **没有 URL 或 URL 信息不足**：使用 [$metainflow-web-search](../metainflow-web-search/SKILL.md)
  - 命令：`metainflow search-summary`

### 幻觉约束

- 使用 `metainflow search-summary` 时，禁止把搜索不到的信息补写成确定结论
- 若无法核实申报时间、资助金额、关键条件，必须明确写 `待确认`
- 若结果来源不足、存在冲突或摘要不稳定，备注中应写 `待顾问复核`

### 推荐 instruction

#### `metainflow web-crawl`

```bash
metainflow web-crawl \
  --url "政策详情页URL" \
  --instruction "提取申报时间、资助金额、关键申报条件，若无法确认请明确写待确认，并输出 json" \
  --output json
```

#### `metainflow search-summary`

```bash
metainflow search-summary \
  --query "{项目名} {地区} 申报时间 申报条件 资助金额" \
  --instruction "提取申报时间、资助金额、关键申报条件；不能确认的字段写待确认，不要编造，并输出 json" \
  --output json
```

## 质量要求

- 联网补强只更新字段和备注，不推翻本地库初筛顺序
- 若联网仍无法确认，就保留 `待确认`，不要编造
- 若存在冲突信息，在备注中明确写 `待确认`
- 若政策方向合理但证据不足，优先保留为 `needs_review`，而不是粗暴剔除
