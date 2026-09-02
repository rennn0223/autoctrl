# Isaac Sim 語意到動作整合評估

此評估器以公開 ROS 2 介面驗證完整鏈路：自然語言 `/autoctrl/command` → AutoCtrl 結構化意圖 → `/sim/cmd_vel` → Isaac Sim → `/sim/odom`。它補充既有 320 句 parser-only benchmark，但不取代該 benchmark。

## 安全預設

預設為 **simulation-only**。AutoCtrl 的實車輸出會改送至隔離的測試 sink，不會發布移動速度到 `/small/cmd_vel`。每筆試驗前及結束後都會送出停止命令，並以 `/sim/odom` 連續三筆低速資料確認虛擬車已靜止。

只有操作人員確認實車架高或場地淨空後，才可加上 `--with-real`。此選項會恢復 `/small/cmd_vel` 與 `/small/odom`，可能使實車移動。

## 環境需求

- Python 3.12 與 `uv`
- ROS 2 Jazzy，Domain ID 2
- Ollama 0.23.4 與 `qwen3.6:35b`
- Isaac Sim 已載入測試場景並按下 Play
- `/sim/odom` 為 `nav_msgs/msg/Odometry`
- `/sim/cmd_vel` 可經 `cmdvel_to_ackermann` 轉為 `/sim/ackermann_cmd`

專案不會替其他部署建立 ROS 2 bridge 或 Zenoh bridge。若 namespace 不是 `/sim` 或 `/small`，請以 CLI topic 選項指定實際介面，並先自行確認通訊橋接。

## 固定試驗協定

固定語料位於 `tests/corpus/isaac_semantic_commands.csv`，共 20 句：繁中及英文各 10 句；前進、後退、左轉、右轉、停止各 4 句。四種移動命令皆持續 2 秒。停止案例會先發布持續前進命令，再量測停止命令與 odom 穩定時間。

每筆成功必須同時符合：

1. AutoCtrl 接受的 kind 與 direction 符合標註。
2. `/sim/cmd_vel` 的速度符號符合方向；停止則兩軸皆為零。
3. `/sim/odom` 的縱向位移或 yaw 符號符合方向且超過預設門檻；停止則連續三筆速度不高於 0.02 m/s。

`MotionSequence` 不包含在這組單步驟整合語料中，需與 320 句 parser-only 結果分開敘述。

## 執行

先確認 Isaac Sim 已按 Play，再執行：

```bash
./scripts/evaluate-isaac \
  --repetitions 3 \
  --output-dir results/isaac-semantic-60
```

快速檢查完整鏈路：

```bash
./scripts/evaluate-isaac --limit 1 --repetitions 1
```

明確授權實車移動的虛實同動試驗：

```bash
./scripts/evaluate-isaac --with-real --repetitions 3
```

## 輸出

每次執行會產生：

- `trials.csv`：逐筆語意、cmd_vel、odom、latency 與失敗原因。
- `summary.csv`：依方向與整體彙整成功率、Wilson 95% CI、延遲及終點 odom 統計。
- `metadata.json`：時間、Git 狀態、模型、Ollama/Python 版本、語料 SHA-256 與門檻。
- `REPORT.md`：可直接閱讀的成功率、終點 odom 與 latency 表。
- `autoctrl-startup.log`：AutoCtrl 接受意圖與執行紀錄。

投稿使用的正式結果應由乾淨 Git commit 重新執行，並保存全部五個輸出檔。若只執行 simulation-only，不可將結果描述成實體車與虛擬車的同步誤差；可描述為 Isaac Sim semantic-to-motion integration evaluation。

## 已知限制

- 語料規模為 20 句、每句預設重複 3 次，適合 integration evidence，不是廣泛語言泛化 benchmark。
- 結果依目前 Isaac 場景、車輛動力學、控制頻率與硬體負載而變。
- 文字停止不是 emergency stop；實車仍需獨立高優先序停止與硬體安全措施。
- 虛實位移與朝向誤差欄位只有在 `--with-real` 且收到兩側 odom 時才具有意義。
