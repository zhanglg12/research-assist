<h1 align="center">research-assist</h1>

<p align="center"><strong>你的 Zotero 文库已经知道你在关心什么。<br/>让它替你找出下周值得看的论文。</strong></p>

<p align="center">
  <img src="assets/readme/hero-overview.svg" alt="research-assist hero" width="100%" />
</p>

<p align="center">
  <a href="README.md"><strong>English</strong></a>
  ·
  <a href="SKILL.md"><strong>Skill 契约</strong></a>
  ·
  <a href="references/workflow.md"><strong>工作流</strong></a>
  ·
  <a href="references/contracts.md"><strong>契约</strong></a>
</p>

<p align="center">
  <code>Zotero 驱动</code>
  <code>语义搜索</code>
  <code>AI 增强摘要</code>
  <code>邮件投递</code>
  <code>反馈闭环</code>
</p>

---

> **如果你是一个 agent**（Claude Code、Codex CLI、OpenClaw，或任何由 LLM 驱动的工具），
> 现在就先读 [`references/setup-routing.md`](references/setup-routing.md)。
> 它会带你完成一次交互式 setup：
> 判断用户真正需要什么，只问相关问题，写入 `config.json`，并总结本次启用了哪些能力。
> **不要把完整 setup 问卷直接塞进这里**。先路由到那里完成配置，再回到用户真正要做的任务。
> 一旦 `config.json` 有效，正常运行时不要重新打开 setup。

---

## 六阶段链条

<p align="center">
  <img src="assets/readme/six-stage-chain.png" alt="六阶段链条" width="100%" />
</p>

| 阶段 | 发生什么 | 输出 |
|---|---|---|
| **`profile_update`** | 读取 Zotero 证据，包括 collections、tags 和代表论文，维护一份紧凑的研究画像 | `research-interest.json` |
| **`retrieval`** | 按兴趣分支查询 arXiv Atom API，跨分支去重，并写出候选 artifacts | 候选 JSON + 批次清单 |
| **`zotero_evidence`** | 从本地 Zotero 索引中为每个候选解析 exact match 与 semantic neighbor | 带 Zotero 锚点打分的候选集 |
| **`agent_patch`** | 宿主 agent 填写 `recommendation`、`why_it_matters`、`caveats`、`zotero_comparison` 和最终保留/丢弃决策 | 合并 review patch 之后的候选集 |
| **`render`** | 从最终入选子集生成 HTML digest、邮件正文或 Telegram 消息 | `.html` + 投递元数据 |
| **`feedback_sync`** | 将非破坏性的反馈写回 Zotero：添加 tags、调整 collection 归属、追加 notes | 已更新的 Zotero 文库，默认 `dry_run` |

## 30 秒看懂它做什么

1. **读取你的 Zotero 文库**：collections、tags、代表论文，一起构成一份紧凑的研究画像
2. **按这份画像去搜索 arXiv**：不是根据你临时输入的关键词，而是基于你已经收集的论文证据
3. **对候选论文排序**：用双信号打分器综合研究地图匹配度与 Zotero 语义亲和度
4. **让宿主 agent 丰富 Top 结果**：补全 recommendation、why it matters、最近邻 Zotero 锚点与 caveats
5. **生成一份干净的 digest**：输出 HTML、邮件或 Telegram，只保留最值得读的少数论文
6. **把信号回流进 Zotero**：tags、collections、notes 回写到文库里，让下一次运行从更好的起点开始

<p align="center">
  <img src="assets/readme/profile-map-card.svg" alt="画像卡片" width="100%" />
</p>

<p align="center"><em>好的画像应该像地图：分支紧凑、标签适合检索、并且证据直接来自文库本身。</em></p>

<p align="center">
  <img src="assets/readme/digest-cards.svg" alt="摘要卡片" width="100%" />
</p>

<p align="center"><em>好的摘要应该扫得很快：分数可见、最近邻锚点明确、AI 写出的推荐理由能解释为什么值得注意。</em></p>

