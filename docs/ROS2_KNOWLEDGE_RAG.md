# ROS 2 知識 RAG

AutoCtrl 內建一個唯讀的 ROS 2 教學回答路徑。它讓展示者可直接詢問：

- 「ROS 2 的 topic、service、action 差在哪？」
- 「QoS 是什麼？為什麼 topic 收不到？」
- 「ROS_DOMAIN_ID 有什麼用途？」
- 「Isaac Sim 的 odom 怎麼接 ROS 2？」
- 「Zenoh bridge 的 namespace 在做什麼？」

## 路由順序

```text
使用者輸入（先保留完整句意）
  ├─ 句首明確停止命令 → 立即停止（例如「先停止，再解釋 ROS2」）
  ├─ 明確 ROS 2 教學問題 → 本地檢索 → 唯讀文字回答
  ├─ 多步動作 → 逐段驗證；非最後一步必須有距離、角度或時間
  ├─ 既有移動／停止 fast path → MotionIntent
  ├─ 即時狀態 fast path → StatusQuery
  └─ 其他內容 → Ollama tool selection／一般對話
```

因此「目前有哪些 ROS topics？」仍查詢即時 ROS graph；「topic 是什麼？」才會讀取
教學知識。RAG 回傳 `ConversationReply(source="ros2_rag")`，payload 不包含 tools，
不能產生 `MotionIntent`、發布 `/cmd_vel` 或連鎖呼叫 Skill。

## 知識範圍與來源

目前包含 15 個具來源 URL 的短知識片段：node 與 graph、topic/service/action、
parameter、QoS、discovery 與 Domain ID、namespace/remapping、Twist/cmd_vel、
Odometry、tf2、CLI introspection、launch、rosbag2、Zenoh ROS2DDS bridge，以及
Isaac Sim ROS 2 Bridge 與 TF/Odometry。來源限定 ROS 2 Jazzy 官方文件、NVIDIA
Isaac Sim 官方文件及 Eclipse Zenoh 官方 repository。

## 實作與限制

- 檢索完全在本機，以中英文關鍵詞與文字片段分數排序，不需要 embedding API。
- Ollama 僅依前 3 個相關片段作答，回答後由程式附上實際來源 URL。
- 知識是隨版本提交的快照，不會自動上網更新；升級 ROS 2、Isaac Sim 或 Zenoh 時應人工複核。
- 目前不是向量語意搜尋；對非常隱晦、沒有 ROS 2 概念詞的問題可能回到一般對話。
- 這是教學輔助，不取代官方文件、底盤手冊或安全操作程序。

教學句會在拆分序列及擷取動作詞之前判斷，例如「如何前進然後停止 ROS2 小車？」
只會回答教學內容。知識不足時明確告知，不退回可呼叫工具的路徑。
「停」與「stop」仍使用確定性停止路徑。
