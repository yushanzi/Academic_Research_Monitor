# Academic Research Monitor vNext 开发计划书

## 1. 项目目标

当前 repo 已完成单用户 MVP：抓取论文、规则筛选、LLM 分析、PDF 报告、邮件发送、Docker + cron 部署。

本次升级目标是把系统重构为 **单容器单配置** 的多用户运行框架：一个容器服务一个用户/一个关注领域，多个用户通过多个容器并行运行。

每个容器统一读取 `/app/config.json`，该配置文件控制：

- 数据源
- 用户名称
- 关注方向描述 / 关键词
- 时间窗口
- cron 运行频率
- 收件人
- 发件人
- 输出目录
- LLM 参数
- 全文访问模式

主题识别升级为：

1. 用户长文本关注描述
2. LLM 生成 interest profile
3. 规则粗筛
4. abstract / full text 精判
5. 阅读理解与趋势总结

对粗筛后的论文：

- 先检查 abstract
- 再尝试获取全文
- 有全文则优先基于全文判断
- 无全文则仅基于 abstract 判断

报告中必须标明：

- 判断依据：全文 / 仅摘要
- 访问方式：Open Access / Authenticated / Abstract Only
- Open Access 状态
- 文章访问地址
- 下载地址或入口地址

v1 只实现 **open access 全文获取**；同时预留 **authenticated access** 接口，未来可接合法订阅/机构账号。

---

## 2. 总体架构与运行模型

### 2.1 多用户模型

采用 **单镜像，多容器，多配置** 的运行方式。

- 一个容器只服务一个用户或一个关注领域
- 每个容器挂载自己的配置文件到 `/app/config.json`
- 每个容器有独立输出目录
- 每个容器有自己的 cron 调度频率
- 多用户通过多个容器并行运行，不做应用内账号体系

### 2.2 推荐目录结构

```text
configs/
  user-a.json
  user-bio.json
  user-chem.json

output/
  user-a/
  user-bio/
  user-chem/
```

### 2.3 关键约束

- 不做应用内多租户
- 不做账号系统
- 不做单容器多任务调度
- 同一用户如果要监控多个完全不同领域，仍推荐拆成多个容器

---

## 3. 配置体系设计

### 3.1 配置文件定位

每个容器启动时只读取一个配置文件：

- 容器内固定路径：`/app/config.json`

宿主机可以有多份不同配置文件，例如：

- `configs/user-a.json`
- `configs/user-bio.json`

它们分别挂载到各自容器中的同一路径 `/app/config.json`。

### 3.2 配置文件结构

```json
{
  "user": {
    "name": "bio-monitor"
  },
  "schedule": {
    "cron": "0 */12 * * *",
    "timezone": "UTC",
    "run_on_start": false
  },
  "sources": {
    "arxiv": {"enabled": true},
    "biorxiv": {"enabled": true},
    "nature": {"enabled": true, "journals": ["nature"]},
    "science": {"enabled": true},
    "acs": {"enabled": false}
  },
  "interest_description": "我希望持续关注 protein language model、protein structure prediction、AI for drug discovery、structure-based design 等方向，优先关注方法创新和真实实验验证，不希望看到泛化很弱或纯工程平台介绍类文章。",
  "topics": [
    "protein language model",
    "protein structure prediction",
    "AI for drug discovery"
  ],
  "time_range_hours": 12,
  "llm": {
    "provider": "claude",
    "model": "claude-sonnet-4-20250514",
    "base_url": null
  },
  "email": {
    "recipient": "user@example.com",
    "from": "Academic Monitor <onboarding@resend.dev>"
  },
  "output_dir": "output/user-bio",
  "access": {
    "mode": "open_access",
    "auth_profile": null
  }
}
```

### 3.3 字段语义

- `user.name`：实例标识，用于日志、报告、邮件主题
- `schedule.cron`：该容器自己的执行频率
- `schedule.timezone`：cron 解析时区；默认 `UTC`
- `schedule.run_on_start`：容器启动后是否立即执行一次；默认 `false`
- `sources`：数据源开关及源级配置
- `interest_description`：用户自然语言兴趣描述
- `topics`：关键词补充；兼容旧版配置
- `time_range_hours`：每次运行回看最近多少小时
- `llm`：模型配置
- `email.recipient`：收件地址
- `email.from`：发件人地址；未来有自定义域名后只需改这里，无需改代码
- `output_dir`：输出目录
- `access.mode`：`open_access` / `authenticated`
- `access.auth_profile`：未来认证配置引用

### 3.4 Schema 约束与校验规则

