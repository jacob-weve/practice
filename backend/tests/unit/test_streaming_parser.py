import json
import random

import pytest

from app.llm.streaming import FieldCompleted, IncrementalObjectParser, ItemCompleted, sse_event

DOC = {
    "intent": {"label": "decline", "confidence": 0.9},
    "emotion": {"temperature": 82, "labels": [{"name": "anger", "score": 0.4}]},
    "red_flags": [{"text": '그걸 "왜" 지금 {말해}요\\', "type": "blame"}],
    "variants": [
        {"kind": "primary", "text": "팀장님, [어렵습니다]."},
        {"kind": "softer", "text": "죄송하지만, 어려울 것 같아요."},
        {"kind": "concise", "text": "어렵습니다."},
    ],
    "count": 3,
    "ok": True,
    "note": None,
    "tags": ["a", "b"],
}


def run(text: str, chunk_sizes: list[int]) -> list[object]:
    parser = IncrementalObjectParser(item_keys=frozenset({"variants", "tags"}))
    events: list[object] = []
    pos = 0
    for size in chunk_sizes:
        events.extend(parser.feed(text[pos : pos + size]))
        pos += size
    events.extend(parser.feed(text[pos:]))
    return events


@pytest.mark.parametrize("indent", [None, 2])
@pytest.mark.parametrize("seed", range(5))
def test_events_are_identical_for_any_chunking(indent: int | None, seed: int) -> None:
    text = json.dumps(DOC, ensure_ascii=False, indent=indent)
    rng = random.Random(seed)
    sizes = [rng.randint(1, 7) for _ in range(len(text))]
    events = run(text, sizes)

    fields = {e.key: e.value for e in events if isinstance(e, FieldCompleted)}
    assert fields == DOC
    items = [(e.key, e.index, e.value) for e in events if isinstance(e, ItemCompleted)]
    assert items == [
        ("variants", 0, DOC["variants"][0]),
        ("variants", 1, DOC["variants"][1]),
        ("variants", 2, DOC["variants"][2]),
        ("tags", 0, "a"),
        ("tags", 1, "b"),
    ]


def test_fields_are_emitted_as_soon_as_they_close() -> None:
    parser = IncrementalObjectParser(item_keys=frozenset({"variants"}))
    first = list(parser.feed('{"intent": {"label": "accept", "confidence": 1}, "variants": [{"k'))
    assert first == [FieldCompleted("intent", {"label": "accept", "confidence": 1})]
    second = list(parser.feed('": 1}, {"k": 2'))
    assert second == [ItemCompleted("variants", 0, {"k": 1})]


def test_trailing_scalar_waits_for_delimiter() -> None:
    parser = IncrementalObjectParser()
    assert list(parser.feed('{"n": 12')) == []
    assert list(parser.feed("3}")) == [FieldCompleted("n", 123)]


def test_sse_event_format() -> None:
    assert sse_event("meta", {"a": "한"}) == 'event: meta\ndata: {"a":"한"}\n\n'
