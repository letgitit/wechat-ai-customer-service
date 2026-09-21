# Goal A 实际验收报告

验证日期：2026-09-20。最终状态：**PASS（仅离线 Goal A）**。M0—M4 已实现；Windows 与真实模型全部 NOT_RUN。

最终 pytest：141 passed，0 failed，0 errors，0 skipped。
核心语句+分支总覆盖：98.40%；纯分支：96.67%（145/150）。目标 ≥85%，无排除核心模块、无删除测试或降低门禁。

## 环境与命令证据

- 实际环境：[environment.json](environment.json)，macOS arm64 / Python 3.11.15；wxauto4 未安装。
- 完整命令、UTC 时间和逐命令退出码：[qa.json](qa.json)。
- 测试明细：[junit.xml](junit.xml)、[qa-3.txt](qa-3.txt)、[coverage-core.json](coverage-core.json)。
- Mock 演示：[demo.json](demo.json)：1 事件、1 任务、1 虚拟发送，真实发送 0、外部模型 0。
- 独立崩溃恢复：[qa-5.txt](qa-5.txt)，退出码 0；故障子进程预期退出 77，父测试成功。
- Mock doctor：[doctor-mock.json](doctor-mock.json)，没有 GUI 初始化或发送。
- 安装/构建/独立临时环境 wheel smoke：[package-validation.json](package-validation.json)，7 个命令全部退出 0，临时环境已清理。
- 适配器隔离测试：[adapter-contract-tests.txt](adapter-contract-tests.txt)、[coverage-adapter.json](coverage-adapter.json)。44 个测试通过，适配器总体覆盖 88.81%，与核心覆盖分开统计；不是 Windows 端到端成功。

| QA 命令 | 退出码 | 证据 |
|---|---:|---|
| `python -m ruff check .` | 0 | [qa-1.txt](qa-1.txt) |
| `python -m ruff format --check .` | 0 | [qa-2.txt](qa-2.txt) |
| `python -m pytest -q -m not live_wechat and not live_llm --cov --cov-branch --cov-report=term-missing --cov-report=json:reports/coverage-core.json --junitxml=reports/junit.xml` | 0 | [qa-3.txt](qa-3.txt) |
| `python -m wechat_cs demo --scenario examples/scenarios/basic.json --report reports/demo.json` | 0 | [qa-4.txt](qa-4.txt) |
| `python -m pytest -q tests/test_m2.py::test_a26_crash_recovery_subprocess` | 0 | [qa-5.txt](qa-5.txt) |
| `python -m wechat_cs doctor --adapter mock --report reports/doctor-mock.json` | 0 | [qa-6.txt](qa-6.txt) |

## A01—A38 映射

以下每行均基于本轮完整 pytest（退出码 0）；参数化变体数量详见 JUnit。

