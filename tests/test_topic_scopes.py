import io

from rich.console import Console
from autoctrl.console_ui import ConsoleUI
from autoctrl.domain import StatusKind, StatusQuery
from autoctrl.status import build_topic_status


def test_both_targets_are_discovered_with_namespace_boundaries():
    graph = [(name, ["type"]) for name in (
        "/small/odom", "/sim/odom", "/sim/cmd_vel", "/similar/odom", "/other/odom"
    )]
    result = build_topic_status(graph, "/small", ("/sim/odom", "/sim/cmd_vel"))
    assert [t["name"] for t in result["topics"]] == ["/sim/cmd_vel", "/sim/odom", "/small/odom"]
    assert len(result["groups"][0]["topics"]) == 1
    assert len(result["groups"][1]["topics"]) == 2


def test_custom_simulation_namespace_follows_configuration():
    result = build_topic_status([
        ("/vehicle/odom", ["type"]), ("/digital/odom", ["type"]), ("/sim/odom", ["type"])
    ], "/vehicle", ("/digital/odom",))
    assert result["namespaces"] == ["/vehicle", "/digital"]
    assert [t["name"] for t in result["topics"]] == ["/digital/odom", "/vehicle/odom"]


def test_missing_simulation_is_visible_in_ui():
    result = build_topic_status([("/small/odom", ["type"])], "/small")
    output = io.StringIO()
    ui = ConsoleUI(Console(file=output, width=100), typing_delay_s=0)
    ui.show_status_result(StatusQuery(StatusKind.ROS_TOPICS), result)
    text = output.getvalue()
    assert "實車" in text and "Isaac Sim" in text and "/sim" in text
    assert "尚未發現此範圍" in text


def test_root_namespace_and_overlap_do_not_duplicate_flat_results():
    result = build_topic_status([("/sim/odom", ["type"])], "/", ("/sim/odom",))
    assert len(result["topics"]) == 1
