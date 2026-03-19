from PyQt6.QtWidgets import (
    QDockWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
    QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal


class VariablesWidget(QDockWidget):
    variablesChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Variables", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        container = QWidget()
        layout = QVBoxLayout(container)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Name", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.itemChanged.connect(self._on_item_changed)

        # Context menu for deleting rows
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self.table)

        # Placeholder row for adding new variables by editing directly.
        self._ensure_placeholder_row()

        self.setWidget(container)
        self.block_signals = False

    def _ensure_placeholder_row(self):
        """Ensure there's always an empty row at the end for adding a new variable."""
        row_count = self.table.rowCount()
        if row_count == 0:
            self.table.insertRow(0)
            return

        # If last row already has a name, append an empty row
        last_name_item = self.table.item(row_count - 1, 0)
        if last_name_item and last_name_item.text().strip():
            self.table.insertRow(row_count)

    def get_variables(self):
        variables = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            if name_item and value_item:
                name = name_item.text().strip()
                value = value_item.text().strip()
                if name:
                    variables.append({"name": name, "value": value})
        return variables

    def set_variables(self, variables):
        self.block_signals = True
        self.table.setRowCount(0)
        for var in variables:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(var.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(var.get("value", "")))
        self._ensure_placeholder_row()
        self.block_signals = False

    def _on_item_changed(self, item):
        if self.block_signals:
            return

        row = item.row()
        name_item = self.table.item(row, 0)
        if name_item and not name_item.text().strip():
            # If user cleared the name, remove the row unless it's the last placeholder row
            if row != self.table.rowCount() - 1:
                self.table.removeRow(row)
                self.variablesChanged.emit()
                return

        # If user filled in the placeholder row, add a new placeholder
        if row == self.table.rowCount() - 1 and name_item and name_item.text().strip():
            self._ensure_placeholder_row()

        self.variablesChanged.emit()

    def _show_context_menu(self, position):
        menu = QMenu()
        delete_action = menu.addAction("Delete Row")
        action = menu.exec(self.table.viewport().mapToGlobal(position))
        if action == delete_action:
            row = self.table.currentRow()
            if row >= 0:
                self.table.removeRow(row)
                self.variablesChanged.emit()