| ID | 状态 | 测试函数（tests/ 下） | 实际行为 |
|---|---|---|---|
| A01 | PASS | `test_m0.py::test_a01_a02_defaults；test_m4.py::test_a01_a36_a38_cli_demo_doctor_help` | 非 Windows 导入/演示，不导入 GUI；全套禁 socket |
| A02 | PASS | `test_m0.py::test_a02_invalid；test_m4.py::test_a02_cli_config_and_platform_errors` | 安全默认；非法类型/枚举/配置、缺授权均拒绝 |
| A03 | PASS | `test_m1.py::test_a03_historical_baseline` | 历史仅建立基线，0 任务/发送 |
| A04 | PASS | `test_m1.py::test_a04_a05_a11_fake_roundtrip` | 重复快照 10 次保持单事件 |
| A05 | PASS | `test_m1.py::test_a04_a05_a11_fake_roundtrip` | 1 事件/1 任务/1 Fake 发送 |
| A06 | PASS | `test_m2.py::test_a06_rolling_anchor` | 窗口滚出，仅处理锚点后的新增 |
| A07 | PASS | `test_m2.py::test_a07_a16_distinct_ids_same_name_text` | 不同 UI ID 两任务，预算限制发送数 |
| A08 | PASS | `test_m2.py::test_a08_idempotent_event` | event/UI 唯一约束不重复创建任务 |
| A09 | PASS | `test_m2.py::test_a09_gap_cancels_tasks；test_delta_reappearing_old_id` | 丢锚点/重建/碰撞/内容变化/重排，取消任务并暂停 |
| A10 | PASS | `test_m2.py::test_a10_empty_baseline_and_read_failure；test_m4.py::test_a37_missing_fields_fail_closed` | 有效空基线接受新增；异常/非列表读取拒绝 |
| A11 | PASS | `test_m1.py::test_a04_a05_a11_fake_roundtrip；test_m2.py::test_a11_a12_ignore_sources_types` | 自身消息不产生回复 |
| A12 | PASS | `test_m2.py::test_a11_a12_ignore_sources_types` | system/other/未知来源与非文本忽略 |
| A13 | PASS | `test_m2.py::test_a13_prefix` | 前缀边界与中文/英文冒号、换行验证 |
| A14 | PASS | `test_m1.py::test_a14_fixed_followup_dry_run；test_m3.py::test_a30_faq_miss_never_calls_model` | 空问题生成固定追问，无 HTTP |
| A15 | PASS | `test_m2.py::test_a15_oversized_question；test_m3.py::test_a30_faq_miss_never_calls_model` | 超长/控制字符拒绝；超长内容不完整落库或外发 |
| A16 | PASS | `test_m2.py::test_a07_a16_distinct_ids_same_name_text` | 同昵称独立事件，不建长期上下文 |
| A17 | PASS | `test_m2.py::test_a17_independent_send_gates；test_a17_adapter_kind_gate；test_m4.py::test_a17_real_sdk_never_called_when_gate_missing` | 逐项禁用门禁；Fake SDK SendMsg 调用次数均为 0 |
| A18 | PASS | `test_m2.py::test_a18_a19_target_or_epoch_change` | 绑定/群名/群类型不符取消并暂停 |
| A19 | PASS | `test_m2.py::test_a18_a19_target_or_epoch_change；test_storage_late_generation_rejected；test_m3.py::test_a19_a34_slow_model_ui_progress_and_late_result` | 旧 epoch/generation/run 结果不能发送 |
| A20 | PASS | `test_m2.py::test_a20_pause_before_claim；test_m4.py::test_pause_resume_race_during_ingestion` | 占用前暂停取消；采集与恢复竞态不写旧事件 |
| A21 | PASS | `test_m2.py::test_a21_pause_after_claim` | 在途数 1，首条可能完成，后续取消 |
| A22 | PASS | `test_m2.py::test_a22_pause_resume_rebaseline` | 恢复重新基线，不补发积压 |
| A23 | PASS | `test_m2.py::test_a23_a24_unknown_no_retry_or_approve；test_m4.py::test_a23_a24_a37_sdk_send_results` | 发送异常 UNKNOWN，循环/审批/恢复不盲重试 |
| A24 | PASS | `test_m2.py::test_a23_a24_unknown_no_retry_or_approve；test_m4.py::test_sdk_preexisting_echo_does_not_prove_new_send` | SDK 成功无新 self 回显仍 UNKNOWN |
| A25 | PASS | `test_m2.py::test_a25_unique_self_echo；test_m4.py::test_a37_free_api_mapping_and_echo` | 新 self 文本/任务标记匹配才 OBSERVED_SENT |
| A26 | PASS | `test_m2.py::test_a26_crash_recovery_subprocess` | 子进程 os._exit(77)：SENDING→UNKNOWN，READY→DRAFT，0 重发 |
| A27 | PASS | `test_m2.py::test_a27_expiry_interval_budget_persist；test_a27_interval_virtual_clock；test_m4.py::test_run_deadline_no_next_send；test_deadline_during_preflight` | 虚拟时钟 TTL/间隔、持久预算、截止时限阻止后续发送 |
| A28 | PASS | `test_m2.py::test_a28_global_lock_different_databases` | 真实模式不同 DB 同用户锁冲突；Mock 独立 |
| A29 | PASS | `test_m3.py::test_a29_faq_aliases` | 精确/别名/正规化返回实际来源，无 HTTP |
| A30 | PASS | `test_m3.py::test_a30_faq_miss_never_calls_model` | 未命中转人工，不调用模型 |
| A31 | PASS | `test_m3.py::test_a31_authorization` | 配置/运行/key 三项缺失拒绝；fixed/faq 不需要 key |
| A32 | PASS | `test_m3.py::test_a32_request_and_review` | 请求仅当前问题/FAQ；合法响应进 DRAFT 等审核 |
| A33 | PASS | `test_m3.py::test_a33_provider_failures` | 16 种故障变体含超时/401/429/5xx/重定向/非法响应；单次请求、人工状态、0 发送 |
| A34 | PASS | `test_m3.py::test_a19_a34_slow_model_ui_progress_and_late_result；test_model_queued_work_cancelled_on_pause` | 慢模型期间 5 次 UI 推进；不同线程，暂停取消排队，退出无工作线程残留 |
| A35 | PASS | `test_m3.py::test_a35_prompt_injection_is_data` | 注入仅是数据，无工具、无改目标、无直接发送 |
| A36 | PASS | `test_m4.py::test_a36_cli_controls_and_terminal_approval；test_a36_cli_invalid_args；test_cli_finite_mock_run` | 诊断/运行/状态/暂停/恢复/审核/帮助/参数错误及终态 |
| A37 | PASS | `test_m4.py::test_a37_free_api_mapping_and_echo；test_a37_missing_fields_fail_closed；test_a37_owner_thread_and_missing_api` | 注入工厂验证免费 API/字段/所有者线程；缺字段 fail-closed |
| A38 | PASS | `scripts/qa.py；test_m4.py::test_cli_untrusted_exception_redaction；reports/package-validation.json` | 六项 QA 退出码均 0，纯分支达标；演示、重启、日志类别脱敏、独立 wheel 安装验证 |

