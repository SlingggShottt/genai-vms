"""vms_gpu_memory_bytes: parsing nvidia-smi and reporting only where there is a GPU."""

import asyncio

from vms_common import gpu_metrics
from vms_common.gpu_metrics import MIB, gpu_memory, parse_memory_csv, start_gpu_metrics


def test_nvidia_smi_csv_is_read_in_bytes():
    assert parse_memory_csv("0, 1873, 4096\n1, 0, 8192\n") == [
        ("0", 1873 * MIB, 4096 * MIB),
        ("1", 0, 8192 * MIB),
    ]


def test_malformed_lines_are_skipped_not_fatal():
    text = "0, 1873, 4096\nN/A, N/A, N/A\n\nnot csv\n1, 5, 6, 7\n2, 10, 20\n"
    assert parse_memory_csv(text) == [("0", 1873 * MIB, 4096 * MIB), ("2", 10 * MIB, 20 * MIB)]
    assert parse_memory_csv("") == []


def test_a_machine_without_nvidia_smi_starts_no_task(monkeypatch):
    monkeypatch.setattr(gpu_metrics.shutil, "which", lambda _: None)

    async def go():
        task = start_gpu_metrics("laptop-a")
        if task is not None:  # a wrong answer must fail the test, not leave a task polling
            task.cancel()
        return task

    assert asyncio.run(go()) is None


def test_the_reporter_sets_used_and_total_and_survives_a_failed_reading(monkeypatch):
    monkeypatch.setattr(gpu_metrics.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    readings = iter([OSError("driver busy"), [("0", 2000 * MIB, 4096 * MIB)]])

    async def fake_read():
        r = next(readings)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(gpu_metrics, "read_memory", fake_read)

    async def go():
        task = start_gpu_metrics("laptop-a", interval_s=0.01)
        await asyncio.sleep(0.15)
        assert not task.done()
        task.cancel()

    asyncio.run(go())
    assert gpu_memory.labels(node="laptop-a", gpu="0", kind="used")._value.get() == 2000 * MIB
    assert gpu_memory.labels(node="laptop-a", gpu="0", kind="total")._value.get() == 4096 * MIB
