from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel


def make_card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    return card


def make_card_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("cardTitle")
    return label
