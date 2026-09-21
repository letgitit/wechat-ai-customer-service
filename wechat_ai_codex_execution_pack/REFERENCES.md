# 原始资料与核验记录

核验日期：2026-09-20。以下是外部能力说明的来源；其余架构、默认参数、状态机和验收阈值均为本项目设计。
开发时应重新检查实际版本与接口，网页声明不等于本机运行验证。

## S1｜OpenAI：Follow a goal

```text
https://learn.chatgpt.com/use-cases/follow-goals
```

说明 `/goal <objective>` 的执行目标、验证循环、暂停/恢复，以及 goals 功能开关。
不代表当前用户安装的所有 Codex 版本都已经具备相同界面。

## S2｜OpenAI：Developer commands / AGENTS.md

```text
https://learn.chatgpt.com/docs/developer-commands?surface=cli
https://learn.chatgpt.com/docs/agent-configuration/agents-md
```

前者列出 `/goal` 命令和 4,000 字符目标上限；后者说明 Codex 读取 AGENTS.md 的机制。
GOAL.md、PLAN.md、ACCEPTANCE.md 是本项目显式要求读取的文件，不是自动生效的内置文件名。

## S3｜wxauto：安装与环境

```text
https://docs.wxauto.org/docs/install.html
```

当次页面：免费包 `wxauto4`，Python 3.9—3.12；免费兼容页列到客户端 4.1.8.107。
此客户端号只用于核验兼容信息，不是指示自动下载或强制降级。项目不提供微信安装包。
该工具是 Windows 桌面 UI 自动化；不据此承诺微信官方授权、稳定性或账号安全。

## S4｜wxauto：WeChat 类

```text
https://docs.wxauto.org/docs/class/WeChat.html
```

窗口定位等基础方法与 Plus 方法混排；带星号的监听、在线信息、子窗口等方法不可用于本项目免费版依赖。

## S5｜wxauto：Chat 类

```text
https://docs.wxauto.org/docs/class/Chat.html
```

基础能力包括 ChatInfo、SendMsg、GetAllMessage。读取范围是当前 UI 会话，而非官方服务端历史消息流。
返回结构与实际安装包需做适配器契约验证。

## S6｜wxauto：Message 类

```text
https://docs.wxauto.org/docs/class/Message.html
```

来源属性区分 self/friend/system/other；UI ID 会随 UI 切换而变化；发送者是显示名称。
消息 hash 标为 Plus 能力。不能把 UI ID 当永久消息主键或把昵称当客户身份。

## S7｜Python：sqlite3

```text
https://docs.python.org/3.11/library/sqlite3.html
```

用于存储实现；应遵守连接线程与事务限制。每个线程/进程拥有自己的连接，耗时外部操作不持有写事务。

## S8｜HTTPX：Transports

```text
https://www.python-httpx.org/advanced/transports/
```

HTTP MockTransport 用于模型成功、超时、错误和无效响应的确定性测试，不产生真实服务商调用。

## S9｜filelock

```text
https://py-filelock.readthedocs.io/en/latest/
```

用于单实例跨进程锁；真实微信锁应按当前桌面用户绑定，不能仅按某个数据库文件路径上锁。

## 解释边界

本方案没有验证用户电脑、微信账号、实际客户群或任何真实模型密钥。
没有获得上述环境的执行证据前，报告中对应项目必须保持未执行或阻塞。
自动化工具的许可与微信平台授权并非同一件事；正式使用前由项目负责人核实适用要求。
