# 普通微信群 AI 客服 v0.1｜技术执行方案

状态：待 Codex 实现。规格日期：2026-09-20。
目标：用尽量少的组件验证“普通微信群文本问题 → 客服处理 → 同一群文本回复”。
本文的参数、接口、状态机和验收指标是项目设计；平台事实来源见 REFERENCES.md。

## 1. 已冻结的范围

**包含：** Python 3.11、wxauto4 免费版、单个普通微信客服账号、单个内部测试群、文本前缀 `#客服`、
固定回答、本地 FAQ 精确/别名匹配、可选文本 LLM 草稿、SQLite、CLI 状态/暂停/恢复/审核、完整 Mock 测试。

**不包含：** 企业微信、微信客服 API、Java/TS 后端、多账号/多群并发、批量触达、自动加人、全量历史抓取、
图片/语音/PDF 处理、真正的结构化 @、长期客户画像、订单/报价权限、联网搜索、复杂 Agent、MCP、
Dify、向量数据库、FastAPI、Web 管理页面和自动部署。

本地 FAQ 是轻量验证，不包装成完整语义 RAG。没有用户产品资料时，示例 FAQ 必须标注“合成测试数据”，
不能编造真实产品操作步骤。每条问题默认独立，不因为昵称相同就拼接长期记忆。

## 2. 成功定义

### 2.1 Goal A：代码交付

在不安装微信、不持有模型 key 的环境里，可安装项目、运行 Mock 演示、通过 A01—A38；
真实适配器代码可隔离测试；有 Windows 诊断和有限运行入口。所有实际测试结果有证据。

### 2.2 Goal B：实机验证

在 Windows 原生 Python 3.11、已登录微信、明确授权的内部测试群内，先只读验证，再有限发送。
收到新的 `#客服 连通测试`，生成一条有唯一任务标记的固定答案，发送并在同一个会话中回读到。
然后验证人工暂停、目标异常、重启和不重复发送。未完成的项目不能宣称通过。

**不承诺：** 全量消息零丢失、服务端 exactly-once、微信送达回执、账号零风险或永久兼容。
本项目只能对可观察到的 UI 消息、自己的任务处理和已执行测试范围提供证据。

## 3. 架构与最小依赖

```text
微信桌面客户端
      ↕
UI 主线程：连接/读取/核验/发送（同一线程）
      │              ↑
      │ 消息事件     │ 经过安全策略检查的发送任务
      ▼              │
触发规则 → SQLite → 客服处理 → 回复草稿/任务
                       │
                       └→ 单个 LLM 工作线程 → 普通数据结果队列

CLI 控制进程 → SQLite 控制状态（暂停/审核/恢复）
FakeWechatAdapter 可替换真实微信，用于全部离线测试
```

建议标准库：argparse、dataclasses、typing、sqlite3、tomllib、queue、threading、concurrent.futures、logging、uuid、time。
运行依赖：HTTPX、filelock；Windows 可选依赖 wxauto4。开发依赖：pytest、pytest-cov、Ruff。
不要求 ORM 或 Pydantic；配置与数据模型须有类型注解和明确校验。

在 pyproject.toml 分离 `dev`、`wechat` 两个 extra，Windows 包用平台条件约束，并延迟导入。
依赖需生成可复现的约束/锁文件并记录验证环境；不要用一份 Linux 的冻结结果冒充 Windows 完整依赖锁。
无网时不无限重装依赖；记录环境阻塞并继续可用的本地检查。

SQLite 默认保留连接线程检查：主线程持有自己的连接；CLI 进程使用自己的连接；LLM 工作线程不直接写库。
启用外键、适当 busy_timeout 和短事务；必要时 WAL。不得跨 UI/HTTP 耗时调用持有写事务。[S7]

真实适配器用按当前 Windows 桌面用户固定位置的进程锁，不能只锁某个 DB 路径，防止更换 DB 后启动第二个微信操作者。
Mock 实例可用独立临时目录运行；测试不得留下常驻进程。[S9]

## 4. 目录建议

