from PyQt6.QtWidgets import (
    QDockWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QHBoxLayout,
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

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add Variable")
        self.add_btn.clicked.connect(self.add_variable)
        btn_layout.addWidget(self.add_btn)

        layout.addLayout(btn_layout)

        self.setWidget(container)
        self.block_signals = False

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
        self.block_signals = False

    def add_variable(self):
        self.block_signals = True
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(f"VAR{row+1}"))
        self.table.setItem(row, 1, QTableWidgetItem("0"))
        self.block_signals = False
        self.variablesChanged.emit()

    def _on_item_changed(self, item):
        if self.block_signals:
            return
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
