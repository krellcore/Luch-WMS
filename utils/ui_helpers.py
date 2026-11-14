from PySide6.QtWidgets import QHeaderView, QAbstractItemView
from PySide6.QtCore import Qt


def search_filter(table, text):
    text = (text or "").strip().lower()
    for row in range(table.rowCount()):
        if not text:
            table.setRowHidden(row, False)
            continue
        match = False
        for col in range(table.columnCount()):
            it = table.item(row, col)
            if it and text in it.text().lower():
                match = True
                break
        table.setRowHidden(row, not match)


def lock_row_height(table, height=28):
    vh = table.verticalHeader()
    vh.setSectionResizeMode(QHeaderView.Fixed)
    vh.setDefaultSectionSize(height)


def tune_table(table, single_selection=False, row_height=28):
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.Stretch)
    hh.setSectionsClickable(False)
    hh.setSectionsMovable(False)
    hh.setHighlightSections(False)

    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(
        QAbstractItemView.SingleSelection if single_selection
        else QAbstractItemView.ExtendedSelection
    )
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setFocusPolicy(Qt.NoFocus)
    table.setShowGrid(True)
    lock_row_height(table, row_height)