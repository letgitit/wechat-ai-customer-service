# 开发目标与 Codex 指令

本文件是任务规格，不是 Codex 内置配置文件。由短 `/goal` 指令显式要求 Codex 阅读。
推荐分为两个 Goal：A 完成可自动验证的代码；B 在明确授权的 Windows 测试群完成实机验证。

## Goal A：完成 v0.1 代码与离线验收（现在执行）

### 可直接复制到 Codex 的指令

```text
/goal 阅读 AGENTS.md、PLAN.md、ACCEPTANCE.md 和 config.example.toml，在当前项目实现普通微信群 AI 客服 v0.1。按 M0→M4 实际编写代码、运行测试并修复，不要只输出方案。限定 Python 3.11、wxauto4 免费版、SQLite、HTTPX、单测试群、#客服 文本触发；不引入 Java、TS 后端、Web 前端、Dify 或复杂 Agent。先实现 FakeWechatAdapter 的完整闭环，再实现 Windows 适配器；本 Goal 不操作真实微信、不调用真实外部模型。完成全部离线核心验收，Ruff 检查通过，核心分支覆盖率达到 85%，Mock 演示和崩溃恢复测试通过，并提供可运行的诊断/启动/暂停/恢复/审核命令、配置示例、Windows 验收步骤和真实测试报告后停止。实机项目标记 NOT_RUN，不得用 Mock 结果替代。如果外部环境阻塞，先完成其他可执行项，再写明证据与最小解除步骤；不得删测试、关闭安全门禁或伪造通过。
```

### Goal A 完成条件

全部 M0—M4 已实现；离线核心案例通过；项目可安装、Mock 演示可复现；真实适配器有隔离的契约测试和诊断入口；
真实微信收发保持未运行。实现了真实适配器不等于已验证客户端兼容。

## Goal B：Windows 实机验证（Goal A 通过后执行）

在本机登录微信，人工打开一个唯一命名的内部测试群，复制并填写 `config.local.toml`；不要提交该文件。
首次进行只读检查。若需少量发送测试，操作者必须额外授权具体群名、本次发送上限和测试范围。

### 可直接复制的指令

```text
/goal 按 PLAN.md 的 M5 和 ACCEPTANCE.md 的 W01—W12 验证当前项目。先复跑离线门禁，再在 Windows 原生 Python 3.11 和已登录的微信桌面会话中执行只读诊断与 dry-run。只使用操作者在 config.local.toml 中明确指定的内部测试群，不使用生产客户群。登录、验证码、当前会话确认和真实发送授权由操作者完成；授权前不调用发送函数。获准后先做不超过 3 条固定回复验证，其他需要发送的案例另行取得有限授权。核验免费版实际接口、历史基线、新消息读取、目标群校验、发送回读、人工暂停和重启恢复。所有结果写入 reports/WINDOWS_VALIDATION.md，注明实际版本、步骤、时间和脱敏证据。环境或权限不足时标记 BLOCKED，不能改用 Mock 冒充实机通过，不能绕过沙箱、自动降级微信或购买 Plus。完成已获授权的测试并关闭程序后停止。
```

### Goal B 的实际完成口径

- READY_FOR_READONLY：离线通过，已具备只读诊断条件。
- READONLY_PASSED：实机读取和 dry-run 有证据；尚未证明能发送。
- FIXED_REPLY_SMOKE_PASSED：有限固定回复闭环有证据；尚未等于全部可靠性测试通过。
- WINDOWS_VALIDATED：约定的 Windows 案例全部完成，剩余限制已列明。
- BLOCKED：缺少环境、授权或兼容性，需明确条件；不是成功完成。

## 可选 Goal C（不属于本次自动执行范围）

只有操作者明确授权提供方、模型、接口地址、费用与可发送数据范围后，才进行真实 LLM 测试。
Goal A 已通过 HTTP MockTransport 测试并不代表真实提供方兼容。测试只发送合成问题和示例 FAQ。

## 使用说明

Codex 的 `/goal` 用于绑定持续目标；可用 `/goal` 查看，`/goal pause` 暂停，`/goal resume` 恢复，`/goal clear` 清除。
官方文档对目标正文设有 4,000 字符上限，所以把详细规格放在文件中，不把整份 PLAN.md 粘进命令。[S1][S2]
若当前 CLI 不显示该功能，先检查版本及 `codex features list`；受支持版本可用 `codex features enable goals` 开启。[S1]
不要为启用 goal 关闭沙箱或审批。这里暂停 Codex Goal，不等同于暂停已经运行的客服进程；客服进程有独立 pause/stop 命令。