<p align="center">
  <img src="assets/readme/feedback-loop.svg" alt="反馈回路" width="100%" />
</p>

<p align="center"><em>闭环最终回到 Zotero：一份有用的 digest 也会让它所依赖的文库本身变得更好。</em></p>

## 它为什么不一样

| 传统工具 | research-assist |
|---|---|
| 从一串关键词开始 | 从你的真实文库开始 |
| 把所有命中的结果都堆给你 | 排序、过滤，只留下最锋利的那部分 |
| AI 是事后附加上的 | AI 增强本身就是流水线的一部分 |
| 结果停留在外部孤岛里 | 反馈会流回 Zotero |

## 快速开始

### 方式 A — 一键 agent 配置（推荐）

如果你已经在用 **Claude Code**、**Codex CLI**、**Gemini CLI** 或任何由 LLM 驱动的编程助手，把下面这段话粘贴给你的 agent 就行：

> **读取 `https://github.com/zhanglg12/research-assist` 的 README，然后按照 `references/setup-routing.md` 为我交互式地配置 research-assist。**

agent 会先定位自己宿主环境下的 skill 目录（如果宿主工具没有标准 skill 路径，就先向用户确认安装目标），优先复用现有的宿主 skill 根目录，而不是上来就引导用户新建目录；然后再把仓库 clone 或更新到那个位置。之后才根据你实际需要的功能（最小 digest、Zotero 集成、邮件投递等）问你几个有针对性的问题，写好 `config.json`，执行所选后端或投递路线需要的安装命令，并在结束前做最小验证。对 OpenClaw 来说，这个路径通常是 `~/.openclaw/skills/research-assist`。

### 方式 B — 手动安装（以下命令以 OpenClaw 为例）

#### 1. 安装

如果 `~/.openclaw/skills/research-assist` 已经是你确认好的 skill 目标路径：

```bash
if [ -d ~/.openclaw/skills/research-assist/.git ]; then
  cd ~/.openclaw/skills/research-assist && git pull --ff-only
else
  mkdir -p ~/.openclaw/skills
  git clone https://github.com/zhanglg12/research-assist ~/.openclaw/skills/research-assist
fi
cd ~/.openclaw/skills/research-assist
uv sync
```

就这些。一条命令会安装这个 skill 的基础 Python 依赖。

#### 2. 配置

```bash
# 在已确认的 skill 根目录内，按需创建运行时子目录
mkdir -p ~/.openclaw/skills/research-assist/profiles
mkdir -p ~/.openclaw/skills/research-assist/reports
cp config.example.json ~/.openclaw/skills/research-assist/config.json
cp profiles/research-interest.example.json \
  ~/.openclaw/skills/research-assist/profiles/research-interest.json
```

然后按你的环境编辑 `~/.openclaw/skills/research-assist/config.json`。

> **如果你是一个 agent**，不要让用户手填一大串配置表。
> 直接遵循 [`references/setup-routing.md`](references/setup-routing.md) 的路由逻辑，它会明确告诉你该根据用户目标询问哪些问题。

#### 3. 运行

```bash
# 完整 digest：检查画像 → arXiv 检索 → 排序 → HTML 输出
uv run research-assist --action digest --config ~/.openclaw/skills/research-assist/config.json

# 临时搜索
uv run research-assist --action search --query "llm multi-agent planning" --top 5

# 检查画像是否需要刷新
uv run research-assist --action profile-refresh --config ~/.openclaw/skills/research-assist/config.json

# 通过 Zotero API 将条目同步到语义索引（无需本地 sqlite）
uv run research-assist --action sync-index --config ~/.openclaw/skills/research-assist/config.json

# 在 agent patch 合并后重新渲染 digest
uv run research-assist --action render-digest \
  --config ~/.openclaw/skills/research-assist/config.json \
  --digest-json path/to/digest.json \
  --format delivery

# 启动内置 Zotero MCP 服务
uv run research-assist-zotero-mcp
```

#### 4. 构建可分发 skill 包

