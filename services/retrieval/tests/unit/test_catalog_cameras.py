"""The camera list the assistant is given must include cameras that were switched off."""

import asyncio

from retrieval.adapters.catalog import Catalog


class _Session:
    def __init__(self, seen: list[str]) -> None:
        self._seen = seen

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def execute(self, statement):
        self._seen.append(str(statement))
        return [("bus-g331",), ("cam01",)]


def test_camera_codes_do_not_leave_out_switched_off_cameras():
    seen: list[str] = []
    codes = asyncio.run(Catalog(lambda: _Session(seen)).camera_codes())
    assert codes == ["bus-g331", "cam01"]
    # A camera with enabled = false still has events and recordings to ask about; the question
    # "how many events on bus-g331 on 4 October" must know bus-g331 is a camera.
    assert "core.cameras" in seen[0] and "enabled" not in seen[0].lower()
