# 普通微信群 AI 客服 v0.1

单账号、单个人工指定的内部测试群，Python 3.11 / SQLite / HTTPX / wxauto4 免费版。
默认 **mock + dry_run + fixed**。本次交付只验证离线程序；没有启动真实微信、发送真实消息或调用真实模型。
规格保留在 `wechat_ai_codex_execution_pack/`；实际源码、命令和验收结果位于项目根目录。

## 安装与离线验收

在项目根目录执行。依赖首次下载需要网络；安装后测试与演示不需要网络，也不需要模型 key。

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python scripts/qa.py
.venv/bin/python -m wechat_cs doctor --adapter mock --report reports/doctor-mock.json
.venv/bin/python -m wechat_cs demo --scenario examples/scenarios/basic.json --report reports/demo.json
```

如果使用 uv：`uv sync --locked --extra dev --python 3.11`，然后 `uv run --locked python scripts/qa.py`。
已安装依赖时可加 `--offline`。`uv.lock` 是跨平台解析锁，`requirements.lock` 含哈希及 Windows 条件。
Windows 依赖已解析，但未在本机安装/运行验证；不能把 macOS 测试当作 Windows 安装成功。
Python 打包构建工具由隔离构建环境安装，以上 `--no-deps` 只控制运行依赖。

`qa.py` 保存每个子命令的时间、退出码、JUnit、核心覆盖率及日志；既检查总体覆盖率，也独立检查
**纯分支覆盖率 ≥85%**。全部自动化案例仅使用合成数据、Fake GUI 和 HTTPX MockTransport。
测试禁用 socket 连接和真实 wxauto 导入；live 标记默认排除，本交付没有可偷偷触发实机的测试。

## 常用命令

```bash
# 使用安全默认值，有限运行 10 秒；Mock 不会自行制造群消息
.venv/bin/python -m wechat_cs run --duration-seconds 10
# 配置文件缺失报错；不隐式创建或猜测配置
cp config.example.toml config.local.toml
.venv/bin/python -m wechat_cs run --config config.local.toml --dry-run --duration-seconds 10

.venv/bin/python -m wechat_cs status --db .runtime/wechat_cs.sqlite3
.venv/bin/python -m wechat_cs pause --db .runtime/wechat_cs.sqlite3
.venv/bin/python -m wechat_cs resume --db .runtime/wechat_cs.sqlite3
.venv/bin/python -m wechat_cs tasks list --db .runtime/wechat_cs.sqlite3
.venv/bin/python -m wechat_cs tasks show TASK_ID --db .runtime/wechat_cs.sqlite3
.venv/bin/python -m wechat_cs tasks approve TASK_ID --db .runtime/wechat_cs.sqlite3
.venv/bin/python -m wechat_cs cleanup --db .runtime/wechat_cs.sqlite3 --retention-days 7
```

所有命令支持 `--help`。退出码：0 成功、2 参数错误/环境或门禁阻塞、130 人工 Ctrl+C；QA 失败返回 1。
`status` 的心跳表示最近读取时间，不是服务端登录证明；`pause` 显示 `inflight_cannot_retract`，非零意味着已有发送动作在途。
`tasks list` 不输出问题/答案；`tasks show` 专供本机人工查看草稿和来源，包含敏感运行内容，不应复制到公开报告。
`approve` 只接受本轮、同 epoch、未过期且答案非空的 DRAFT；它不能绕过运行级授权。
dry_run 的 SIMULATED、UNKNOWN、CANCELLED 等终态不能重新批准。FAQ 未命中或模型异常的空草稿由人工另行处理。

- `pause`：持久化暂停，取消未开始任务；在途 UI 动作可能无法撤回。
- `resume`：只解除人工暂停，下一份快照重新建立基线，暂停期问题需要成员重发。
- 安全暂停（目标异常/缺锚点/结果不明）：先 Ctrl+C 停止旧进程，人工核对当前群与 UNKNOWN 记录，
  再以 `run --config config.local.toml --adapter wxauto --dry-run --rebind --confirm-target "完整测试群名"` 重绑。
  `resume` 不能清除安全暂停；`pause` 也不能把安全原因改成人工暂停。
- **停止程序**用运行终端的 Ctrl+C，或等时限/预算结束；没有常驻服务或自动重启。
- Codex Goal 的暂停仅控制开发任务，不会暂停或停止已经运行的客服程序。

## 行为与状态

只处理来源 `friend`、类型 `text`、正文开头 `#客服` 后跟空白/冒号/文本结束的消息。
`#客服端`、普通聊天、引用、图片、语音及 self/system/other/未知来源均不触发。
昵称只是显示名；同名成员不合并身份。两条相同问题但不同 UI ID 分别处理。