```bash
uv run python scripts/distribution/build_skill_package.py
unzip dist/research-assist-skill-v*.zip -d /tmp/research-assist-skill
/tmp/research-assist-skill/research-assist-skill-v*/install.sh
```

生成出来的 skill 包会自带 `install.sh`。它会把运行时文件复制到 `~/.openclaw/skills/research-assist`，在缺失时创建 `config.json` 和 `profiles/research-interest.json`，把新建配置里的运行路径改写成实际安装目录，并在本机存在 `uv` 时自动执行 `uv sync`。

通过便携包安装后，请把 CLI 指向已安装的 skill 根目录：

```bash
uv run --project ~/.openclaw/skills/research-assist \
  research-assist --action digest --config ~/.openclaw/skills/research-assist/config.json
```

## Pipeline 阶段

```text
Zotero 文库
    ↓
1. profile_update    → 读取 Zotero 证据，构建紧凑研究地图
    ↓
2. retrieval         → 按兴趣检索 arXiv、去重、写出候选 JSON
    ↓
3. rank              → 双信号打分：map_match (0.30) + zotero_semantic (0.70)
    ↓
4. agent_patch       → 宿主 agent 填写：recommendation, why_it_matters, caveats, zotero_comparison
    ↓
5. render            → 从最终入选子集生成 HTML / email / Telegram
    ↓
6. feedback_sync     → 将 tags、collections、notes 写回 Zotero，默认 dry_run
```

## 关键设计选择

- **流水线内部不调用 LLM。** 检索、排序与格式化都是纯数据操作。真正的智能判断来自调用它的宿主 agent。
- **ownership 边界是严格的。** 宿主 agent 只填写 `candidate.review`，不能重写论文元数据、分数或投递外壳。
- **digest 必须保持精简。** 系统可以搜得很宽，但最终可见的 digest 目标是 5 篇或更少。更锋利的 shortlist 优先于更大的倾倒。
- **反馈是非破坏性的。** Zotero 写回默认 `dry_run=true`。不会自动删除，也不会做投机性的分类体系重写。

## Feedback sync：闭环如何收口

最后一个阶段会把你这一轮学到的判断推回 Zotero，让下一次运行从更好的文库开始。

**反馈可以做什么：**
- 添加 `ra-status:*` tags，例如 `ra-status:read_first`、`ra-status:archive`
- 添加或修改 collection 归属
- 追加带决策理由的结构化 notes
- 为整理目的创建新的 collections

**反馈绝不会做什么：**
- 删除条目、collections 或 attachments
- 修改论文元数据，例如标题、作者、DOI
- 不给出 dry-run 预览就直接应用修改

**它的工作方式：**
1. 在 digest review 结束后，宿主 agent 按 `reports/schema/zotero-feedback.schema.json` 构造 feedback payload
2. 先用 `dry_run=true` 调用 `zotero_apply_feedback` 预览变更
3. 把计划展示给用户确认
4. 只有在那之后，才会用 `dry_run=false` 真正应用

支持的决策值有：`read_first`、`skim`、`watch`、`skip_for_now`、`archive`、`watchlist`、`ignore`、`unset`

条目会通过 `item_key`、`doi` 或 `title_contains` 来匹配。应用新决策时，旧的 `ra-status:*` tags 会被替换。

## 可选：Zotero 语义搜索

如果你想使用 semantic neighbors，而不只是 exact matches，需要配置本地搜索索引：

- 默认推荐的后端是 `semantic_search.embedding_model = "qwen"`。
- 默认 `qwen` 路径除了 `uv sync` 之外，不需要再额外安装 Python 包。
- 但你仍然需要本地 Ollama 服务，并提前拉取 `qwen3-embedding:0.6b`：

```bash
ollama pull qwen3-embedding:0.6b
```

如果 setup 是由 agent 驱动的，agent 应该自己执行这条 pull 命令，并在宣告 setup 完成前验证 backend 初始化成功。

如果你暂时不想启用本地 semantic search，把 `semantic_search.enabled` 设为 `false` 即可；digest 主链条仍然可以正常工作。

