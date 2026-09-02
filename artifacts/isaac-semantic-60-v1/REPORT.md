# AutoCtrl–Isaac Sim Integration Evaluation

| Group | Trials | Semantic | Command | Odom | Overall |
|---|---:|---:|---:|---:|---:|
| backward | 12 | 100.0% | 100.0% | 100.0% | 100.0% |
| forward | 12 | 100.0% | 100.0% | 100.0% | 100.0% |
| left | 12 | 100.0% | 100.0% | 100.0% | 100.0% |
| right | 12 | 100.0% | 100.0% | 100.0% | 100.0% |
| stop | 12 | 100.0% | 100.0% | 100.0% | 100.0% |
| overall | 60 | 100.0% | 100.0% | 100.0% | 100.0% |

## Endpoint odometry

| Direction | Metric | Mean | SD | Min | Max |
|---|---|---:|---:|---:|---:|
| backward | Longitudinal displacement (m) | -0.2473 | 0.0046 | -0.2549 | -0.2398 |
| forward | Longitudinal displacement (m) | 0.2470 | 0.0045 | 0.2388 | 0.2537 |
| left | Yaw change (deg) | 12.1026 | 0.3914 | 11.3055 | 12.6658 |
| right | Yaw change (deg) | -11.7846 | 0.6543 | -12.8449 | -10.4950 |

## Latency

| Direction | Decision mean / P95 (ms) | Actuation mean / P95 (ms) | Odom response mean / P95 (ms) |
|---|---:|---:|---:|
| backward | 682.4 / 2597.9 | 696.0 / 2645.3 | 1506.9 / 3483.0 |
| forward | 672.2 / 2683.0 | 716.3 / 2720.5 | 1529.0 / 3546.2 |
| left | 39.7 / 104.7 | 81.2 / 142.4 | 1168.1 / 1255.1 |
| right | 33.4 / 109.1 | 69.3 / 152.1 | 1156.6 / 1288.7 |
| stop | 50.2 / 105.8 | — | — |
| overall | 295.6 / 2537.8 | 390.7 / 2645.3 | 1340.2 / 3426.3 |

Stop zero-command latency: mean 97.2 ms, P95 192.2 ms. Stop odometry-settle latency: mean 962.2 ms, P95 1179.5 ms.

Mode: **simulation-only**.
Generated from public ROS 2 interfaces: `/autoctrl/command`, `/autoctrl/status`, `/sim/cmd_vel`, and `/sim/odom`.
