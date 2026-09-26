# 轻量终端方案：参考 ccusage，不引入全屏 TUI

日期：2026-09-27。用户明确认为 Textual 全屏过重，要求参考 ccusage 类工具。结论：**终端保持一等入口，但采用一次性响应式 Rich 报表，不做全屏应用。** 本地浏览器 UI 方向不变。

## 1. ccusage 值得借鉴的具体机制

本轮研究代理浅克隆并核实官方源码 `25ca71b1a029a88356406f0c53323975adbecd01`：

- [输出决策](https://github.com/ccusage/ccusage/blob/25ca71b1a029a88356406f0c53323975adbecd01/rust/crates/ccusage-core/src/output.rs#L18-L25)：显式 `--compact`，或者 stdout 是 TTY 且宽度小于阈值时紧凑。不是所有管道都自动按窄屏输出。
- [阈值](https://github.com/ccusage/ccusage/blob/25ca71b1a029a88356406f0c53323975adbecd01/rust/crates/ccusage-core/src/lib.rs#L57) 是100列；[终端探测](https://github.com/ccusage/ccusage/blob/25ca71b1a029a88356406f0c53323975adbecd01/rust/crates/ccusage-terminal/src/terminal.rs#L3-L18) 优先 COLUMNS，缺失回退120。
- [单源报表选列](https://github.com/ccusage/ccusage/blob/25ca71b1a029a88356406f0c53323975adbecd01/rust/crates/ccusage-core/src/output.rs#L385-L403) 紧凑模式保留日期/模型/Input/Output/Cost；[多源报表](https://github.com/ccusage/ccusage/blob/25ca71b1a029a88356406f0c53323975adbecd01/rust/crates/ccusage-adapter-all/src/report.rs#L521-L569) 另保留 Agent。完整模式有缓存等更多指标。
- [表格实现](https://github.com/ccusage/ccusage/blob/25ca71b1a029a88356406f0c53323975adbecd01/rust/crates/ccusage-terminal/src/table.rs#L256-L366) 仍有缩列、换行/截断，不是100列以上就对任意数据完美排版。
- 每次 print 计算并写行，不是长驻全屏重排。官方“扩大终端”的建议应理解为重跑后按新宽度输出，不能承诺进程退出后改造历史表格。

不照搬100列或Rust实现；借鉴的是**命令快照、列优先级、紧凑模式、可组合输出**。

## 2. 当前 Rich 栈已足以做轻量布局

研究代理使用现有 `.venv/bin/python` / Rich 15.0.0 运行临时合成探针，没有修改产品。包含中文项目名、中文未知费用和不同宽度；以 `rich.cells.cell_len` 而不是字符串长度测显示宽度。

| 设置宽度 | 策略 | 实测最大显示宽度 |
|---|---|---:|
| 120 | 日期、名称、模型、输入、输出、缓存、费用 | 120 |
| 80 | 日期、名称、输入、输出、费用 | 80 |
| 60 | 名称、输入、费用 | 60 |
| 40 | 无框双行记录，名称/日期一行，数值一行 | 39 |

命令环境为隔离 HOME/cache、`TERM=xterm-256color`；`Console(width=N,height=24)`。各尺寸探针退出码0。断点只是演示，不是对任意长模型/超大数字/emoji的普适保证，也不是最终视觉定稿。

60列示例：

```text
 项目/会话                                   输入      费用
 项目/会话：长中文名称 演示                12,345    $10.23
 另一个项目/代理                               98      未知
```

### 探针发现的边界

- `NO_COLOR=1` 关闭颜色不等于零 ANSI：强制TTY时 Rich 仍可能输出 bold/reset。严格纯文本需 `color_system=None` 等明确控制并验证。
- 真正 shell pipe 的小样本检测为 `escape=False`、5行、中文正常，退出0。不能扩展成任意数据均兼容。
- Rich 15 的 dumb terminal 路径在仅固定width、不同时固定height时会回退80×25。初次探针据此出现请求60却实际80；加入明确TERM与height后才通过。尺寸验证需记录环境，不能只传一个width就认为模拟真实终端。

## 3. 推荐输出约定

1. 默认执行一次并退出，保留终端滚动历史；不清屏、不进入备用屏幕、不隐藏光标、不接管键盘。
2. 顶部一行查询范围/时区，简短总计与缺价提示；随后输出当前分组的表格，不默认堆多张大表。
3. 关键列是可识别名称、tokens、费用及其性质。宽度不足隐藏次要列；更窄时转成纵向字段，不随机截碎数字。
4. 模型/会话详情通过参数查询；完整精确值通过JSON获取。终端仍可独立完成分析，不降为网页启动器。
5. 支持显式width/compact选择；默认输出前读取终端宽度。窗口改变后重新执行得到新布局，历史输出不由程序追溯重排。
6. 不根据终端高度偷偷丢行；长列表用过滤/范围或用户外部分页器。可用 `| less`，但默认不自动启动pager，JSON不进pager。
7. 管道与TTY明确分流，JSON不受宽度影响；不把固定250列作为自动适配策略。
8. 索引、价格、过滤和计量核心与网页共用；网页用交互，终端用命令，不要求视图或手势镜像。

## 4. watch 与分页不作为默认负担

外部 `watch` 会反复运行查询、重绘并增加IO；已有数据扫描是秒级，不适合默认为高频轮询。没有用户确认持续监控需求，不新增内置watch。

Rich 有 pager API，但系统pager行为取决于终端、locale与程序；先采用用户显式管道。分页器里的折行也不等于报表重新选列。

## 5. CodeBurn 的轻量入口

CodeBurn 默认/report 是交互 dashboard，但另有 `overview`、`models`、`sessions`、`status` 和 JSON。主代理实际运行固定日 `overview --no-color`：正常退出，93行、无ANSI、无备用屏幕序列；它确实能作为一次性输出，不必启动dashboard。不过一次输出多块内容偏长，是否符合目标仍要看具体查询。

此处不是说CodeBurn整体“依赖很轻”：其package含React/Ink等。**交互轻量、安装依赖、启动成本是三个维度**，不能因有静态输出就当三者都满足，也不能因Textual被否决便自动接受另一个全屏框架。

具体能力替代结论与PTY结果见 [CodeBurn实测](2026-09-27-codeburn-verification.md)。

## 6. 验收边界

后续产品验收：120/80/60/40列代表性真实数据；中文/长标识/超大数字/未知费用；颜色开关/pipe/JSON；显式width/compact；正常退出和BrokenPipe。不得只通过“每行不越界”便宣称好看，还要看名称是否可识别、数字是否完整、层级和密度是否清楚。

本轮没有实现生产renderer，没有进行所有用户终端实机验证；临时探针只是证明现有Rich可以承载该方向。