| 字段 | 必填 | 类型/枚举 | 默认值 | 校验规则 |
|---|---|---|---|---|
| `user.name` | 是 | string | 无 | 非空，推荐仅包含字母、数字、`-`、`_`，用于实例标识而非账号名 |
| `schedule.cron` | 否 | string | `0 8 * * *` | 必须是合法 5 段 cron 表达式 |
| `schedule.timezone` | 否 | string | `UTC` | v1 默认支持 `UTC`；如扩展为 IANA 时区名，非法值启动失败 |
| `schedule.run_on_start` | 否 | boolean | `false` | 控制容器启动后是否立即执行一次 |
| `interest_description` | 否 | string | `null` | 与 `topics` 至少存在一个 |
| `topics` | 否 | string[] | `[]` | 允许为空，但与 `interest_description` 不可同时缺失 |
| `time_range_hours` | 否 | integer | `24` | 必须大于 `0`，建议范围 `1-168` |
| `llm.provider` | 否 | `claude` / `openai_compatible` | `claude` | 与当前 repo 实现保持一致 |
| `llm.model` | 是 | string | 无 | 非空 |
| `llm.base_url` | 否 | string/null | `null` | 仅 `openai_compatible` 时使用 |
| `email.recipient` | 是 | string | 无 | 非空，需满足基本邮箱格式 |
| `email.from` | 否 | string | `Academic Monitor <onboarding@resend.dev>` | 非空时必须是合法发件人格式 |
| `output_dir` | 否 | string | `output/<user.name>` | 启动时必须可创建或可写 |
| `access.mode` | 否 | `open_access` / `authenticated` | `open_access` | v1 实际只实现 `open_access`，`authenticated` 仅保留接口 |

配置处理规则：

- 顶层未知字段：**fail-fast**
- 已知 source 下的未知扩展字段：**warning 并忽略**
- 必填字段缺失、枚举非法、cron 非法、输出目录不可写：**容器启动失败**

### 3.5 兼容策略

- 旧版仅 `topics` 的配置仍可运行
- 若未设置 `email.from`，默认回退为 `Academic Monitor <onboarding@resend.dev>`
- 若未设置 `schedule.cron`，默认值为 `0 8 * * *`
- 若未设置 `schedule.timezone`，默认值为 `UTC`
- 若未设置 `schedule.run_on_start`，默认值为 `false`
- 若缺少 `interest_description`，则基于 `topics` 构建最简 interest profile

---

## 4. 调度体系设计

### 4.1 当前问题

当前 repo 的 `crontab` 是写死的，不能支持不同容器配置不同运行频率。

### 4.2 目标方案

容器启动时执行：

1. 读取 `/app/config.json`
2. 校验 `schedule.cron`
3. 校验 `schedule.timezone`
4. 如配置 `run_on_start = true`，先执行一次主流程
5. 生成该容器自己的 crontab
6. 启动 cron
7. 固定执行 `python run.py --config /app/config.json`

运行约定：

- `schedule.timezone` 是调度真源；v1 默认 `UTC`
- `time_range_hours` 是抓取窗口真源，不随 cron 自动推导
- 单实例默认**不允许重入**：若上一轮未结束，下一轮直接跳过并记日志
- 单次运行失败只影响当前轮次，不阻断后续 cron
- `run_on_start = false` 时，容器启动后等待下一次 cron；`true` 时立即执行一次再进入 cron
- 调度日志中必须能区分：启动执行、cron 执行、跳过执行、失败执行

### 4.3 需要新增/调整

- 新增 entrypoint 或启动脚本，负责生成运行时 crontab
- `Dockerfile` 改为使用 entrypoint
- `docker-compose.yml` 改为多实例模板，不写死单一容器名

### 4.4 错误处理

以下情况容器启动失败：

- 配置文件不存在
- `schedule.cron` 非法
- `schedule.timezone` 非法
- `output_dir` 不可写
- 必填字段缺失

以下情况仅当前轮次失败，不导致容器退出：

- 某个 source 抓取失败
- 单篇全文解析失败
- 单篇精判失败
- 邮件发送失败

---

## 5. 主题理解与筛选能力升级

### 5.1 当前能力

当前系统依赖 `topics` 的规则匹配：短语匹配 + 关键词重叠。

### 5.2 新目标

支持用户直接写长文本关注描述，并通过 LLM 生成结构化兴趣画像 `interest profile`。

### 5.3 Interest Profile 结构

```json
{
  "core_topics": ["..."],
  "synonyms": ["..."],
  "must_have": ["..."],
  "nice_to_have": ["..."],
  "exclude": ["..."],
  "summary": "..."
}
```

