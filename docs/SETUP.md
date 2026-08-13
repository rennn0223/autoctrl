# AutoCtrl 設定與操作手冊

本文件包含 Automation 2026（自動化展）展示環境的安裝、啟動、參數與測試方式。產品介紹請回到 [README](../README.md)。

## 展示環境

- 運算主機：NVIDIA DGX Spark
- 車體：WHEELTEC 小車
- DGX ROS2：Jazzy，預設 `/opt/ros/jazzy/setup.bash`
- Python：3.12，由 uv 管理隔離環境
- 本地模型：Ollama `qwen3.6:35b`
- ROS domain：`2`
- Zenoh bridge：DGX 與小車皆位於 `/opt/zenoh-bridge`
- 小車 namespace：`/small`

## 第一次設定

在 DGX Spark 進入專案並建立 uv 隔離環境：

```bash
cd /home/nvidia/autoctrl
./scripts/bootstrap
```

腳本會先載入 ROS2 Jazzy，再建立使用 system site packages 的 Python 3.12 `.venv` 並執行 `uv sync`。這讓 uv 管理的套件可以與 ROS2 的 `rclpy` 共存。

若 ROS2 安裝位置不同：

```bash
AUTOCTRL_ROS_SETUP=/path/to/setup.bash ./scripts/bootstrap
```

確認 Ollama 模型：

```bash
ollama list
```

預載模型：

```bash
./scripts/autoctrl --warmup
```

## 小車端準備

DGX 的快速啟動指令不會 SSH 到小車。執行 `autoctrl` 前，請先在小車端啟動：

1. Zenoh bridge
2. WHEELTEC 底盤 driver

如果小車已安裝先前建立的快速指令：

```bash
carctrl
```

手動啟動時使用相同 ROS domain 與 discovery 設定：

```bash
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_DOMAIN_ID=2
sudo ip link set lo multicast on

cd /opt/zenoh-bridge
sudo docker compose down
sudo docker compose up -d

set +u
source /opt/ros/humble/setup.bash
source ~/wheeltec_ros2/install/setup.bash
set -u
ros2 launch turn_on_wheeltec_robot turn_on_wheeltec_robot.launch.py
```

底盤 driver 所在終端需保持執行。

## DGX 一鍵啟動

小車端就緒後，在 DGX Spark 執行：

```bash
cd /home/nvidia/autoctrl
./scripts/start-dgx
```

若已安裝全域快速指令，直接執行：

```bash
autoctrl
```

DGX 快速啟動會依序：

1. 確認 loopback multicast；已啟用時不要求 `sudo` 密碼。
2. 使用目前帳號的 Docker 群組權限重啟 DGX Zenoh bridge。
3. 載入 ROS2 Jazzy 並重整 ROS discovery。
4. 等待 `/small/cmd_vel` 與 `/small/odom`，預設最多 30 秒。
5. 建立或同步 uv 環境並啟動 AutoCtrl CLI。

若 Zenoh bridge 已經就緒，只檢查 topics 並啟動 AutoCtrl：

```bash
./scripts/start-dgx --skip-bridges
```

## 展場操作

建議依序輸入：

```text
停 → 往前 → 停 → 後退 → 停 → 左轉 → 停 → 右轉 → 停
```

常用英文也會走確定性快速路徑：

```text
stop
go forward
go backward
go left
go right
```

- `停` 或 `stop`：只停止小車，CLI 保持開啟。
- `Ctrl-C`：發布零速度、停止小車並退出 CLI，不需再按 Enter。

## 單獨使用文字解析器

此入口只解析命令，不發布 ROS2 速度：

```bash
./scripts/autoctrl "前進五十公分"
./scripts/autoctrl "往前走"
./scripts/autoctrl "左轉九十度"
./scripts/autoctrl "go right"
./scripts/autoctrl "停"
```

沒有帶命令時會進入純解析互動模式：

```bash
./scripts/autoctrl
```

## 單獨啟動 ROS2 控制節點

不重啟 Zenoh bridge，直接啟動控制節點：

```bash
./scripts/autoctrl-ros
```

預設介面：

| 用途 | Topic | 訊息型別 |
|---|---|---|
| 自然語言命令輸入 | `/autoctrl/command` | `std_msgs/msg/String` |
| AutoCtrl 狀態輸出 | `/autoctrl/status` | `std_msgs/msg/String`（JSON） |
| 車速輸出 | `/small/cmd_vel` | `geometry_msgs/msg/Twist` |
| 里程計輸入 | `/small/odom` | `nav_msgs/msg/Odometry` |

從另一個 ROS2 終端送命令：

```bash
source /opt/ros/jazzy/setup.bash
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_DOMAIN_ID=2

ros2 topic pub --once /autoctrl/command std_msgs/msg/String "{data: '往前走'}"
ros2 topic pub --once /autoctrl/command std_msgs/msg/String "{data: '停'}"
```

## ROS2 參數

調整直行速度、轉彎線速度與轉彎角速度：

```bash
./scripts/start-dgx -- --ros-args \
  -p linear_speed_mps:=0.30 \
  -p turn_linear_speed_mps:=0.30 \
  -p angular_speed_rps:=0.50
```

直接啟動節點時也可以指定 namespace：

```bash
./scripts/autoctrl-ros --ros-args \
  -p robot_namespace:=/small \
  -p linear_speed_mps:=0.30 \
  -p turn_linear_speed_mps:=0.30 \
  -p angular_speed_rps:=0.50
```

若 Zenoh bridge 暫時沒有 namespace，可測試本機 `/cmd_vel` 與 `/odom`：

```bash
./scripts/autoctrl-ros --ros-args -p robot_namespace:=/
```

## 可調整的環境變數

| 變數 | 預設值 | 用途 |
|---|---|---|
| `AUTOCTRL_ROS_SETUP` | `/opt/ros/jazzy/setup.bash` | ROS2 環境檔 |
| `AUTOCTRL_LOCAL_ZENOH_DIR` | `/opt/zenoh-bridge` | DGX Zenoh bridge 目錄 |
| `AUTOCTRL_TOPIC_WAIT_SECONDS` | `30` | 等待 ROS2 topics 的秒數 |
| `ROS_DOMAIN_ID` | `2` | ROS2 domain |
| `ROS_AUTOMATIC_DISCOVERY_RANGE` | `LOCALHOST` | DDS discovery 範圍 |

## 測試

完整測試不會對 `/small/cmd_vel` 發布移動指令；Ctrl-C 整合測試使用隔離 namespace：

```bash
set +u
source /opt/ros/jazzy/setup.bash
set -u
uv run python -m unittest discover -s tests -v
```

目前鎖定版本應通過 23 項測試。

## 疑難排解

### 找不到 ROS2 Python 環境

請透過專案腳本啟動，或先執行：

```bash
./scripts/bootstrap
```

### 等不到 `/small/cmd_vel` 或 `/small/odom`

確認 DGX Zenoh bridge：

```bash
cd /opt/zenoh-bridge
docker compose ps
docker compose logs --tail=100
```

確認 ROS2：

```bash
source /opt/ros/jazzy/setup.bash
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_DOMAIN_ID=2
ros2 topic list | grep '^/small/'
```

並確認小車端的 Zenoh bridge 與 WHEELTEC 底盤 driver 仍在執行。
