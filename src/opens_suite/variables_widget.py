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
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Name", "Value", "Unit"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.itemChanged.connect(self._on_item_changed)

        # Context menu for deleting rows
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self.table)

        self.user_variables = []
        self.design_points = []
        self._refresh_table()

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
        # Always return the editable generic user variables
        variables = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            unit_item = self.table.item(row, 2)
            if name_item and name_item.data(Qt.ItemDataRole.UserRole) == "dp":
                continue
            if name_item and value_item:
                name = name_item.text().strip()
                value = value_item.text().strip()
                unit = unit_item.text().strip() if unit_item else ""
                if name:
                    var_dict = {"name": name, "value": value}
                    if unit:
                        var_dict["unit"] = unit
                    variables.append(var_dict)
        return variables

    def set_variables(self, variables):
        self.user_variables = variables
        self._refresh_table()
        
    def set_design_points(self, dps):
        from opens_suite.design_points import DesignPoints
        self.design_points = []
        
        user_names = {var.get("name", "") for var in self.user_variables if var.get("name")}
        
        if dps and dps._length > 0:
            first_row = dps.to_dict(0)
            for k, v in first_row.items():
                parsed_name, unit_from_key = dps._parse_key(k)
                if parsed_name in user_names:
                    continue
                    
                unit = dps._units.get(parsed_name, unit_from_key)
                self.design_points.append({
                    "name": parsed_name,
                    "value": DesignPoints._format_si(v),
                    "unit": unit
                })
        self._refresh_table()

    def _refresh_table(self):
        self.block_signals = True
        self.table.setRowCount(0)
        
        from PyQt6.QtGui import QColor
        
        for dp in self.design_points:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            name_item = QTableWidgetItem(dp["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, "dp")
            name_item.setBackground(QColor("#f0f0f0"))
            
            val_item = QTableWidgetItem(dp["value"])
            val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            val_item.setBackground(QColor("#f0f0f0"))
            
            unit_item = QTableWidgetItem(dp["unit"])
            unit_item.setFlags(unit_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            unit_item.setBackground(QColor("#f0f0f0"))
            
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, val_item)
            self.table.setItem(row, 2, unit_item)
            
        for var in self.user_variables:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(var.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(var.get("value", "")))
            self.table.setItem(row, 2, QTableWidgetItem(var.get("unit", "")))
            
        self._ensure_placeholder_row()
        self.block_signals = False

    def _on_item_changed(self, item):
        if self.block_signals:
            return

        row = item.row()
        name_item = self.table.item(row, 0)
        
        if name_item and name_item.data(Qt.ItemDataRole.UserRole) == "dp":
            return

        if name_item and not name_item.text().strip():
            if row != self.table.rowCount() - 1:
                self.table.removeRow(row)
                self.user_variables = self.get_variables()
                self.variablesChanged.emit()
                return

        if row == self.table.rowCount() - 1 and name_item and name_item.text().strip():
            self._ensure_placeholder_row()

        self.user_variables = self.get_variables()
        self.variablesChanged.emit()

    def _show_context_menu(self, position):
        menu = QMenu()
        delete_action = menu.addAction("Delete Row")
        action = menu.exec(self.table.viewport().mapToGlobal(position))
        if action == delete_action:
            row = self.table.currentRow()
            name_item = self.table.item(row, 0)
            if name_item and name_item.data(Qt.ItemDataRole.UserRole) == "dp":
                return
            if row >= 0 and row != self.table.rowCount() - 1:
                self.table.removeRow(row)
                self.user_variables = self.get_variables()
                self.variablesChanged.emit()
