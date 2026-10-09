# 全自动死亡循环（auto-loop）使用说明

## 这是什么

双击 `agent/run_loop.bat` 之后，不用再管：

```
bot 自动跑 → 死了 → executor 自动分析修 → 独立过测试门 →
通过才 promote 上线 → git 自动提交+push → bot 重启 → 下一局
```

只有熔断器触发时才需要你（控制台蜂鸣 + 生成 `agent/loop_ALERT.txt`）。

## 启动 / 停止

- 启动：双击 `agent/run_loop.bat`，窗口开着就行（建议睡前开）。
- 停止：直接关窗口，或 Ctrl+C（会优雅停掉 bot）。
- 干跑检查（不启动 bot，只验证环境）：

```
"..\dota_automaton\.venv\Scripts\python.exe" agent\loop.py --dry-run
```

## 三道熔断（停机条件）

1. **测试门失败**：executor 改了代码但 `test_harness` 的 errors 不是 0
   → 不上线，直接停机。看 `agent/loop_testfail_<死亡名>.log`。
2. **连续无产出**：executor 连续 3 次死亡没改代码（默认 3 次，可配）
   → 停机，需要人工看死因。
3. **分数大跌**：某次上线后，连续 2 局分数 < 基线 50%
   → 自动回滚 `work.py` + `blimp_bot.py` 到上一个版本，停机。

熔断后：看 `agent/loop_ALERT.txt`（写明原因和处理建议）+
`agent/loop_log.txt` + 对应的 `agent/loop_executor_<死亡名>.log`，
人工处理完重新双击 `run_loop.bat`。

## 这次顺带修的 executor 老毛病

- **endgame enforcer**：executor 在最后 5 步会收到强制收敛提醒；
  步数用完还没写报告，runner 会自动生成带 `VERDICT` 的收敛记录，
  不会再出现"35 步烧完、什么都没留下"的情况。
- executor 的 prompt 更新：上线改为自动（测试通过后 loop 负责），
  它只管 `analysis/work.py` 和报告。

## 文件说明（都在 agent/ 下）

| 文件 | 说明 |
|---|---|
| `loop_log.txt` | 主日志，每局一行，平时只看它 |
| `loop_bot.log` | bot 进程的输出（原来控制台刷的那些） |
| `loop_executor_<死亡名>.log` | 每次 executor 的完整输出 |
| `loop_state.json` | 循环状态（见过的死亡、计数器、分数基线）。删掉它可重置基线和计数 |
| `loop_ALERT.txt` | 熔断告警（只在熔断时出现） |
| `loop_testfail_<死亡名>.log` | 测试门失败时的测试输出（只在熔断 1 时出现） |

## 配置（可选）

`agent/config.json` 里加 `"loop"` 一节即可调参，不加就用默认值：

```json
"loop": {
  "poll_sec": 5,              // 轮询 deaths/ 的间隔（秒）
  "debounce_sec": 10,         // 文件夹 N 秒无新文件视为写完
  "executor_timeout_sec": 3600, // executor 单次上限（秒）
  "max_no_change_streak": 3,  // 连续几次无改动后停机
  "max_fail_streak": 2,       // 连续几次崩溃/超时后停机
  "score_drop_ratio": 0.5,    // 分数 < 基线×此比例 视为大跌
  "score_watch_games": 2,     // 每次上线后观察几局
  "auto_push": true           // 上线后自动 git push
}
```

注意：不要动 `config.json` 里的 `model.api_key`。

## 和旧流程的关系

- `run_watcher.bat`（阶段 0 打包 zip）在全自动模式下退休了，不用再跑。
- `run_executor.bat` 还在，想手动分析某次死亡时照样可以用。
- `run_promote.bat` 还在，手动 promote 时用；自动 loop 里由程序调 `promote.py`。
- 每次自动上线都是一次 git commit（`[auto-loop]` 开头），
  想回滚：`git log --oneline` 找到上一个好版本，`git checkout <hash> -- analysis/work.py blimp_bot.py`。
