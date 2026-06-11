"""Background data loading for TUI screens with a spinner fallback."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner_frame() -> str:
    return _SPINNER[int(time.monotonic() * 10) % len(_SPINNER)]


def start_load(
    sync: bool,
    load_fn: Callable[[], T],
    on_done: Callable[[T], None],
    on_error: Callable[[str], None],
) -> None:
    """Run load_fn and deliver the result.

    Synchronous when sync is true or no asyncio loop is running (unit tests,
    pre-app construction); otherwise runs in a thread-pool executor and
    invalidates the app on completion so the spinner is replaced.
    """
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if sync or loop is None:
        try:
            on_done(load_fn())
        except Exception as e:  # surface in the UI, never crash the app loop
            on_error(str(e))
        return

    from prompt_toolkit.application import get_app

    app = get_app()

    async def task() -> None:
        try:
            result = await asyncio.get_running_loop().run_in_executor(None, load_fn)
        except Exception as e:
            on_error(str(e))
        else:
            on_done(result)
        finally:
            app.invalidate()

    app.create_background_task(task())
