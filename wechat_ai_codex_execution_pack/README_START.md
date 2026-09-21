# 普通微信群 AI 客服：Codex 技术执行包

版本：v0.1 规格，2026-09-20。
交付物性质：开发目标、技术方案、验收契约和配置模板；**不包含已经实现的客服程序，也没有实际微信测试结论**。

## 你的目标

保留已有普通微信群，让普通微信客服账号加入群内。先用 wxauto 免费版测试；全 Python 开发，尽量少组件。
首版仅一个测试群、文本 `#客服 问题`、固定回复/本地 FAQ/可选模型草稿、SQLite 记录和命令行人工控制。

## 开始开发

1. 在电脑上创建一个项目目录，例如 `wechat-ai-customer-service`，将本包的内容放进项目根目录。
   已有项目应合并文件，不能覆盖既有 AGENTS.md 或配置。
2. 在该目录中打开 Codex。先让其读取 AGENTS.md；把 GOAL.md 中的 **Goal A** 整段命令粘给 Codex。
3. Goal A 结束后，查看 `reports/ACCEPTANCE_REPORT.md`，确认离线测试有真实命令和结果，不只是声明“已完成”。
4. 把项目放到 Windows 测试电脑，再按 Goal B 开始只读和有限真实发送验证。

任务可先在 Mac/Linux/WSL 的 Mock 环境开发；wxauto 的真实执行路径限定 Windows 原生 Python 和可交互桌面。[S3]
不能因为 Codex 在非 Windows 环境，就跳过业务开发；也不能因此声称微信实机已验证。

## 文件说明

| 文件 | 作用 |
|---|---|
| AGENTS.md | Codex 每次执行应遵守的项目约束 |
| GOAL.md | 可复制的 Goal A / Goal B，及停止条件 |
| PLAN.md | 架构、数据流、状态机、CLI、实现里程碑 |
| ACCEPTANCE.md | 离线和 Windows 实机验收清单 |
| config.example.toml | 待实现程序的默认安全配置契约 |
| REFERENCES.md | 已核查的原始资料与使用边界 |
| reports/PROGRESS.md | 执行进度模板，初始未执行 |
| reports/ACCEPTANCE_REPORT.md | 验收报告模板，初始未执行 |

## 两个阶段的区别

Goal A 的目标是“代码可运行、模拟闭环和恢复测试通过”，不是“客服已经上线”。
Goal B 的目标是“在明确授权的真实测试群中验证所选客户端和免费库”。
真实模型接口与真实群发送是两个独立的对外动作，均不应由一条笼统的开发 Goal 默认授权。

## 最少需要你提供的内容

离线开发：只需要本任务包，不需要真实群名、微信账号密码或 LLM key。
实机测试：可运行的 Windows 电脑、已人工登录的普通微信账号、唯一名称的内部测试群、明确测试授权。
接模型：服务商地址、模型名和环境变量中的 key；不要把 key 发到群里或提交到 Git。

## 当前状态

文档包：已编写。
客服代码：待 Codex 实现。
离线测试：NOT_RUN。
Windows 微信读取/发送：NOT_RUN。
真实模型：NOT_RUN。

本包中的 `wechat_cs` 和 scripts 命令是 **Codex 需要实现的接口**，解压后不能直接当现成程序运行。
