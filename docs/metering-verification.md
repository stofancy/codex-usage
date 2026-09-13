# T6 计量口径独立验证报告

- 验证人：verify-dev（独立验证者，不写实现）
- 验证对象：task-6（计量口径改为「累计值增量」）+ task-7/task-9（定价回退/档位/别名）中与计量相关的部分
- 快照时间：2026-09-13 21:52 +0800（机器在跑，`~/.codex/sessions` 会持续追加；下文所有分窗数字均用**定窗**避免漂移）
- 环境指纹：HEAD `a3c9e18`；`src/codex_usage/parser.py` md5 `806bdf592ab8b55745b31bd070814ee7`；`stats.py` md5 `b6d4789e7a672609f5a105fc0a324ca6`；`pricing.py` md5 `0fe7abdcdfbd2dfb9328a81db454a3c7`；`data/tier_pricing.json` md5 `44d09459ead2f940c20cc6ad0711fb4e`；ccusage `20.0.20`
- 复算工具（本报告所有数字的来源，见文末命令汇总）：`tests/test_metering_regression.py`（独立实现的 oracle + `--recompute/--ledger/--cost` 三个对账入口，不复用 `codex_usage` 的解析代码，只读实现用于对账）

## 0. 结论摘要（实测）

1. **逐文件复算 0 误差**：定窗 `--since 20260911 --until 20260912` 119 个文件、118 个有用量（1 个无任何 token_count 用量），与 `codex-usage --json --raw` 逐模型（毛输入/缓存读/输出/推理/调用数）**完全一致，0 处不一致**；全窗 `--since 20260911 --until 20260913` 128 个文件、127 个一致、0 处不一致。
2. **与 ccusage 的 token 差异 100% 查到根因**：逐 (天,模型) 台账在把「跨日目录文件」补回后**逐项完全一致，总差 0**（两边都是 1,830,205,933，定窗）。
   - 未解释项 `gpt-5.6-sol` 少 **24,632,119** = `sessions/2026/09/08/` 里一个 09-08 开始、09-12 仍在写轮次的长会话在窗口内的用量。
   - 另一项 `gpt-6-astra` 少 **38,148,793** 是同源问题（`sessions/2026/09/09/` 35,828,470 + `sessions/2026/09/10/` 2,320,323）。
   - 根因是 **我们的 `collect()` 只扫 `[since, until]` 的日期目录**，不打开更早日期目录里仍在写入的文件；ccusage 的文件筛选包含「路径日期早于窗口但 mtime 晚于窗口起点」的文件。
3. **推翻「astra 差 ≈ 继承快照」这一归因**：astra 的 38,148,793 与继承量 38,126,772 数值接近纯属巧合（两者相差 22,021，且分属不同模型/不同文件）。真实继承首帧只有 6 个文件、合计 38,126,772、全部落在 `codex-auto-review` 首帧且 `last=0`；T6 的首帧规则与 ccusage 都正确排除了它，它**不构成**与 ccusage 的任何差异。
4. **成本对账（task-9 后）**：定窗我们（补齐跨日文件、档位感知）**$1,116.0424**，ccusage **$1,064.6425**，差 **+$51.3999**，全部等于 `gpt-6-astra` 的 Fast/priority 档加成——即 **ccusage 少算了 astra 的 Fast 档**，我们是对的；`ccusage − 我们标准价 = +$3.1896` 恰好等于 luna + `codex-auto-review` 的档位加成（research-dev 的推断在整窗级别被独立证实）。
5. **当前唯一让我们的数字偏低的实现缺口**：跨日目录文件漏扫（定窗 token −62,780,912、成本 −$66.7472）。除此之外，未发现其它低估：`tiers` 合计 == `models` 合计在 126 个会话上 **0 破例**；cache_read 价缺失/为 0 时回退 input 价（不是 0）；priority 档按 2.0× Fast 价计；`gpt-reserve` 两边都按 $0 且我们标 `*`。
6. **两份文件交付**：`tests/test_metering_regression.py`（19 passed + 1 xfailed，xfail 即第 5 节的已知缺口）、本报告。

