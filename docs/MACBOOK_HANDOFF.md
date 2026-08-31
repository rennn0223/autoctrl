# MacBook 論文工作交接

這份文件列出從公開 GitHub 取得 Automation 2026 論文資料的方法。公開 Repo 只保存可重現的程式、語料、統計與圖表；審查中的 ICCR 稿、Automation 待許可稿、官方 Word 模板與投稿往來不在 Repo 內。

## 取得專案

```bash
git clone https://github.com/rennn0223/autoctrl.git
cd autoctrl
git checkout automation2026-eval-v1
```

若要使用包含後續文件與圖表整理的最新版，改用：

```bash
git checkout main
```

## 論文使用的公開材料

| 路徑 | 用途 |
|---|---|
| `tests/corpus/commands_320.csv` | 320 句繁中／英文固定語料 |
| `artifacts/automation2026-eval-v1/metrics.csv` | 整體 accuracy、Wilson 95% CI、mean/P95 latency |
| `artifacts/automation2026-eval-v1/predictions.csv` | 四方法共 1,280 筆逐句預測 |
| `artifacts/automation2026-eval-v1/mcnemar.csv` | exact two-sided McNemar 檢定 |
| `artifacts/automation2026-eval-v1/metadata.csv` | 評估環境與可重現識別資料；不需逐字放入正文 |
| `artifacts/automation2026-eval-v1/summary.json` | 分類、語言與方法的完整機器可讀統計 |
| `artifacts/automation2026-eval-v1/REPORT.md` | 人工可讀結果摘要 |
| `artifacts/automation2026-eval-v1/figures/` | 可直接插入 Word 的 PNG、PDF、SVG 與 Table I CSV |
| `docs/EVALUATION.md` | 評估方法與重現方式 |
| `docs/GUARD_DESIGN.md` | Guarded Hybrid 條件與架構說明 |
| `docs/REPRODUCIBILITY.md` | 證據邊界、限制與版本保存方式 |

## Mac Word 建議流程

1. 將本機的 Automation 待許可 DOCX 與官方模板另外傳到 Mac，不要提交到公開 GitHub。
2. 使用 Microsoft Word 開啟 DOCX，確認全文為 Times New Roman。
3. 保持 US Letter、標題／作者跨欄、首頁 Abstract 起雙欄，以及正文雙欄。
4. 跨雙欄圖優先使用 `figures/*.pdf` 或 SVG；若 Word 相容性不佳，使用 300 dpi PNG。
5. Table I 從 `table-i-manuscript.csv` 匯入，不從圖片或四捨五入後的段落反推。
6. 由 Mac Word 匯出最終 PDF，檢查總頁數、字型嵌入、圖片清晰度與欄位溢出。

## 論文數字來源

正文可使用的核心結果為：Guarded Hybrid exact-request 93.4%、request-class 94.1%、requested-slot 100.0%、mean latency 611.8 ms、P95 latency 1699.2 ms。Guarded Hybrid 對 Hybrid v0 的 exact McNemar p 值為 0.0000660；對 LLM-only 為 0.6072。

這些是 parser-only 結果，不是實車成功率、安全認證、緊急停止能力或物理控制誤差。
