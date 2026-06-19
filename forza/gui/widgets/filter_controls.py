from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QSizePolicy


def fit_combo_to_contents(combo: QComboBox) -> QComboBox:
    """Keep filter combo boxes readable in single-line filter bars.

    Qt's default policy can compress combo text aggressively when many filters
    share a horizontal layout. The previous GUI behavior depended on combo boxes
    sizing themselves to their contents. This helper restores that contract
    without changing filter semantics or wrapping the filter bar to multiple rows.
    """
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    combo.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    resize_combo_to_contents(combo)
    return combo


def resize_combo_to_contents(combo: QComboBox) -> None:
    combo.setMinimumWidth(max(combo.minimumSizeHint().width(), combo.sizeHint().width()))
    view = combo.view()
    if view is not None:
        view.setMinimumWidth(combo.minimumWidth())