---

## 1. 方法：独立复算怎么保证「独立」

- 复算脚本（`tests/test_metering_regression.py` 的 `oracle()` 与 `_event_metering()`）**自己实现** T6 约定：累计差分、首帧取 last、跳升以 last 封顶、回落/缺 total 回退 last、窗口按事件时间戳过滤。它**不 import** `codex_usage.parser` 的解析函数（仅在对账时调用 CLI 子进程/读其 JSON）。
- 与实现的对账走 `codex-usage --json --raw`（每文件一行）与 `--json`（每会话一行，含 tiers/metering 诊断）。
- 与 ccusage 的对账走 `npx ccusage@latest codex daily --json`；npm 缓存固定到仓库内 `.scratch/npm`（不写家目录）。
- 定窗说明：所有台账数字都用 `--since 20260911 --until 20260912`（两个完整过去的日期）。机器在持续写 09-13 的数据，不定窗的数字会分钟后漂移；正文中「实时窗口」的数字都单独标注了采样时刻。
- 时区：本机 `+0800`；两边都按本地日期分桶，事件时间戳在 rollout 里是 UTC。

---

## 2. 第 1 项：手工复算抽查（≥5 文件，含 ≥2 子代理、≥1 分页）

### 2.1 一条命令

```bash
cd /home/ztmdsbt/workspaces/codex-usage
.venv/bin/python tests/test_metering_regression.py --recompute --verbose --since 20260911 --until 20260912
```

输出末尾（实测）：

```
窗口 20260911 ~ 20260912：文件 119 个，逐文件完全一致 118 个，无用量 1 个，不一致 0 个
```

全窗（含 09-13）：

```bash
.venv/bin/python tests/test_metering_regression.py --recompute --since 20260911 --until 20260913
# 窗口 20260911 ~ 20260913：文件 128 个，逐文件完全一致 127 个，无用量 1 个，不一致 0 个
```

（`--raw` 每文件一行共 127 行；不加 `--raw` 是 126 个会话——相差 1 正是分页合并的那一对文件，见 2.3。）

### 2.2 抽查样本（独立复算值；`--verbose` 会逐文件打印这些行）

| # | 文件（`~/.codex/sessions/` 下） | 类型 | 模型 | 毛输入 | 缓存读 | 输出 | 调用 | 旧口径 delta_sum |
|---|---|---|---|---|---|---|---|---|
| 1 | `2026/09/11/rollout-2026-09-11T01-50-02-01a08c70-dfa2-7b73-b709-393c95342ae5.jsonl` | **subagent**（Kepler(sol_analyst)，父 `01a08c1a…`） | gpt-5.6-sol | 11,776,215 | 11,360,128 | 41,135 | 81 | 12,397,095 |
| 2 | `2026/09/12/rollout-2026-09-12T12-33-55-01a093e4-b916-7f53-a84c-2cad7751f0d7.jsonl` | **subagent**（Euler(sol_analyst)，父 `01a093e4-47d3…`） | gpt-5.6-sol | 1,414,928 | 1,057,408 | 12,729 | 15 | 1,499,985 |
| 3 | `2026/09/12/rollout-2026-09-12T13-18-37-01a0940d-a705-7dc1-acf9-0268e7659ea7.jsonl` | user（**分页第 1 页**） | gpt-6-astra | 11,615,168 | 11,267,072 | 39,616 | 94 | 11,740,931 |
| 4 | `2026/09/12/rollout-2026-09-12T13-54-05-01a0940d-…_01a0942e-1faa-7a60-a657-5867007f4df7.jsonl` | user（**分页第 2 页**，双 UUID） | gpt-6-astra | 4,810,982 | 4,780,416 | 6,551 | 49 | 4,817,533 |
| 5 | `2026/09/12/rollout-2026-09-12T12-53-30-01a093f6-a594-74e2-8515-a39e385a159c.jsonl` | guardian（**继承首帧**：首帧 total=14,051,760 / last=0） | codex-auto-review | 233,857 | 182,784 | 1,181 | 6 | 235,038 |
| 6 | `2026/09/11/rollout-2026-09-11T02-22-15-01a08c8e-5ea5-78d2-bd55-2a4e2beb678f.jsonl` | user | gpt-5.6-luna | 6,770,584 | 6,568,448 | 33,831 | 55 | 6,951,166 |

