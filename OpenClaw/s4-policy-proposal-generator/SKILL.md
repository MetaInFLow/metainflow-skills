---
name: policy-proposal-generator
description: 辅助政策咨询师完成企业深度调研、战略分析、项目动态匹配和规划表生成；当用户需要为客户生成政策申报方案、制定项目规划或输出申报规划表时使用
dependency:
  python:
    - openpyxl==3.1.5
---

# 政策申报方案生成器

## 任务目标

为政策咨询师快速生成企业项目申报规划方案，输出专业的政策申报规划表。

## 执行流程

### 步骤1：企业信息收集

**目标**：通过多种渠道收集企业基础信息，形成完整的企业画像。

**信息来源优先级**：
1. 用户直接提供的信息
2. 文档解析结果（PDF/Word/Excel 等）
3. 工商查询补充

**工商查询调用**：
```bash
# 精确查询
metainflow enterprise-query --type business --keyword "企业名称" --output json

# 模糊搜索
metainflow enterprise-search --keyword "企业简称" --output json
```

**必填字段**：
| 字段 | 说明 |
|------|------|
| company_name | 企业名称 |
| registered_capital | 注册资金 |
| registration_date | 注册时间 |
| registered_address | 注册地址 |
| employee_count | 社保人数 |
| industry | 所属行业 |
| main_business | 主营业务 |
| existing_qualifications | 已有资质 |
| intellectual_property | 知识产权 |
| declared_projects | 已申报项目 |

**输出**：标准化企业画像。若关键信息缺失，明确标注 `待补充`。

---

### 步骤2：分析并输出备忘录

**目标**：以分析师视角梳理企业适配方向，输出备忘录作为后续查询依据。

**分析框架**（详见 [references/strategy-analysis-guide.md](references/strategy-analysis-guide.md)）：

**一、核心业务定位**
- 从经营范围提炼 3 条核心业务
- 每条业务关联对应的政策方向

**二、产业机遇判断**
- 行业是否处于政策风口
- 注册地区域政策优势
- 企业已有条件能否借势

**三、短板与风险识别**
- 缺失的关键资质
- 知识产权储备情况
- 时间窗口风险

**四、适配方向推导**
基于以上分析，明确 3-5 个政策适配方向。

**输出**：参考 [assets/templates/memo-template.md](assets/templates/memo-template.md) 输出备忘录，包含：
- 企业概况（核心业务、关键优势、主要短板）
- 适配方向（方向+理由+优先级）
- 查询重点（政策关键词、区域范围、需核验信息）
- 待确认事项

---

### 步骤3：政策查询与核验

**目标**：基于备忘录的查询重点，检索匹配的政策项目。

**本地政策库预筛**：
```bash
python3 scripts/filter-policy-library.py \
  --company '{"company_name":"xxx",...}' \
  --policy-jsonl references/policy_list.jsonl \
  --output "./output/policy-screening.json"
```

**筛选规则**（详见 [references/policy-screening-guide.md](references/policy-screening-guide.md)）：
- 地区过滤：保留国家/省/市/企业所在区级政策
- 主体过滤：剔除不适配的主体类型
- 关键词匹配：按备忘录中的适配方向检索
- 输出 Top 30 候选

**联网核验**（针对高优先级且信息缺失的项目）：
```bash
# 抓取政策详情页
metainflow web-crawl --url "政策URL" \
  --instruction "提取申报时间、资助金额、关键申报条件，输出json" \
  --output json

# 搜索政策信息
metainflow search-summary \
  --query "项目名 地区 申报条件 资助金额" \
  --output json
```

**禁止编造**：无法核实的信息必须标注 `待确认`。

---

### 步骤4：输出规划表

**目标**：整理查询结果，生成专业的政策申报规划表。

**内部整理**：
- 按优先级排序项目（短期/中期/长期）
- 标注匹配状态（明确匹配/有条件匹配/需顾问复核）
- 整理待补充条件和风险提示

**调用方式**：

仅填企业信息：
```bash
python3 scripts/generate-plan.py \
  --fill-company-only \
  --company '{"company_name":"xxx"}' \
  --output "./output/项目申报规划表.xlsx"
```

完整模式：
```bash
python3 scripts/generate-plan.py \
  --company '{"company_name":"xxx",...}' \
  --projects '[{"category":"qualification","project_name":"xxx",...}]' \
  --output "./output/项目申报规划表.xlsx"
```

**输出结构**：
- 顶部：企业信息区
- ①产业政策-资质认定类
- ②产业政策-资助类

**落表规则**：
- 三档候选（eligible/conditional/needs_review）都可落表
- `needs_review` 项目必须在备注中标注 `需顾问复核`

---

### 步骤5：交付

**飞书渠道**：上传到飞书云空间并回传链接。
```bash
feishu_drive_file upload --file_path "/path/to/规划表.xlsx"
feishu_drive_file list --order_by CreatedTime --direction DESC --page_size 5
```

**其他渠道**：返回本地文件路径。

## 外部工具依赖

本 Skill 依赖 `metainflow` 命令行工具（已预装）：

| 命令 | 用途 |
|------|------|
| `metainflow parse-doc` | 解析文档 |
| `metainflow enterprise-query` | 工商精确查询 |
| `metainflow enterprise-search` | 工商模糊搜索 |
| `metainflow web-crawl` | 抓取指定 URL |
| `metainflow search-summary` | 联网搜索 |

## 注意事项

- **备忘录必输出**：步骤 2 的备忘录是后续查询的依据，必须输出
- **方向先于查询**：先梳理适配方向，再进行政策查询，避免盲目筛选
- **禁止编造**：无法核实的信息标注 `待确认` 或 `待补充`
- **标注状态**：需复核项目必须在备注中明确标注

## 资源索引

| 资源 | 用途 |
|------|------|
| [assets/templates/memo-template.md](assets/templates/memo-template.md) | 备忘录模板 |
| [references/strategy-analysis-guide.md](references/strategy-analysis-guide.md) | 战略分析框架 |
| [references/policy-screening-guide.md](references/policy-screening-guide.md) | 政策筛选规则 |
| [references/information-collection-guide.md](references/information-collection-guide.md) | 深度调研方法论 |
| [references/project-database.md](references/project-database.md) | 项目格式规范 |
| [scripts/filter-policy-library.py](scripts/filter-policy-library.py) | 政策筛选脚本 |
| [scripts/generate-plan.py](scripts/generate-plan.py) | Excel 生成脚本 |
| [references/公司项目规划表_空表.xlsx](references/公司项目规划表_空表.xlsx) | 输出模板 |
