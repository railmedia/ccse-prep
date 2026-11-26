from __future__ import annotations

from app.ingest.parse import _question_id, _split_options


def test_question_id_accepts_ranges_and_rejects_years() -> None:
    assert _question_id("1001") == "1001"
    assert _question_id("5084") == "5084"
    # 2026 is a valid task-2 id and a year; range checks alone cannot tell them
    # apart, which is why question ids are only read from question pages.
    assert _question_id("2026") == "2026"
    assert _question_id("1121") is None
    assert _question_id("9999") is None
    assert _question_id("PREGUNTAS") is None


def test_split_options_multiple_choice() -> None:
    stem, options = _split_options(
        "¿Quién es el jefe del Estado? a. El presidente. b. El rey. c. El ministro."
    )
    assert stem == "¿Quién es el jefe del Estado?"
    assert options == {"a": "El presidente.", "b": "El rey.", "c": "El ministro."}


def test_split_options_true_false() -> None:
    stem, options = _split_options(
        "La Constitución obliga a practicar una religión. a. Verdadero. b. Falso."
    )
    assert stem.startswith("La Constitución")
    assert list(options) == ["a", "b"]


def test_split_options_keeps_wrapping_text_in_one_option() -> None:
    _, options = _split_options("Enunciado. a. Uno. b. Dos, con una coma. c. Tres.")
    assert options["b"] == "Dos, con una coma."
