from __future__ import annotations


class ValidationContext:
    """Accumulates facts across messages in a batch so cross-message rules
    (e.g. StartSortOrder consistency) can compare values seen earlier.

    Keys are caller-built strings, e.g. f"startorder:{athlete_code}".
    `seen` becomes True after the first remember(), letting single-message
    runs (empty context) skip cross-message rules instead of false-flagging.
    """

    def __init__(self):
        self._store: dict[str, object] = {}
        self.seen = False

    def remember(self, key: str, value) -> None:
        self._store[key] = value
        self.seen = True

    def recall(self, key: str):
        return self._store.get(key)

    def has(self, key: str) -> bool:
        return key in self._store
