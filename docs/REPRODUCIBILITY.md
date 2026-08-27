# Automation 2026 可重現性說明

本頁是 AutoCtrl 論文 reference artifact 的入口。產品操作請看 [SETUP](SETUP.md)，評估細節請看 [EVALUATION](EVALUATION.md)，Guard 條件請看 [GUARD_DESIGN](GUARD_DESIGN.md)。

## 固定研究物件

- 語料：`tests/corpus/commands_320.csv`
- 評估器：`scripts/evaluate.py` 與 `src/autoctrl/evaluation.py`
- Python：3.12
- Ollama：0.23.4
- 模型 tag：`qwen3.6:35b`
- baseline：rule-only、LLM-only、Hybrid v0、Guarded Hybrid
- sampling：temperature 0、seed 42、每句一次 observation

語料包含 320 句，繁中與英文各 160 句；期望類別為 motion 176、status 64、no-tool 80，其中 64 句包含距離或角度 slot。

## 安全邊界

此 benchmark 只測文字解析。評估器會確認未匯入 `rclpy`、未建立 ROS node、未建立 publisher，也未發布 `/cmd_vel`。它可以在小車與 Zenoh bridge 關閉時執行。

## 驗證與正式執行

```bash
cd /path/to/autoctrl
uv sync --frozen --group dev

set +u
source /opt/ros/jazzy/setup.bash
set -u

uv run pytest -q
./scripts/release-eval
```

`release-eval` 會先執行完整測試，再以 `--release` 執行完整 320 句、四 baseline 評估。`--release` 會拒絕：

- dirty 或未提交的 Git working tree
- 非預設或不完整的 corpus
- 缺少任一 baseline
- 無法取得 Ollama 版本或 model digest

## 保存的識別資料

每次正式結果包含：

- timestamp
- Git commit hash 與 dirty 狀態
- corpus SHA-256
- `uv.lock` SHA-256
- evaluator SHA-256
- Python／平台版本
- Ollama 版本
- 完整 model digest、大小與修改時間
- baseline 與 sampling 設定
- ROS import／node／publisher 安全欄位

## 統計輸出

- `metrics.csv`：request-class、exact-request、requested-slot accuracy，Wilson 95% CI，以及 mean/P95 latency。
- `predictions.csv`：逐句期望、預測、來源、正誤與 latency。
- `mcnemar.csv`：Guarded Hybrid 對 Hybrid v0、LLM-only 的 exact two-sided McNemar test。
- `metadata.csv`：版本與 hash。
- `summary.json`、`REPORT.md`：完整機器／人工可讀摘要。

## 證據限制

語料與初始標籤由作者建立，尚未完成雙人獨立標註；它不是自然使用者語料的代表性抽樣。PFNS 只是在 64 status、80 no-tool 與 16 stop 案例上的 parser-risk proxy，不是實際致動率或安全認證。實車只完成 ROS 2／Zenoh 整合示範，尚無 HIL、距離／角度誤差或 stop latency 的量化結果。
