# Academic Research Monitor 部署清单

## 一、部署前检查

### 1. 环境准备
确认机器上已有：

- Docker Desktop（Windows 推荐启用 WSL2 backend）
- Docker Compose
- 可联网访问外部 API
- 可写目录用于挂载 `output/`
- 编辑器不会把 shell 脚本改成 CRLF

### 2. 凭据准备
准备好 `.env` 文件，至少包含：

```bash
RESEND_API_KEY=...
ANTHROPIC_API_KEY=...
```

或：

```bash
RESEND_API_KEY=...
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
```

可选：

```bash
NEWS_MONITOR_IMAGE=news-monitor:latest
```

### 3. 配置文件检查
确认 `configs/<instance>.json` 至少正确填写：

- `user.name`
- `schedule.cron`
- `schedule.timezone` = `UTC`
- `schedule.run_on_start`
- `topics` 或 `interest_description`
- `llm.provider`
- `llm.model`
- `email.recipient`
- `output_dir`
- `access.mode` = `open_access`

### 4. 输出目录规划
建议先确认目录结构：

```text
output/
  bio-monitor/
  chem-monitor/
```

每个实例一个独立目录。

---

## 二、首次多实例/实例化部署建议顺序

### Step 1：先跑本地测试
在项目目录执行：

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests -v
```

预期：
- 全部测试通过

---

### Step 2：本地 dry-run
先不要发邮件，先看链路是否打通：

```bash
python3 run.py --config configs/bio-monitor.json --dry-run
```

预期检查：

- 没有配置报错
- 能正常抓取/分析/生成报告
- 生成文件：
  - `output/<instance>/interest_profile.json`
  - `output/<instance>/academic_report_YYYY-MM-DD.html`
  - `output/<instance>/academic_report_YYYY-MM-DD.pdf`

---

### Step 3：Docker 构建并启动
```bash
docker compose -f docker-compose.multi-instance.yml up --build -d
```

预期检查：

- 容器成功启动
- 没有因为配置错误退出
- `entrypoint.sh` 正常生成 cron
- 如果 `run_on_start=true`，启动后会先执行一次

---

### Step 4：查看容器日志
```bash
docker logs -f <container_name>
```

可先用：

```bash
docker compose -f docker-compose.multi-instance.yml logs -f
```

重点检查日志里是否有：

- Starting academic research monitor
- Using query topics
- Found X papers
- Total relevant papers
- Report saved

Windows 上如果容器无法读取挂载目录，优先检查 Docker Desktop 的文件共享/路径访问权限。

---

### Step 5：验证输出文件
检查实例输出目录，例如：

```bash
ls -la output/bio-monitor
```

确认有：

- `interest_profile.json`
- `.html`
- `.pdf`

---

### Step 6：验证邮件发送
把 `--dry-run` 去掉后真实运行，确认：

- 收件箱收到邮件
- 发件人正确
- 附件 PDF 可打开
- 报告字段完整

---

## 三、多实例扩容建议顺序

### Step 1：准备实例配置
例如：

- `configs/bio-monitor.json`
- `configs/chem-monitor.json`

确认每个实例：
- `user.name` 唯一
- `output_dir` 唯一
- 收件人正确
- cron 合理

### Step 2：先启动一个实例做首次验证
```bash
docker compose -f docker-compose.multi-instance.yml up --build -d bio-monitor
docker logs -f academic-monitor-bio
```

建议首次验证时把目标实例的 `schedule.run_on_start` 临时改为 `true`，这样容器启动后会立刻跑一次。

### Step 3：确认单实例验证通过后，再启动多实例
```bash
docker compose -f docker-compose.multi-instance.yml up --build -d
```

### Step 4：检查容器状态
```bash
docker compose -f docker-compose.multi-instance.yml ps
```

预期：
- 每个实例都处于运行中

### Step 5：分别看日志
```bash
docker logs -f academic-monitor-bio
docker logs -f academic-monitor-chem
```

### Step 6：检查输出隔离
确认：
- `output/bio-monitor/` 只属于 bio 实例
- `output/chem-monitor/` 只属于 chem 实例

---

## 四、首次上线建议配置

为了第一次验证更顺利，建议：

- `schedule.run_on_start = true`
- 先只启一个实例
- topic 不要设得太宽
- `time_range_hours` 先设 12 或 24
- 先验证邮件和 PDF 内容，再开多实例

第一次成功后，如果你只想靠 cron 调度：

- 把 `schedule.run_on_start` 改回 `false`
- 重启容器

---

## 五、常见失败排查

### 1. 容器启动即退出
优先检查：

- 配置文件路径是否挂载正确
- `schedule.timezone` 是否不是 `UTC`
- `schedule.cron` 是否非法
- `email.recipient` 是否为空
- `output_dir` 是否可写

### 2. 没有生成报告
检查：

- 是否没有候选论文
- 是否 relevance 阶段全部被过滤
- 外部 API 是否失败
- LLM key 是否有效

### 3. 收不到邮件
检查：

- `RESEND_API_KEY`
- 收件地址
- `email.from`
- Resend 发信域/沙箱限制

### 4. 一直提示已有运行任务
检查输出目录里是否有残留：

```bash
ls output/<instance>/.run.lock
```

如果确认没有活跃进程，可删除：

```bash
rm output/<instance>/.run.lock
```

---

## 六、推荐首次执行命令顺序

### 多实例
```bash
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests -v
python3 run.py --config configs/bio-monitor.json --dry-run
docker logs -f academic-monitor-bio
docker compose -f docker-compose.multi-instance.yml up --build -d bio-monitor
docker compose -f docker-compose.multi-instance.yml logs -f
docker compose -f docker-compose.multi-instance.yml up --build -d
docker compose -f docker-compose.multi-instance.yml ps
docker logs -f academic-monitor-chem
```

---

## 七、部署验收标准

首次部署成功，至少满足：

- 配置能正常加载
- 容器能正常启动
- 能生成 `interest_profile.json`
- 能生成 HTML/PDF 报告
- 邮件能正常送达
- 多实例输出互不污染
- 不出现明显重入/锁死问题