样本 1/2 覆盖 ≥2 个子代理；样本 3+4 覆盖 ≥1 个分页会话；样本 5 覆盖继承首帧；每个文件的模型五元组与 CLI `--json --raw` 逐字段相等。

### 2.3 分页合并（用 CLI 非 raw 行复核）

```bash
.venv/bin/python -m codex_usage.cli --since 20260912 --until 20260912 --json --session 01a0940d
```

实测该会话（两个分页文件合并后）：`total_tokens=16,472,317`、`cost_usd_known=22.1425`，
`models.gpt-6-astra = {input_gross: 16,426,150, cached: 16,047,488, output: 46,167, reasoning: 10,390, calls: 143}`，
`tiers.gpt-6-astra = {unknown: 4,819,202g/35 calls, default: 11,606,948g/108 calls}`，
`metering.delta_sum = 16,558,464`。

- 校验：`4,819,202 + 11,606,948 = 16,426,150`（tiers 合计 == models）；`35 + 108 = 143`；`delta_sum = 11,740,931 + 4,817,533`（两页相加）。
- 这条同时确认了 HEAD `a3c9e18` 修的「分页合并漏合并 tiers」：修前 `tiers` 只有第 1 页（少 4,810,982 毛输入），修后吻合。
- 全窗不变式检查（126 会话）与定窗（117 会话）：`tiers` 各档合计 != `models` 的条目 **0 个**。

---

## 3. 第 2 项：边界用例固化为 `tests/test_metering_regression.py`

```bash
.venv/bin/python -m pytest tests/test_metering_regression.py -q
# 19 passed, 1 xfailed
```

设计：每个用例用合成 rollout 夹具（`session_meta`/`turn_context`/`thread_settings_applied`/`token_count` 四类行）调用 `parse_rollout`，同时用文件内**独立 oracle** 复算同一行序列，断言两者逐字段一致（不是把期望值硬编码一遍，而是让两套实现互证）。

| 用例 | 钉住的行为 |
|---|---|
| `test_duplicate_cumulative_event_counted_once` | 完全重复帧只计一次；`delta_sum` 仍按旧语义把重复帧的 last 累加（2530，这正是被修掉的虚高来源） |
| `test_duplicate_with_stale_nonzero_last_still_counted_once` | 重复帧带着陈旧非零 last 时增量仍为 0 |
| `test_inherited_first_snapshot_not_counted` | 首帧 total=14M / last=0 不计入 |
| `test_middle_jump_capped_by_last` | 中间累计跳升远超 last 时以 last 封顶 |
| `test_zero_component_in_last_falls_back_to_increment` | last 某分量为 0 时该分量取累计增量，不少算 |
| `test_cumulative_drop_falls_back_to_last` | 累计回落 → 用 last，`resets=1` |
| `test_missing_total_falls_back_to_last` | 缺 total → 逐轮回退 last，`fallbacks=2` |
| `test_total_and_last_both_missing_is_dropped` | 两者都缺的事件不产生用量，整文件返回 None |
| `test_window_skips_out_of_window_events` | 窗口按事件时间戳裁；窗口内首帧仍按「首帧=自己的 last」，不把窗口外历史再算一遍 |
| `test_tier_split_and_switch` | `unknown → priority → default` 分段；各档合计 == 模型合计 |
| `test_multi_model_same_session` | 同会话切模型按当时 turn_context 归因，`primary_model`/`multi_model` 正确 |
| `test_usage_before_turn_context_attributed_to_unknown` | turn_context 之前的用量归 `unknown`（理论路径，实测真实数据 0 条） |
| `test_paginated_pages_merge_token_totals` / `test_paginated_pages_merge_tiers_and_delta_sum` | 分页文件合并 token、tiers、delta_sum |
| `test_archived_duplicate_not_double_counted` | sessions/ 与 archived_sessions/ 同 UUID 只算一次 |
| `test_cache_read_price_fallback_uses_input_price` 等 4 个 | 定价反例（见第 5 节） |
| `test_cross_day_dir_file_with_in_window_event_is_scanned`（**xfail**） | 已知缺口：早日期目录文件含窗口内事件时被漏扫（第 6.1 节） |

