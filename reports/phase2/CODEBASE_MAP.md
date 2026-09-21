# P0 实际代码地图与离线基线

- 时间：2026-09-21；基线提交：5e2ae80ec4ebba89fa793c0b0682cf1892eb6d0d。
- 初始工作区：未跟踪 docs/ 和 wechat_ai_phase2_codex_pack.zip，属于用户提供资料，保留原样，不纳入本轮提交。
- 根目录无磁盘 AGENTS.md；遵循会话提供约束。已读执行包 AGENTS.md（其目录范围）以及 README、配置、phase2 PLAN/INTERFACES/ACCEPTANCE/schemas。
- 实跑 `.venv/bin/python scripts/qa.py`：总体 FAIL；pytest、demo、重启恢复、mock doctor 退出码均 0；核心纯分支覆盖率 96.67%。
- 已有失败：docs/phase2/scripts/score_predictions.py、validate_pack.py、tests/test_score_predictions.py 共 10 个 Ruff lint 问题、3 个格式问题。保留用户文件，不删测试、不降低门禁。详细命令/时间/退出码见 baseline/qa.json，日志见 baseline/qa-*.txt。

## 真实链路与最小扩展点

| 文件/符号 | 当前能力 | 增量边界 |
|---|---|---|
| src/wechat_cs/config.py Config/load_config | 冻结配置、类型及出网门禁 | 增加独立 knowledge 开关及配置路径 |
| src/wechat_cs/replies.py Replies.generate/_model | fixed/FAQ、HTTPX限时限量请求、无重试 | 抽取原HTTP传输供知识结构化生成复用 |
| src/wechat_cs/engine.py Engine.ingest/tick | 主线程接收、单模型线程、去重、迟到结果入库 | 知识 provider 复用线程并在主线程复核、只保存 shadow |
| src/wechat_cs/storage.py Store.accept/finish_draft/approve/start | SQLite 事件唯一约束、审核、过期、暂停、恢复 | 不迁移现有业务表；知识独立库，task_id 关联 shadow；现有任务答案留空，无法 approve |
| src/wechat_cs/policy.py send_gate | 多重发送授权 | 不改；shadow 永不进入发送器 |
| src/wechat_cs/cli.py parser/main/run | argparse、本机任务控制 | kb ingest/status/search、answer preview/explain、eval |
| tests/test_m0.py—test_m4.py | 配置、窗口差分、恢复、发送、模型失败、GUI fake | 全量回归并新增 tests/test_knowledge.py |
| scripts/qa.py | 全仓lint/format、pytest覆盖率、演示、恢复、doctor | 保留原门禁另记录 phase2 实测 |

## 实施范围 P1—P5

新增独立资料清单、三类安全读取/增量索引、SQLite FTS5 中文预分词、严格范围与精确版本匹配、可选向量排名融合；独立schema/引用/来源复核；复用HTTP客户端；shadow接入、CLI、离线测试与报告。未运行向量服务明确 DEGRADED，真实模型/客户问题/Windows 标 NOT_RUN。产品源必须独立显式配置，无默认客服工程扫描。开发仅使用 docs/phase2/fixtures 的合成内容。
