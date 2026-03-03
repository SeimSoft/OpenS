from PyQt6.QtWidgets import (
    QDockWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QPushButton,
    QHBoxLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal
from opens_suite.schematic_item import SchematicItem


class ResultsSelectionWidget(QDockWidget):
    settingsChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Results Selection", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)

        # Buttons
        btn_layout = QHBoxLayout()
        self.save_all_btn = QPushButton("Save Everything")
        self.save_all_btn.clicked.connect(self.save_everything)
        btn_layout.addWidget(self.save_all_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        btn_layout.addWidget(self.refresh_btn)

        layout.addLayout(btn_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Instance", "Voltage", "Current"])
        self.table.itemChanged.connect(self.on_item_changed)
        layout.addWidget(self.table)

        self.setWidget(main_widget)
        self.current_scene = None
        self._updating = False

    def set_scene(self, scene):
        self.current_scene = scene
        self.refresh()

    def refresh(self):
        if not self.current_scene:
            self.table.setRowCount(0)
            return

        self._updating = True
        items = [i for i in self.current_scene.items() if isinstance(i, SchematicItem)]
        # Filter out GND
        items = [i for i in items if i.prefix != "GND"]
        items.sort(key=lambda x: x.name)

        self.table.setRowCount(len(items))

        for row, item in enumerate(items):
            # Instance Name
            name_item = QTableWidgetItem(item.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, item)
            self.table.setItem(row, 0, name_item)

            # Voltage Checkbox
            v_check = QTableWidgetItem()
            v_check.setCheckState(
                Qt.CheckState.Checked if item.save_voltage else Qt.CheckState.Unchecked
            )
            v_check.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
            )
            self.table.setItem(row, 1, v_check)

            # Current Checkbox
            c_check = QTableWidgetItem()
            supports_current = (
                str(item.parameters.get("SUPPORTS_CURRENT", "False")).lower() == "true"
            )

            if supports_current:
                c_check.setCheckState(
                    Qt.CheckState.Checked
                    if item.save_current
                    else Qt.CheckState.Unchecked
                )
                c_check.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                )
            else:
                c_check.setCheckState(Qt.CheckState.Unchecked)
                c_check.setFlags(Qt.ItemFlag.NoItemFlags)  # Grayed out/Disabled
                item.save_current = False

            self.table.setItem(row, 2, c_check)

        self.table.resizeColumnsToContents()
        self._updating = False

    def on_item_changed(self, table_item):
        if self._updating:
            return

        row = table_item.row()
        col = table_item.column()
        name_item = self.table.item(row, 0)
        sch_item = name_item.data(Qt.ItemDataRole.UserRole)

        if col == 1:  # Voltage
            sch_item.save_voltage = table_item.checkState() == Qt.CheckState.Checked
        elif col == 2:  # Current
            sch_item.save_current = table_item.checkState() == Qt.CheckState.Checked

        self.settingsChanged.emit()

    def save_everything(self):
        self._updating = True
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            sch_item = name_item.data(Qt.ItemDataRole.UserRole)

            # Voltage
            sch_item.save_voltage = True
            self.table.item(row, 1).setCheckState(Qt.CheckState.Checked)

            # Current (only if supported)
            supports_current = (
                str(sch_item.parameters.get("SUPPORTS_CURRENT", "False")).lower()
                == "true"
            )
            if supports_current:
                sch_item.save_current = True
                self.table.item(row, 2).setCheckState(Qt.CheckState.Checked)

        self._updating = False
        self.settingsChanged.emit()
