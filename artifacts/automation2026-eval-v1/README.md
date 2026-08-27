# automation2026-eval-v1

AutoCtrl 的 320 句雙語 parser-only reference benchmark。此目錄對應乾淨程式版本 `afd4aba3ea910a78e186328f5c706882d3d551e7`，執行時未匯入 ROS、未建立 publisher，也未發布 `/cmd_vel`。

## 檔案

- `metrics.csv`：論文表格的整體指標與 Wilson 95% CI。
- `predictions.csv`：四種方法的 1,280 筆逐句預測。
- `mcnemar.csv`：exact two-sided McNemar 檢定。
- `metadata.csv`：commit、corpus／evaluator／lockfile hash、Ollama 與模型 digest。
- `summary.json`：完整機器可讀統計。
- `REPORT.md`：人工可讀摘要。

## 引用與驗證

論文或報告請同時記錄 release tag、commit hash、corpus SHA-256 和 model digest。語料由作者建立與標註，尚未完成雙人獨立標註；此 benchmark 衡量的是 parser 請求選擇，不是實車致動成功率或安全認證。
