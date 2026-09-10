# AutoCtrl Skill 平台設計與驗收規格

本文件是四個堆疊式 PR 的共同規格。目標是在不改變既有控制器與 Guarded Hybrid 行為的前提下，讓 AutoCtrl 能管理、篩選及擴充 LLM 可呼叫的能力，並加入唯讀的 ROS 2 知識檢索。

## 不可破壞的行為

- 先辨識整句教學意圖，避免提到動作的問題變成控制；其餘命令保留確定性移動、明確停止及即時狀態路徑。
- LLM 只能選擇 Registry 公開的 Skill，不能透過工具參數指定任意 ROS topic 或自行產生底盤速度。
- 「讓小車移動一下」「Make the robot move a bit」等簡短無方向命令會在 LLM 前被拒絕，連續命令也逐段檢查；這是特定句型防護，不宣稱涵蓋所有模糊自然語言。
- 所有移動仍轉成既有 `MotionIntent` / `MotionSequence`，由既有 ROS 2 控制器執行。
- `stop_vehicle` 必須持續可用，且不被一般能力開關移除。
- ROS 2 知識 RAG 只能產生文字回答，不得發布速度或觸發其他 Skill。
- 外部 Skill 必須由使用者明確允許；未允許的已安裝套件不載入。允許同程序 provider 等同授予其 Python 程式碼執行權限，allowlist 不構成沙箱。
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
- 回答必須以取回的內容為依據並標示來源；知識不足時回覆缺少資料，不交給可呼叫工具的路徑。
- RAG 路徑回傳 `ConversationReply`，不得產生可執行命令。

## 合併前驗收

1. `uv run pytest -q` 全數通過。
2. `tests/corpus/commands_320.csv` 四方法評估可重現，Guarded Hybrid 不退步。
3. Isaac Sim 語意整合測試維持 60/60，並人工確認 `/skills`、ROS 2 教學問答與 `/twin`。
4. 四個 PR 依序合併；不得單獨將後層 PR 合併到 `main`。

## 產品入口驗收

`uv run pytest tests/test_product_acceptance.py -q` 覆蓋完整序列＋Hybrid＋RAG 入口、
教學中提及動作、即時狀態、外掛例外恢復、schema 邊界、長文字顯示與里程計新鮮度。
ROS 環境下另執行 `tests/test_ros_recovery.py`；測試使用獨立 namespace，並攔截速度輸出。
原 320 句仍屬 parser benchmark，不代表新增 RAG 與外掛功能的完整驗收。
