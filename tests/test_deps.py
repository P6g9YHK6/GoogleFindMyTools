from webui.deps import run_blocking


async def test_run_blocking_calls_the_wrapped_function():
    result = await run_blocking(lambda x, y: x + y, 2, y=3)
    assert result == 5


def test_webui_points_the_shared_throttle_at_settings_store():
    """webui/deps.py reconfigures NovaApi/query_throttle.py's shared
    singleton to read config.yaml (via settings_store.load, editable on the
    Config page) instead of the env-var defaults that apply when running
    standalone via the CLI - see NovaApi/query_throttle.py's module
    docstring."""
    from NovaApi.query_throttle import query_throttle as shared_throttle
    from webui import settings_store
    from webui.deps import query_gate

    assert query_gate is shared_throttle
    assert query_gate._settings is settings_store.load
