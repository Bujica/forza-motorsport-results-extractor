from __future__ import annotations

import pytest

from forza.prompts import DEFAULT_PROMPT_ID, SYSTEM_PROMPTS, get_system_prompt


def test_get_system_prompt_returns_default_prompt() -> None:
    assert get_system_prompt() == SYSTEM_PROMPTS[DEFAULT_PROMPT_ID]


def test_get_system_prompt_returns_named_prompt() -> None:
    assert get_system_prompt(DEFAULT_PROMPT_ID) == SYSTEM_PROMPTS[DEFAULT_PROMPT_ID]


def test_get_system_prompt_rejects_unknown_prompt_id_with_available_ids() -> None:
    with pytest.raises(ValueError, match="Unknown prompt_id 'missing'. Available: user_header_shaped_v1"):
        get_system_prompt("missing")
