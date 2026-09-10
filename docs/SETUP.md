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
- 小車 namespace：預設 `/small`，可依實際 ROS2／Zenoh 部署調整

## 第一次設定

### curl 一鍵安裝

在已具備 ROS2 Jazzy 的 DGX Spark 上，可用下列指令下載專案、建立 uv 隔離環境，
並在 `~/.local/bin/autoctrl` 建立啟動指令：

```bash
curl -fsSL https://raw.githubusercontent.com/rennn0223/autoctrl/main/install.sh | bash
```

這個安裝器不會自動安裝或修改 ROS2、Docker、Zenoh bridge 與 Ollama 系統服務；
它只安裝 uv（尚未存在時）、AutoCtrl 專案環境與使用者層級啟動連結。

> **重要：一鍵安裝不包含機器人通訊設定。** 使用者必須自行準備 DGX 與機器人
> 兩端的 ROS2 環境及 Zenoh bridge，並確認 ROS domain、Zenoh endpoint／routing、
> topic allow list、namespace 與訊息型別一致。namespace 不必是 `/small`；它只是
> AutoCtrl 的預設值，改用其他 namespace 時也必須同步修改 bridge 規則與
> `robot_namespace` 參數。

因為 `curl | bash` 會直接執行遠端程式碼，正式環境可先下載並檢查內容：

```bash
curl -fsSL https://raw.githubusercontent.com/rennn0223/autoctrl/main/install.sh \
  -o /tmp/autoctrl-install.sh
less /tmp/autoctrl-install.sh
bash /tmp/autoctrl-install.sh
```

可用環境變數調整安裝位置或 ROS2 setup：

```bash
curl -fsSL https://raw.githubusercontent.com/rennn0223/autoctrl/main/install.sh | \
  AUTOCTRL_INSTALL_DIR=/home/nvidia/autoctrl \
  AUTOCTRL_ROS_SETUP=/opt/ros/jazzy/setup.bash bash
```

### 手動設定

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

DGX 快速啟動會以靜默方式確認 loopback multicast、重啟 DGX Zenoh bridge、
載入 ROS2 Jazzy、重整 ROS discovery、同步 uv 環境並進入 AutoCtrl CLI。
啟動時不等待小車 topics，因此小車尚未開啟或部分狀態缺失時仍可使用 CLI。

AutoCtrl 進入聊天介面後會自動執行一次 `/doctor`。全部通過時不顯示額外訊息；
只有失敗項目會列出，而且不會關閉程式。任何時候都能手動輸入 `/doctor` 重新檢查。
一般啟動不再顯示逐步狀態；完整紀錄保存在 `/tmp/autoctrl-startup.log`。
除錯時可要求在終端保留完整輸出：

```bash
autoctrl --verbose
```

`clear` 只清除目前終端畫面，不會停止 Zenoh、ROS2 或小車 driver。

若 Zenoh bridge 已經就緒，可略過 bridge 重啟並直接啟動 AutoCtrl：

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
- `/exit`：發布零速度、停止小車並離開 CLI。
- `Ctrl-C`：發布零速度、停止小車並退出 CLI，不需再按 Enter。

輸入 `/` 會顯示 slash 指令選單：選單開啟時以方向鍵上、下選擇，按 Enter
執行；沒有開啟選單時，方向鍵上、下會瀏覽本次執行期間的歷史命令。

系統檢查：

```text
/doctor
```

`/doctor` 只檢查三項：ROS2 環境是否已 source、DGX 的 `zenoh-bridge`
Docker 容器是否為 `running`（若有 healthcheck 也必須為 `healthy`），以及本地
Ollama 模型是否能回應。小車 driver、`/small/*` topics、odom 與電池資料都不影響
Doctor 成敗；任何檢查失敗也不會阻止 CLI 開啟。

`/doctor` 的 Zenoh 項目只確認 **DGX 本機 `zenoh-bridge` 容器狀態**，不代表
DGX 到機器人的端到端路由或 topics 已經打通。展場控制前仍必須另外執行：

