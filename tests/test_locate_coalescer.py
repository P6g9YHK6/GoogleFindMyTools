"""Unit tests for webui/locate_coalescer.py's LocateCoalescer - the
per-canonic_id single-flight wrapper webui/deps.py's locate_device() puts
around every locate. See tests/test_deps.py for the "does locate_device
itself actually dedupe" coverage; these tests exercise the coalescer in
isolation, same split as tests/test_device_list_cache.py does for
DeviceListCache."""

import asyncio

import pytest

from webui.locate_coalescer import LocateCoalescer


async def test_concurrent_calls_for_the_same_key_collapse_into_one_fetch():
    coalescer = LocateCoalescer()
    calls = []
    started = asyncio.Event()

    async def fetch():
        calls.append(1)
        started.set()
        await asyncio.sleep(0.05)
        return "value"

    async def caller():
        return await coalescer.get_or_fetch("dev-1", fetch)

    t1 = asyncio.ensure_future(caller())
    await started.wait()
    t2 = asyncio.ensure_future(caller())

    results = await asyncio.gather(t1, t2)

    assert results == ["value", "value"]
    assert len(calls) == 1


async def test_concurrent_calls_for_different_keys_each_get_their_own_fetch():
    coalescer = LocateCoalescer()
    calls = []

    async def make_fetch(value):
        async def fetch():
            calls.append(value)
            await asyncio.sleep(0.02)
            return value
        return fetch

    results = await asyncio.gather(
        coalescer.get_or_fetch("dev-1", await make_fetch("a")),
        coalescer.get_or_fetch("dev-2", await make_fetch("b")),
    )

    assert set(results) == {"a", "b"}
    assert len(calls) == 2


async def test_a_call_after_the_inflight_one_finished_triggers_a_fresh_fetch():
    coalescer = LocateCoalescer()
    calls = []

    async def fetch():
        calls.append(1)
        return f"value-{len(calls)}"

    assert await coalescer.get_or_fetch("dev-1", fetch) == "value-1"
    assert await coalescer.get_or_fetch("dev-1", fetch) == "value-2"
    assert len(calls) == 2


async def test_a_joining_callers_cancellation_does_not_cancel_the_shared_fetch():
    coalescer = LocateCoalescer()
    started = asyncio.Event()
    finished = asyncio.Event()

    async def fetch():
        started.set()
        await asyncio.sleep(0.05)
        finished.set()
        return "value"

    async def caller():
        return await coalescer.get_or_fetch("dev-1", fetch)

    leader = asyncio.ensure_future(caller())
    await started.wait()
    joiner = asyncio.ensure_future(caller())
    await asyncio.sleep(0)  # let the joiner actually attach to the in-flight task

    joiner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await joiner

    assert await leader == "value"
    assert finished.is_set()


async def test_exceptions_are_shared_with_every_caller():
    coalescer = LocateCoalescer()

    async def fetch():
        await asyncio.sleep(0.02)
        raise ValueError("boom")

    async def caller():
        return await coalescer.get_or_fetch("dev-1", fetch)

    t1 = asyncio.ensure_future(caller())
    t2 = asyncio.ensure_future(caller())

    with pytest.raises(ValueError, match="boom"):
        await t1
    with pytest.raises(ValueError, match="boom"):
        await t2
