# 实现决策与能力核验

日期：2026-09-20；Goal A。

- 项目根目录放实现，原 `wechat_ai_codex_execution_pack` 规格保持原样；原包内报告仍为模板，不是本轮结果。
- 小回复引擎合并为 `replies.py`；公共数据契约位于 `models.py`，不引入额外服务或框架。
- 四张 SQLite 表，默认线程检查、外键、WAL、5 秒 busy timeout、短事务；耗时操作在事务外。
- 内部增加 GENERATING 状态，先持久化任务再提交单线程模型队列；run_id/generation/epoch 三重隔离。
- 暂停/恢复竞态以入库时校验采集 generation 处理；暂停取消尚未开始的模型 future。
- 保守预算累计在数据库审计中，重启、内容清理、重绑均不清零。无自动预算重置命令；后续实机测试需明确新授权。
- 重启旧 READY 降为 DRAFT 供核对，禁止跨 epoch 批准；不提供 UNKNOWN 重发接口。
- 固定/FAQ 仅 auto 可自动 READY；LLM 始终人工审核，配置关闭此门禁直接报错。
- 用完整 UUID 作消息标记，避免短 ID 碰撞；wire 文本由程序加前缀，模型不提供发送目标。
- Wxauto 使用操作者当前主会话，不使用 ChatWith 模糊搜索或 Plus 接口。调用 SendMsg 时只传 msg。
- 发送后最多 3 次快照回读（未出现回显时每次间隔 0.2 秒），未证实时 UNKNOWN，不补发。
  该窗口是保守本地确认策略，可能把较慢成功发送标为 UNKNOWN；人工核对优先于重复发送。
- 启动按 retention_days 清理，另有显式 CLI 内容擦除，保留幂等/预算/审计，不删除用户数据库。
- 未实现实机 live 自动测试入口，Goal A 测试套件拒绝网络与 GUI 导入；实机逐项按 README 单独验收。

## 当次官方资料核验（网页不是实机证据）

- [wxauto 安装](https://docs.wxauto.org/docs/install.html)：Windows 桌面要求；网页与 PyPI Python 支持范围存在不同，项目固定 Python 3.11。
- [PyPI wxauto4](https://pypi.org/project/wxauto4/)：当次版本 41.1.7，2026-09-01 发布，提供 CPython 3.11 Windows x64 wheel。
  已锁定包版本；本机 macOS 不安装 GUI 包，实际已安装版本记录为 NOT_INSTALLED。
- [Chat 类](https://docs.wxauto.org/docs/class/Chat.html)：ChatInfo 返回 chat_name/chat_type；GetAllMessage 返回列表；SendMsg 的 msg 参数与可省略 who 已核对。
- [Message 类](https://docs.wxauto.org/docs/class/Message.html)：使用 id、attr、type、sender、content；attr 区分来源，id 是 UI ID，hash 是 Plus 能力，未使用。
- [HTTPX Transports](https://www.python-httpx.org/advanced/transports/)：HTTP MockTransport 测试；实际安装 httpx 0.28.1。
- [filelock](https://py-filelock.readthedocs.io/en/latest/)：进程锁；实际安装 3.20.3，已做双进程锁冲突测试。
- `uv.lock` 为全部 extras 解析，`requirements.lock` 为含哈希、Windows markers 的导出；macOS 已执行 locked/offline sync。
  Windows 依赖解析成功不等于 Windows 安装/客户端兼容测试通过。

## 外部环境与最小解除步骤

本机 macOS arm64、Python 3.11.15，无 Windows 原生桌面与 wxauto4，且 Goal A 明确未授权操作真实微信/模型。
M5/W01—W12、L 全部 NOT_RUN。需要操作者另开 Goal B、提供 Windows 原生 Python 3.11 和已登录的授权内部测试群，
按 README 先只读；有限发送还需本次目标、上限和范围授权。模型实调需另行授权提供方、数据范围和费用。
无需解除任何安全门禁；不需要替换测试或修改系统保护。
