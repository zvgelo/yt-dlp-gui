"""Tab order that follows the visible layout.

Qt walks the focus chain in the order the widgets were constructed. That is
usually the same as the layout, but not always: a `QDialogButtonBox` arranges
its buttons by platform convention, so with the Fusion style the accept button
sits to the left of Cancel even though Cancel was created first. A keyboard
user would then tab through the dialog in an order that does not match what
they see.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from PySide6.QtWidgets import QDialogButtonBox, QWidget


def apply_tab_order(parent: QWidget, widgets: Sequence[QWidget]) -> None:
    """Chain the widgets so Tab visits them in the given order."""
    present = [widget for widget in widgets if widget is not None]
    for first, second in itertools.pairwise(present):
        parent.setTabOrder(first, second)


def order_button_box(parent: QWidget, box: QDialogButtonBox) -> None:
    """Tab through a button box left to right, whatever the creation order.

    The layout is activated first so the buttons have real positions; that
    works before the dialog is shown, which keeps the call next to the rest of
    the construction.
    """
    layout = box.layout()
    if layout is not None:
        layout.activate()
    apply_tab_order(parent, sorted(box.buttons(), key=lambda button: button.pos().x()))