### 5.4 生成与缓存规则

- `interest_description` 为主输入
- `topics` 为人工补充词
- 如果只有 `topics`，则构建简单画像
- interest profile 缓存到输出目录，例如：
  - `output/<user>/interest_profile.json`
- 以下任一变化时缓存失效并重建：
  - `interest_description`
  - `topics`
  - `llm.provider`
  - `llm.model`
  - `llm.base_url`
- 以下任一内部版本变化时缓存失效并重建：
  - `prompt_version`
  - `schema_version`
  - `parser_version`

说明：

- 上述版本号为系统内部常量，不要求用户写入配置
- cache key 必须同时包含配置指纹与内部版本指纹，避免 prompt/解析逻辑升级后复用旧缓存

---

## 6. 论文处理流程重构

### 6.1 新流程

1. 读取配置
2. 生成或加载 interest profile
3. 抓取候选论文
4. 基于画像做规则粗筛
5. 去重
6. 检查摘要可用性
7. 解析访问入口与全文可用性
8. 获取 open access 全文（如可获取）
9. 基于全文或摘要做相关性精判
10. 对通过精判论文做详细分析
11. 生成趋势总结
12. 生成报告
13. 发送邮件

### 6.2 粗筛规则

粗筛继续采用低成本规则，避免对所有候选都调用 LLM：

- 命中 `core_topics`
- 命中 `synonyms`
- 满足 `must_have`
- 规避 `exclude`
- 标题与摘要共同参与判断

### 6.3 精判规则

新增 `judge_relevance(...)`，输出结构例如：

```json
{
  "is_relevant": true,
  "relevance_score": 0.84,
  "matched_aspects": ["..."],
  "reason": "..."
}
```

默认纳入报告条件：

- `is_relevant = true`
- `relevance_score >= 0.70`

职责边界：

- `judge_relevance(...)` 只输出相关性结论，不负责生成访问事实
- `evidence_level`、`open_access`、访问入口等字段由访问解析层统一生成
- 精判阶段可以消费访问层结果，但不得重复写入访问元数据

### 6.4 失败策略

- 精判失败：记录日志，不纳入报告
- 摘要缺失且全文不可得：直接剔除
- 单篇失败不影响整次运行

---

## 7. 全文访问策略

### 7.1 v1 范围

只实现 **open access / 直接可访问** 的全文获取。

### 7.2 获取顺序

1. 源数据自带 PDF / HTML 正文链接
2. DOI / landing page 中可直接访问的全文链接
3. 官方页面公开暴露的 PDF / HTML 内容

### 7.3 未来扩展接口

预留统一接口，例如：

- `DocumentAccessProvider`
- `FullTextResolver`

支持模式：

- `open_access`
- `authenticated`

### 7.4 `authenticated` 未来范围

仅支持合法授权访问：

- 用户名 / 密码
- 机构订阅
- SSO
- session cookie
- token
- 受控代理 / VPN

### 7.5 v1 明确不做

- 付费墙绕过
- 验证码 / MFA 自动化
- 复杂浏览器对抗登录

### 7.6 访问元数据字段

论文对象新增：

- `landing_page_url`
- `entry_url`
- `download_url`
- `full_text_available`
- `full_text`
- `open_access`
- `effective_access_mode`
- `evidence_level`

其中：

- `evidence_level`：`full_text` / `abstract_only`
- `entry_url`：报告中展示的访问入口，必须非空
- `download_url`：仅在存在 PDF/全文直链时填写；否则可为空
- `effective_access_mode`：文章最终判断时使用的访问方式，取值为 `open_access` / `authenticated` / `abstract_only`

命名说明：

- 配置层 `access.mode` 表示实例允许使用的访问策略
- 论文层 `effective_access_mode` 表示该篇文章实际采用的访问方式
- `user.name` 在配置中视为实例标识，不表示应用内账号

---

## 8. 阅读理解、报告与邮件升级

### 8.1 单篇分析

- 有全文：优先基于全文生成研究方向、创新点、中文摘要总结
- 无全文：仅基于 abstract，总结中需体现较低置信度

### 8.2 趋势总结

只基于最终通过精判的论文集合生成。

### 8.3 报告首页新增

- 实例名
- 用户关注方向摘要
- 核心关注点
- 排除方向
- 调度频率
- 时间窗口
- 本次入选论文数量

### 8.4 每篇论文必须展示