---

## 4. 第 3 项：与 ccusage 对账

### 4.1 token 台账（定窗 `--since 20260911 --until 20260912`）

```bash
.venv/bin/python tests/test_metering_regression.py --ledger --ccusage --since 20260911 --until 20260912
```

实测（`(净输入, 缓存读, 输出)`）：

| 日期 | 模型 | 我们（目录内） | 跨日目录文件补充 | ccusage | 判定 |
|---|---|---|---|---|---|
| 09-11 | gpt-5.6-luna | (4,579,668, 160,038,656, 573,997) | — | 同左 | 逐项一致 |
| 09-11 | gpt-5.6-sol | (1,958,101, 51,642,368, 240,114) | — | 同左 | 逐项一致 |
| 09-11 | gpt-5.6-terra | (505,796, 17,040,384, 106,071) | — | 同左 | 逐项一致 |
| 09-11 | gpt-6-astra | (1,858,971, 81,452,032, 300,258) | (871,756, 37,156,480, 120,557) | (2,730,727, 118,608,512, 420,815) | 逐项一致（跨日补 38,148,793） |
| 09-12 | codex-auto-review | (3,595,007, 16,871,680, 42,344) | — | 同左（ccusage 记为 `gpt-5.5`） | 逐项一致 |
| 09-12 | gpt-5.6-luna | (20,201,332, 700,867,584, 2,826,551) | — | 同左 | 逐项一致 |
| 09-12 | gpt-5.6-sol | (2,916,426, 51,595,264, 199,814) | (922,839, 23,624,064, 85,216) | (3,839,265, 75,219,328, 285,030) | 逐项一致（跨日补 24,632,119） |
| 09-12 | gpt-5.6-terra | (1,600,390, 44,061,696, 185,497) | — | 同左 | 逐项一致 |
| 09-12 | gpt-6-astra | (12,062,971, 530,349,952, 1,704,238) | — | 同左 | 逐项一致 |
| 09-12 | gpt-reserve | (1,831,531, 56,109,568, 106,760) | — | 同左 | 逐项一致 |

```
总 tokens：独立复算(含跨日) 1,830,205,933 | ccusage 1,830,205,933 | 差 0
```

- 我们的「目录内」合计 = 1,767,425,021，与 `codex-usage --by-model` 的「合计」逐位一致（同一命令的交叉校验）。
- 补正项合计 62,780,912 = astra 38,148,793 + sol 24,632,119。

### 4.2 根因：三条「早日期目录、窗口内事件」的文件（实测）

对全部目录（不止 `[since, until]`）扫描、再按事件时间戳裁窗口，只有 3 个早目录文件含窗口内事件：

