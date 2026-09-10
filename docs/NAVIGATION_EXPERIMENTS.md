# Navigation and vision experiments

Branch: `codex/navigation-vlm-experiments`. These are opt-in experiment entry points;
ordinary natural-language control does not yet dispatch navigation or vision tasks.

## Coordinate navigation in Isaac Sim

Start Isaac Sim and press Play. The experiment consumes `/sim/odom` and publishes
only `/sim/ackermann_cmd` on ROS domain 2. Stop other driving programs first so
there is a single command owner. The default coordinate frame starts at the car's
position and heading when each task begins: +x forward, +y left, metres.

```bash
scripts/test-navigation waypoints --points '[[0.7,0],[1.4,0.3]]' --output results/navigation-vlm/waypoints.json
scripts/test-navigation figure8 --radius 0.8 --output results/navigation-vlm/figure8.json
```

`--frame odom` uses fixed odometry coordinates. For the generated figure eight,
that means its crossing is at the odometry origin; prefer the default relative
frame. `--speed` defaults to 0.3 m/s (maximum 0.4); `--timeout` defaults to 300 wall
clock seconds. Ctrl+C cancels and sends repeated zero-speed commands.

This implementation uses feedback-based ordered target pursuit, with a 0.24 m
steering conversion length matching the installed Isaac converter. Sparse
waypoints are reached within 0.10 m in order, without stopping at each intermediate
point. The eight is two tangent circles, each sampled at 120 points. Dense interior
points use 0.22 m lookahead; the final point uses 0.10 m tolerance. Ordered progress
prevents the shared crossing from skipping a loop. Pose receipt time is used for
freshness because this simulator currently emits zero odometry timestamps.

A stale odometry stream (1 s), changed coordinate frame, deadline, or Ctrl+C aborts
the task and publishes zero speed. These are software checks, not an independent
watchdog: forcibly killing the process can leave the simulator holding its last
command. No map, obstacle avoidance, localization recovery, reversing, or final
heading constraint is implemented. Use a clear simulated area with gentle turns;
unreachable goals can circle until timeout. This is not a Nav2 deployment or a
real-vehicle acceptance test.

## Local VLM snapshot experiment

The installed `qwen3.6:35b` advertises vision support. With an RGB snapshot saved
locally and Ollama running:

```bash
scripts/capture-sim-camera results/navigation-vlm/camera-before.jpg
scripts/test-vision results/navigation-vlm/camera-before.jpg --output results/navigation-vlm/vision.json
```

This command sends the image only to localhost and produces text and a JSON
artifact. It has no ROS publisher or motion tools. Camera `/sim/rgb` provides
1280×720 RGB; `/sim/depth` is also present but not consumed here. A useful next
step is grounding a selected object using calibrated depth and transforming it
to the navigation frame. The snapshot description alone cannot determine metric
goals or certify obstacle clearance.

## Acceptance evidence

Run `uv run pytest -q` for the existing suite plus kinematic navigation tests.
The simulation JSON records every pose, command, ordered target index, final
error, and cancellation reason. The report and plotted trajectories in
`results/navigation-vlm/` capture this branch's actual simulator runs. Results are
ignored by Git; the summary below records the measured outcome for reviewers.

Measured in Isaac Sim on 2026-09-11:

| Task | Outcome | Wall time | Final position error |
| --- | --- | --- | --- |
| Relative waypoints `(0.7, 0)`, `(1.4, 0.3)` | 2/2 reached in order | 17.3 s | 8.3 cm |
| Figure eight, radius 0.8 m | 240/240 path samples reached, both loops | 137.5 s | 8.4 cm |
| Local VLM snapshot | Identified car, cube, cone, grid floor | 9.0 s | Not a metric localization test |

These are single-run measurements on the current scene, not a reliability rate.
The final vehicle heading is unconstrained. The VLM called the yellow part a rear
wing; the snapshot supports coarse object recognition but not detailed component
accuracy. Natural-language object-goal navigation is not connected yet.

Final checks: **185 tests passed**. Simulator fault injection stopped delivering
odometry to the controller after 5 s; it aborted on stale feedback. A separate
SIGINT run also aborted cleanly. An independent ROS subscriber observed 10
zero-speed commands after each cancellation; displacement over the final 0.5 s
was 0.0096 m in each run. Geometric path RMS error was 1.8 cm for the waypoint run
and 3.1 cm for the eight (nearest reference segment, separate from endpoint error).
