# MetaInFlow Skills

MetaInFlow 自研 Skills 集合仓库。

## 仓库约定

- `main` 分支用于沉淀完整 Skills 全集。
- 企业或场景分支只保留该企业/场景适用的 Skills。
- `Enterprise-Template` 分支作为企业分支模板，保持在初始目录骨架状态。
- 新建企业分支统一从 `Enterprise-Template` 拉出，命名为 `Enterprise-<name>`。
- 收录与分支规则见 [COLLECTION_RULES.md](./COLLECTION_RULES.md)。

### 企业分支创建示例

```bash
git checkout Enterprise-Template
git checkout -b Enterprise-<name>
git push -u origin Enterprise-<name>
```

## 根目录结构

```text
.
├── OpenClaw/
├── Coze/
├── TUI-General/
└── COLLECTION_RULES.md
```

## 分类说明

- `OpenClaw/`: 适用于 OpenClaw 的 Skills，目录说明见 [OpenClaw/README.md](./OpenClaw/README.md)
- `Coze/`: 适用于 Coze 的 Skills
- `TUI-General/`: 适用于通用 TUI / CLI Agent 场景的 Skills

## 当前收录概览

当前 `Enterprise-Beeclaw` 分支主要维护 BeeClaw 场景下可直接使用的 OpenClaw Skills：

- [OpenClaw/s5-interview-policy-planner](./OpenClaw/s5-interview-policy-planner/): 面向 OpenClaw 的政策规划表匹配技能版本
- [OpenClaw/s11-customer-profile-generator](./OpenClaw/s11-customer-profile-generator/): S11 客户计划生成器，负责创建或更新标准化 Account Plan
- [OpenClaw/s28-customer-feedback-opportunity-analyzer](./OpenClaw/s28-customer-feedback-opportunity-analyzer/): S28 客户反馈收集与商机识别主技能

如需查看某一分类下的完整说明，优先阅读对应目录内的 `README.md`。
