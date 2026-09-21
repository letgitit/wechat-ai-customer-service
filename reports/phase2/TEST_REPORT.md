# P0—P5 实际交付报告

执行日期：2026-09-21，macOS / Python 3.11；基线提交 `5e2ae80ec4ebba89fa793c0b0682cf1892eb6d0d`。
详细环境、命令、UTC 时间、退出码见 `validation.json`；基线证据在 `baseline/`，最终原门禁证据在 `final/`。

## 结论

已实际完成增量导入、检索、结构化草稿、独立政策检查、原任务 shadow 接入、CLI 与操作手册。
未修改微信适配器、原任务表结构、去重算法、发送授权或原测试；未降低覆盖率/验收阈值。
原业务任务留空答案，结构化内容存入独立知识库并关联 task_id，不能通过原 approve 命令发送。

- 原 141 项测试 + 新增 65 项 = **206 PASS**；加规格包评分器 13 项 = **219 PASS**。
- 原核心综合覆盖率 **97.88%**，纯分支 **96.39%**（门槛仍 ≥85%）。
- 全 src 覆盖率 **93.93%**，纯分支 **89.93%**；见 `coverage-all.json` / `all-tests.txt`。
- 实现范围 Ruff check / format、Mock 演示、进程恢复、Mock doctor、包内 Schema 构建均 PASS。
- **全仓 scripts/qa.py 仍为 FAIL（exit 1）**：用户放入的 phase2 规格包既有 10 项 lint、3 个文件格式问题。
  最终 lint 日志与基线逐字一致，未新增失败；没有通过排除文件、修改规格包或降低门禁把它标成 PASS。

## 阶段与证据

| 阶段 | 实测结果 | 证据 |
|---|---|---|
| P0 | PASS：先跑原 QA，141 测试通过，单列现存 lint/format 失败 | CODEBASE_MAP.md、baseline/qa.json |
| P1 | PASS：三类实际读取、10 个片段、Schema、增量幂等/单片变更/删除/撤权、政策审计 | ingest.json、test_three_source_incremental_and_locators 等 |
| P2 | PASS：中文短词、精确错误码、可信范围、版本/commit、FTS 转义、预算和词典；向量数学/维度降级用 Mock 验证 | test_scope_before_recall_and_query_escaping、test_vector_contract_fusion_and_degradation 等 |
| P3 | PASS：复用 HTTPX；合成三类证据进入同一次结构化生成；异常状态/JSON/字段/引用/敏感内容/超长/运行态声明被处理 | test_structured_model_uses_three_sources_and_server_locators、test_model_failures 等 |
| P4 | PASS：原事件任务唯一性、shadow 关联、空答案不可审批、暂停/取消/过期/撤权/绑定变更/异常隔离；关闭开关原测试不回归 | test_engine_shadow_pause_duplicate_recovery、test_finalize_races_and_failure_are_isolated、test_cli_* |
| P5 | PASS（离线开发交付）：CLI 演示、报告、配置、操作手册与本地构建 | README、OPERATIONS.md、validation.json、package-build.txt |

## 验收条款映射与边界

