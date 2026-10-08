"""`vms_gpu_memory_bytes{node,gpu,kind}`: how much of the GPU's memory is in use, from `nvidia-smi`.

The whole card, not one process: on a 4 GB laptop the models of every service (perception, Ollama)
share it, and what matters is the total. `kind` is `used` or `total`. A process on a machine
without `nvidia-smi` (a container with no GPU, the cloud VM) reports nothing and starts no task.
"""

from __future__ import annotations

import asyncio
import shutil

from vms_common.logging import get_logger
from vms_common.metrics import gauge

log = get_logger(__name__)

gpu_memory = gauge(
    "gpu", "memory", "bytes", "GPU memory in use / in total", ("node", "gpu", "kind")
)
QUERY = [
    "nvidia-smi",
    "--query-gpu=index,memory.used,memory.total",
    "--format=csv,noheader,nounits",
]
MIB = 1024 * 1024
REPORT_INTERVAL_S = 15.0
_TIMEOUT_S = 5.0


def parse_memory_csv(text: str) -> list[tuple[str, int, int]]:
    """[(gpu index, used bytes, total bytes)] from `nvidia-smi`'s CSV (MiB, no header, no units).
    A malformed line is skipped rather than failing the others."""
    rows = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        rows.append((parts[0], int(parts[1]) * MIB, int(parts[2]) * MIB))
    return rows


async def read_memory() -> list[tuple[str, int, int]]:
    proc = await asyncio.create_subprocess_exec(
        *QUERY, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), _TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        raise
    return parse_memory_csv(out.decode(errors="replace")) if proc.returncode == 0 else []


async def _report(node: str, interval_s: float) -> None:
    while True:
        try:
            for index, used, total in await read_memory():
                gpu_memory.labels(node=node, gpu=index, kind="used").set(used)
                gpu_memory.labels(node=node, gpu=index, kind="total").set(total)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a missed reading is not worth a crash
            log.debug("gpu_memory_unavailable", error=str(exc))
        await asyncio.sleep(interval_s)


def start_gpu_metrics(node: str, interval_s: float = REPORT_INTERVAL_S) -> asyncio.Task | None:
    """Start the reporter on the running loop; None when this machine has no `nvidia-smi`."""
    if shutil.which(QUERY[0]) is None:
        return None
    return asyncio.create_task(_report(node, interval_s))
