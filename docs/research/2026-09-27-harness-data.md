# 跨 harness 数据接入与计量可信度研究

日期：2026-09-27。研究基线：`5ede8e57dcddde18cde4e836d5f5b469e3afd9d3`。本轮只研究，不修改解析器、配置或源数据库。

后续验证：已实际运行CodeBurn与本项目真实日期和合成数据对账，见[非绘图能力实测](2026-09-27-codeburn-verification.md)。本文保留第一轮调查的证据边界；下文“尚未运行”描述该轮状态，不代表后续仍未验证。

## 结论

统一层需要保留**逐条用量记录**，不能以现有 Codex `Session.models` 汇总为最底层。OMP 的会话记录和统计数据库都可作为研究入口，但不能未经覆盖验证就把 `stats.db` 当成完整、最新、不可争议的事实源。

产品目标是读取各 harness 已记录的 LLM 用量；不自动代理流量、不估算聊天文本 tokens、不修改 harness 配置。没有落盘的数据必须显示为覆盖缺口，不能承诺恢复全部历史调用。

## 1. 已核实的现项目边界

- `src/codex_usage/parser.py:32-56` 的 `Session` 缺少 harness、provider、独立调用标识与缓存写入维度。
- `parser.py:136-259` 按 Codex 的累计快照差分计量，处理重复帧、继承首帧、回落与缺失累计值。该策略应留在 Codex 适配器，不应用于 OMP 逐调用 usage。
- `parser.py:262-329` 扫描目录、处理归档副本并合并分页；最终已丢失每条记录的时间粒度。
- `stats.py:110-114,150-156` 将整份会话归到 `first_local` 所在日期。时间窗口内正确筛选，不等于跨日分桶正确。
- `stats.py:12-30` 和 `cli.py:100-105,144-158` 存在不同成本计算路径。新界面不应各自复制这些公式；必须收敛到共享查询结果。

### 实际运行：跨日聚合

使用临时目录生成两条合成 Codex `token_count` 记录，分别发生于 UTC 2026-09-25 12:00 和 2026-09-26 12:00，每条新增输入 100 tokens。直接调用当前 `parse_rollout`、`group_by_day`、`rec_tokens`。

观察结果：

```json
{
  "first": "2026-09-25 20:00:00",
  "last": "2026-09-26 20:00:00",
  "day_buckets": {"2026-09-25": 200}
}
```

两天应各为 100，现有聚合全部进入首日。执行成功，临时文件已自动清除；未增加测试或修改产品。这是选择调用粒度统一模型的实证，不是本轮已修复的缺陷。

### 实际运行：筛选污染复用记录

构造同时包含 `model-a`（100 tokens）和 `model-b`（200 tokens）的一个 `Session`，对同一记录集合依次调用 `apply_filters(model='model-a')` 和 `apply_filters(model='model-b')`。

观察：第一次查询后，缓存对象的 models 只剩 `model-a`；第二次查询返回 0 个会话。执行成功，没有文件写入。这证明 `stats.py:138-143` 的原地修改不能直接搬到 Web/TUI 长生命周期共享缓存中。修复属于后续实现，本轮只记录。

## 2. OMP 真实数据与官方统计能力

### 本机已验证

- `omp --version`：`omp/18.3.2`，退出码 0。
- `omp stats --help`：有 `--port`、`--host`、`--json`、`--summary`；`-s` 是 summary，退出码 0。
- `~/.omp/stats.db` 只读 schema 检查：`messages` 有 `session_file`、`entry_id`、`provider`、`api`、`model`、毫秒 timestamp、duration、ttft、stop_reason、输入/输出/缓存读/缓存写、cost 分量、`agent_type`、`cost_unpriced`。
- 当前项目 OMP 日志只做结构计数，不输出会话正文：141 条带 usage 的 assistant message、72 条 `model_usage`，后者 purpose 均为 `find`。
- 同一只读检查中，上述 72 条辅助记录按 `(session_file, entry_id)` 查询，没有一条已在统计库中；库共有 20,828 行，最大记录时间为 UTC `2026-09-26T05:40:40.679000+00:00`。