```text
wechat-ai-customer-service/
├── AGENTS.md
├── GOAL.md
├── PLAN.md
├── ACCEPTANCE.md
├── REFERENCES.md
├── README.md                    # 由 Codex 生成的软件使用说明
├── config.example.toml
├── pyproject.toml
├── src/wechat_cs/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── engine.py                # 主循环与状态转换
│   ├── storage.py
│   ├── delta.py                 # 窗口快照差分
│   ├── policy.py                # 触发/发送/暂停规则
│   ├── adapters/
│   │   ├── base.py
│   │   ├── fake.py
│   │   └── wxauto_adapter.py
│   └── replies/
│       ├── base.py
│       ├── fixed.py
│       ├── faq.py
│       └── llm.py
├── examples/
│   ├── faq.json                 # 合成测试数据
│   └── scenarios/basic.json
├── tests/
│   ├── unit/
│   ├── integration/
│   └── live/
├── scripts/
│   ├── qa.py
│   └── validate_windows.ps1
├── reports/
└── .runtime/                    # 忽略版本控制
```

小模块可以合并，行为契约和验收不能省略。不要生成一堆无实现的空接口来冒充完成。

## 5. 微信适配器契约

定义自有 `WechatAdapter` 协议；业务层不得直接导入 wxauto4。

```text
connect() -> AdapterCapabilities
snapshot() -> ChatSnapshot
send_text(request: SendRequest) -> SendResult
close() -> None
```

这些是本项目接口，不是 wxauto 原生方法名。`send_text` 只能在 UI 所有者线程执行。
`FakeWechatAdapter` 必须可注入快照序列、群切换、异常、发送结果不明和自身消息回显，并记录实际调用次数。

### 5.1 基础数据

`MessageObservation`：ui_id（可空）、attr、type、sender_display、content、observed_at、source_time（可空）。
`ChatSnapshot`：binding_id、binding_epoch、chat_name、chat_type、captured_at、messages 有序列表。
`SendRequest`：task_id、binding_id、binding_epoch、expected_chat_name、text、expires_at。
`SendResult`：OBSERVED_SENT / NOT_ATTEMPTED / UNKNOWN，及 reason、attempted_at、observed_at（可空）。

observed_at 是采集时间，不能伪装成微信消息原始发送时间。所有机器时间存储为带时区 UTC，展示保留偏移。
wxauto 的 sender 只是显示名称；不能生成假 external_userid 或假 wxid。[S6]

### 5.2 真实 API 适配

只验证免费版基础能力：WeChat 初始化、ChatInfo、GetAllMessage、SendMsg；如需首次打开目标，可用已核实的 ChatWith。
优先由操作者手动打开测试群，再附着当前会话，不要循环搜索或自动切换多个群。
ChatInfo 至少核对 `chat_type == group` 和人工指定的完整群名；缺失/不一致时停止采集和发送。[S4][S5]

上述检查不是稳定群 ID 认证。同名群、窗口切换的不可观察竞争和 UI 误识别仍存在风险；
首版要求唯一命名测试群、专用桌面和人工绑定。无法可靠确认时只能暂停，不能宣称绝对杜绝串群。

免费版不使用 Plus 的 IsOnline 或 GetMyInfo；doctor 根据可用窗口/会话信息给出能力状态。
不能把“能找到窗口”报告为“登录状态已被服务端验证”。

## 6. 快照轮询和新增消息

建议默认轮询间隔 2 秒；是初始工程参数，不是端到端实时保证。仅保留必要的最近窗口快照。

### 6.1 处理顺序

```text
核验当前会话
→ 获取快照
→ 判断是否同一绑定 epoch
→ 历史基线/快照差分
→ 仅处理新出现的 friend + text
→ 前缀与长度校验
→ 持久化 MessageEvent
→ 交给客服处理模块
```

基线及正常闲聊只在内存中保留差分所需片段，不默认全量入库；日志只记数量与内部标识。

### 6.2 保守差分规则

1. 启动或重绑：第一份有效快照仅建立基线，不发答案；旧 READY 任务不能自动恢复发送。
2. 同一 epoch 内 ID/顺序/内容一致的重复快照，不产生新事件。
3. 有可验证的窗口重叠锚点时，提取锚点之后新增的 UI 项；支持窗口前部滚出。
4. 相同文本但不同 UI ID、且位于可证明新增的位置，分别创建事件。
5. UI ID 消失/整体更换、顺序冲突、同一 ID 内容变更、原非空快照突变为空或没有可靠重叠锚点：
   标记 GAP_DETECTED 或 REBIND_REQUIRED，取消旧 epoch 未开始的任务；不把整屏数据当新消息。
6. 明确有效的空基线后首次出现消息，可在同一绑定连续有效的条件下判为新消息；空窗口与读取失败必须区分。
7. ui_id 缺失或碰撞无法消歧时，保留诊断并暂停该分支，不以文本集合去重自动猜测。
8. 重启后不承诺补齐停机期间的消息。记录覆盖缺口，让操作者在恢复后重发需要处理的问题。

