# 虛實同動模式

AutoCtrl 可在同一個自然語言控制迴路中，同時驅動 WHEELTEC 實車與 Isaac Sim 虛擬車。使用者仍只需執行：

```bash
autoctrl
```

## Topic 隔離

實車與模擬器不可共用 odom topic，否則兩個 publisher 的資料會混在同一個回授來源。建議配置為：

```text
AutoCtrl
├─ /small/cmd_vel → WHEELTEC → /small/odom
└─ /sim/cmd_vel   → Isaac Sim → /sim/odom
```

Isaac Sim 的 ROS 2 Context 使用 Domain 2；`/ROS2/Robots` 的 `isaac:namespace` 設為 `sim`。Ackermann subscriber 使用 `ackermann_cmd`，odometry publisher 使用 `odom`，讓 namespace 將它們解析成 `/sim/ackermann_cmd` 與 `/sim/odom`。

## 一鍵啟動行為

`autoctrl` 會照常啟動或檢查實車 Zenoh 通訊，並立即準備 `/sim` 虛實通道，不等待 Isaac Sim discovery。Isaac Sim 可在 AutoCtrl 啟動前或啟動後按下 Play，DDS 端點出現後會自動接通。啟動器會：

1. 載入 Isaac ROS workspace。
2. 啟動或沿用 `cmdvel_to_ackermann`。
3. 將每一筆 Twist 同時發布到 `/small/cmd_vel` 與 `/sim/cmd_vel`。
4. 訂閱兩邊 odom，計算每次命令開始後的相對位移差與朝向差。
5. AutoCtrl 離開時送出零速度，並只清理自己啟動的轉換器。

Isaac Sim 未開啟時，CLI 仍會立即啟動；此時 `/twin` 顯示資料未就緒，待模擬器上線後即可取得資料。預設模式與 `on` 都會準備虛實通道，只有 `off` 會停用：

```bash
AUTOCTRL_TWIN_MODE=on autoctrl
AUTOCTRL_TWIN_MODE=off autoctrl
```

## CLI 遙測

每次非停止動作開始時，系統會把實車與模擬器的當前 pose 設為各自基準。輸入：

```text
/twin
```

可查看實車位移、模擬位移、位移差與朝向差。`/twin` 只讀取目前遙測，不會開啟、關閉或改變 Twin 模式。這些數值是兩個 odom frame 內的相對運動比較，不代表兩邊共享同一個絕對世界座標。

此功能可描述為 command-level virtual–physical co-motion。若要主張高精度 digital twin synchronization，仍須執行固定路徑的重複試驗並報告誤差分布、延遲與失敗案例。


## 自動化整合評估

以固定雙語語料自動發布自然語言、比對 `/sim/cmd_vel` 並由 `/sim/odom` 判定動作方向與延遲的程序，請參閱 [Isaac Sim 語意到動作整合評估](ISAAC_EVALUATION.md)。評估器預設只驅動模擬器；必須明確加入 `--with-real` 才會控制實車。
