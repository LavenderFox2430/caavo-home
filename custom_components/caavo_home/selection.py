"""Per-entry command choices. Selecting never transmits to the device."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


def named_options(names: dict[str, str]) -> dict[str, str]:
    """Readable, sorted labels with stable IDs only where names collide."""
    qualified: set[str] = set()
    while True:
        labels = {
            key: f"{name} ({key})" if key in qualified else name for key, name in names.items()
        }
        counts = Counter(labels.values())
        collisions = {key for key, label in labels.items() if counts[label] > 1}
        if not collisions:
            return {
                label: key
                for key, label in sorted(
                    labels.items(), key=lambda item: (item[1].casefold(), item[0])
                )
            }
        qualified.update(collisions)


@dataclass
class AutomationSelection:
    """Selections use IDs, survive renames, and reset on integration reload."""

    ir_device: str | None = None
    ir_function: str | None = None
    macro: str | None = None

    def options(self, state: dict, kind: str) -> dict[str, str]:
        devices = state.get("devices", {})
        if kind == "ir_device":
            names = {key: row["name"] for key, row in devices.items()}
        elif kind == "ir_function":
            names = devices.get(self.ir_device, {}).get("commands", {})
        elif kind == "macro":
            names = state.get("macros", {})
        else:
            raise ValueError("Unknown command selector")
        return named_options(names)

    def current_option(self, state: dict, kind: str) -> str | None:
        selected = getattr(self, kind)
        return next(
            (label for label, key in self.options(state, kind).items() if key == selected), None
        )

    def select(self, state: dict, kind: str, option: str) -> None:
        key = self.options(state, kind).get(option)
        if key is None:
            raise ValueError("This choice changed; choose a current option")
        if kind == "ir_device" and key != self.ir_device:
            # A same-named function on another device is not an intentional choice.
            self.ir_function = None
        setattr(self, kind, key)

    def reconcile(self, state: dict) -> None:
        """Only call with a successfully refreshed library, never a failed poll."""
        devices = state.get("devices", {})
        if self.ir_device not in devices:
            self.ir_device = self.ir_function = None
        elif self.ir_function not in devices[self.ir_device]["commands"]:
            self.ir_function = None
        if self.macro not in state.get("macros", {}):
            self.macro = None

    def request(self, state: dict, kind: str) -> dict | None:
        if kind == "ir":
            key = ("command", self.ir_device, self.ir_function)
        elif kind == "macro":
            key = ("macro", self.macro)
        else:
            raise ValueError("Unknown command action")
        row = state.get("buttons", {}).get(key)
        return dict(row["request"]) if row else None