| 文件 | 路径日期 | 窗口内事件时间 | 窗口内贡献（模型/净/缓存/输出/总） |
|---|---|---|---|
| `2026/09/08/rollout-2026-09-08T08-52-16-01a07e80-5d57-7fc1-818d-f95b13f22637.jsonl` | 09-08 | 09-12 14:22 起 183 条 | gpt-5.6-sol `922,839 / 23,624,064 / 85,216 / 24,632,119` |
| `2026/09/09/rollout-2026-09-09T09-18-49-01a083b7-51de-7973-877e-46240174d882_01a083bf-0884-70b1-a6f5-0044c6a5b38d.jsonl` | 09-09 | 09-11 11:52 起 260 条 | gpt-6-astra `739,535 / 34,972,032 / 116,903 / 35,828,470` |
| `2026/09/10/rollout-2026-09-10T14-52-01-01a08a16-71c8-7db3-bb99-0e374b801634.jsonl` | 09-10 | 09-11 09:32 起 20 条 | gpt-6-astra `132,221 / 2,184,448 / 3,654 / 2,320,323` |

- 我们的 `collect()`（只按 `since.date()..until.date()` 拼日期目录）**不会打开**这 3 个文件，因此少 62,780,912 tokens。
- ccusage 的文件准入规则包含 `路径日期 >= since 或 mtime >= since 时刻`（参考其 `rust/adapters/codex/src/paths.rs`，本机 npx 的是发布包 `20.0.20`，源码取自 main 分支，仅作旁证；实测结论不依赖该源码），所以它把这 3 个文件算进来了，且按事件时间戳把它们落在 09-11/09-12。
- 我们自己的口径文档也承诺「跨窗口会话只统计窗口内的轮次」——即**应该**包含这些轮次，因此这是实现与文档不一致的缺口，而不是「窗口约定不同」。修复方向（由 Lead/实现负责人决定）：`collect()` 在日期目录之外，再补扫 mtime >= since 的 `rollout-*.jsonl`（archived 目录本来就是无日期过滤全扫的，存在不对称）。

### 4.3 `gpt-5.6-sol` −24,632,119 与 `gpt-6-astra` −38,148,793 的落点

- `gpt-5.6-sol`：**就是**上表第 1 个文件在 09-12 的窗口内轮次（`24,632,119`，与差异逐位相等）。既不是窗口内的「事件边界」漏算，也不是归因错误，更不是继承前缀。
- `gpt-6-astra`：上表第 2、3 个文件之和（`35,828,470 + 2,320,323 = 38,148,793`）。
- **反证（实测）**：把「首帧改为累计整块」（一个会把继承快照全算进去的变体）只会在 `codex-auto-review` 上多出 38,126,772，而 astra/sol 两行分毫不动；继承首帧实测只有 6 个文件（合计 38,126,772，`last` 全 0，首帧最大 14,051,760），T6 与 ccusage 都把它们排除。因此「astra 差 ≈ 继承量」只是两个 38.1M 级数字的巧合，不是同源。

### 4.4 成本台账与分解（定窗，task-9 已接入统计层）

```bash
.venv/bin/python tests/test_metering_regression.py --cost --ccusage --since 20260911 --until 20260912
```

实测输出（节选）：

```
model                        档位感知          标准价       档位加成   calls      无价token
codex-auto-review         30.7531      27.6812     3.0719     291            0
gpt-5.6-luna              26.3727      26.2550     0.1178    6483            0
gpt-5.6-sol               84.4370      84.4370     0.0000     985            0
gpt-5.6-terra             19.9316      19.9316     0.0000     411            0
gpt-6-astra              954.5480     903.1481    51.3999    5004            0
gpt-reserve                0.0000       0.0000     0.0000     372   58,047,859
TOTAL                   1116.0424    1061.4529    54.5895
priority/fast 轮次（独立复算）：
    codex-auto-review    priority calls=50
    gpt-5.6-luna         priority calls=29
    gpt-6-astra          priority calls=292
day          ccusage costUSD        我们标准价        我们档位感知
2026-09-11          210.7462     210.7462      210.7462
2026-09-12          853.8963     850.7067      905.2962
合计：ccusage 1064.6425 | 我们标准价 1061.4529 | 我们档位感知 1116.0424
我们(档位感知) − ccusage = +51.3999；ccusage − 我们标准价 = +3.1896
分项：gpt-6-astra 档位加成 = +51.3999（ccusage 未计）；其它模型档位加成合计 = +3.1896（ccusage 已计）
```

