---
name: s5-interview-policy-planner
description: 读取 Excel 顶部已有企业信息和访谈纪要，默认结合 skill 内置的标准化政策库 JSONL 匹配适合的政策项目；如需刷新政策库，可额外传入 CSV。主表不改，只在附表输出符合的匹配政策、纪要总结和匹配结果总结。用户只要提到“根据访谈纪要匹配政策规划表”“从政策库里找适合企业的项目并更新附表”“根据表头企业信息和纪要生成政策建议”，就应使用这个 skill。
---

# S5 Interview Policy Planner

一句话定义：

先把 `Excel 顶部已有企业信息 + 访谈纪要 + 内置政策库 JSONL` 抽成一份待确认的企业画像和 `Top 20` 预估候选，再在用户确认或明确要求继续后，生成新的 Excel 副本并写入 `审核与补采` sheet。

## 适用范围

- 输入必须包含：
  - 一份已整理好的访谈纪要（`.txt` 或 `.md`）
  - 一份待更新的目标工作簿（`.xlsx`）
- 默认使用内置政策库：
  - `references/policy_library.normalized.jsonl`
- 如政策库有更新，再额外提供一份政策库 CSV 进行刷新
- 只完整支持当前项目规划表模板家族；其他模板先走识别校验，未命中则报错，不强行写入

## 目录结构

- `examples/`: 示例访谈纪要与项目规划表
- `requirements.txt`: 本地运行所需的 Python 依赖
- `scripts/normalize_policy_csv.py`: 把政策库 CSV 标准化为 JSONL，用于刷新内置政策库
- `scripts/extract_profile_from_minutes.py`: 从纪要中抽取企业画像
- `scripts/match_policies.py`: 将企业画像与政策库做规则过滤和打分匹配
- `scripts/update_workbook.py`: 保持主表不变，只新增/更新 `审核与补采` sheet
- `scripts/run_pipeline.py`: 一键串联整条流程
- `templates/registry.json`: 模板注册表
- `templates/project_planning_workbook.json`: 当前项目规划表模板配置
- `references/policy_library.normalized.jsonl`: 默认使用的政策库 reference
- `references/company_profile.schema.json`: 企业画像输出结构

## 运行依赖

- Python 3
- `openpyxl`（见 `requirements.txt`）

Windows PowerShell:

```powershell
python -m pip install -r .\requirements.txt
```

macOS / Linux:

```bash
python3 -m pip install -r ./requirements.txt
```

## 默认工作流

以下命令默认在当前 skill 根目录执行。默认先执行 `prepare`，不要一上来就写 Excel：

Windows PowerShell:

```powershell
python .\scripts\run_pipeline.py `
  --stage prepare `
  --workbook <用户提供的工作簿路径.xlsx> `
  --minutes <用户提供的访谈纪要路径.txt> `
  --output-dir .\output\s5-interview-policy-planner
```

macOS / Linux:

```bash
python3 ./scripts/run_pipeline.py \
  --stage prepare \
  --workbook <用户提供的工作簿路径.xlsx> \
  --minutes <用户提供的访谈纪要路径.txt> \
  --output-dir ./output/s5-interview-policy-planner
```

`prepare` 会输出：

- `company_profile.extracted.json`
- `company_profile.json`
- `session_state.json`
- `preview_candidates.json`
- 一份终端 JSON 摘要，包含：
  - `status`
  - `missing_fields`
  - `conflicts`
  - `pending_questions`
  - `preview_candidates`

如果用户补充了信息，再次执行 `prepare`，并通过 `--confirmations` 注入补采结果：

Windows PowerShell:

```powershell
python .\scripts\run_pipeline.py `
  --stage prepare `
  --output-dir .\output\s5-interview-policy-planner `
  --confirmations <本轮补采结果.json>
```

macOS / Linux:

```bash
python3 ./scripts/run_pipeline.py \
  --stage prepare \
  --output-dir ./output/s5-interview-policy-planner \
  --confirmations <本轮补采结果.json>
```

只有在以下任一条件满足时，才进入 `finalize`：

- `prepare` 后已经没有待确认项，脚本会自动继续
- 用户明确说“开始”“按当前信息继续”“直接往下做”

显式执行 `finalize` 时：

Windows PowerShell:

```powershell
python .\scripts\run_pipeline.py `
  --stage finalize `
  --output-dir .\output\s5-interview-policy-planner
```

macOS / Linux:

```bash
python3 ./scripts/run_pipeline.py \
  --stage finalize \
  --output-dir ./output/s5-interview-policy-planner
