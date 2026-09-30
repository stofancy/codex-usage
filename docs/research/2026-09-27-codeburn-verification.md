# CodeBurn 能否替代 codex-usage：非绘图能力实测

日期：2026-09-27。结论：**不能直接完整替代；普通日报、模型汇总、总 tokens/调用基本能力可用，Codex 家族身份、分钟过滤、档位计价、原始文件粒度和若干机器接口存在明确缺口。** 绘图全部排除，不作为优劣或阻断理由。

## 1. 实际拉取、安装与运行范围

- 源码：`https://github.com/getagentseal/codeburn.git`，浅克隆到 `/tmp/codeburn-research-20260927`。
- 固定 commit：`2a7d9588d88ac4fd938f4f13462de51735d59334`，包版本 `0.9.25`，Node `v24.18.0`。
- `npm ci --ignore-scripts --no-audit --no-fund`：退出0，250个依赖包。`npm run build:cli`：退出0。未运行安装脚本、全局安装、构建Web或运行完整测试套件。
- 实际入口：`node /tmp/codeburn-research-20260927/dist/cli.js`。
- 合成检查分别使用 `/tmp/codeburn-capabilities` 和 `/tmp/codeburn-metering`；真实窗口只读 `~/.codex`，HOME/cache改为 `/tmp/codeburn-lead-home`。
- 全部统计命令设置 `CODEBURN_PRICING_SNAPSHOT_ONLY=1`，避免在线价格漂移；源码把此变量定位为测试用途，不能当作已承诺的正式离线CLI接口。
- 没有启用 sync/share/quota/guard/optimize，没有改真实配置、源日志或OMP stats库。自定义价测试只写隔离HOME的CodeBurn配置。

并行分工：轻量终端研究、用户命令能力、计量语义；主代理完成源码构建、真实日期对账、完整会话命令核验与最终整合。

## 2. 真实窗口：tokens和调用一致，但会话粒度不同

窗口：上海时区 `2026-09-11` 全天。

```bash
# Bash；CodeBurn 输出只在本机解析，不导出私密正文
HOME=/tmp/codeburn-lead-home \
CODEBURN_CACHE_DIR=/tmp/codeburn-lead-home/cache \
CODEBURN_PRICING_SNAPSHOT_ONLY=1 \
CODEX_HOME=/home/ztmdsbt/.codex TZ=Asia/Shanghai \
node /tmp/codeburn-research-20260927/dist/cli.js report \
  --provider codex --from 2026-09-11 --to 2026-09-11 --format json

TZ=Asia/Shanghai .venv/bin/python -m codex_usage.cli \
  --since 20260911 --until 20260911 --archived --json
```

两者退出0。CodeBurn约3.17秒，codex-usage约1.85秒；单次样本不是性能排行榜。

| 指标 | codex-usage | CodeBurn | 判断 |
|---|---:|---:|---|
| 净输入 | 9,774,292 | 9,774,292 | 相等 |
| 缓存读 | 347,329,920 | 347,329,920 | 相等 |
| 输出 | 1,340,997 | 1,340,997 | 相等 |
| 总 tokens | 358,445,209 | 各分量相加358,445,209 | 相等 |
| 调用 | 2,570 | 2,570 | 相等 |
| 成本 | 210.7462（逐会话舍入后加总） | 210.74618712 | 展示舍入差 |
| 会话实体 | 13：4 user + 9 subagent | 4，`sessionCountBasis=partial` | 不等价 |

四个模型净输入/缓存/输出/调用逐一相等：

| 原始模型 | 净输入 | 缓存读 | 输出 | 调用 |
|---|---:|---:|---:|---:|
| gpt-6-astra | 2,730,727 | 118,608,512 | 420,815 | 920 |
| gpt-5.6-sol | 1,958,101 | 51,642,368 | 240,114 | 380 |
| gpt-5.6-terra | 505,796 | 17,040,384 | 106,071 | 113 |
| gpt-5.6-luna | 4,579,668 | 160,038,656 | 573,997 | 1,157 |