启动先建立历史基线。差分只接受连续窗口后缀/前缀重叠；ID 缺失、碰撞、重排、内容变化、
非空突变空、窗口重建或无锚点都会暂停，不把整屏当新增。UI ID 只在本地 epoch 有效。
普通闲聊和历史不全量落库；触发事件及回复属于本地敏感数据。

```text
GENERATING → DRAFT → READY → SENDING → OBSERVED_SENT / UNKNOWN / FAILED
       └→ SIMULATED（dry_run）
GENERATING / DRAFT / READY → CANCELLED / EXPIRED
```

发送前重新检查群名、群类型、epoch、generation、暂停、TTL、预算、间隔、进程锁、配置和 CLI 授权。
SENDING 在短事务中先提交，再操作 UI；不跨 HTTP/UI 持有写事务。
重启时 SENDING→UNKNOWN，READY→DRAFT，未完成生成→人工处理。旧轮次草稿只供核对，不能跨 epoch 审批；请重发问题。
SDK 返回成功不足以确认发送；必须在同群读到**新的 self 文本**，且包含完整 task 标记、全文匹配。
OBSERVED_SENT 只是客户端可见证据，不是对方已读或微信服务端送达回执。

发送预算保守地累计保留在当前数据库的审计中，**不会在重启、cleanup、rebind 时归零**。
CLI `--max-sends` 和 `--duration-seconds` 只能收紧配置上限。达到上限后退出，不自动重新获得额度。
新一轮实机试验必须另获明确范围/预算授权，保留旧库作为证据；不要通过清库、换库或循环重启绕过授权。
真实 GUI 使用当前 Windows 用户固定目录 `%LOCALAPPDATA%\wechat-cs\desktop.lock`，不同数据库也不能并行操纵桌面。
Mock 使用各自数据库的锁。LLM 单工作线程只收发普通数据，不操作 wxauto 或 SQLite 主线程连接。
暂停取消排队请求；已进行的 HTTP 请求可能要等网络超时返回，迟到结果不能发送。

`cleanup` 按指定天数擦除终态任务的内容字段，保留幂等键、状态和无内容审计，避免清理刷新预算。
每次启动按配置中的 `retention_days` 清理（默认 7 天），也可显式执行清理命令。它不是磁盘取证意义上的安全擦除，
SQLite WAL/备份由本机数据管理策略保护。不用删除数据库解决去重或发送失败。

## 固定回答、FAQ 与模型草稿

- `fixed` 只给测试答复，不提供产品事实。
- `faq` 用 NFKC、大小写与空白正规化后做精确/别名匹配；示例 JSON 明确标为合成数据。
  答案携带真实配置的 `source_id`；未命中转人工，不自由编造。
- `llm` 仍须 FAQ 命中，仅发送当前问题和命中 FAQ 的答案/来源 ID。
  模型输出只能作为待审草稿，不能提供目标群、工具调用、shell 或管理操作。
  群内“停止机器人/发往别群”等内容只是问题数据，管理仅走本机 CLI。

模型契约：HTTPS 完整 endpoint，POST chat/completions 类 JSON：
`{"model":"...","max_tokens":500,"messages":[{"role":"system",...},{"role":"user","content":"包含 question/faq 的 JSON"}]}`。
HTTP 响应须为 `choices[0].message.content` 字符串，其内部是
`{"answer":"草稿文本","source_ids":["命中的真实来源ID"]}`。不支持 tools/function_call、流式 API 或任意供应商自动兼容。
响应来源必须完全匹配 FAQ，答案非空且不超长；不以模型自报置信度代替来源审核。