```bash
uv run python - <<'PY'
from codex_research_assist.zotero_mcp.semantic_search import create_semantic_search
search = create_semantic_search()
print(search.update_database(force_rebuild=False))
PY
```

在 `config.json` 里填写这些键：
- `semantic_search.zotero_db_path`：本地 `zotero.sqlite` 的路径
- `semantic_search.local_group_id` 或 `semantic_search.local_library_id`

## 架构

```text
config.json
    ↓
openclaw_runner.py          ← CLI 入口，向 stdout 输出 markdown/HTML
    ├── profile_refresh_policy  → 判断是否需要更新画像
    ├── pipeline.py             → arXiv Atom API 检索
    ├── ranker.py               → 双信号打分
    ├── review_digest.py        → 系统生成的 review fallback
    ├── review_patch.py         → agent review patch 合并
    ├── html_fmt.py             → 暖色调 HTML digest
    ├── email_sender.py         → SMTP 投递
    └── telegram_fmt/sender.py  → Telegram 投递
```

## Agent 兼容性

research-assist 从设计之初就是一个 **agent 原生的 skill**。它可以与任何能读文件、跑 CLI 命令并遵循结构化指令的 LLM 驱动工具配合使用。

| Agent / 工具 | 兼容程度 | 备注 |
|---|---|---|
| **Claude Code** | 完整 | 读取 `SKILL.md` + `references/setup-routing.md` 即可交互式配置 |
| **Codex CLI** | 完整 | 同样的工作流；本代码库最初由 Codex 脚手架搭建 |
| **Gemini CLI** | 完整 | 遵循相同的 `references/setup-routing.md` 路由 |
| **OpenClaw** | 完整 | 通过 `SKILL.md` 原生支持 skill 契约 |
| **Cursor / Windsurf / Cline** | 可用 | 可读取文档并运行 CLI；基础功能无需 MCP 服务器 |
| **任何支持 MCP 的 agent** | 完整 + MCP | 可连接内置 Zotero MCP 服务器以实时访问文库 |

核心设计：所有的智能判断都在 **宿主 agent** 而不在流水线内。流水线只做纯数据操作（检索、排序、格式化），agent 决定丰富什么、保留什么、写回什么反馈。

## 给 agents：如何使用这个 skill

> **如果你是第一次读到这里的 agent：**
>
> 1. 先读 [`references/setup-routing.md`](references/setup-routing.md)，按交互方式配置 skill
> 2. 再读 [`SKILL.md`](SKILL.md)，了解完整 skill 契约，包括 CLI 用法、阶段顺序和硬约束
> 3. 再读 [`references/workflow.md`](references/workflow.md)，了解阶段顺序与 controller 边界
> 4. 再读 [`references/contracts.md`](references/contracts.md)，了解 profile 与 review 的 ownership 规则
>
> **重要行为规则：**
> - Setup 是一次性操作。一旦 `config.json` 有效，正常运行时不要重新打开 setup 问题。
> - 运行 digest 时，直接使用现有配置。不要重新讨论安装选项。
> - 如果配置缺失或损坏，重新路由回 `setup-routing.md`，不要猜测配置值。

## 参考文档

- [`SKILL.md`](SKILL.md) — OpenClaw / agent 集成所用的 skill 契约
- [`references/workflow.md`](references/workflow.md) — 阶段顺序与 controller 边界
- [`references/contracts.md`](references/contracts.md) — profile 与 review 的 ownership 规则
- [`references/setup-routing.md`](references/setup-routing.md) — 交互式 agent setup 指南
- [`references/review-generation.md`](references/review-generation.md) — agent 填写 review 的行为约束
- [`references/profile-map-generation.md`](references/profile-map-generation.md) — 如何从 Zotero 证据构建研究地图

## 视觉示意中的演示数据

README 里的视觉示意使用的是一个虚构的公开主题画像（Agent memory、Multi-agent planning、World models、RL systems、Tool use、Simulation），并配合真实论文作为中性的展示素材。
