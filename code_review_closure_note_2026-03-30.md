# Code Review Closure Note

本次已根据 `code_review_report_2026-03-30.md` 完成一轮较完整的修复与收敛，重点覆盖了真实存在且影响行为、稳定性、可维护性的核心问题。

## 已完成修复

- **访问模式**
  - `access.mode="authenticated"` 不再静默回退到 `open_access`
  - 当前改为显式报错，避免配置误导

- **兴趣过滤**
  - `must_have` 从“形同无效”改为真正参与筛选
  - 当前语义：**命中任一项 must_have 才进入后续判定**

- **抓取稳健性**
  - 为 Nature / Science / ACS 抓取补充：
    - 超时控制
    - 有限次重试
    - 指数退避
    - 总预算控制
  - 避免单个站点或单批页面抓取拖慢整轮任务

- **容器内 secret 处理**
  - 移除 `printenv > /etc/environment`
  - 改为白名单变量写入受限权限 env 文件，减少 secrets 暴露面

- **重复与脆弱逻辑**
  - JSON 提取逻辑抽成共享工具
  - analyzer 中去掉 `locals().get("raw", "")` 这种脆弱写法

- **邮件与日志**
  - mailer 兼容多种 Resend 返回结构
  - logging 中剩余 f-string 基本已收口为 lazy formatting

- **抓取标识**
  - 把浏览器伪装 User-Agent 改为描述性应用标识

- **数据模型**
  - 已引入 typed `Paper` model
  - 主链路基本改为以 `Paper` 对象传递，而不是裸 `dict`

- **依赖组织**
  - `run.py` 中 deferred imports 已明显减少
  - 改为模块级可选绑定 + 显式 guard

- **重复 cutoff 逻辑**
  - 各 source 已统一复用 `PaperSource._cutoff_time()`

## 测试结果

- 当前全量单测结果：**48 tests passed**

新增/增强覆盖包括：
- `access`
- `analyzer`
- `config`
- `interest_profile`
- `json_utils`
- `mailer`
- `models`
- `report`
- `run`
- `source scraping helper`
- `arxiv / biorxiv source`
- `topic matching`

## 仍未完成但建议后续继续处理

1. **进一步补 source 单测**
   - Nature / Science / ACS 的 feed + abstract scrape 分支测试还可更细

2. **继续类型化**
   - `Paper.analysis`
   - `Paper.relevance`
   - source config 结构

3. **文档系统化清理**
   - README / OPERATIONS / DEPLOYMENT_CHECKLIST 存在一定重复，可再统一

4. **日志策略统一**
   - warning / error / debug 的使用口径还可进一步收敛

## 结论

这轮修改后，项目相比审查时：
- **行为更一致**
- **配置误导更少**
- **抓取更稳**
- **secret 更安全**
- **类型边界更清晰**
- **测试保障更强**