仅在另行批准真实模型调用后，才设置 `reply_engine="llm"`、`allow_external_calls=true`、endpoint/model，
将 key 放到 `api_key_env` 指定的环境变量，再加运行参数 `--allow-llm`。两层授权/配置/key 任一缺失即报错。
本 Goal 不执行这些实调步骤。HTTP 禁止跟随重定向、忽略环境代理、分别配置 connect/read/write/pool 超时，
限制响应字节数并检查应用截止时间。迟到响应转人工；这不是对恶意阻塞底层调用的强制线程终止保证。
所有网络错误不重试、不切供应商、不把堆栈发到群中；密钥不进入应用日志。

## Windows 验收（单独 Goal B，本次 NOT_RUN）

只允许原生 Windows Python 3.11、已经由操作者登录的普通微信、唯一命名的内部测试群。
先人工核对 [免费版环境文档](https://docs.wxauto.org/docs/install.html) 与客户端兼容性。
锁定 `wxauto4==41.1.7`；程序不会下载微信、修改更新策略、绕过登录或购买 Plus。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item config.example.toml config.local.toml
.\.venv\Scripts\python.exe scripts/qa.py
```

操作者在本地配置填写唯一完整 `target_group`；保留 dry_run 和 fixed。人工打开该群，
确认有权读取合成测试消息、已告知成员。先记录 OS/Python/wxauto4/实际微信客户端版本（W01），再执行只读命令：

```powershell
.\.venv\Scripts\python.exe -m wechat_cs doctor --adapter wxauto --config config.local.toml --report reports/doctor-windows.json
.\.venv\Scripts\python.exe -m wechat_cs run --adapter wxauto --config config.local.toml --dry-run --reply-engine fixed --duration-seconds 60
# 等价的只读脚本；不修改 PowerShell 执行策略
.\scripts\validate_windows.ps1
```

W02 核对字段/免费 API；W03 启动前放旧问题，确认 0 回复；W04 由另一成员发新问题、测试账号发同前缀，
确认仅前者产生 SIMULATED。doctor 找到窗口不代表服务端登录验证。报告不包含聊天全文。

只有取得**本次具体测试群、范围及预算的单独发送授权**后，才在本地设置 `allow_send=true`，执行：

```powershell
.\.venv\Scripts\python.exe -m wechat_cs run --config config.local.toml --adapter wxauto --reply-engine fixed --send-mode auto --allow-send --confirm-target "完整测试群名" --max-sends 3 --duration-seconds 300
```

W05 核对群内带唯一标记的固定答复；W06 同内容不同 UI ID 与重复轮询；W07 人工切换目标，
W08 重启/历史/UNKNOWN 不重放，W09 pause/resume 不补发，W10 锁屏/退出后安全暂停。
W05—W09 的发送总数必须在批准预算内，首次 3 条不代表整套验收；追加范围须另外授权。
W11 以离线故障注入为主，不为测试破坏真实微信；W12 确认时限/预算退出且无残留进程。
每项记录真实命令、时间、退出码、实际版本及脱敏观察到 `reports/WINDOWS_VALIDATION.md`。
不能将 Fake 的成功复制为 W 项 PASS。

## 已知边界与故障处理

- 同名群、人工切换后又切回且 UI 无可见变化的竞争无法用群名可靠认证。使用唯一测试群名、专用桌面；
  操作者应先 pause 再操作微信。无法证明窗口连续性就暂停。
- 只看到当前 UI 窗口，不能承诺消息零丢失或服务端 exactly-once；重启/间隙后的问题须重发。
- SDK 可能因客户端版本、桌面锁定或字段变化失败。doctor BLOCKED 时记录版本/原因，恢复授权桌面后重测；
  不自动降级微信，不把失败改成 Mock。
- 软件包不包含真实 key、群内容、账号资料或截图。`.runtime`、本地配置、DB、密钥、日志、截图均被忽略。
- Windows 安装、桌面兼容、PowerShell 脚本实跑、真实收发和真实 LLM 均未在本次执行。
- 报告入口：[验收报告](reports/ACCEPTANCE_REPORT.md)、[阶段记录](reports/PROGRESS.md)、
  [实现决策与资料](reports/DECISIONS.md)。阶段报告保留验收当时的环境与仓库状态。

## v0.2 多源知识草稿（默认 shadow）

增量引擎复用现有接收、去重、线程和任务状态机。默认 `[knowledge] enabled=false`，旧 fixed/FAQ/LLM 行为保留。
知识库使用独立 SQLite；本轮 **只保存 shadow**，原任务答案为空、不能 approve，不存在自动审批或自动发送路径。
原因：原审核入口尚不具备知识来源撤权复核与结构化证据呈现，不能直接复用它放行新草稿。

安装依赖仍用上方锁文件命令。下面只读取 `docs/phase2/fixtures` 合成材料，不调用网络、模型或微信：

```bash
.venv/bin/python -m wechat_cs kb ingest --config examples/knowledge.toml --offline
.venv/bin/python -m wechat_cs kb status --config examples/knowledge.toml
.venv/bin/python -m wechat_cs kb search --config examples/knowledge.toml --group test-group-a --query "发布权限"
.venv/bin/python -m wechat_cs answer preview --config examples/knowledge.toml --group test-group-a --query "W403_PUBLISH_PERMISSION 发布权限" --offline
.venv/bin/python -m wechat_cs answer explain --config examples/knowledge.toml --group test-group-a --query "发布权限"
# 查看与原 task_id 关联的本地 shadow 快照（含资料正文，仅供授权本机操作者查看）
.venv/bin/python -m wechat_cs answer explain --config examples/knowledge.toml --task-id TASK_ID
.venv/bin/python -m wechat_cs eval --config examples/knowledge.toml --cases docs/phase2/fixtures/cases.jsonl --predictions .runtime/predictions.jsonl --offline
# 合成测试夹具对照：独立为每例设置可信范围和语料；不把 golden 标签传入生产引擎
.venv/bin/python scripts/evaluate_phase2.py
.venv/bin/python -m pytest -q tests/test_knowledge.py
```

`eval` CLI 使用本地群绑定，绝不会用题目文本或评测文件覆盖部署范围；产生的是实际预测，不宣称答题通过。
夹具中的标签 ID 与程序内容哈希 ID 不同，不能直接混算。
`evaluate_phase2.py` 专门核对夹具真实文件/行号/哈希后登记证据、映射 ID，再用原评分器对比
manual-only、manual-history、all-sources，包含缺预测分母和引用追踪检查。报告在 `reports/phase2`。
夹具是用户提供的 `docs/phase2` 输入包；本轮保留其原始文件，未将它们混入实现提交。

要在原 Mock 接收链中启用，将本地配置的 `[knowledge]` 设置为：

```toml
[knowledge]
enabled = true
config_path = "examples/knowledge.toml"
```

同时把 `[wechat] binding_id` 设置为独立知识配置中已登记的绑定 ID（示例为 `test-group-a`），保留
`adapter="mock"`、`send_mode="dry_run"`、`allow_send=false`。
运行 `.venv/bin/python -m wechat_cs run --config config.local.toml --duration-seconds 10`。
Mock 不会自行制造问题；确定性测试使用 Fake 快照验证完整接收→检索→草稿→shadow 链路。
设回 `enabled=false` 即使用原回复引擎，不删库、不重置发送预算、不重放旧事件。

具体资料清单、权限、更新/撤销、定位、人工处理及能力限制见 [知识操作手册](reports/phase2/OPERATIONS.md)。
实际基线和验证结论见 [P0 代码地图](reports/phase2/CODEBASE_MAP.md)、[交付报告](reports/phase2/TEST_REPORT.md)。
