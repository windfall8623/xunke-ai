"""Drain bounded synchronous IO before acknowledging task cancellation."""

from __future__ import annotations

import asyncio


async def run_file_io(function, *args):
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = None
    while True:
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancelled = exc
            if task.done():
                if not task.cancelled():
                    task.exception()
                raise
            # A second cancellation must not abandon the still-writing thread.
            continue
        except BaseException:
            if cancelled is not None:
                raise cancelled
            raise
        if cancelled is not None:
            raise cancelled
        return result