| 条款 | 状态 | 范围/说明 |
|---|---|---|
| A01—A07 | PASS | 原门禁真实执行、独立知识库、老状态机继续工作、没有真实 Sender 调用；原有 docs/ZIP 保留未提交 |
| B01—B03 | PASS | MD/TXT、合成 DOCX 表格、合成 PDF 页号；空白/损坏/加密异常已测；失败文件移除旧片段 |
| B04—B07 | PASS | 显式产品目录、合成 Git commit 对照、AST/fallback、路径/大小/秘密保护、已审已解决历史过滤 |
| B08 | PASS（确定性） | egress=false 时 HTTP MockTransport 收不到资料；查询和回复常见敏感内容规则通过；不表示任意敏感信息皆可检测 |
| C01—C05、C08—C09 | PASS | 先授权再 FTS；相同问题无法覆盖本机绑定，unknown 不猜 latest；生成期间撤权被拦截 |
| C06 | PASS（接口/数学）；真实语义 NOT_RUN | 可注入向量 encode，维度/有限值/L2/RRF；当前无真实后端，显式 lexical 降级 |
| C07 | PASS（当前路径） | 超预算整片排除，不截断前提；未引入相邻块扩展 |
| D01—D03 | PASS | 严格 Schema、额外字段拒绝、HTTP/截断/非法引用处理、位置从后台读取 |
| D04—D05 | PASS（合成场景） | 无证据/未知版本/互斥操作路径/注入夹具分别转人工或追问；任意语义冲突识别不是已验证能力 |
| D06—D10 | PASS（确定性及设计边界） | 常见敏感文本/源码/私有路径/现实操作声明拦截；始终审阅，保存 prompt/index/model/证据，不回灌答案 |
| E01—E02、E05—E06 | PASS（仅合成机械对照） | 三类端到端；30 条合成题独立语料及可信范围；原评分器区分 Hit/Recall，未缩小分母 |
| E03 | NOT_RUN | 真实模型、真实 embedding 契约均未授权运行；无下载模型、无付费服务调用 |
| E04、E07—E08 | NOT_RUN（真实质量） | 没有脱敏真实客户集/人工 held-out 评审；引用存在不等于支持结论，人工采用率等未测 |
| Windows/微信 | NOT_RUN | 没有操作真实微信或发送真实消息 |

## 30 条合成题对照

这里的生成器是明确标记的机械摘录 Mock；没有把预期答案或动作写进生产引擎。
评测驱动先验证夹具文件/行号/内容哈希，再登记内容身份；撤销/到期两个共用正文的夹具以不同授权快照登记。
只将问题、可信测试范围和真实检索结果传入引擎；golden 仅进入评分器。

| 配置 | Hit@8 | Recall@8 | 动作正确率 | 命中禁止来源/文本的案例数 |
|---|---:|---:|---:|---:|
| manual-only | 100% | 78.95% | 100% | 0 / 0 |
| manual-history | 100% | 85.96% | 100% | 0 / 0 |
| all-sources | 100% | 100% | 100% | 0 / 0 |

检索分母是有相关证据标注的 **19 题**，动作分母是全部 **30 题**，缺预测数 0。
对照说明在这批合成资料中加代码增加了标注证据覆盖率，不能推出真实客户回答更好。
成本 0 是无外部调用的 Mock 成本；p50/p95 是本机 Mock 时延，详见 `evaluation.json`，不可当真实服务 SLA。
人工可直接采用率、无依据断言率、引用语义支持率、真实泄露率均 **NOT_RUN**。

## 已知能力限制与后续所需材料

1. 只支持 shadow；原审核入口尚缺知识证据复核，所以没有启用待审到发送的通路。
2. FTS 为每次查询构建已授权临时分区，适合小数据集；未进行大规模压力/性能验收。
3. 当前精确部署版本/commit 匹配，不自动解析版本区间；未知部署必须由操作者核实。
4. DOCX 使用段落/表格行定位；复杂 PDF 表格和真实扫描件提取质量未实测，扫描件不做 OCR。
5. 矛盾检测为引用操作路径保守规则；一般语义冲突、敏感信息完整识别和事实蕴含必须人工审核。
6. 向量接口实现并测试，但未预设远端服务协议/模型；真实语义效果、服务鉴权和服务超时契约尚未验证。
7. 历史案例导入为人工整理 JSONL/CSV，未新增原始数据库候选导出；没有自动按群成员拼接记录。
8. 来源更新/删除/授权调整须执行 ingest；历史 shadow 是审计快照，不是持续有效的审批结论。
9. 真正试点需单独授权模型/向量端点、批准产品目录及部署映射、脱敏真实问题集和人工审阅。

## 交付与停止

主入口见 README；详细操作见 OPERATIONS.md。实现及报告本地提交，不 push、不创建 PR、不部署、不发群消息。
本轮运行的原 reports 根目录自动生成文件已还原为基线提交版本；新旧实测记录保留在 reports/phase2，避免覆盖上一阶段历史报告。
