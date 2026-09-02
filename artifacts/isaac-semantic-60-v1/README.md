# isaac-semantic-60-v1

AutoCtrl 的 Isaac Sim 語意到動作整合 reference artifact。固定 20 句繁中／英文語料各重複 3 次，共 60 trials；驗證自然語言解析、`/sim/cmd_vel` 方向與 `/sim/odom` settled endpoint。

## 結果摘要

- 前進、後退、左轉、右轉、停止各 12 次。
- semantic、command、odom 與 overall 皆為 60/60。
- overall Wilson 95% CI 為 93.98%–100%。
- 每筆開始前皆送零速度，並以連續三筆 odom 低速資料確認初始狀態已靜止。
- 本次為 **simulation-only**，不包含實體車，因此不可解讀為虛實同步誤差。

## 檔案

- `trials.csv`：60 筆逐次預測、速度、odom、延遲與失敗原因。
- `summary.csv`：依方向及整體彙整成功率、Wilson 95% CI、延遲與 endpoint 統計。
- `metadata.json`：乾淨版本、模型、環境、語料 hash 與判定門檻。
- `REPORT.md`：可直接閱讀及轉入論文的表格。
- `autoctrl-startup.log`：AutoCtrl 接受意圖的原始執行紀錄。

固定語料位於 `tests/corpus/isaac_semantic_commands.csv`，重現步驟請見 `docs/ISAAC_EVALUATION.md`。`MotionSequence` 不在此單步驟語料內。