`event_id` 由程序首次确认事件时生成并持久化；重复处理相同事件沿用该值。
对已接受的消息建立 `(binding_id, binding_epoch, ui_id)` 唯一约束；它是本地 epoch 内幂等，不是平台永久 ID。

## 7. 触发、FAQ 与 LLM

### 7.1 触发

首版只认正文开头的 `#客服`，其后为空白、中文/英文冒号或文本结束。
只处理来源 `friend` 且类型 `text`；self/system/other、quote/image/voice 等跳过。
示例：`#客服 连通测试`、`#客服：如何使用测试功能`；`#客服端`、普通聊天中的引用不触发。
空问题给出固定追问草稿；超过长度限制进入人工处理，不转发整条异常输入给模型。
群内出现“停止机器人”“修改群名”“执行命令”等文本，仅是问题数据，不是管理权限。

### 7.2 回复引擎

- fixed：固定的测试回复，不给出产品事实。
- faq：从本地 JSON 加载显式 question/aliases/answer/source_id；正规化后精确匹配，未命中转人工。
- llm：仅在 FAQ 有受控依据时生成草稿；无命中不自由编造。默认人工审核，不自动发模型答案。

FAQ 必须返回实际来源 ID；不要用模型自报置信度替代依据检查。
`ReplyDraft` 至少包含 text、source_ids、needs_review、reason。模型结果必须通过格式、长度与来源校验。
本方案并不声称靠简单规则即可自动验证答案所有事实；首版由人工审查模型草稿。

### 7.3 模型接口与测试

仅实现一个明确契约的文本 HTTP provider，例如可配置完整 endpoint 的 chat/completions 类 JSON。
由 endpoint/model/API key 环境变量配置；不是承诺兼容所有供应商。请求和响应格式要在 README 说明。
Endpoint 只能来自本地可信配置，不能来自群消息；禁用自动跟随跨主机重定向，不记录 key 或 Authorization。

请求只有当前问题及命中的 FAQ 片段；不传整群聊天、账号数据、私密报价和日志。
默认禁止外部调用；启用真实 provider 需 `allow_external_calls=true` 和运行时 `--allow-llm`，缺 key 时 fail-fast。
配置 connect/read/write/pool 超时及应用级截止时间；异常转人工，不自动切换另一供应商或无限重试。

HTTPX MockTransport 验证请求结构、成功结果、401/429/5xx、超时、空答案、非法 JSON、超长响应。[S8]
设置 HTTPX 传输超时不等于已经严格实现了所有形式的总墙钟期限；实现需检查截止时间并拒绝迟到答案。
LLM 线程的结果带 run_id/generation，暂停、重启或 epoch 改变后迟到的结果不能进入发送队列。

## 8. 数据持久化与状态机

### 8.1 四张表足够

| 表 | 核心字段 |
|---|---|
| message_event | event_id, binding_id, binding_epoch, ui_id, sender_display, question, observed_at, processing_status |
| reply_task | task_id, event_id, engine, answer, source_ids, needs_review, status, generation, created_at, expires_at, attempt_started_at, observed_at, error_code |
| runtime_state | binding_id, run_id, binding_epoch, generation, mode, paused, pause_reason, heartbeat_at |
| audit_event | id, time, event_type, task_id, binding_id, reason, metadata_redacted |

使用参数化 SQL。event_id 唯一，同一 event 的初次回答任务创建幂等；重试生成不能造成多个待发任务。
消息和答案属于敏感运行数据；默认只保留测试所需内容，保留期按配置，提供可核对的清理入口。
不要自动删除用户的其他数据库或用清库解决失败的去重测试。

### 8.2 任务状态

```text
生成草稿 → DRAFT --人工审核通过--> READY
           │                       │
           │ dry_run               │ 原子检查并占用
           └→ SIMULATED             ▼
                               SENDING
                               ├→ OBSERVED_SENT
                               └→ UNKNOWN

DRAFT/READY → CANCELLED / EXPIRED
明确尚未发起 UI 动作的不可恢复错误 → FAILED
```

fixed/faq 可由配置允许直接进入 READY；LLM 默认停留 DRAFT。
SIMULATED、OBSERVED_SENT、UNKNOWN、CANCELLED、EXPIRED 为不可自动重放的状态。
UNKNOWN 不能靠普通 approve 变成 READY；需要人工核对，并明确创建新任务，原尝试记录保留。
首版可不实现 UNKNOWN 后重发入口，只提供查看和人工处理说明。

