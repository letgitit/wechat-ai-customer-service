# 多源知识操作手册

## 配置和安全默认值

`config.example.toml` 的 `[knowledge] enabled=false, config_path=""` 是主程序开关。
独立知识配置参考 `examples/knowledge.toml`：`mode=shadow, auto_send=false, require_review=true`。
其他模式直接拒绝。知识配置的 db_path/manifest 相对该配置文件，manifest 的 root 相对 manifest；
主程序 config_path 相对启动目录。群绑定来自本机 group_bindings，必须明确 tenant/product/version，
代码召回还要求 deployed_revision 精确相等。unknown 不等于 latest；未配置版本只追问。
版本采用管理员登记的精确字符串相等，不做字符串大小排序或自动挑最新。

本轮原审核命令不具备知识证据复核能力，因此影子草稿关联原 task_id 后写入 knowledge.sqlite3/shadow，
原 reply_task.answer 留空，不能通过 tasks approve。需要人工到原业务渠道核实处理；本轮不实现发送。
模型线程只接收文本及普通配置，在自身线程创建知识库连接；微信及原业务库保持主线程所有权。

## 三类来源登记

以 `examples/knowledge-sources.toml` 为可运行合成样例。每个来源须填写 enabled/id/type/root/include、
product_id/version/revision、tenant_ids/group_ids/status/reviewer、audience、valid_from、synthetic，
以及 allow_customer_derivation / allow_external_generation / allow_external_embedding 三项明确布尔值。
valid_until 不填表示无指定截止日，其余缺项按文件 BLOCKED，不猜产品、版本或权限。
只有 active、未过期、已审核、客户衍生授权为 true 的资料参与回复检索。
shared 必须显式登记；默认没有共享范围。external generation 与 embedding 分别校验。

- 手册：MD/TXT 按标题完整分块；DOCX 读取 OOXML 段落和表格行，保留单元格分隔符，不伪造页号。
  DOCX locator 的 line 是导出段落/表格行序号，section 描述这种定位约定；PDF 使用实际页号和页内提取行。
  PDF 空页、扫描页、损坏、加密均报告文件级具体原因，不做 OCR，不将零正文标为成功。
  PDF 排版提取不保证复杂跨页表格的语义顺序，仍须人工核查；需要时使用已校对文本。
- 产品代码：必须显式 `role="product"`、独立 root 和扩展名 include，绝无客服工程默认扫描。
  非 synthetic 源必须填完整 40 位 commit；读取 `git show commit:relative-path` 与工作树字节一致才接受。
  Python 使用 AST 原始范围，其他语言只作带重叠行块的 fallback，不声称调用图/语义分析。
  不执行产品脚本。拒绝 symlink、路径逃逸、秘密/生产配置、依赖/构建目录、二进制和超 2 MB 文件。
- 历史案例：JSONL 或 CSV，显式 question/context/answer/resolution、resolved=true、review_status=approved、
  reviewer、case_id、product_id/version/tenant_id/group_id。CSV 布尔值使用小写 true/false。
  locator 保留实际物理行范围，section 为原 case_id。没有原事件ID的合成记录以原 case_id+文件行追溯，
  不制造事件ID；真实导入前由操作者整理原事件/时间上下文。失败/未审/无确认结果的记录不会变成正向知识，
  不按昵称关联群聊；不将生成答案自动回灌。数据库原始群日志候选导出未实现，本轮采用人工整理文件。

源文件发现常见密钥、手机号、邮箱等敏感内容会拒绝整个文件而非上传。应先人工去身份化并审核授权；
规则无法证明任意敏感信息都可识别，真实资料仍需人工数据审核。源根目录、清单和本地数据库应由可信操作者控制。

## 增量更新和撤销

重复执行 `kb ingest`，证据身份由 source_id+revision+locator+内容 SHA256 确定。
相同片段不更新，变更片段替换；文件删除、include 移除、来源禁用会清除本清单旧片段。
撤销 status 或更改范围后必须再次 ingest；库中保存前后政策元数据审计及内容哈希。
读取失败的文件会移除旧片段，避免继续使用旧授权正文，查看 files 中 BLOCKED 原因后处理。
导入同一清单是一笔事务；不同清单不得抢占同一证据身份。修改清单前建议复制知识数据库作运维备份。
既有客服业务库没有 schema 修改或数据迁移。

检索每次使用当前知识数据，无问答缓存。先按授权构造 SQLite FTS5 分区再 BM25，索引/查询统一 jieba 搜索分词，
保留错误码、权限键、路由、snake_case/CamelCase 原词与拆词；本机 retrieval.aliases 为可审核术语词典。
FTS SQL 参数化，用户查询词加双引号转义，不解释用户 FTS 语法。
小数据量下保存预分词，并为每次查询构建授权临时 FTS 分区（O(n)）；未声称大规模性能达标。
片段超上下文预算时整片排除，不截断前提或表头；本轮不做相邻片段扩展或模型改写。
分词器版本不匹配拒绝使用，需在新的知识 DB 完整重导，不删除业务 DB。

## 模型、向量和人工审阅

默认 Mock 是机械证据摘录，只验证链路。HTTPX 请求复用原 Replies.request_json：独立超时、输出字节限制、
禁止重定向/环境代理、无自动重试、拒绝工具调用/截断/非法 Schema/额外字段。真实配置需 provider=httpx，
原 llm 段 allow_external_calls=true、endpoint/model/key 环境变量以及运行级 --allow-llm。
本轮未授权或执行真实模型；知识 CLI 只支持离线 Mock，不提供偷偷切换真实模型的选项。

向量默认 disabled，报告 lexical + embedding_disabled/semantic_retrieval=NOT_RUN。
代码提供可注入 encode/model/dimension/external 的向量接口，授权候选先过滤，维度和有限值校验后余弦排序/RRF，
失败显式降级。无预装 embedding 服务/权重，也没有真实服务 CLI 配置；不可用时拒绝未知 provider。
当前按次计算向量、不持久化向量，因此不存在跨模型混用旧向量；记录模型、维度、归一化与来源revision。
契约测试向量仅验证数学与范围，不代表真实语义能力。

每次生成独立校验 Schema、引用属于当次证据、当前来源一致性、权限/版本/到期、常见敏感内容和运行态断言。
同版本互斥的引用操作路径会转人工；这只是保守规则，任意语义矛盾和引用是否支持结论仍须人工确认。
生成结束后主线程再次校验任务/暂停/取消/TTL/run/epoch/generation，重新读取群绑定和来源。
shadow 在本机可追溯但不具备发送授权。`answer explain --task-id` 展示的是历史快照，不是重新审批；
来源之后撤销时历史记录仍用于审计，严禁把历史 safe_customer_reply 当作最新可发送结论。
shadow 内容按 retention_days 在新草稿归档时清理；长期停机时需由管理员按本机数据保留政策处理备份。

## 验收边界

报告区分原测试、新增安全契约、合成夹具检索、真实模型、真实语义检索与真实客户质量。
当前真实模型/向量服务、真实客户题人工采用率/无依据断言率/引用支持、Windows 微信均 NOT_RUN。
启用真实服务或用于客户前需要单独授权与评测；没有“Mock 全过所以可自动发送”的结论。
