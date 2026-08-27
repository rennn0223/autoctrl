# Guarded Hybrid 設計規格

本文件描述目前程式實際實作的 Guarded Hybrid 路由。它是研究 artifact 的可讀規格；若本文與程式不一致，以 release tag 所指向的程式為準。

## 輸出邊界

文字解析只能產生三種型別：

- `MotionIntent`：直線移動、阿克曼弧線轉向或停止。
- `StatusQuery`：ROS topics、odom 相對位置或電池電壓查詢。
- `ConversationReply`：不呼叫工具的一般回覆。

LLM 不匯入 ROS，也不能直接建立或發布 `geometry_msgs/Twist`。ROS node 只在收到經型別驗證的 `MotionIntent` 後，才由固定程式產生速度訊息。

## 路由流程

```text
motion_candidate = guarded_motion(text)

if motion_candidate is explicit STOP and text is not a pose question:
    return STOP

status_candidate = guarded_status(text)

if motion_candidate and status_candidate:
    reject mixed motion/status request

if status_candidate:
    return status_candidate

if motion_candidate:
    return motion_candidate

return constrained_local_llm(text)
```

明確 stop 的優先權只發生在該句文字進入 interpreter 後；同步 CLI 無法用下一句文字搶占已在執行的 LLM request，因此它不是 emergency-stop 機制。

## Motion fast-path guards

| 條件 | 行為 |
|---|---|
| 空白輸入 | 不產生 candidate |
| 否定 stop，例如「不要停」或 `do not stop` | 延後交給 LLM |
| 否定移動，例如「不要前進」或 `do not move` | 保守產生 stop |
| 英文或中文問句提示 | 延後交給 LLM |
| 同一句出現多個方向提示 | 延後交給 LLM |
| 出現速度單位 | 延後交給 LLM |
| 有距離單位但規則未成功解析距離 | 延後交給 LLM |
| 有角度單位但規則未成功解析角度 | 延後交給 LLM |
| 恰有一個方向且可完整解析 | 接受 deterministic candidate |

## Status fast path

Guarded status path 只支援：

- ROS topics
- robot pose／position／heading
- battery voltage

同一句匹配多種 status query 時會拒絕。若 motion 與 status 同時匹配，也會拒絕並要求拆成兩句。

## 數值與執行限制

`MotionIntent` 會檢查距離、角度與速度為正值，並檢查動作種類與方向欄位一致。ROS 執行層預設使用 0.30 m/s 線速度與 0.50 rad/s 角速度；這些是預設控制參數，不應被描述為 parser guard 的硬性上限。正式部署仍需要獨立速度限制、deadman timeout、安全監督器與硬體急停。

## 評估解讀

`hybrid-v0` 使用未防護的 motion/status fast paths；`guarded-hybrid` 使用上述完整 production router。因此兩者是 bundled routing comparison，不是每一條 guard 的獨立消融。個別 guard 的因果貢獻需要另行 ablation。
