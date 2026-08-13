# AutoCtrl

**Automation 2026（自動化展）展示專用**的獨立自然語言 ROS2 小車控制器。

AutoCtrl 在 NVIDIA DGX Spark 上執行，透過 ROS2 與 Zenoh bridge 控制 WHEELTEC 小車；專案不依賴 JenAI，未來可由 JenAI 透過 `/autoctrl/command` 或 Python 介面呼叫。

![AutoCtrl PixPet](assets/pixpet-dachshund.png)

> 展示版本已鎖定功能與 CLI。展場操作前仍應先架高車輪或確保周圍淨空，再依序測試停止、前進、後退與轉向。

## 目前功能

- 繁體中文與常用英文的前進、後退、左轉、右轉、停止
- 前後未指定距離時持續移動，直到收到停止命令
- 阿克曼轉向：左右會同時前進並轉彎；未指定角度時持續到收到停止命令
- 常見命令走本機快速解析，其他自然語言交給 `qwen3.6:35b`
- 根據 `/small/odom` 完成指定距離與角度
- 發布 `/small/cmd_vel`
- ROS namespace、topic、直行速度及阿克曼轉向速度皆可透過 ROS2 parameters 修改
- Codex 風格繁體中文 CLI 與高保真 PixPet 啟動畫面
- 單按 `Ctrl-C` 發布零速度並安全退出，不需再按 Enter

安全 topic 的整合與展場限制會在確認實際訊息型別後加入。目前程式結束時一定會發布零速度，
而無法解析的命令不會產生運動。

## 建立隔離環境

啟動腳本會先載入 `/opt/ros/jazzy/setup.bash`，再進入 uv 管理的 `.venv`：

```bash
./scripts/bootstrap
```

若 ROS2 安裝位置不同：

```bash
AUTOCTRL_ROS_SETUP=/path/to/setup.bash ./scripts/bootstrap
```

## 先測試中文解析

```bash
./scripts/autoctrl "前進五十公分"
./scripts/autoctrl "往前走"
./scripts/autoctrl "左轉九十度"
./scripts/autoctrl "停"
```

預載 Ollama 模型：

```bash
./scripts/autoctrl --warmup
```

沒有帶命令時會進入互動模式。

## 啟動 ROS2 控制節點

### 展場一鍵啟動（建議）

在 Automation 2026 展場的 DGX Spark 執行：

```bash
cd /home/nvidia/autoctrl
./scripts/start-dgx
```

若已安裝全域快速指令，也可以直接執行：

```bash
autoctrl
```

這個指令只處理 DGX Spark，會依序：

1. 確認 loopback multicast；正常情況不需輸入 `sudo` 密碼。
2. 使用目前帳號的 Docker 群組權限重啟 DGX `/opt/zenoh-bridge`。
3. 載入 ROS2 Jazzy 並重啟 ROS daemon。
4. 等待 `/small/cmd_vel` 與 `/small/odom` 出現。
5. 啟動 AutoCtrl 互動介面。

小車端的 Zenoh bridge 與 WHEELTEC 底盤 driver 需事先啟動。DGX 啟動流程本身不會讓車移動。

若兩端 bridge 與底盤已經啟動，只想快速進入 AutoCtrl：

```bash
./scripts/start-dgx --skip-bridges
```

調整直行、轉彎線速度與轉彎角速度：

```bash
./scripts/start-dgx -- --ros-args -p linear_speed_mps:=0.30 -p turn_linear_speed_mps:=0.30 -p angular_speed_rps:=0.50
```

### 單獨啟動 AutoCtrl

```bash
./scripts/autoctrl-ros
```

預設介面：

- 中文命令輸入：`/autoctrl/command` (`std_msgs/msg/String`)
- 狀態輸出：`/autoctrl/status` (`std_msgs/msg/String`，JSON)
- 速度輸出：`/small/cmd_vel` (`geometry_msgs/msg/Twist`)
- 里程計輸入：`/small/odom` (`nav_msgs/msg/Odometry`)

也可以直接在節點所在終端輸入中文。從另一個終端送命令：

```bash
source /opt/ros/jazzy/setup.bash
ros2 topic pub --once /autoctrl/command std_msgs/msg/String "{data: '往前走'}"
ros2 topic pub --once /autoctrl/command std_msgs/msg/String "{data: '停'}"
```

修改 namespace 或預設轉向角度：

```bash
./scripts/autoctrl-ros --ros-args \
  -p robot_namespace:=/small \
  -p linear_speed_mps:=0.30 \
  -p turn_linear_speed_mps:=0.30 \
  -p angular_speed_rps:=0.50
```

若 zenoh bridge 暫時沒有 namespace，也能測試本機 `/cmd_vel` 與 `/odom`：

```bash
./scripts/autoctrl-ros --ros-args -p robot_namespace:=/
```

## 測試

```bash
source /opt/ros/jazzy/setup.bash
uv run python -m unittest discover -s tests -v
```