进一步运行 `sessions --provider codex --from 2026-09-11 --to 2026-09-11 --format json`：退出0，仍4行，不是 `report.topSessions` 截断造成。四行合计仍包含全部13实体的用量，4个ID均为原工具主会话ID。**这个样本里子代理消耗没有丢，丢的是独立子代理身份与家族查询维度。** 不能把“4 vs 13”误说成9个子代理tokens漏算，也不能用总额一致掩盖实体能力差别。

## 3. 非绘图能力逐项对照

判定“支持”要求可完成同一业务任务，不要求命令名相同；“部分”表示有替代路径但输出/语义/控制不等价。下面成功命令退出0，未知选项与非法日期反例退出1。

| codex-usage现有能力 | CodeBurn实际入口/观察 | 结论 |
|---|---|---|
| 会话明细 | `sessions --format json`及文本表；`report`只提供topSessions | 支持基本明细，实体/字段不等价 |
| 模型汇总 | `models --format table/json --min-cost 0`，两合成模型各一行 | 支持；注意默认最小成本筛选，不能遗漏低成本记录 |
| 按天汇总 | `overview`每日表；report JSON的daily；`--day`单日 | 支持 |
| 天×模型直接报表 | report/export里的daily和models分别聚合；contributions可用于自行处理 | 部分，不是直接交叉表 |
| 同会话多模型 | 合成两轮切换模型，分别入模型汇总 | 支持 |
| 文件分页合并 | 两文件同会话，合并calls/tokens | 支持 |
| `--raw`逐文件实体 | sessions拒绝`--raw`，无等价文件明细命令 | 不支持 |
| `--family`家族树 | 拒绝`--family`；work-unit不是Codex家族等价实现 | 不支持 |
| 父会话＋子代理、昵称/角色、parent关系 | 真实与合成均不能保留原有Codex家族维度 | 不支持完整能力 |
| `--type`角色过滤 | task分类不等于user/subagent角色；没有同等通用过滤 | 不支持等价能力 |
| `--parent`父线程过滤 | 无等价父线程报表过滤 | 不支持 |
| `--session`前缀及分页UUID匹配 | sessions拒绝`--session`；context有会话入口但不等价用量过滤 | 不支持等价能力 |
| `--model`模型子串过滤 | models拒绝`--model`；compare有model-a/b但只服务比较 | 部分，无通用子串过滤 |
| 日期范围 | `--from/--to YYYY-MM-DD`与timezone、day | 支持日粒度 |
| 分钟/秒窗口 | ISO时间和带空格时间参数均报expected YYYY-MM-DD | 不支持 |
| 紧凑日期格式 | `20260926`等报expected YYYY-MM-DD | 不支持；可外部转换但不是原生能力 |
| 是否纳入归档 | 默认扫描archived_sessions并去重；拒绝`--archived` | 部分，缺显式含/不含开关 |
| JSON输出 | report/models/sessions成功解析 | 支持机器输出，不兼容原JSON契约 |
| JSON的reasoning/tiers/metering/parent等细节 | 普通报表未输出等价字段 | 不支持完整契约 |
| 自描述`--schema` | unknown option；export的schema只是版本标签 | 不支持 |
| 数据源自检 | `doctor --json --provider codex`给路径、发现数、解析健康 | 支持该业务用途；不要求匹配原字段 |
| 自定义价格 | `price-override`实测仅改变目标模型价格 | 支持自己的配置格式，不直接兼容cc-switch价格文件 |
| 手动`--update-pricing`/选择价格源 | 没有等价显式刷新命令；默认LiteLLM定时cache/fallback | 不支持相同控制方式 |
| 默认统计离线 | 默认cache过期可能联网；本次用测试变量强制内置快照 | 与原工具不等价 |
| 调用数 | 总览、模型和会话均有calls | 支持 |
| 缓存命中率 | overview/report有；合成40%与真实97.3% | 支持总览，逐行列不完全等价 |
| 单次成本 | compare JSON包含Cost / call | 部分，非所有原有聚合行都直接显示 |
| 每百万tokens混合有效单价 | report/models/sessions/compare未直接输出；只能自行相除 | 不支持直接列/字段 |
| priority/Fast分档费用 | 合成三档都按standard输出 | 不支持该计价语义 |
| 字符终端一次性输出 | overview/models/sessions（加no-pager）实际运行退出 | 支持轻量使用方式；默认report仍交互 |
| 帮助/版本 | `--help`、子命令help、`--version`可用 | 基本支持；原工具单横线纠正、`/?`等便捷别名未作完整测试 |