- 标题、作者、日期、来源
- 相关性评分
- 命中的关注点
- 纳入原因
- 判断依据：全文 / 仅摘要
- 访问方式：Open Access / Authenticated / Abstract Only
- Open Access 状态
- 文章访问入口（`entry_url`）
- 下载地址（如有 `download_url`）

### 8.5 下载地址回退规则

- `entry_url` 不允许为空，回退顺序为：PDF/全文直链 > DOI > 文章落地页
- `download_url` 仅在存在 PDF/全文直链时展示
- 若无直链但有 DOI 或落地页，则只展示 `entry_url`

### 8.6 邮件升级

- 邮件主题中包含实例名
- `email.from` 改为可配置
- 无结果通知细分为：
  - 无粗筛候选
  - 有候选但无高相关论文

---

## 9. 对外接口与内部数据结构

### 9.1 配置接口

- `user.name`
- `schedule.cron`
- `schedule.timezone`
- `schedule.run_on_start`
- `interest_description`
- `topics`
- `time_range_hours`
- `sources`
- `llm.provider`
- `llm.model`
- `llm.base_url`
- `email.recipient`
- `email.from`
- `output_dir`
- `access.mode`
- `access.auth_profile`

### 9.2 新增内部类型

- `InterestProfile`
- `RelevanceResult`
- `AccessInfo`
- `DocumentAccessProvider`

类型职责定义：

- `InterestProfile`：LLM 生成的结构化兴趣画像
- `RelevanceResult`：相关性判断结果，不包含访问事实
- `AccessInfo`：访问入口、下载链接、open access 状态、证据层级、实际访问方式
- `DocumentAccessProvider`：按实例访问策略解析全文与访问元数据

### 9.3 论文对象新增字段

- `matched_topics`
- `landing_page_url`
- `entry_url`
- `download_url`
- `full_text_available`
- `full_text`
- `open_access`
- `effective_access_mode`
- `evidence_level`
- `relevance`
- `analysis`

---

## 10. 分阶段实施计划

### Phase 1 — 配置与部署底座

- 重构配置 schema
- 增加配置校验
- 增加 runtime cron 生成脚本
- 修改 Dockerfile / compose 示例
- 支持 `email.from`
- 确保单容器单配置可运行

### Phase 2 — Interest Profile 能力

- 新增画像 prompt、解析、校验、缓存
- 兼容旧版 `topics`
- 将主题筛选切换到画像粗筛入口

### Phase 3 — 全文访问与访问元数据

- 新增 `AccessInfo` / `DocumentAccessProvider`
- 实现 open access 全文解析
- 统一生成 `landing_page_url` / `download_url`
- 标记 `evidence_level` / `effective_access_mode`

### Phase 4 — 精判与分析升级

- 新增 relevance prompt / parser
- 接入全文优先、摘要回退逻辑
- 仅对通过精判论文做详细分析
- 更新趋势总结输入集合

### Phase 5 — 报告与邮件升级

- 首页新增画像与调度信息
- 每篇论文新增相关性与访问元数据
- 发件人改为可配置
- 空结果通知细分

### Phase 6 — 多容器验证与运维文档

- 验证两个以上实例并行运行
- 验证 cron、输出、报告隔离
- 编写“如何新增一个用户容器”文档

### 10.7 开发执行清单

1. 收口配置 schema、默认值、校验规则与兼容策略
2. 收口调度规则：时区、启动即跑、互斥执行、失败处理
3. 收口内部类型边界与字段命名，避免访问层/相关性层重复写字段
4. 为 interest profile cache 增加版本维度说明与失效规则
5. 同步报告字段、邮件字段、验收标准中的命名与回退逻辑
6. 检查 `README.md`、`config.json` 示例、当前代码命名与开发计划的一致性

---

## 11. 测试计划

### 11.1 配置与调度

- cron 合法/非法校验
- 时区合法/非法校验
- 配置缺失报错
- `email.from` 默认值与自定义值生效
- `run_on_start` 开/关行为正确
- 上一轮未结束时下一轮跳过，不发生重入

### 11.2 兼容性

- 旧版 `topics` 配置可运行
- 仅 `interest_description` 可运行
- 同时存在 `topics + interest_description` 可运行

### 11.3 Interest Profile

- JSON 解析正确
- 缓存命中生效
- 配置变化导致缓存失效
- `prompt_version` / `schema_version` / `parser_version` 变化导致缓存失效

### 11.4 筛选质量

- 同义词召回
- `exclude` 拦截误报
- 精判失败安全回退

### 11.5 全文逻辑

- open access 成功获取全文
- 无全文时回退摘要模式
- 无摘要无全文时剔除

### 11.6 报告内容

