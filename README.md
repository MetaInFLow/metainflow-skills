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

- `OpenClaw/`: 适用于 OpenClaw 的 Skills
- `Coze/`: 适用于 Coze 的 Skills
- `TUI-General/`: 适用于通用 TUI / CLI Agent 场景的 Skills