`--ascii`、所有chart/metric绘图路径、图片依赖与图形协议检测均排除。机器接口既有字段不能因为可以通过自编脚本重算便判为原生完整支持。

## 4. 合成计量测试：支持的边界与反例

### 已通过样例

- 基本输入：毛1000、缓存600、净400、输出100、推理20；两端token/call一致，推理属于输出子集不重复相加。CodeBurn普通JSON未显示逐模型reasoning明细。
- 模型切换：同会话分别归入gpt-5.2和gpt-5.1。
- 重复累计100→100→200：两端计2 calls，不计重复帧。
- 继承首帧累计大值、last=0：只计后续新增量。
- 累计重置1000→100：两端计两轮，并非负数相减。
- 跨日：同文件两天事件，CodeBurn日桶正确分开；它在此行为优于当前codex-usage按会话首日分桶。
- 同会话分页：两文件合并；active/archived同basename副本不重复。

以上不代表算法完全相同。CodeBurn偏向last并用累计识别重复；本项目以累计差分及last封顶。中途正跳升、缺累计但last相同等组合未完整测遍。

### 反例A：父子累计碰撞误去重

合成父会话模型gpt-5.2、子代理模型gpt-5.1；两次独立调用都记录毛200/缓存100/输出20，子调用晚6秒，last均为实际本次用量，子代理有parent_thread_id与双UUID文件名。

- codex-usage：父与子两实体，共2 calls。
- CodeBurn：子调用被跨fork累计键判重，少1 call、净输入100、缓存100、输出20。
- 改为子调用毛250/缓存100/输出30后：总量两端一致，但CodeBurn仍合入父会话，sessions=1，subagents=[]。