```

如果政策库 CSV 有更新，需要重新刷新政策库时，在 `prepare` 或 `full` 阶段额外带上：

Windows PowerShell:

```powershell
python .\scripts\run_pipeline.py `
  --stage prepare `
  --workbook <用户提供的工作簿路径.xlsx> `
  --minutes <用户提供的访谈纪要路径.txt> `
  --policy-csv <用户提供的政策库路径.csv> `
  --output-dir .\output\s5-interview-policy-planner
```

macOS / Linux:

```bash
python3 ./scripts/run_pipeline.py \
  --stage prepare \
  --workbook <用户提供的工作簿路径.xlsx> \
  --minutes <用户提供的访谈纪要路径.txt> \
  --policy-csv <用户提供的政策库路径.csv> \
  --output-dir ./output/s5-interview-policy-planner
```

如需保持旧的一次性跑完模式，可显式使用：

Windows PowerShell:

```powershell
python .\scripts\run_pipeline.py `
  --stage full `
  --workbook <用户提供的工作簿路径.xlsx> `
  --minutes <用户提供的访谈纪要路径.txt> `
  --output-dir .\output\s5-interview-policy-planner
```

macOS / Linux:

```bash
python3 ./scripts/run_pipeline.py \
  --stage full \
  --workbook <用户提供的工作簿路径.xlsx> \
  --minutes <用户提供的访谈纪要路径.txt> \
  --output-dir ./output/s5-interview-policy-planner
```

## 本地回归评测

需要验证抽取和匹配规则是否回归时，执行：

Windows PowerShell:

```powershell
python .\scripts\run_eval_suite.py
```

macOS / Linux:

```bash
python3 ./scripts/run_eval_suite.py
```

这会读取 `evals/evals.json`，用固定样例和固定 `--today` 日期跑完整流水线，并输出通过/失败汇总。

注意：

- 当前仓库已收录 `examples/深圳市云动创想科技有限公司项目规划表.xlsx` 和 `examples/transcript_sample.txt`
- `evals/evals.json` 里引用的 `transcript_sample_01.txt`、`transcript_sample_02.txt`、`transcript_sample_03.txt`、`transcript_sample_04_same_company.txt`、`企业信息采集表.xlsx` 未随本次源包一起提供
- 因此本地 `eval` 目前只能验证脚本与依赖链是否可执行，无法在缺少完整 fixture 的前提下通过全部断言

## 输出约定

- `prepare` 阶段不写 Excel，只输出待确认状态和 `Top 20` 预估候选
- `finalize/full` 阶段才输出新的工作簿副本，不覆盖原文件
- 最终工作簿中必须新增 `审核与补采` sheet
- `finalize/full` 的终端输出同时返回 `访谈纪要总结` 和 `匹配结果总结`

## 写入原则

- 只用 `openpyxl` 精准修改目标模板
- 顶部 10 个企业基础字段是只读上下文，不做自动回填或覆盖
- 主表现有项目名称和政策区内容不改动
- 用户补充信息只覆盖 `transcript_facts`，不自动覆盖 Excel 顶部字段
- 如果用户补充的是顶部字段冲突，只记录为待处理的 Excel 更正请求；最终匹配仍按 Excel 顶部字段执行
- 政策匹配前先做地区保守预过滤：仅剔除明确不属于企业地区层级的政策，未知地区继续保留
- 把所有“符合”“有条件符合”“证据不足”的政策结果写入 `审核与补采` sheet，供人工复核
- “Excel 顶部字段与纪要冲突”信息也只写入 `审核与补采` sheet

## 确认阶段交互

- 首轮默认只做 `prepare`
- 每轮最多追问 3 个问题
- 问题优先级固定：
  - `Excel 顶部字段冲突`
  - 高优先级缺失字段：`region`、`annual_output_wanyuan`、`patent_count_total`、`rd_ratio_pct`
  - 其他缺失字段
- `preview_candidates.json` 只展示 `Top 20` 预估候选，不写入 Excel
- `preview_candidates` 来源于未进入正式审核候选、但仍值得人工扩筛的弱候选 longlist

## 审核与补采 sheet

固定列：

- `缺失信息`
- `为什么需要`
- `建议追问或材料`
- `影响政策或单元格`
- `优先级`
- 另需展示一块 `访谈纪要总结`
- 另需展示一块 `上下文冲突`，列出 Excel 顶部字段与访谈纪要的冲突项
- 另需展示一块 `匹配政策结果`，列出全部“符合 / 有条件符合 / 证据不足”政策
- 另需展示一块 `匹配结果总结`

## 失败处理

- 如果模板未识别，明确报错并停止，不生成改写文件
- 如果刷新时传入的政策库 CSV 结构不合法，先修复/标准化，不跳过
- 如果纪要与 Excel 顶部字段冲突，以 Excel 顶部字段为准继续匹配，并在审核页中保留冲突提示
