"""Validate the example dashboard's native cards and API key mappings."""

import unittest

import yaml
from support import ROOT, component

KEYS = component("const").KEYS


class DashboardTests(unittest.TestCase):
    def setUp(self):
        dashboard = yaml.safe_load((ROOT / "examples/caavo-dashboard.yaml").read_text("utf-8"))
        self.cards = {view["path"]: view["cards"][0]["cards"] for view in dashboard["views"]}

    def test_named_control_groups_point_to_existing_actions(self):
        groups = {card["title"]: card for card in self.cards["controls"]}
        self.assertEqual(
            list(groups),
            [
                "Switching inputs",
                "CEC controls",
                "Theater Actions",
                "Macros",
                "Theater job",
                "System status",
                "Theater job history",
            ],
        )
        self.assertEqual(groups["Theater job history"]["type"], "history-graph")
        self.assertIn(
            {"entity": "select.caavo_home_hdmi_input"}, groups["Switching inputs"]["entities"]
        )
        self.assertEqual(
            [row["entity"] for row in groups["CEC controls"]["entities"][:2]],
            ["button.caavo_home_wake_caavo", "button.caavo_home_caavo_standby"],
        )
        self.assertEqual(
            [row["entity"] for row in groups["Macros"]["entities"]],
            ["select.caavo_home_macro", "button.caavo_home_run_macro"],
        )
        self.assertIn(
            {"entity": "button.caavo_home_ir_send"}, groups["Theater Actions"]["entities"]
        )
        self.assertIn(
            {"entity": "button.caavo_home_cancel_theater_job"}, groups["Theater job"]["entities"]
        )

    def test_remote_maps_each_supported_key_once(self):
        commands = []
        for grid in self.cards["remote"][1:]:
            self.assertEqual(grid["type"], "grid")
            for button in grid["cards"]:
                action = button["tap_action"]
                self.assertEqual(button["type"], "button")
                self.assertEqual(action["action"], "perform-action")
                self.assertEqual(action["perform_action"], "remote.send_command")
                self.assertEqual(action["target"], {"entity_id": "remote.caavo_home_remote"})
                commands.append(action["data"]["command"])
        self.assertCountEqual(commands, KEYS)