### 8.3 发送前置条件

真实发送必须同时满足：wxauto 模式、config allow_send=true、CLI --allow-send、
CLI --confirm-target 与已核验测试群一致、manual/auto 模式、同一有效 epoch、
未暂停、未过期、任务已授权、发送预算与速率限制未耗尽、真实适配器锁仍有效。
检查不通过，绝不调用 SendMsg。dry_run 的真实 SendMsg 调用次数必须为 0。

由短事务把 READY 转成 SENDING，记录 attempt_started_at 后提交，再操作 UI。
不得用数据库事务包住微信 UI 调用。这个转换是“发送已开始”的可观察边界。
暂停在转换前提交，必须阻止发送；转换后暂停，任务已在途，不承诺能撤回。
操作者应先暂停程序再手动操作同一个微信客户端。

调用发送时不让 LLM 提供目标参数。避免已检查目标后再次执行不受控模糊搜索。
消息前缀携带唯一短 task_id，如 `[AI测试 #7B2C]`，用于本地核验，不宣称微信官方消息 ID。
发送函数返回成功后仍要观察同一会话中新的 self 文本；能匹配唯一任务标记和答案才记 OBSERVED_SENT。
无法证明时记 UNKNOWN，即使 SDK 返回真；客户端可见也不等于收件人已读。

### 8.4 崩溃与恢复

启动后所有 SENDING → UNKNOWN；READY → DRAFT 并要求重新审查；未完成模型事件记录为待人工处理。
重建历史基线，默认保持 dry_run/人工控制，不恢复旧的真实发送授权。
系统不能保证 UI 自动化 exactly-once；此策略优先避免崩溃后盲重发，代价是部分未发任务需人工核对。

### 8.5 暂停和恢复

`pause` 持久化 paused=true、递增 generation，取消尚未开始的 DRAFT/READY。
暂停期间不生成新回复；可以采集最少差分信息用于维护基线，但不保存闲聊。
`resume` 仅用于人工暂停；重建基线后接受新问题，不回放暂停期消息。
REBIND_REQUIRED/GAP/桌面异常需要人工重新绑定或重新启动，普通 resume 不能绕过。
停止程序、Codex Goal 暂停和客服暂停是不同操作，README 必须分别说明。

## 9. 项目 CLI 契约（待 Codex 实现）

所有下面命令属于本项目，不是 wxauto/Codex 已有命令。必须支持 `--help`。

```bash
# 完全离线；不得导入或初始化真实微信
python -m wechat_cs doctor --adapter mock --report reports/doctor-mock.json
python -m wechat_cs demo --scenario examples/scenarios/basic.json --report reports/demo.json

# 运行读取/草稿流程；默认不真实发送
python -m wechat_cs run --config config.local.toml --adapter wxauto --dry-run

# CLI 控制只访问应用 DB，不直接操作微信窗口
python -m wechat_cs status --db .runtime/wechat_cs.sqlite3
python -m wechat_cs pause --db .runtime/wechat_cs.sqlite3
python -m wechat_cs resume --db .runtime/wechat_cs.sqlite3
python -m wechat_cs tasks list --db .runtime/wechat_cs.sqlite3
python -m wechat_cs tasks approve TASK_ID --db .runtime/wechat_cs.sqlite3
```

`demo` 固定使用 Fake 适配器和临时 DB，允许在虚拟通道完成模拟发送；不能切换 wxauto 或 external LLM。
`dry_run` 不调用 send_text；生成 SIMULATED 任务和预览，不能把这些任务审批成真实发送。
`tasks approve` 对 UNKNOWN/SIMULATED/EXPIRED/CANCELLED 无效；approved 不代表绕过运行级发送授权。
缺少配置/错误平台/无权限返回有说明的非零退出码；不悄悄换成 Mock 并返回成功。

## 10. Windows 操作步骤（M5）

### 10.1 安装