分解（每一项都是实测）：

| 项 | 金额（定窗 09-11~09-12） | 说明 |
|---|---|---|
| 我们 CLI 当前输出（仅日期目录内，117 会话） | $1,049.30 | `codex-usage --by-model --since 20260911 --until 20260912` |
| 跨日目录文件应补 | +$66.7472 | astra $51.9019 + sol $14.8453（与 token 缺口同一根因） |
| **我们（补齐后、档位感知）** | **$1,116.0424** | 应为正确值 |
| ccusage | $1,064.6425 | 同窗口 |
| 差额 | **+$51.3999** | 恰好 = astra 的 Fast 档加成 |
| ccusage − 我们标准价 | +$3.1896 | 恰好 = luna $0.1178 + auto-review $3.0719 的档位加成 |

- 09-11 双方完全相等（`210.7462`，该日无 priority 轮次）；全部差异集中在 09-12。
- 结论：**剩余差异不是我们低估，而是 ccusage 低估**——它没有对 `gpt-6-astra` 的 292 个 priority 轮次施加 Fast 倍率（仍按标准价计）。旁证：ccusage 20.0.20 二进制内嵌的 fast-multiplier-overrides 模型清单里有 `gpt-5.6-sol`/`gpt-5.6-terra`/`gpt-5.6-luna`/`gpt-5.5` 等，`strings` 中 `gpt-6-astra` 出现次数为 **0**（推断，见第 7 节）。
- research-dev 的推断（ccusage costUSD 与标准价之差 = luna + auto-review 的 priority 加成）在本窗被**独立证实**（$3.1896 vs 两个加成之和 $3.1897，差 1e-4 为四舍五入）；差异量级是 astra 的 **+$51.3999**，而不是某一日单独的 $52.2（那是 09-12 的局部估计，本窗跨 09-11/09-12，astra priority 轮次实测 292 个而非常引用的 297 个）。
- 「实时窗口」抽样（2026-09-13 21:48:22 +0800，`--since 20260911`，未定 until）：我们（全目录、档位感知）$1,211.2052、我们标准价 $1,156.6157、ccusage $1,159.8053，差仍是 **+$51.3999**。Lead 先前看到的「我们 $1,144.46 / ccusage $1,159.65」中，我们那一侧是**未补跨日文件**的值（117+9 会话层），所以看起来低 $15；补齐后方向反转。
- 别名：`codex-auto-review → gpt-5.5`（assumed，task-9）在两边 token 完全相等（09-12 = 20,509,031），成本一致性由 sum 校验支撑；`gpt-reserve` 无公开价，两边都计 $0，我们标 `*`（58,047,859 tokens / 372 轮）。

### 4.5 ccusage 侧语义（旁证，非结论依据）

从 main 分支源码（`rust/adapters/codex/src/parser.rs`、`paths.rs`）读到、并与实测一致的点：

- 每轮口径：`last_token_usage` 存在且累计值相对上一条事件「有推进」时取 last，否则取累计差分（`total − prev`，saturating）；累计未推进的重复帧记 0。
- 有 fork/replay 前缀跳过机制（`CodexReplayState`、`detect_rewritten_burst`），与我们的「首帧只取 last」殊途同归：本窗两边的逐帧结果完全一致。
- `codex-auto-review` 按事件日期映射到 released-on 表里的模型（本窗全部 → `gpt-5.5`，2.5× Fast）。
- 文件准入含 `mtime >= since` 分支（4.2 节的根因旁证）。

### 4.6 ccusage `--until` 的边界语义（未完全查清，已记录）

实测 `--since 20260913 --until 20260913-0000 / -1200 / -2100 / 20260913` 的 09-13 总 tokens 分别为 `183,232,509 / 183,232,509 / 183,279,341 / 183,279,341`——显然不是「按 HHMM 严格截断到 00:00」，`-1200` 与 `-2100` 有差、裸日期等于 `-2100`。因此本报告所有 ccusage 对照一律用**已经过去的整日** `--until 20260912`，避免这个未查清的边界约定影响结论。

