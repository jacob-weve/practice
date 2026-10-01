import pytest

from app.privacy.pii import MaskResult, mask, unmask


@pytest.mark.parametrize(
    ("raw", "expected", "kind"),
    [
        ("연락은 010-0000-0000으로 주세요", "연락은 [PHONE_1]으로 주세요", "PHONE"),
        ("+82 10 0000 0000 로 전화", "[PHONE_1] 로 전화", "PHONE"),
        ("사무실 02-000-0000", "사무실 [PHONE_1]", "PHONE"),
        ("메일 test.user@example.com 확인", "메일 [EMAIL_1] 확인", "EMAIL"),
        ("주민번호 900101-1234567", "주민번호 [RRN_1]", "RRN"),
        ("카드 1234-5678-9012-3456", "카드 [CARD_1]", "CARD"),
        ("계좌 110-123-456789 로 보내", "계좌 [ACCOUNT_1] 로 보내", "ACCOUNT"),
        ("서울시 강남구 테헤란로 123 으로 와", "[ADDRESS_1] 으로 와", "ADDRESS"),
        ("민수씨 내일 봐요", "[NAME_1]씨 내일 봐요", "NAME"),
        ("김지은 대리님이 그러셨어요", "[NAME_1] 대리님이 그러셨어요", "NAME"),
    ],
)
def test_masks_each_pii_kind(raw: str, expected: str, kind: str) -> None:
    result = mask(raw)
    assert result.text == expected
    assert result.types == {kind}
    assert unmask(result.text, result.mapping) == raw


@pytest.mark.parametrize(
    "text",
    [
        "팀장님, 내일까지는 어렵습니다.",
        "고객님 죄송합니다",
        "2026-10-01 회의는 3시에요",
        "오늘 기분이 별로야. 그걸 왜 지금 말해요?",
        "선생님 감사합니다",
    ],
)
def test_does_not_mask_ordinary_text(text: str) -> None:
    result = mask(text)
    assert result.text == text
    assert result.types == set()


def test_same_value_gets_same_token_across_texts() -> None:
    shared = MaskResult(text="")
    a = mask("민수씨 번호 010-0000-0000", shared).text
    b = mask("010-0000-0000 은 민수씨 거예요. 지은씨는 010-1111-1111", shared).text
    assert a == "[NAME_1]씨 번호 [PHONE_1]"
    assert b == "[PHONE_1] 은 [NAME_1]씨 거예요. [NAME_2]씨는 [PHONE_2]"