Goal A 需生成可安装工程，再执行以下程序命令；这些命令现在还没有对应实现。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,wechat]"
Copy-Item config.example.toml config.local.toml
```

操作者填写真实测试群名，保留默认 dry_run；按实际批准的依赖锁/约束文件复现环境。
先核对当前免费版和微信的兼容信息，不自动降级客户端。[S3]

### 10.2 只读

```powershell
.\.venv\Scripts\python.exe -m wechat_cs doctor --adapter wxauto --config config.local.toml --report reports/doctor-windows.json
.\.venv\Scripts\python.exe -m wechat_cs run --adapter wxauto --config config.local.toml --dry-run --duration-seconds 60
```

操作者从另一个群成员账号发合成问题，测试账号本身发的问题应被 own-message 过滤。
doctor 不发送消息，不输出群历史内容或密钥。沙箱不能访问桌面时报告 BLOCKED；
只读调试也需有权读取该测试群。不得绕过登录、验证码或系统保护。

### 10.3 有限固定回复

操作者明确授权后，先在本地配置打开 allow_send；本次命令再显式开启。

```powershell
.\.venv\Scripts\python.exe -m wechat_cs run --adapter wxauto --config config.local.toml --reply-engine fixed --send-mode auto --allow-send --confirm-target "填写已经核验的测试群完整名称" --max-sends 3 --duration-seconds 300
```

CLI 上限只能进一步收紧配置预算，不能静默放宽；达到预算/时限后停发并退出，不由 Goal 循环重启来突破。
测试不使用 LLM、不使用生产群。其余发送案例需要单独批准预算，不能将一次 3 条授权当作整套持续群聊授权。
普通控制命令的失败不得使程序恢复自动发送。

## 11. 实现里程碑

| 阶段 | 工作 | 必须交付/验证 |
|---|---|---|
| M0 | 检查目录、Python、依赖；核对参考文档；建立 pyproject、配置与类型 | Mock 可导入；安全默认值；已知版本/未知能力写清 |
| M1 | Fake 适配器、前缀处理、固定回复、SQLite 最小闭环、demo | 合成问题产生唯一模拟发送；无前缀/自身消息不触发 |
| M2 | epoch 差分、唯一约束、发送状态机、暂停/恢复、单实例锁 | A01—A28 相关场景；崩溃 UNKNOWN 不重试 |
| M3 | 本地 FAQ、HTTPX 模型 provider、审核、异常处理 | 合成 FAQ 和 Mock HTTP 测试；无 key 能运行全套离线测试 |
| M4 | wxauto 免费适配器、doctor、CLI、QA/Windows 脚本与文档 | 全部 A01—A38；隔离真实适配器契约测试；无真实 UI 操作 |
| M5 | 单独 Goal B，Windows 只读及有限群回复实测 | W01—W12 的实际结果；不足项标记阻塞，不制造通过 |

各阶段用小步实现和回归测试。关键结果写入 reports/PROGRESS.md；架构偏差有理由才写 DECISIONS。
没有 pytest 或依赖时先修复可解决的工程问题；外部权限问题不可通过修改测试预期来“解决”。

## 12. 自动验收入口

Codex 应实现 `scripts/qa.py`，按顺序执行并保留退出码：

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -m "not live_wechat and not live_llm"
python -m wechat_cs demo --scenario examples/scenarios/basic.json --report reports/demo.json
```

pytest-cov 对 delta/policy/engine/storage/replies 统计核心分支覆盖，目标 85%；不能为了达标排除上述核心模块。
真实 Windows GUI 适配层的覆盖单独报告，不能混入 Mock 覆盖宣称端到端通过。
测试套件默认禁止真实网络/GUI；live 标记必须显式开启且检查授权，收集测试时不能初始化微信。

`scripts/validate_windows.ps1` 默认只读，先确认 OS/解释器/配置；无条件时返回 BLOCKED 和非零退出码。
PowerShell 脚本不得修改执行策略、关闭杀毒软件、注册服务或自动登录。

## 13. 非功能要求与交付边界

完整日志仅记录内部 event_id/task_id、状态、耗时、错误类别；问题/答案默认不写明文日志。
JSON 报告区分 PASS、FAIL、NOT_RUN、SKIPPED_ENV、BLOCKED；给出真实命令、退出码和时间。
README 提供安装、Mock 演示、Windows 只读、有限发送、暂停、停止、故障排查与已知限制。
.gitignore 排除 config.local.toml、密钥文件、.runtime、真实 DB、运行截图、日志和临时缓存。
只保留合成 fixture；截图若人工提供，脱敏后只在授权的本地证据目录保存。

Goal A 结束时不启动常驻真实客服，不创建自动开机任务，不推送 Git、不对外部署。
首版完成仅代表已具备受控试验能力，正式客户服务接入需要另行评估兼容性、数据处理与使用权限。