---

## 5. 第 4 项：反例检查（确认没有引入低估）

| 检查 | 方法 | 实测结果 |
|---|---|---|
| 缓存读价缺失/为 0 时是否被计成 0 | `model_cost_detail` 直接构造无 cache read 价与显式 0 的记录 | 两种情况 `fallbacks=["cacheReadCostPerMillion"]`，成本 = `(1000+1,000,000)×$10/M = $10.01 > 0`（回退 input 价） |
| cache read 价存在时误标回退？ | 同上有价记录 | `fallbacks=[]`，成本 `$1.01` |
| `tier=priority` 是否被按标准价 | `model_cost_detail(..., tier="priority")`（gpt-5.6-sol） | 标准 $4.00 → priority **$8.00**（2.0×），`tier_priced=True`、`confidence=official`；`default/unknown/None` 仍 $4.00；`fast` 与 `priority` 同价；`flex` $2.00（0.5×） |
| 档位明细是否漏计 | 全部 126 个会话比对 `tiers` 合计 vs `models` | 0 破例 |
| 无定价模型是否被静默按 $0 当成免费 | `gpt-reserve` 58,047,859 tokens | 我们输出 `$0.00*` 并标注无定价（`pricing_full=False`），token 照常统计 |
| 别名是否改变 token/成本 | `codex-auto-review` vs `gpt-5.5` | 同一命令两种口径成本相等（$30.7531 含档位；`priced_as=gpt-5.5`、`assumed=True`） |
| 分页合并修好后是否仍漏 tiers | 定窗 117 + 全窗 126 会话不变式 | 0 破例（修前该会话 tiers 少 4,810,982 毛输入） |
| 新旧口径方向 | 定窗 `--json` 汇总 | 新口径 `total_tokens=1,767,425,021`；旧口径 `delta_sum=1,810,764,843`，旧口径高 **2.452%**；`resets=0`、`fallbacks=3` |
| 重复累计事件是否真的是旧口径虚高来源 | 全窗逐文件扫描「累计值未推进」事件 | 128 个文件里 **68 个**含至少 1 条重复累计事件（这就是旧口径多算的部分） |

注：`fallbacks=3` 的 3 次是真实数据里缺 `total_token_usage` 的轮次，T6 回退 last 后未丢数据；`resets=0` 表示本窗没有累计回落。

---

## 6. 缺口与其它观察

### 6.1 已知缺口（唯一影响正确性的一项）：跨日目录文件漏扫

- 现象/证据/影响见 4.2、4.3：定窗 token −62,780,912（−3.43%）、成本 −$66.7472。
- 已固化为 `test_cross_day_dir_file_with_in_window_event_is_scanned`（`xfail(strict=False)`），修复后会自动转为 XPASS 不报错。
- 影响面：任何「文件创建日 < since 但窗口内仍有轮次」的长会话/分页续写；`sessions/` 按用户选择很常见（跨夜长跑会话）。
- 未做：实现修改（按分工由 Lead/实现负责人决定）。

### 6.2 `--raw --session <线程ID>` 选不到分页续页

`--raw` 把 sid 改成文件名末位 UUID，分页第 2 页的 sid 是 `01a0942e…`，`--session 01a0940d` 前缀匹配不到它（实测 `--raw --session 01a0940d` 只返回第 1 页）。聚合口径（非 `--raw`）不受影响。属过滤器语义的小坑，供参考，未改。

### 6.3 `unknown` 档是真实存在的档位

本机 `~/.codex/config.toml` 的 `service_tier` 解析结果为 `default`，因此 `unknown` 档按标准价计（符合「宁多算不少算」）。定窗里 astra 有 `unknown` 档用量（如分页会话 4,819,202 毛输入 / 35 轮），全部有价。

### 6.4 理论边界：首帧有 total、无 last、且非真正首帧