## 实机和外部模型

| ID | 状态 | 原因/最小解除步骤 |
|---|---|---|
| W01 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W02 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W03 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W04 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W05 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W06 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W07 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W08 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W09 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W10 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W11 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| W12 | NOT_RUN | Goal A 不授权真实微信；需 Windows 原生 Python 3.11、已登录的授权内部测试群，按 README 单独 Goal B 执行 |
| L | NOT_RUN | 未授权真实模型/费用；需另行批准提供方和合成数据范围，不能用 HTTP MockTransport 代替实调 |

Windows PowerShell 脚本仅完成代码交付，实跑 NOT_RUN；没有通过修改系统保护或绕过授权解除阻塞。

## 边界与过程

- 测试数据完全合成；HTTP 成功仅表示已实现契约的 Mock 行为。
- 群名不是稳定群 ID；同名群、不可观察的桌面竞争、消息漏读、客户端升级风险仍存在。
- 不保证服务端 exactly-once、消息零丢失或官方送达/已读回执。
- SDK 返回成功无回显仍 UNKNOWN；旧 READY 重启为草稿供核对，不能跨 epoch 审批。
- 所有测试进程已返回；模型线程有退出断言，未启动常驻微信、服务或自动任务。
- 首轮 M4 有 1 个测试失败与 4 个 Ruff 问题；失败证据保留在 m4-tests-initial.txt / ruff-m4.txt。已修复并通过最终门禁，不把首次失败写成通过。
- 当前目录没有 .git，不初始化 Git、不创建提交、不推送。
- [PROGRESS.md](PROGRESS.md) 记录阶段；[DECISIONS.md](DECISIONS.md) 记录依据、偏差与外部解除步骤。
