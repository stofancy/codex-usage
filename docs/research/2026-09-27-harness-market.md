# 跨 harness 用量工具竞品研究

日期：2026-09-27。本文是第一轮文档/源码研究截面，旧 `docs/competitors.md` 仅作线索。后续已拉取构建并实跑CodeBurn，优先阅读[非绘图能力实测](2026-09-27-codeburn-verification.md)。用户已否决全屏Textual方向，终端选择见[轻量终端研究](2026-09-27-lightweight-terminal.md)；下文旧“同等完整TUI”标准不再作为新方案要求。

## 1. 结论

**市场上已有“多 harness + TUI + 本地网页”的产品，OMP 支持也不是空白。** CodeBurn 是本需求最接近的整体候选；Tokscale 是重要的 TUI/多来源参考；agentsview 是本地 Web 分析与会话浏览参考；OMP 自带 stats 网页是最相关的单源参考。

不建议现在以“还没人做”为理由扩写本项目，也不建议看见支持 OMP 就直接替换。选择依据应是：能否统计本机真正产生的调用、两端能否完成核心操作、未知值是否诚实、默认网络与数据边界是否符合单机本地需求。

## 2. 核心对照

| 工具 | OMP 支持证据 | 本地浏览器 UI | 交互式 TUI | 数据/隐私边界 | 本轮判断 |
|---|---|---|---|---|---|
| [CodeBurn](https://github.com/getagentseal/codeburn) | 独立 OMP provider 文档和源码 export，目录与 Pi 分开 | 官方 `codeburn web`，同类 breakdown 与图表 | 默认命令有交互 dashboard | 本地读文件；价格每日刷新；另有可选 quota/guard/optimize/设备汇总等能力，不应顺便启用 | **整体最匹配，优先验证采用或补差** |
| [Tokscale](https://github.com/junhoyeo/tokscale) | README 将 OMP/Pi 分列，源码有独立 client 注册 | 有 Web 可视化，但本轮未证实与本地 TUI 同等完整的私有分析入口 | Ratatui，多页、筛选、排序、会话/项目等 | 部分来源需 API 同步；价格自动获取；公开 submit/排行榜是独立路径 | **TUI 与来源广度的强参考** |
| [agentsview](https://github.com/kenn-io/agentsview) | README 明列 OhMyPi 数据目录 | 本地 server、SQLite、会话/用量分析 | 未确认与 Web 等价的完整 TUI | local-first，但会索引会话内容；有可选远程/S3/语义能力 | **Web 强，单独不满足双入口目标** |
| [OMP stats](https://github.com/can1357/oh-my-pi/tree/main/packages/stats) | 官方 OMP 自身数据 | `omp stats`，React/Chart.js、本地 SQLite | summary 是非交互报表，不是同等 TUI | 仅 OMP sessions；API 等价估算；同步会写统计库 | **最相关单源参考，不能代替跨 harness 产品** |
| [ccusage](https://github.com/ccusage/ccusage) | 本轮支持清单有 Pi，但没有确认 OMP 独立适配 | 未确认第一方本地图形 UI | 主要是 CLI 报表，不把静态表格算 TUI | 本地读取、JSON 与定价选项；需按版本检查联网策略 | **可作对账参考，不是完整双端方案** |
| [Splitrail](https://github.com/Piebald-AI/splitrail) | 有 Pi，未确认 OMP 独立支持 | 主要参考是 VS Code/Cloud；本地网页未确认 | CLI/TUI 有文档展示 | 可上传 Cloud，配置默认 auto_upload=false；本轮未核实完整离线价格路径 | 用户已选单机本地，优先级低 |
| [Anthropometer](https://github.com/arian-shamaei/anthropometer) | 本轮确认 Claude/Codex/Gemini，未确认 OMP | 主要为 PDF 报告，不是目标网页 | 上下文调试 TUI，子代理下钻 | 本地 transcript、API 标价；不是跨所有来源总账 | **追溯与子代理交互参考** |
| [omp-token-usage](https://github.com/Corundum-Ling/omp-token-usage) | 专用 OMP 扩展 | 未确认 | OMP 内全屏面板，不是独立多源入口 | 从 OMP stats 库读、估算金额；第三方插件 | 只想看 OMP 时可考虑，不作跨源底座 |

“未确认”不是不存在。支持列表数量会变化，本报告不拿星数或目录数量代替可靠性评估。

## 3. 两个高匹配候选的深入核查

### 3.1 CodeBurn

- [浏览器文档](https://github.com/getagentseal/codeburn/blob/main/docs/web.md) 明示：本地端口、`--no-open`、与 TUI 同类 task/model/tool/project breakdown；趋势按时间窗口选 15 分钟/小时/天桶，可按 session/model 拆线。
- [OMP provider](https://github.com/getagentseal/codeburn/blob/main/docs/providers/omp.md) 与 [Pi provider](https://github.com/getagentseal/codeburn/blob/main/docs/providers/pi.md) 是独立来源，共用解析器；不是把 Pi 支持误称 OMP。
- [实际解析器](https://github.com/getagentseal/codeburn/blob/main/src/providers/pi.ts) 读取 session header/model_change/message；OMP 会扫描主记录及一层子代理目录。模型身份来自消息和会话状态。
- **源码级缺口：** `if (entry.type !== 'message') continue` 排除了 OMP 独立 `model_usage` 辅助调用。当前项目已观察到这种记录，因此采用门槛必须包括辅助调用。尚未运行整个 CodeBurn 验证是否存在其他补偿路径，不把源码路径结论夸大为完整运行结果。
- 同一源码以 `input === 0 && output === 0` 跳过记录，缓存专属/零输出记录需要夹具核验；未知模型回退和有限层级目录发现也需要检查。
- [Codex provider 说明](https://github.com/getagentseal/codeburn/blob/main/docs/providers/codex.md) 有累计值/重复事件处理，也描述缺 usage 时的文本估算；必须区分权威 usage 与估计值，不把统计总额都当精确调用账本。
- 许可 MIT；本次包元数据 `0.9.25`、Node ≥22.13。版本仅记录本轮截面，未做供应链/完整安全审计。

**结论：** 不可直接宣称满足“所有 LLM 调用”；但这不自动意味着要重写整个产品。先估算补齐计量与两端交互差距的范围。

### 3.2 Tokscale

- [README](https://github.com/junhoyeo/tokscale) 明列 `.omp/agent/sessions/**/*.jsonl` 与 `.pi/agent/sessions/`；[clients.rs](https://github.com/junhoyeo/tokscale/blob/main/crates/tokscale-core/src/clients.rs) 注册独立 OMP client。
- 官方当前 README 列 Overview、Usage、Models、Daily、Hourly、Monthly、Sessions、Projects、Stats、Agents 等交互视图；旧报告里的四视图不是现状完整能力。
- README 区分本地读取、API cache、headless capture、估算来源；这说明“支持几十种工具”并不等于每一种都拥有同粒度、同可靠性的真实调用记录。
- 主代理查看了官方 TUI 截图：有时间趋势、模型列表、选中行、滚动提示和底部按键帮助。但截图本身标有较旧版本，不能证明当前小屏/CJK/resize 兼容。
- Web 贡献图、排行榜与 `submit` 包含上传路径；本地使用不能默认进入这些功能。README 还说明定价自动请求与缓存，故不能笼统称默认全程离线。
- 本轮 workspace 元数据 `4.17.0`、MIT。没有运行其 parser 做本机对账，也未核实 OMP 辅助调用的全部语义。

**结论：** 如果仅求强 TUI，它是优先候选；用户已要求本地 Web 与 TUI 同等，需核验网页深度，不能因为有前端仓库就算过关。

## 4. OMP 官方看板的复用边界

OMP stats 的数据模型、调用追溯、增量索引和“API 等价估算”措辞值得参考。本机 `omp stats --help` 已运行成功，确有 dashboard server 参数。

不能直接把它嵌入本项目充当 Web：其核心围绕 OMP 会话，Python/TUI 与 Bun/Web 若各自计算，会形成两套口径。也不必断言不能扩展上游——若将整个产品迁往该底座，技术上仍是一个候选，只是要迁移现有 Codex 语义、扩多来源、再建设等价 TUI，当前没有证据证明总成本更低。

[官方 README](https://github.com/can1357/oh-my-pi/tree/main/packages/stats) 与 [parser](https://github.com/can1357/oh-my-pi/blob/main/packages/stats/src/parser.ts) 为主要证据。数据新鲜度与本机版本差异见[数据研究](2026-09-27-harness-data.md)。

## 5. 采用、扩展、自建三条路

| 路线 | 当下收益 | 持续成本/风险 | 进入条件 | 否决条件 |
|---|---|---|---|---|
| 直接采用 CodeBurn | 最快获得现成双入口、多来源 | 数字口径与审美不一定满足，功能面超过需求 | Codex/OMP 用量可对账，两端核心路径和窄屏通过，默认网络边界可控 | 辅助调用或子代理漏计且无法解释；必须上传；未知金额冒充真实成本 |
| 扩展 CodeBurn 等现成工具 | 复用解析器生态和双端，集中补缺 | 上游协作或维护 fork；需要理解其 TS 核心 | 缺口有限、补丁可独立维护；不需要全面替换两套 UI | 修改范围最终等于重写计量与两端；用户不接受现有交互 |
| 改造本项目 | 可控制计量、数据边界和界面设计；复用部分 Codex 知识 | 长期维护各 harness 格式、Web/TUI、价格与发布 | 两端/可信度确有现成产品难以补足的需求，且接受维护责任 | 只是因为已有仓库而重造；拿“支持 OMP”或“终端真图”当差异化 |

### 主代理裁决

竞品研究代理倾向继续改本项目，理由是现有 Codex 计量可审计。主代理**不将其直接升级为已定路线**：已运行的跨日探针证明旧核心也需要改造；同时竞品已经覆盖大量来源和双入口。沉没成本不是自建理由。

当前建议顺序：**现成候选的有界验证 → 判断可否小补差 → 再决定是否完整改造本项目**。与此同时，本轮已完成本项目改造的可行设计，便于对比维护边界，不是让用户盲选。

单个 `model_usage` 分支缺口只证明不能原样接受，不能单凭它证明自建比修复更便宜。

## 6. 采用验证清单

使用脱敏/合成 fixture 或只读本地数据；禁止上传和启用 guard/optimize 配置写入。

1. Codex 同一窗口的 tokens、缓存、服务档位、分页、归档副本、父子历史无重复，跨日桶正确。
2. OMP 主消息、子代理、advisor、辅助 `model_usage`；purpose 保留；每种来源能力明确。
3. 估算成本、来源报告金额、未知价格的含义正确；不同 provider 同名模型不误价。
4. TUI 在 80×24 和 resize 后可筛选、排序、详情、返回；无图片协议；中文和退出恢复正常。
5. 本地 Web 的同一查询结果与 TUI 一致；基本功能不依赖公网、账号或上传。
6. 来源失败和索引过期可见，不以“0”掩盖；没有实际 usage 的来源不能伪装精确统计。
7. 判断需要修改的是有限 adapter/交互缺口，还是计量模型和两端的大规模重写。

上述为下一决策门的验收条件，不是本轮已通过的测试，也没有假称已亲测 CodeBurn/Tokscale。

## 7. 外部研究的边界

- 不以星数/最近推送当质量保证；选用前固定版本、核许可与安装依赖。
- “本地优先”不保证没有价格更新、配额 API 或可选云上传；需逐功能看边界。
- Langfuse 等 SDK/代理型可观测平台可以参考追溯信息架构，但它们不直接解决无侵入读取已有 harness 历史日志，因此不选作本需求底座。
- 本轮没有完整安全审查或网络抓包，不给竞品作安全背书。