- 每篇论文都有 `entry_url`
- 有直链时展示 `download_url`，无直链时不伪造下载地址
- 每篇论文都有 evidence/access 标记
- 首页显示实例名、画像摘要、调度频率

### 11.7 多容器场景

- 两个容器不同配置、不同 cron、不同邮箱并行运行
- 输出互不污染
- 一个容器失败不影响另一个容器

---

## 12. 验收标准

- 同一镜像可同时启动多个容器，每个容器使用自己的 `/app/config.json` 独立运行
- 每个容器可独立配置：
  - 运行频率
  - 调度时区
  - 是否启动即跑
  - 时间窗口
  - 关注方向
  - 收件人
  - 发件人
  - 输出目录
- 非法配置（必填缺失、cron 非法、timezone 非法、输出目录不可写）会 fail-fast
- 旧版仅 `topics` 配置仍可运行
- 用户可用长文本描述关注方向，系统可生成 interest profile 并参与筛选
- 系统可区分全文判断和摘要判断，且访问元数据与相关性结论职责分离
- 报告中每篇文章都包含：
  - 相关性结论
  - 判断依据
  - `entry_url`
  - `download_url`（如存在）
  - Open Access / `effective_access_mode` 标记
- v1 可获取 open access 全文，并为 future authenticated access 保留接口

---

## 13. 开发前准备清单

### 13.1 必须准备

#### 邮件发送

- Resend 账号
- `RESEND_API_KEY`（只放环境变量，不写入 repo 或文档）

#### LLM

至少准备一套：

- `ANTHROPIC_API_KEY`

或：

- `OPENAI_API_KEY`
- 如使用兼容接口，还需 `OPENAI_BASE_URL`

#### 配置样例

至少准备 2 份真实用户配置样例，用于验证多容器隔离：

- 不同领域
- 不同收件邮箱
- 不同 cron

#### 验收样本

- 至少一组 open access 样本论文
- 最好再准备一组非 open access 样本，用于摘要回退验证

### 13.2 建议准备

- 提前确定 `configs/` 与 `output/` 目录结构
- 准备字段说明文档，明确用户可填项与系统保留项
- 规划未来 authenticated access 的 secret 存储方式，确保凭据不会直接写进 `config.json`

### 13.3 当前不需要先准备

- 自有域名
- 数据库
- Web UI
- 统一账号系统
- 付费墙自动登录逻辑

---

## 14. 环境变量与最小配置说明

### 14.1 环境变量示例

使用 Claude：

```bash
RESEND_API_KEY=<set-in-env>
ANTHROPIC_API_KEY=<set-in-env>
```

使用 OpenAI 兼容接口：

```bash
RESEND_API_KEY=<set-in-env>
OPENAI_API_KEY=<set-in-env>
OPENAI_BASE_URL=<set-in-env>
```

### 14.2 最小配置示例

```json
{
  "user": {
    "name": "bio-monitor"
  },
  "schedule": {
    "cron": "0 8 * * *",
    "timezone": "UTC",
    "run_on_start": false
  },
  "sources": {
    "arxiv": {"enabled": true},
    "biorxiv": {"enabled": true},
    "nature": {"enabled": true, "journals": ["nature"]},
    "science": {"enabled": true},
    "acs": {"enabled": false}
  },
  "topics": [
    "protein folding",
    "AI for drug discovery"
  ],
  "time_range_hours": 24,
  "llm": {
    "provider": "claude",
    "model": "claude-sonnet-4-20250514",
    "base_url": null
  },
  "email": {
    "recipient": "you@example.com",
    "from": "Academic Monitor <onboarding@resend.dev>"
  },
  "output_dir": "output/bio-monitor",
  "access": {
    "mode": "open_access",
    "auth_profile": null
  }
}
```

---

## 15. 默认假设

- 多用户通过多容器解决，不做应用内账号体系
- 每个容器只服务一个配置文件
- `schedule.cron` 是执行频率真源；`time_range_hours` 是抓取窗口
- `schedule.timezone` 默认 `UTC`
- `schedule.run_on_start` 默认 `false`
- 单实例默认不允许重入；重叠调度直接跳过
- 默认相关性阈值为 `0.70`
- 默认 `access.mode = open_access`
- `email.from` 未配置时回退到 `Academic Monitor <onboarding@resend.dev>`
- 未来若启用 `authenticated`，仅支持合法授权访问，不做违规绕过
- 报告中的 `entry_url` 回退顺序为：直链 > DOI > 落地页
- `download_url` 仅表示真实可访问的 PDF/全文直链
