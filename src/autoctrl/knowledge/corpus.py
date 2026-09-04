from __future__ import annotations


ROS2_KNOWLEDGE = (
    {
        "id": "ROS2-NODES",
        "title": "Node 與 ROS graph",
        "keywords": ("node", "nodes", "節點", "ros graph", "ros圖"),
        "content": (
            "ROS 2 node 是 ROS graph 中的運算參與者，通常各自負責一項邏輯工作。"
            "Node 可同時建立 publisher、subscriber、service、action 與 parameter；"
            "不同程序或不同電腦上的 node 透過 discovery 找到彼此。"
        ),
        "source_url": "https://docs.ros.org/en/ros2_documentation/jazzy/Concepts/Basic/About-Nodes.html",
    },
    {
        "id": "ROS2-INTERFACES",
        "title": "Topic、Service 與 Action 的選擇",
        "keywords": ("topic", "service", "action", "主題", "服務", "動作", "介面"),
        "content": (
            "Topic 是非同步 publish/subscribe，適合感測器或狀態等連續資料流；"
            "Service 是短時間的同步 request/response；Action 適合長時間任務，"
            "能回報 feedback、傳回 result，也能取消。"
        ),
        "source_url": "https://docs.ros.org/en/jazzy/How-To-Guides/Topics-Services-Actions.html",
    },
    {
        "id": "ROS2-PARAMETERS",
        "title": "Node parameters",
        "keywords": ("parameter", "parameters", "param", "參數", "設定"),
        "content": (
            "ROS 2 parameter 隸屬特定 node，用來在啟動或執行期間調整設定，"
            "不必修改程式碼。Node 預設需先宣告可接受的 parameter；"
            "可用 ros2 param 或 --ros-args -p name:=value 操作。"
        ),
        "source_url": "https://docs.ros.org/en/ros2_documentation/jazzy/Concepts/Basic/About-Parameters.html",
    },
    {
        "id": "ROS2-QOS",
        "title": "Quality of Service（QoS）",
        "keywords": ("qos", "quality of service", "reliable", "best effort", "可靠性", "收不到"),
        "content": (
            "QoS profile 由 history、depth、reliability、durability 等 policy 組成。"
            "Publisher 與 subscription 的 QoS 必須相容才會傳資料。感測器常用 best effort"
            " 以換取即時性；需要補送給晚加入訂閱者時才考慮 transient local。"
        ),
        "source_url": "https://docs.ros.org/en/ros2_documentation/jazzy/Concepts/Intermediate/About-Quality-of-Service-Settings.html",
    },
    {
        "id": "ROS2-DISCOVERY",
        "title": "Discovery 與 ROS_DOMAIN_ID",
        "keywords": ("discovery", "domain id", "ros_domain_id", "dds", "發現", "網域"),
        "content": (
            "ROS 2 的 DDS discovery 讓同一 logical domain 的 node 自動找到彼此。"
            "ROS_DOMAIN_ID 可在同一實體網路上隔離不同 ROS 2 系統；兩端 domain 不同時"
            "通常無法互相發現。它是通訊分區，不是存取控制或安全驗證。"
        ),
        "source_url": "https://docs.ros.org/en/ros2_documentation/jazzy/Concepts/Intermediate/About-Domain-ID.html",
    },
    {
        "id": "ROS2-NAMES",
        "title": "Namespace、名稱解析與 remapping",
        "keywords": ("namespace", "remap", "remapping", "命名空間", "重新映射"),
        "content": (
            "Namespace 會組成 node、topic 與 service 的完整名稱，常用來區分多台機器人。"
            "Remapping 可在 node 啟動時改變名稱，例如以 __ns 設 node namespace，"
            "或把原 topic 名稱映射到另一名稱；一般是程序生命週期內的靜態設定。"
        ),
        "source_url": "https://docs.ros.org/en/ros2_documentation/jazzy/How-To-Guides/Node-arguments.html",
    },
    {
        "id": "ROS2-TWIST",
        "title": "geometry_msgs/msg/Twist 與 cmd_vel",
        "keywords": ("twist", "cmd_vel", "速度命令", "linear.x", "angular.z"),
        "content": (
            "geometry_msgs/msg/Twist 用 linear 與 angular 兩個 Vector3 表示自由空間中的"
            "線速度與角速度。移動底盤常在 cmd_vel 接收 Twist；平面車常用 linear.x"
            " 表示前後速度、angular.z 表示偏航角速度，但最終語意仍由底盤驅動定義。"
        ),
        "source_url": "https://docs.ros.org/en/jazzy/p/geometry_msgs/msg/Twist.html",
    },
    {
        "id": "ROS2-ODOMETRY",
        "title": "nav_msgs/msg/Odometry",
        "keywords": ("odom", "odometry", "里程計", "位姿", "pose", "twist covariance"),
        "content": (
            "nav_msgs/msg/Odometry 是位置與速度的估計，不等同絕對真值。Pose 以"
            " header.frame_id 指定的座標系表示，twist 以 child_frame_id 指定的座標系表示，"
            "並各自附 covariance 描述不確定性。"
        ),
        "source_url": "https://docs.ros.org/en/jazzy/p/nav_msgs/msg/Odometry.html",
    },
    {
        "id": "ROS2-TF2",
        "title": "tf2 座標轉換樹",
        "keywords": ("tf2", "/tf", "tf_static", "frame", "座標系", "轉換樹"),
        "content": (
            "tf2 會隨時間保存多個 coordinate frame 的樹狀關係，讓程式查詢特定時間點"
            "兩個 frame 之間的轉換。動態 transform 通常持續發布；不變的 transform"
            "可用 static broadcaster，接收端會快取靜態關係。"
        ),
        "source_url": "https://docs.ros.org/en/ros2_documentation/jazzy/Concepts/Intermediate/About-Tf2.html",
    },
    {
        "id": "ROS2-CLI",
        "title": "ROS 2 CLI introspection",
        "keywords": ("ros2 topic list", "ros2 node list", "ros2 topic info", "cli", "診斷", "查看topic"),
        "content": (
            "ros2 node list、ros2 topic list、ros2 service list 與 ros2 action list 可檢查"
            "目前 graph；ros2 topic info -v 可看 publisher、subscription、型別與 QoS。"
            "看得到名稱但收不到資料時，應再確認型別、QoS、domain 與 namespace。"
        ),
        "source_url": "https://docs.ros.org/en/jazzy/Tutorials/Beginner-CLI-Tools.html",
    },
    {
        "id": "ROS2-LAUNCH",
        "title": "Launch 與系統啟動",
        "keywords": ("launch", "launch file", "啟動檔", "ros2 launch"),
        "content": (
            "ROS 2 launch 可一次描述與啟動多個 node，並集中設定 arguments、parameters、"
            "namespace、remapping 與啟動條件。大型系統通常把可重用的 launch description"
            "分層組合，而不是依賴多個手動終端。"
        ),
        "source_url": "https://docs.ros.org/en/ros2_documentation/jazzy/Tutorials/Intermediate/Launch/Launch-Main.html",
    },
    {
        "id": "ROS2-ROSBAG",
        "title": "rosbag2 記錄與重播",
        "keywords": ("rosbag", "rosbag2", "bag", "錄製", "重播", "record", "play"),
        "content": (
            "rosbag2 可記錄 ROS 2 topics 並在之後重播，適合除錯、重現問題與離線分析。"
            "Bag 保存的是收到的 topic 訊息；重播前仍要確認訊息型別、QoS 與時間來源是否"
            "符合下游 node 的期待。"
        ),
        "source_url": "https://docs.ros.org/en/jazzy/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data.html",
    },
    {
        "id": "ZENOH-ROS2DDS",
        "title": "Zenoh bridge for ROS 2 DDS",
        "keywords": ("zenoh", "ros2dds", "bridge", "橋接", "多機器人"),
        "content": (
            "zenoh-bridge-ros2dds 在本地 DDS 與 Zenoh 之間建立 ROS 2 interface 路由。"
            "Bridge 的 namespace 可替跨網路的 topic、service、action 加前綴，方便多機器人"
            "隔離；domain 與 allow/deny route 設定仍須在兩端正確配置。"
        ),
        "source_url": "https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds",
    },
    {
        "id": "ISAAC-ROS2-BRIDGE",
        "title": "Isaac Sim ROS 2 Bridge",
        "keywords": ("isaac sim", "isaac", "omnigraph", "ros 2 bridge", "模擬器", "simulation"),
        "content": (
            "Isaac Sim ROS 2 Bridge 讓 OmniGraph publisher、subscriber 與 service node 和"
            "外部 ROS 2 系統交換資料。ROS 2 環境需在啟動 Isaac Sim 前準備，且 publisher"
            "與 subscriber 通常只在模擬播放時工作。"
        ),
        "source_url": "https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.ros2.bridge/docs/index.html",
    },
    {
        "id": "ISAAC-TF-ODOM",
        "title": "Isaac Sim 的 TF、Odometry 與 namespace",
        "keywords": ("isaac odom", "isaac tf", "isaac namespace", "simulation odometry", "模擬里程計"),
        "content": (
            "Isaac Sim 可用 ROS 2 OmniGraph 發布 /tf、/tf_static 與 Odometry。Odometry graph"
            "需要指定 articulation root 與 chassis prim；node namespace 會前置到發布或訂閱的"
            "topic 名稱，必須與外部 ROS 2 node 的預期一致。"
        ),
        "source_url": "https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_ros2_tf.html",
    },
)