**限制：** 这是采样时的索引新鲜度证据，不是证明当前安装版本永久忽略 `model_usage`。本轮没有执行可能更新源库的 `omp stats --summary`、`--json` 或启动 dashboard，也没有同步/修改源库。计数会随新会话写入而变化，不作固定产品指标。

### 当前官方上游

[官方 stats README](https://github.com/can1357/oh-my-pi/tree/main/packages/stats) 明确：JSONL → SQLite 增量同步 → 本地网页；支持模型、项目、时间趋势、缓存、错误与性能指标。费用是 **API-equivalent estimate（按 API 价目折算）**，不是订阅用户账单；无公开价模型显示 N/A。

[官方当前 parser](https://github.com/can1357/oh-my-pi/blob/main/packages/stats/src/parser.ts) 有 `isModelUsage` 和 `extractModelUsageStats`，会处理独立辅助调用记录。`classifyAgentType` 区分 main/subagent/advisor。`resolveUsageTotal` 还涉及 provider 报告的 orchestration tokens，不能假定所有来源总量永远等于四个常见分量。

本机另有一份较旧的 OMP 源码，其中 stats parser 只处理 assistant message；它不等于本机安装二进制，也不等于当前上游。**版本差异必须成为适配能力诊断的一部分。**

第三方 [omp-token-usage](https://github.com/Corundum-Ling/omp-token-usage) 是参考实现，不是官方插件。其调用 `omp stats -s` 不能单独证明该参数的语义，也不能代替官方同步覆盖核验。

## 3. 竞品“支持 OMP”仍有覆盖边界

[CodeBurn 的 OMP/Pi 解析器](https://github.com/getagentseal/codeburn/blob/main/src/providers/pi.ts) 已确认单列 OMP 目录并发现子代理文件，但本次读取的主分支实现存在：

```typescript
if (entry.type !== 'message') continue
```

因此这个解析路径不会统计独立的 `type: model_usage`。这是源码级边界，尚未运行 CodeBurn 完整产品证明所有其他路径都没有补偿；不能将其扩大成整个产品绝对漏算的已实测结论。它足以否决“看到 OMP 支持列表便直接宣称覆盖所有调用”的决策方法。

同一源码只在有限嵌套层级发现子代理，缺省模型还有回退值；采用前需核验深层子代理、未知模型和模型/provider 身份，而非接受一个貌似完整的总数。

## 4. 统一记录与不变量

### 建议的最小内部记录

| 字段组 | 契约 |
|---|---|
| 来源 | harness、source kind、source record key、原始记录位置/格式版本；路径不作为跨源唯一身份 |
| 身份 | session ID、可核实的 parent session ID、agent kind/label；事件 parentId 不冒充父会话 |
| 调用 | UTC 时间、usage kind（主对话/子代理/辅助调用或 unknown）、原始 purpose；source 只有汇总时显式标粒度 |
| 模型 | provider、API 类型、原始 model；显示别名与计量身份分离，不猜测跨 provider 等价 |
| tokens | 净输入、缓存读、缓存写、输出、可选推理及其他源报告分量；保留源报告 total 与其语义 |
| 金额 | 来源记录的金额及其性质、按指定价格折算的金额、币种、价格来源/版本、未定价状态 |
| 质量 | 字段缺失、时间/身份可靠性、解析告警、覆盖能力；unknown 不等于 0 |

### 必须保持

1. 同一源记录重复扫描只贡献一次；OMP transcript 与其 stats 投影不可相加。
2. 不按模型名、时间接近或 token 相同跨 harness 猜测去重。可确认的复制/继承历史由源适配器处理。
3. 调用次数是可观察用量记录的次数，不声称包括未落盘的网络重试；零 token 的已记录请求与缺失 usage 区分。
4. 时间筛选和日桶以事件时间为准；内部 UTC，展示时区明确；窗口采用明确边界。日期缩写可继续映射到该本地日，不在核心使用 naive datetime。
5. 缓存字段按源语义归一，reasoning 若是输出子集不得再次相加。OMP orchestration 等额外分量必须保留来源语义，不能硬凑等式。
6. 同一查询的总量、明细、图表、JSON 在同一数据快照上相等；平均比率使用总量重算。
7. 来源估算金额、自己重算金额、实际账单是三种性质；来源字段叫 cost 不证明实际付费。未知价为 null，已知成本小计必须带缺价覆盖提示。
8. 金额计算采用十进制定点/Decimal，明确输入精度和舍入，展示层不能重复计算费用。

## 5. 数据接入方案取舍

### 推荐：独立适配器 + 自有可重建用量索引

Codex 保留专用计量策略；OMP 直接提取 assistant usage 和 `model_usage`，只持久化统计字段，不保存 prompt/message/tool 参数。两者进入统一记录，然后由同一查询核心服务两个界面。

自有 SQLite 索引是建议，不是已确定的性能结论。它服务于两端反复筛选、调用明细和稳定快照，避免每次操作重扫日志。先测代表性数据的扫描与查询耗时；若内存索引已达目标，可推迟磁盘增量机制。不要先造通用事件总线或后台常驻守护进程。

源文件只读；追加时暂存不完整尾行，完整后再入账；文件截断/替换按源范围重建；价格更新可重算估值但不改 token 原始量；适配器版本升级允许重新索引。扫描失败不发布半成品快照，保留上次可用快照并标过期/部分失败。

### 备选：只读 OMP stats 数据库

优点：读取便宜，已规范化且有大量指标。缺点：同步新鲜度不由本工具控制；schema 随版本变化；用途和家族关系等可能在投影中丢失；不能静默执行 OMP 命令并写别人的统计库来满足“只读”。

只有能证明该版本字段、覆盖和同步契约满足要求时才选它。数据库与 transcript 二选一计量；另一来源只能用于对账，不作额外来源叠加。

### 不采用

- 为读 OMP 引入其整个 agent 运行时、安装自动采集 hook、拦截 API 流量。
- 把所有模型名自动归一成一个计费身份。
- 保存聊天正文、做语义搜索、用 LLM 推断任务归因。
- 多机同步、团队服务、遥测、复杂插件商店。

## 6. 覆盖报告与失败状态

每个来源显示：未发现 / 已发现未接入 / 读取中 / 可用 / 部分记录失败 / 格式不支持 / 索引过期。显示最后成功扫描、最新记录时间、读取记录数、告警数和支持的调用类别。不能把空目录、无匹配查询、解析失败三者都显示“0 消耗”。

“所有 harness”应表达为产品扩展目标；实际界面必须列出当前发现和已覆盖的来源。实施前还需确认首批命名 harness 清单，不能由研究代理私自缩成仅 Codex+OMP，也不能承诺任意未记录用量的工具立即可用。

## 7. 实施验收建议

- 合成夹具覆盖 Codex 累计回落/重复/继承/分页、OMP assistant 与辅助调用、子代理、同名异 provider、缓存写、缺价、零用量与缺 usage、跨日/DST。
- 两端同一筛选、时区、价格基准、快照的总量与可见记录集合相等。
- 索引重建前后相同；追加半行、截断、文件替换后无漏重；读锁冲突显示可恢复状态。
- 未知来源不清零；单源失败不隐瞒，其他来源仍可查询。
- 默认不联网、不读凭据、不输出正文；只写自有可重建缓存。

## 8. 研究方法与验证限制

四线并行研究中的数据代理提供目录/schema 和官方入口线索；主代理进一步运行本机帮助、版本、只读 SQLite 查询、项目日志结构计数和跨日合成探针。没有测试/构建/安装竞品，没有运行新的 Web/TUI，没有把后续验收目标写成已通过结果。

外部主分支源码是本次观察截面，实施前需固定具体版本。没有对整个 OMP 安装、全部 provider 或所有历史会话做完整对账。
