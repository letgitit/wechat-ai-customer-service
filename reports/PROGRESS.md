# 阶段执行记录

日期：2026-09-20。按 M0→M4 实际实现；所有路径相对项目根目录。
原执行包仅为规格，本目录才是此次运行结果。

| 阶段 | 实现与验证 | 结果/证据 | 剩余项 |
|---|---|---|---|
| M0 | 读取全部规格/参考资料、核对 Python 和官方 API；工程、配置、模型、依赖 | `python -m pytest -q tests/test_m0.py`，11 passed；m0-tests.txt | 进入 Fake 闭环 |
| M1 | Fake、固定回复、SQLite 最小闭环、基线/self 过滤 | M0+M1 14 passed；m1-tests.txt | 安全与恢复场景 |
| M2 | 保守差分、状态机、双进程锁、暂停/恢复、持久预算与重启恢复 | M0—M2 64 passed；m2-tests.txt；崩溃子进程退出77为预期故障注入 | FAQ/HTTP |
| M3 | FAQ 来源、HTTPX provider、审核、异步队列、错误/迟到结果 | M0—M3 96 passed；m3-tests.txt | Windows 隔离适配与 CLI |
| M4 首轮 | 免费 API 工厂适配、诊断/运行/管理 CLI、QA、场景演示 | 133 passed / 1 failed；m4-tests-initial.txt。Ruff 4 个问题见 ruff-m4.txt | 修复后重新门禁 |
| M4 修复 | CLI 取消后查询补齐；默认参数/长行；暂停恢复入库竞态、发送截止时限、排队模型取消及错误脱敏 | 最终 141 passed / 0 failed / 0 skipped；完整 qa.json 中六命令退出码均0；纯分支96.67% | 离线项无剩余 |
| M4 打包 | locked/offline sync、源码包和 wheel 构建、独立临时环境安装/doctor/demo | package-validation.json 中7命令退出码均0；独立环境已清理 | 无 |
| M5 / L | 本 Goal 不执行实机/真实模型 | 全部 NOT_RUN；WINDOWS_VALIDATION.md | 单独授权与 Windows 环境 |

## 执行中的问题与修复

1. 系统默认 python3 为 3.14.6，切换到已有 Python 3.11.15 创建 .venv，未改系统 Python。
2. 初次依赖安装受沙箱网络限制，退出2；经工具授权后只访问 PyPI 安装指定依赖成功。
   网络仅用于开发资料/依赖解析；测试没有访问真实模型。
3. M4 首轮 CLI 测试断言希望输出 CANCELLED，却只在取消前读列表；补上取消后 list 调用，保留数据库状态断言。
   同轮 Ruff 提示默认构造调用与三行过长；修改实现后重新检查全部通过。
4. 最后安全检查补充了 generation 入库原子校验、发送循环时限检查、暂停取消排队模型任务、CLI 错误白名单脱敏。
   每项均补了回归测试，不删除旧测试。另验证 GUI 初始化失败前先恢复 SENDING，避免界面不可用时遗留在途状态。
5. 含 Windows markers 的锁文件只完成解析；没有在 macOS 冒充验证 Windows GUI 或依赖安装。

## 退出码与最终运行

阶段早期日志为 pytest 原始输出；最终 `python scripts/qa.py` 自身退出0，并在 qa.json 逐项记录子命令实际退出码/时间。
`python -m pytest -q tests/test_m4.py --cov=wechat_cs.adapters.wxauto_adapter --cov-branch ...`
独立适配器报告退出0、44 passed、总体覆盖88.81%；不混入核心或实机统计。
完整复现命令、验收映射及日志链接见 ACCEPTANCE_REPORT.md。

当前目录不是 Git 仓库，无本地提交；没有推送、部署、修改系统安全策略、操作真实微信或启动常驻进程。
