# Automation 2026 評估重現指南

本文件說明如何執行 AutoCtrl 的 parser-only 評估，重現論文 Table I 使用的四種解析方法比較。評估固定使用 [`tests/corpus/commands_320.csv`](../tests/corpus/commands_320.csv) 中的 320 句繁中／英文語料，只測量文字到結構化請求的解析結果。

評估器不會載入 `rclpy`、不會建立 ROS2 node，也不會發布 `/cmd_vel`，因此不必啟動小車 driver、ROS2 或 Zenoh bridge，亦可在小車關機時執行。

## 環境需求

`automation2026-eval-v1` 正式結果使用以下環境：

- Python 3.12
- [uv](https://docs.astral.sh/uv/)（依 `uv.lock` 建立隔離環境）
- Ollama 0.23.4，服務位址預設為 `http://127.0.0.1:11434`
- 本地模型 `qwen3.6:35b`

先確認版本與模型：

```bash
python3 --version
uv --version
ollama --version
ollama list
```

預期至少可看到：

```text
Python 3.12.x
ollama version is 0.23.4
qwen3.6:35b
```

若尚未下載模型：

```bash
ollama pull qwen3.6:35b
```

執行評估前，請確認本機 Ollama 服務已啟動且模型可回應。

## 安裝專案環境

從專案根目錄依鎖定檔同步 Python 環境：

```bash
cd /home/nvidia/autoctrl
uv sync --frozen
```

`--frozen` 可避免重現過程更新 `uv.lock`。若專案位於其他路徑，請將 `cd` 改為實際 clone 位置。

## 重現 Table I

執行完整 320 句、四種解析方法的評估：

```bash
cd /home/nvidia/autoctrl
uv run python scripts/evaluate.py
```

預設依序評估：

1. `rule-only`：僅使用確定性 motion/status 規則，未匹配時回傳 no-tool。
2. `llm-only`：每句皆直接交給本地 Ollama 模型。
3. `hybrid-v0`：原始、尚未加入 guard 的確定性優先路由。
4. `guarded-hybrid`：現行加入高信心 guard 的 HybridInterpreter。

評估開始前會暖機模型；暖機時間不計入 latency。模型推論使用 temperature `0.0`、seed `42`，每句只觀測一次。完整執行會呼叫本地模型數百次，所需時間取決於硬體與當時系統負載。

若只想先驗證流程，可執行前 4 句 smoke test：

```bash
uv run python scripts/evaluate.py --limit 4
```

smoke test 只能確認流程，不能作為論文 Table I 的結果。

## 輸出與 Table I 欄位

完整結果預設寫入：

```text
results/<YYYYMMDD-HHMMSS+TZ>/
```

主要檔案如下：

| 檔案 | 用途 |
|---|---|
| `metrics.csv` | Table I 的整體準確率、Wilson 95% CI、mean/P95 latency |
| `predictions.csv` | 四種方法對每一筆語料的預測、正誤、延遲與錯誤訊息 |
| `metadata.csv` | timestamp、Git commit、dirty 狀態、模型標籤、語料 SHA-256 與執行環境 |
| `mcnemar.csv` | Guarded Hybrid 對 Hybrid v0、LLM-only 的 exact two-sided McNemar test |
| `summary.json` | 完整的機器可讀摘要與分類／語言分組結果 |
| `REPORT.md` | 方便人工檢查的 Markdown 報告 |

Table I 對應 `metrics.csv` 的欄位：

| 論文指標 | CSV 欄位 |
|---|---|
| Exact-request accuracy | `exact_request_accuracy` |
| Requested-slot accuracy | `requested_slot_accuracy` |
| Request-class accuracy | `request_class_accuracy` |
| Mean latency (ms) | `latency_mean_ms` |
| P95 latency (ms) | `latency_p95_ms` |

三個 accuracy 欄位以 `0` 到 `1` 的比例儲存；製作論文表格時乘以 100 即為百分比。相對應的 `*_ci95_low` 與 `*_ci95_high` 是 Wilson 95% 信賴區間。

評估完成後，先確認 `metadata.csv`：

- `cases` 必須為 `320`。
- `model_tag` 必須為 `qwen3.6:35b`。
- `git_commit_hash` 與語料 `corpus_sha256` 必須保存於論文實驗紀錄。
- `ros_imported`、`ros_node_created`、`cmd_vel_published` 必須皆為 `False`。

## 可選參數

指定結果目錄、模型服務位址或逾時：

```bash
uv run python scripts/evaluate.py \
  --output-dir results/table-i-candidate \
  --model qwen3.6:35b \
  --ollama-url http://127.0.0.1:11434 \
  --timeout-s 120
```

只執行部分 baseline：

```bash
uv run python scripts/evaluate.py \
  --baselines rule-only,guarded-hybrid
```

省略任一 baseline 的結果都不能直接取代完整 Table I。若略過 `hybrid-v0` 或 `llm-only`，相對應的 McNemar 比較也不會產生。

## 正式 release run

程式、語料、測試與鎖定檔提交後，確認 working tree 乾淨，再執行：

```bash
./scripts/release-eval
```

這個入口會以鎖定的 pytest 8.x 跑完整測試，再執行 `evaluate.py --release`。`--release` 會拒絕 dirty tree、不完整 corpus、缺少 baseline，以及無法取得 Ollama 版本或 model digest 的環境。

## 公開正式結果

論文 Table I 的正式 reference run 收錄於 [`artifacts/automation2026-eval-v1`](../artifacts/automation2026-eval-v1)：

- 執行時間：2026-08-27 14:42（UTC+8）
- Git commit：`afd4aba3ea910a78e186328f5c706882d3d551e7`
- working tree：clean（`git_dirty=False`）
- corpus SHA-256：`0747f1777e22668ca9c2e289449334030fb6d93f76db7d0f539d77774052ffa4`
- model digest：`07d35212591fc27746f0a317c975a6d68754fb38e9053d82e25f06057af28522`

| 方法 | Request class | Exact request | Requested slots | Mean latency (ms) | P95 (ms) |
|---|---:|---:|---:|---:|---:|
| Rule-only | 70.9% | 70.6% | 67.2% | 0.0 | 0.0 |
| LLM-only | 95.3% | 94.4% | 100.0% | 1304.9 | 1719.7 |
| Hybrid v0 | 93.1% | 87.5% | 76.6% | 582.0 | 1708.5 |
| Guarded Hybrid | 94.1% | 93.4% | 100.0% | 611.8 | 1699.2 |

完整精度、Wilson 95% CI 與檢定結果應以 artifact 內的 CSV 為準。Guarded Hybrid 對 Hybrid v0 的 exact McNemar `p=0.0000660`；對 LLM-only 為 `p=0.6072`。

## Known limitations

- 每個 utterance 只執行一次模型推論；結果尚未量化跨次推論變異。
- 語料與初始標籤由同一作者建立，尚未完成雙人獨立標註。
- parser-only benchmark 不代表實際底盤運動誤差或緊急停止能力。
- 延遲數值與 DGX Spark、當下負載及模型 runtime 綁定，不應直接外推至其他硬體。
