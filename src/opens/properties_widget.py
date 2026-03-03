from PyQt6.QtWidgets import QDockWidget, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt, pyqtSignal
from opens.wire import Wire

# Avoid circular import if possible, or use simple check
# from opens.schematic_item import SchematicItem


class PropertiesWidget(QDockWidget):
    propertyChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Properties", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Property", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self.on_item_changed)

        self.setWidget(self.table)

        self.current_item = None
        self.block_signals = False

    def update_selection(self, items):
        self.block_signals = True
        self.table.setRowCount(0)
        self.current_item = None

        if len(items) == 1:
            item = items[0]
            self.current_item = item

            # Check for SchematicItem (has parameters and name)
            if hasattr(item, "parameters") and hasattr(item, "name"):
                # Name
                self.add_row("Name", item.name, editable=True)

                # Parameters
                for name, value in item.parameters.items():
                    self.add_row(name, value, editable=True)

            elif isinstance(item, Wire):
                # Net Name
                self.add_row("Net Name", item.name or "", editable=True)

        self.block_signals = False

    def add_row(self, name, value, editable=True):
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(name)
        name_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        )  # Name not editable
        self.table.setItem(row, 0, name_item)

        value_item = QTableWidgetItem(str(value))
        if not editable:
            value_item.setFlags(value_item.flags() ^ Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 1, value_item)

    def on_item_changed(self, item):
        if self.block_signals or not self.current_item:
            return

        # We only care about edits to column 1 (Value)
        if item.column() != 1:
            return

        row = item.row()
        prop_name = self.table.item(row, 0).text()
        new_value = item.text()

        # Logic for SchematicItem
        if hasattr(self.current_item, "parameters"):
            if prop_name == "Name":
                if new_value:
                    # Check for collisions
                    if (
                        hasattr(self.current_item, "scene")
                        and self.current_item.scene()
                    ):
                        for item in self.current_item.scene().items():
                            if (
                                item != self.current_item
                                and getattr(item, "name", None) == new_value
                            ):
                                from PyQt6.QtWidgets import QMessageBox

                                QMessageBox.warning(
                                    self,
                                    "Invalid Name",
                                    f"The name '{new_value}' is already taken in this schematic.",
                                )

                                # Revert visually
                                self.block_signals = True
                                self.table.item(row, 1).setText(
                                    self.current_item.name or ""
                                )
                                self.block_signals = False
                                return

                if hasattr(self.current_item, "set_name"):
                    self.current_item.set_name(new_value)
            else:
                # Check SI validity?
                try:
                    val = self.parse_si(new_value)
                except ValueError:
                    pass

                if hasattr(self.current_item, "set_parameter"):
                    self.current_item.set_parameter(prop_name, new_value)

        # Logic for Wire
        elif isinstance(self.current_item, Wire):
            if prop_name == "Net Name":
                self.current_item.name = new_value if new_value.strip() else None

        self.propertyChanged.emit()

    def parse_si(self, value_str):
        # Basic parser: 10k, 10M, 1n...
        suffixes = {
            "p": 1e-12,
            "n": 1e-9,
            "u": 1e-6,
            "m": 1e-3,
            "M": 1e-3,  # In Spice, M is milli
            "k": 1e3,
            "Meg": 1e6,
            "meg": 1e6,
            "G": 1e9,
            "T": 1e12,
        }

        value_str = value_str.strip()
        if not value_str:
            return 0.0

        # Sort suffixes by length descending to match 'Meg' before 'm'
        sorted_suffixes = sorted(suffixes.keys(), key=len, reverse=True)
        for s in sorted_suffixes:
            if value_str.endswith(s):
                try:
                    num_str = value_str[: -len(s)].strip()
                    if not num_str:
                        return 0.0  # Handle case like "k"
                    return float(num_str) * suffixes[s]
                except ValueError:
                    continue

        try:
            return float(value_str)
        except ValueError:
            return 0.0
