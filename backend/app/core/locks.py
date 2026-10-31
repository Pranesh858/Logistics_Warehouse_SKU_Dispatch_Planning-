"""Named in-process locks for work that must not interleave (plan writes, stock writes, webhook handling).

An asyncio.Lock belongs to the event loop that first waits on it. The app runs one loop, but a module-level lock
would break the moment a second loop uses it (the tests start servers one after another), so each loop gets its
own set. Like the in-memory stock copy, this serialises work within one server process: the app runs as one.
"""
import asyncio
import weakref

_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = weakref.WeakKeyDictionary()


def named(name: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    per_loop = _locks.setdefault(loop, {})
    if name not in per_loop:
        per_loop[name] = asyncio.Lock()
    return per_loop[name]