窗口内第一个 token_count 若缺 `last_token_usage`，T6 会用整块累计值（可能偏大）；ccusage 会用 `total − 窗口外上一条的 total`。实测本机 1357 个 rollout 文件里 `total 存在但 last 缺失` 的事件 **0 条**，该路径当前不可达，仅记录。

### 6.5 文档不一致（非功能缺陷）

`src/codex_usage/parser.py` 顶部模块 docstring 第 8–10 行仍写着旧口径（「token 计量用每轮 token_count.last_token_usage」），与同文件 `parse_rollout` 的新口径 docstring 矛盾。属陈旧注释，建议顺手更新（未改，不在我的写范围）。

---

## 7. 实测 / 推断 / 未获取

**实测（可复现）**
- 第 2 节全部逐文件值、第 4.1 节全部逐 (天,模型) 值与总差 0、第 4.2 节 3 个跨日文件的贡献、第 4.4 节全部金额与档位加成、第 5 节全部反例检查结果、`tiers/models` 不变式 0 破例。
- ccusage 二进制里 `gpt-6-astra` 出现 0 次、内嵌倍率表包含 `gpt-5.6-sol`: 2.0 / `gpt-5.5`: 2.5（`strings`）。

**推断（有证据但非直接实测）**
- ccusage 少算 astra 成本的**机制**：它的 Fast 倍率/模型表未收录 `gpt-6-astra`，因此 priority 轮次按标准价计。证据是「差额 $51.3999 恰好等于 astra 档位加成」+ 二进制里 astra 缺失；但我没有直接读到 20.0.20 的定价表结构。
- ccusage 的文件准入规则（`路径日期 >= since 或 mtime >= since`）来自 main 分支源码；发布包是 20.0.20，未逐行确认。
- 跨日文件漏扫的修复方向（补扫 mtime >= since 的文件）是建议，未实现、未验证。

**未获取**
- ccusage 的**逐模型** costUSD（JSON 只给每日总额），因此无法逐模型逐位核对它的成本；只能靠「总额 − 我们标准价」的恒等式分解。
- ccusage `--until` 的精确时间截断语义（4.6 的 4 种输入互不一致）。
- 那 6 个继承首帧文件的父线程来源（哪个父文件产生了被继承的 38,126,772）；不影响本报告结论（两边都排除了它）。
- 09-13 当日完整数据（采样时 21:52，机器仍在写），故正文以定窗为准。

---

## 8. 复现命令汇总（工作目录 = 仓库根）

```bash
# 1. 边界用例回归 + 全量测试 + lint
.venv/bin/python -m pytest tests/test_metering_regression.py -q      # 19 passed, 1 xfailed
.venv/bin/python -m pytest tests/ -q                                 # 183 passed, 1 xfailed
.scratch/bin/ruff-x86_64-unknown-linux-gnu/ruff check .              # All checks passed!

# 2. 逐文件独立复算 vs codex-usage --json --raw（第 2 节）
.venv/bin/python tests/test_metering_regression.py --recompute --verbose --since 20260911 --until 20260912
.venv/bin/python tests/test_metering_regression.py --recompute --since 20260911 --until 20260913

# 3. token 台账 + ccusage 对账（第 4.1 节）
.venv/bin/python tests/test_metering_regression.py --ledger --ccusage --since 20260911 --until 20260912

# 4. 成本分解 + ccusage 对账（第 4.4 节）
.venv/bin/python tests/test_metering_regression.py --cost --ccusage --since 20260911 --until 20260912

# 5. 我们 CLI 的直接数字
.venv/bin/python -m codex_usage.cli --since 20260911 --until 20260912 --by-model
.venv/bin/python -m codex_usage.cli --since 20260912 --until 20260912 --json --session 01a0940d

# 6. ccusage 原始数据（缓存固定到仓库内）
env npm_config_cache="$PWD/.scratch/npm" npx --yes ccusage@latest codex daily --json --since 20260911 --until 20260912
```