证据：[固定版本codex parser](https://github.com/getagentseal/codeburn/blob/2a7d9588d88ac4fd938f4f13462de51735d59334/src/providers/codex.ts#L1245-L1276)，去重键以fork身份及累计分量构成，未区分这两次不同模型调用。本轮为人工合成反例，不能声称已证明真实历史发生同种损失。

另一种父子元数据夹具使用独立session ID时，`sessions --by-work-unit`把子线程作为独立root而非父的child。两种结果不同但结论一致：其work-unit不能替代本工具Codex父子家族语义。

### 反例B：服务档位费用

同模型三轮default/priority/fast，每轮毛200/缓存100/输出20：两端均3 calls、净300/缓存300/输出60。

CodeBurn为 `$0.0014175`，三轮标准价；codex-usage为 `$0.0024`（四位舍入）且保留三档。固定版本parser在 [L1291-L1317](https://github.com/getagentseal/codeburn/blob/2a7d9588d88ac4fd938f4f13462de51735d59334/src/providers/codex.ts#L1291-L1317) 指定 `speed: 'standard'`，未按该 `thread_settings_applied` 档位定价。**费用差不是tokens差。** 本次用内置表；不以该单例推导所有历史模型费率差。

### 新能力：OMP

合成assistant message usage：CodeBurn实际返回2 calls、净输入65、cacheRead35、cacheWrite5、output14，证明OMP基本接入可用。

追加独立顶层 `model_usage`（input100/cache50/output30）后重跑，总量不变，该记录未被计入。主代理前轮已只读确认真实OMP存在这种记录类型；[pi.ts](https://github.com/getagentseal/codeburn/blob/2a7d9588d88ac4fd938f4f13462de51735d59334/src/providers/pi.ts#L252) 非message跳过与运行结果一致。本轮未做全体真实OMP用途逐条对账，不承诺其他来源都已验证。

## 5. 轻量终端实际体验

### 已运行

- 真实固定日 `overview --no-color`：退出0，93行，无ANSI、无alternate-screen。输出成本、tokens、calls、命中率及多块表；总览偏长，但不是必须进入交互应用。
- 真正PTY `TIOCSWINSZ(24,80)` 下运行合成数据 `sessions ... --no-pager`：退出0；该样本每行≤80字符，自动收缩为Started/Session/Project/Models/Cost。
- `models ... --format table --min-cost 0`、JSON、Markdown入口已有相应命令；本轮主要实跑table/JSON。

### 限制

80列CodeBurn样例主要ASCII，字符长度不等于所有CJK显示宽度保证；中文/40列的验证来自独立Rich原型，不能嫁接成CodeBurn的测试通过。未运行默认dashboard完整按键流程，因为用户已转向轻量终端，且本轮关注现有非绘图能力替代。

CodeBurn包仍依赖React/Ink等。采用它的静态入口能满足轻量交互方式，但不等于安装依赖也与小型Python报表相同。

## 6. 自定义价格和离线边界

隔离HOME执行 `price-override gpt-5.2-codex --input 100 --output 100 --cache-read 100`，退出0；仅沙箱config写入。目标模型费用从0.00392变为0.12，另一模型不变，证明覆写有效。

[loadPricing](https://github.com/getagentseal/codeburn/blob/2a7d9588d88ac4fd938f4f13462de51735d59334/src/models.ts#L308-L328) 先读有效cache，缺失/过期时通常联网LiteLLM，失败用内置快照。测试变量阻止该价格请求，但它不是公开CLI的 `--offline` 契约。没有网络抓包，不把“价格快照模式”扩大成整套产品绝无任何网络路径的保证。

## 7. 能否采用：现在可以给出的判断

### 能直接解决

跨多个harness的普通日报/模型汇总、基础tokens与calls、JSON、来源自检、自定义价格、一次性终端概览。真实日窗口核心数字一致说明它不是只能看截图的候选。

### 替代现有能力前必须解决

1. **Codex计量与归属：** 独立子代理实体/家族、父子过滤，以及累计碰撞误去重反例。
2. **计价：** priority/Fast档位、默认离线和显式更新控制。
3. **查询：** 分钟级窗口、通用model/session/type/parent过滤、天×模型、raw和归档开关。
4. **接口与指标：** schema、自有JSON诊断/tiers/reasoning、逐行单位费用等。
5. **新目标覆盖：** OMP辅助调用不能只统计assistant message。

**推荐：保留为扩展候选，不作为无需改造的直接替换。** 补差并非只加一个OMP适配器；会触及Codex身份/去重、定价、查询与输出契约。是否值得fork取决于愿意放弃哪些旧功能；用户尚未授权放弃，因此本轮按完整非绘图范围判为“不满足直接替代”。

这也不自动证明自建更省。下一步应拿这份具体缺口比较“扩展CodeBurn”与“保留本项目数据能力、做轻量终端＋本地网页”，不再泛泛比较框架或截图。

## 8. 验证限制与产物

未进行：全量历史审计、所有harness验证、完整Web运行、在线价格更新、CJK全终端矩阵、性能基准、完整安全审查。没有编写或修改产品测试，也没有实施修复。

临时证据：`/tmp/codeburn-capabilities/` 的命令输出与PTY结果；`/tmp/codeburn-metering/` 的合成生成脚本、report/export结果；源码克隆保留便于复查。研究报告只保存结构和统计数值，不提交真实日志/正文。临时Rich探针和第三方源码不是项目产品交付，不纳入源码目录。

## 9. 后续补测：本机真实七种harness与正式安装

用户进一步要求验证多来源并安装供手动试用。本轮重点由“是否完整替代Codex专项能力”转向“本机多来源能否真正读取”，两者不应混为一谈。

### 安装与入口

- npm registry当前版本0.9.25，与之前源码版本一致。
- `npm install -g codeburn@0.9.25 --ignore-scripts --no-audit --no-fund` 成功，新增163个包；安装在用户自己的nvm前缀，无sudo。
- 可执行文件 `/home/ztmdsbt/.nvm/versions/node/v24.18.0/bin/codeburn`，普通shell及 `fish -ic 'command -v codeburn; codeburn --version'` 均成功返回0.9.25。切换nvm Node版本后可能需重新安装。
- `codeburn web --no-open --period today --port 4747` 实际启动，HTTP首页返回CodeBurn HTML；验证后停止，不留后台服务。此为启动/资源烟测，不是完整浏览器交互验收。

### 真实来源结果

使用真实HOME自动发现来源，统计缓存指定临时目录 `/tmp/codeburn-live-verification-cache`，价格仍用 `CODEBURN_PRICING_SNAPSHOT_ONLY=1` 测试变量；没有启用上传或辅助改配置功能。

`doctor --json` 检测41种provider定义，其中7种发现本机数据；每种抽样最多8条，所有抽样解析成功。这里的发现文件/候选数不是最终会话数，不据此声称每条数据均解析正确。

正式安装版执行 `codeburn report --period lifetime --format json`：退出0，首次约19.19秒，汇总162,536 calls、21,973,155,358 tokens。随后分别指定 `--provider` 执行同一命令，全部退出0：

| 本机来源 | calls | tokens（四分量相加） | 报告费用USD | 缺价模型数 |
|---|---:|---:|---:|---:|
| Claude Code | 1,785 | 286,362,259 | 194.2151 | 0 |
| Codex | 111,603 | 14,387,573,152 | 10,800.3834 | 2 |
| DeepSeek Harness | 6,358 | 1,063,424,023 | 9.5874 | 2 |
| Grok Build | 75 | 146,433,902 | 75.4413 | 0 |
| OMP | 19,142 | 2,824,731,778 | 2,318.5937 | 0 |
| OpenCode | 2,250 | 425,579,537 | 0 | 4 |
| ZCode | 21,324 | 2,839,310,459 | 646.2703 | 5 |

重要边界：

1. **七种本机真实来源都能统计，不只是支持名单或合成OMP测试。** 上述calls是各parser报告的计量条目，不能统一解释为真实网络请求次数。
2. 费用是CodeBurn报告值，不是账单；有缺价。尤其OpenCode用量非零但费用0，不能解读成免费。
3. DSH明确警告部分attempt没有usage，统计可能不完整；不把成功退出等同完整覆盖。
4. 所有来源的sessionCountBasis均为partial；OMP顶层model_usage缺口仍然存在，本次不再逐条复算。
5. 全来源与逐来源是先后运行、源日志仍在追加，并非冻结快照。逐来源相加多1 call、259,752 tokens；可能来自期间新增记录，未定位差值，不宣称两次完全对账通过。
6. 本轮证明实际发现、解析、聚合与输出可用，没有证明每个来源的计量口径、费用或所有历史记录都准确。Codex上一轮固定窗口对账与合成缺陷结论仍独立有效。

手动体验（fish/Bash通用）：

```sh
codeburn overview --period lifetime --no-color
codeburn report --provider omp --period lifetime --format json
codeburn doctor
codeburn web --period lifetime
```

不带子命令的 `codeburn` 是交互终端仪表盘；偏好轻量输出时先用overview。普通运行未设置本轮测试变量，会按默认策略更新价格，可能访问在线价格源；这不同于上传聊天记录，本轮未作全面网络审计。