```bash
ros2 topic list
ros2 topic info /small/cmd_vel --verbose
```

使用其他 namespace 時，將 `/small/cmd_vel` 換成實際控制 topic。

唯讀狀態查詢：

```text
現在有哪些 ROS2 topics？
小車現在在哪裡？
目前電壓多少？
```

- topics 查詢只列出目前 ROS graph 中可見的 `<robot_namespace>/*` 名稱與訊息型別。
- 位置預設來自 `/small/odom`，是相對於 odom 起點的座標，不是地圖絕對位置。
- 電池資料預設來自 `/small/PowerVoltage`；未建立校正曲線前只顯示伏特，不推測百分比。
- 狀態查詢不會建立 MotionIntent，也不會發布非零速度。
- 同一句若同時要求移動與查詢會被拒絕；明確停止命令仍維持最高優先權。

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
| 電池電壓輸入 | `/small/PowerVoltage` | `std_msgs/msg/Float32` |

上表只是預設值。若車輛使用 `/robot_a`、`/amr` 或其他 namespace，不需要改原始碼；
啟動時指定 `robot_namespace` 即可。Zenoh bridge 必須允許相同 namespace 的 topics，
且底盤控制 topic 仍須為 `geometry_msgs/msg/Twist`。`odom` 是指定距離／角度及位置
查詢所需資料，`PowerVoltage` 則只影響電壓查詢。

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
  -p robot_namespace:=/robot_a \
  -p linear_speed_mps:=0.30 \
  -p turn_linear_speed_mps:=0.30 \
  -p angular_speed_rps:=0.50
```

若 Zenoh bridge 暫時沒有 namespace，可測試本機 `/cmd_vel` 與 `/odom`：

```bash
./scripts/autoctrl-ros --ros-args -p robot_namespace:=/
```

### 限制提供給 LLM 的 Skill

預設會提供全部內建 Skill。若展示情境只允許唯讀查詢，可用逗號分隔的允許清單；
`stop_vehicle` 為必要能力，無論清單內容都會保留：

```bash
AUTOCTRL_LLM_SKILLS=query_ros_topics,query_robot_pose,query_battery_voltage,query_twin_status autoctrl
```

ROS 2 節點也可使用 `llm_enabled_skills` 參數。這個設定只限制 LLM fallback
能選擇的能力，不會停用確定性 fast path，也不是速度限制或緊急停止安全層。

## 可調整的環境變數

| 變數 | 預設值 | 用途 |
|---|---|---|
| `AUTOCTRL_ROS_SETUP` | `/opt/ros/jazzy/setup.bash` | ROS2 環境檔 |
| `AUTOCTRL_LOCAL_ZENOH_DIR` | `/opt/zenoh-bridge` | DGX Zenoh bridge 目錄 |
| `AUTOCTRL_STARTUP_LOG` | `/tmp/autoctrl-startup.log` | 靜默啟動的完整紀錄 |
| `AUTOCTRL_LLM_SKILLS` | `*` | 提供給 LLM 的內建 Skill 允許清單 |
| `ROS_DOMAIN_ID` | `2` | ROS2 domain |
| `ROS_AUTOMATIC_DISCOVERY_RANGE` | `LOCALHOST` | DDS discovery 範圍 |

## 測試

完整測試不會對 `/small/cmd_vel` 發布移動指令；Ctrl-C 整合測試使用隔離 namespace：

```bash
set +u
source /opt/ros/jazzy/setup.bash
set -u
uv run --with pytest pytest -q
```

目前版本應通過 58 項測試與 4 個 subtests。論文用 parser-only 評估另見 `evals/README.md`；它不會載入 ROS 或發布 `/cmd_vel`。

## 疑難排解

### 找不到 ROS2 Python 環境

請透過專案腳本啟動，或先執行：

```bash
./scripts/bootstrap
```

### `/doctor` 顯示 ROS2、Zenoh bridge 或本地模型檢查失敗

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
