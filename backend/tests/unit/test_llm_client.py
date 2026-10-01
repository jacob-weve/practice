import json

import pytest
from fakeredis import FakeAsyncRedis

from app.core.config import Settings
from app.core.errors import LlmBusyError, LlmOutputInvalidError, LlmRefusedError, LlmUpstreamError
from app.db.models import LlmTier
from app.llm.client import CircuitBreaker, LlmCall, LlmClient, TextDelta
from app.llm.schemas import GuardrailVerdict
from tests.fakes import FakeLlmProvider, Script

CALL = LlmCall(system="sys", user="usr", output_schema={}, max_tokens=256)
SAFE = json.dumps({"category": "safe", "score": 0.01})


def make(
    provider: FakeLlmProvider, **overrides: object
) -> tuple[LlmClient, CircuitBreaker, Settings]:
    settings = Settings(app_env="test", llm_first_event_timeout_seconds=0.05, **overrides)  # type: ignore[arg-type]
    clock = [0.0]
    breaker = CircuitBreaker(threshold=2, open_seconds=30, clock=lambda: clock[0])
    breaker.clock_ref = clock  # type: ignore[attr-defined]
    return LlmClient(provider, settings, FakeAsyncRedis(), breaker), breaker, settings


async def test_light_tier_uses_haiku_without_effort_or_server_fallback() -> None:
    provider = FakeLlmProvider()
    client, _, _ = make(provider)
    await client.complete(LlmTier.LIGHT, CALL)
    call = provider.calls[0]
    assert (call.model, call.effort, call.server_fallback) == ("claude-haiku-4-5", None, False)


async def test_heavy_tier_uses_sonnet_with_low_effort_and_server_fallback() -> None:
    provider = FakeLlmProvider()
    client, _, _ = make(provider)
    await client.complete(LlmTier.HEAVY, CALL)
    call = provider.calls[0]
    assert (call.model, call.effort, call.server_fallback) == ("claude-sonnet-5-5", "low", True)


async def test_template_effort_overrides_default_only_for_effort_capable_models() -> None:
    provider = FakeLlmProvider()
    client, _, _ = make(provider)
    with_effort = LlmCall(system="s", user="u", output_schema={}, max_tokens=10, effort="medium")
    await client.complete(LlmTier.HEAVY, with_effort)
    await client.complete(LlmTier.LIGHT, with_effort)
    assert [c.effort for c in provider.calls] == ["medium", None]


@pytest.mark.parametrize("failure", ["before_start", "hang"])
async def test_falls_back_to_same_tier_model_before_first_token(failure: str) -> None:
    provider = FakeLlmProvider()
    provider.queue("claude-haiku-4-5", Script(fail=failure))
    client, _, _ = make(provider)
    result = await client.complete(LlmTier.LIGHT, CALL)
    assert [c.model for c in provider.calls] == ["claude-haiku-4-5", "claude-sonnet-5-5"]
    assert result.done.model == "claude-sonnet-5-5"


async def test_failure_after_tokens_is_not_retried() -> None:
    provider = FakeLlmProvider()
    provider.queue("claude-haiku-4-5", Script(text=SAFE, fail="mid_stream", chunk=3))
    client, _, _ = make(provider)
    with pytest.raises(LlmUpstreamError):
        await client.complete(LlmTier.LIGHT, CALL)
    assert len(provider.calls) == 1


async def test_all_models_failing_raises_upstream_error() -> None:
    provider = FakeLlmProvider()
    provider.queue("claude-haiku-4-5", Script(fail="before_start"))
    provider.queue("claude-sonnet-5-5", Script(fail="before_start"))
    client, _, _ = make(provider)
    with pytest.raises(LlmUpstreamError):
        await client.complete(LlmTier.LIGHT, CALL)


async def test_circuit_breaker_skips_failing_model_then_half_opens() -> None:
    provider = FakeLlmProvider()
    provider.queue("claude-haiku-4-5", Script(fail="before_start"), Script(fail="before_start"))
    client, breaker, _ = make(provider)
    await client.complete(LlmTier.LIGHT, CALL)
    await client.complete(LlmTier.LIGHT, CALL)
    assert breaker.is_open("claude-haiku-4-5")

    provider.calls.clear()
    await client.complete(LlmTier.LIGHT, CALL)
    assert [c.model for c in provider.calls] == ["claude-sonnet-5-5"]

    breaker.clock_ref[0] = 31  # type: ignore[attr-defined]
    provider.calls.clear()
    await client.complete(LlmTier.LIGHT, CALL)
    assert [c.model for c in provider.calls] == ["claude-haiku-4-5"]
    assert not breaker.is_open("claude-haiku-4-5")


async def test_refusal_and_truncation_are_errors() -> None:
    provider = FakeLlmProvider()
    provider.queue("claude-haiku-4-5", Script(text="{", stop_reason="refusal"))
    provider.queue("claude-haiku-4-5", Script(text="{", stop_reason="max_tokens"))
    client, _, _ = make(provider)
    with pytest.raises(LlmRefusedError):
        await client.complete(LlmTier.LIGHT, CALL)
    with pytest.raises(LlmOutputInvalidError):
        await client.complete(LlmTier.LIGHT, CALL)


async def test_structured_output_retries_once_on_invalid_json() -> None:
    provider = FakeLlmProvider()
    provider.queue("claude-haiku-4-5", Script(text='{"category": "safe", "score": 7}'))
    provider.queue("claude-haiku-4-5", Script(text=SAFE))
    client, _, _ = make(provider)
    verdict, _ = await client.complete_structured(LlmTier.LIGHT, CALL, GuardrailVerdict)
    assert verdict.category == "safe"
    assert len(provider.calls) == 2

    provider.queue("claude-haiku-4-5", Script(text="nope"), Script(text="still nope"))
    with pytest.raises(LlmOutputInvalidError):
        await client.complete_structured(LlmTier.LIGHT, CALL, GuardrailVerdict)


async def test_concurrency_limit_per_tier() -> None:
    provider = FakeLlmProvider()
    client, _, _ = make(provider, llm_max_concurrency={"light": 1, "heavy": 1})
    stream = client.stream(LlmTier.LIGHT, CALL)
    first = await anext(stream)  # 첫 요청이 슬롯을 차지한 상태
    assert first is not None
    with pytest.raises(LlmBusyError):
        await client.complete(LlmTier.LIGHT, CALL)
    await stream.aclose()
    # 슬롯이 반환되면 다시 호출할 수 있다.
    result = await client.complete(LlmTier.LIGHT, CALL)
    assert result.text == "{}"


async def test_complete_measures_ttft_and_joins_text() -> None:
    provider = FakeLlmProvider()
    provider.queue("claude-haiku-4-5", Script(text=SAFE, chunk=2))
    client, _, _ = make(provider)
    result = await client.complete(LlmTier.LIGHT, CALL)
    assert result.text == SAFE
    assert result.ttft_ms is not None
    assert result.done.cached_tokens == 80
    events = [e async for e in client.stream(LlmTier.LIGHT, CALL)]
    assert any(isinstance(e, TextDelta) for e in events)
