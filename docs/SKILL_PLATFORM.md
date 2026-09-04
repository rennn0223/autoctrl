# AutoCtrl Skill 平台設計與驗收規格

本文件是四個堆疊式 PR 的共同規格。目標是在不改變既有控制器與 Guarded Hybrid 行為的前提下，讓 AutoCtrl 能管理、篩選及擴充 LLM 可呼叫的能力，並加入唯讀的 ROS 2 知識檢索。

## 不可破壞的行為

- 確定性移動 fast path、文字停止優先權及既有狀態 fast path 保持原順序。
- LLM 只能選擇 Registry 公開的 Skill，不能指定任意 ROS topic 或自行產生底盤速度。
- 所有移動仍轉成既有 `MotionIntent` / `MotionSequence`，由既有 ROS 2 控制器執行。
- `stop_vehicle` 必須持續可用，且不被一般能力開關移除。
- ROS 2 知識 RAG 只能產生文字回答，不得發布速度或觸發其他 Skill。
- 外部 Skill 必須由使用者明確允許；未允許的已安裝套件不載入。
- 每一層均須通過既有測試；完整堆疊還須回歸 320 句語料與 Isaac Sim 整合測試。

## PR 1：Skill Registry 核心

- 將 Ollama 的硬編碼工具定義集中到單一 Registry。
- 每個 Skill 具有名稱、用途、風險分類、JSON schema 與 domain request 轉換器。
- 保留原有六個工具名稱與輸出行為，拒絕未知 Skill 及未宣告參數。

## PR 2：選擇策略與驗證

- 依允許清單產生當次提供給模型的 Skill 集合。
- 在解析後再次驗證 Skill 風險與參數，避免模型繞過工具 schema。
- 加入唯讀的虛實同動狀態查詢，但不改變 `/twin` 原有操作。

## PR 3：可安裝 Skill 與 CLI

- 透過 Python entry point 發現可信任的外部 Skill provider。
- 只有設定在明確允許清單內的 provider 才會載入。
- `/skills` 顯示目前啟用能力及風險，不執行能力。
- 文件提供獨立套件擴充方式與信任邊界。

## PR 4：ROS 2 知識 RAG

- 內建可追溯來源的 ROS 2 教學知識片段與本地檢索器。
- 僅在明確詢問 ROS 2 概念時檢索；移動與即時狀態問題仍走既有路徑。
- 回答必須以取回的內容為依據並標示來源；低相關度時回到一般對話。
- RAG 路徑回傳 `ConversationReply`，不得產生可執行命令。

## 合併前驗收

1. `uv run pytest -q` 全數通過。
2. `tests/corpus/commands_320.csv` 四方法評估可重現，Guarded Hybrid 不退步。
3. Isaac Sim 語意整合測試維持 60/60，並人工確認 `/skills`、ROS 2 教學問答與 `/twin`。
4. 四個 PR 依序合併；不得單獨將後層 PR 合併到 `main`。
