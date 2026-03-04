from PyQt6.QtWidgets import (
    QDockWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QDialog,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QDialogButtonBox,
    QStackedWidget,
    QCheckBox,
    QLabel,
)
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtCore import Qt, pyqtSignal


class AnalysisWidget(QDockWidget):
    analysesChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Analysis", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.tree_view = QTreeView()
        self.tree_view.setHeaderHidden(True)
        self.tree_view.doubleClicked.connect(self.on_double_click)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.show_context_menu)

        self.model = QStandardItemModel(self)
        self.tree_view.setModel(self.model)
        self.model.itemChanged.connect(self.on_item_changed)

        # Add Root/Placeholder
        self.add_placeholder()

        self.setWidget(self.tree_view)

        self.analysis_data = {}  # type -> config_dict

    def add_placeholder(self):
        # Only add if not already present
        for i in range(self.model.rowCount()):
            if (
                self.model.item(i)
                and self.model.item(i).text() == "Click here to add analysis"
            ):
                return

        item = QStandardItem("Click here to add analysis")
        item.setEditable(False)
        self.model.appendRow(item)

    def on_item_changed(self, item):
        if item.isCheckable():
            self.analysesChanged.emit()

    def on_double_click(self, index):
        item = self.model.itemFromIndex(index)
        if item.text() == "Click here to add analysis":
            # New Analysis
            dialog = AnalysisDialog(self)
            if dialog.exec():
                config = dialog.get_config()
                self.add_analysis(config)
        else:
            # Edit Analysis (parse type from text or data)
            # Store config in user role?
            config = item.data(Qt.ItemDataRole.UserRole)
            if config:
                dialog = AnalysisDialog(self, config)
                if dialog.exec():
                    new_config = dialog.get_config()
                    self.add_analysis(new_config, item)

    def show_context_menu(self, position):
        index = self.tree_view.indexAt(position)
        if not index.isValid():
            return

        item = self.model.itemFromIndex(index)

        # Don't show context menu for the placeholder or child items (parameters)
        if item.text() == "Click here to add analysis" or item.parent() is not None:
            return

        from PyQt6.QtWidgets import QMenu

        menu = QMenu()
        remove_action = menu.addAction("Remove Analysis")

        action = menu.exec(self.tree_view.viewport().mapToGlobal(position))
        if action == remove_action:
            if item.checkState() == Qt.CheckState.Checked:
                # Need to emit signal if removing an active analysis
                emit = True
            else:
                emit = False
            self.model.removeRow(item.row())
            if emit:
                self.analysesChanged.emit()

    def add_analysis(self, config, existing_item=None):
        an_type = config.get("type")
        text = f"{an_type} Analysis"

        # Determine Check State
        enabled = config.get("enabled", True)
        check_state = Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked

        if existing_item:
            parent_item = existing_item
            parent_item.setText(text)
            parent_item.setData(config, Qt.ItemDataRole.UserRole)
            parent_item.setCheckState(check_state)

            # Clear children to rebuild
            if parent_item.hasChildren():
                parent_item.removeRows(0, parent_item.rowCount())
        else:
            # Check if we have "Click here..."
            root = self.model.invisibleRootItem()
            count = root.rowCount()

            # Find insertion point (before placeholder)
            placeholder_row = -1
            for i in range(count):
                if root.child(i).text() == "Click here to add analysis":
                    placeholder_row = i
                    break

            parent_item = QStandardItem(text)
            parent_item.setEditable(False)
            parent_item.setData(config, Qt.ItemDataRole.UserRole)
            parent_item.setCheckable(True)
            parent_item.setCheckState(check_state)

            if placeholder_row != -1:
                self.model.insertRow(placeholder_row, parent_item)
            else:
                self.model.appendRow(parent_item)

        # Add Parameters as Children
        # Config has keys like 'start', 'stop', 'source', etc.
        # We can format them nicely.
        for key, value in config.items():
            if key in ("type", "enabled"):
                continue
            if not value:
                continue

            child_text = f"{key}: {value}"
            child = QStandardItem(child_text)
            child.setEditable(False)
            parent_item.appendRow(child)

        # Expand
        self.tree_view.expand(self.model.indexFromItem(parent_item))

        if not self.signalsBlocked():
            self.analysesChanged.emit()

    def get_all_analyses(self):
        analyses = []
        root = self.model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            if item.text() != "Click here to add analysis":
                config = item.data(Qt.ItemDataRole.UserRole) or {}
                # Update enabled state
                config["enabled"] = item.checkState() == Qt.CheckState.Checked
                analyses.append(config)
        return analyses

    def restore_analyses(self, analyses_list):
        # Using beginResetModel/endResetModel is the safest way to clear/reset
        self.model.beginResetModel()
        try:
            # Use removeRows to avoid QStandardItemModel.clear()'s internal reset signals
            self.model.removeRows(0, self.model.rowCount())

            # Add analyses
            self.blockSignals(True)
            for config in analyses_list:
                # Convert old boolean or string to boolean if needed
                if "enabled" in config and isinstance(config["enabled"], str):
                    config["enabled"] = config["enabled"].lower() == "true"

                self.add_analysis(config)

            # Add placeholder at end
            self.add_placeholder()
        finally:
            self.blockSignals(False)
            self.model.endResetModel()

    def get_current_analysis_type(self):
        """Returns the type of the currently selected analysis, or the first active one."""
        # 1. Check selection
        indexes = self.tree_view.selectedIndexes()
        if indexes:
            item = self.model.itemFromIndex(indexes[0])
            config = item.data(Qt.ItemDataRole.UserRole)
            if config and "type" in config:
                return config["type"]

        # 2. Fallback to first enabled analysis
        root = self.model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            if item.checkState() == Qt.CheckState.Checked:
                config = item.data(Qt.ItemDataRole.UserRole)
                if config and "type" in config:
                    return config["type"]

        return "Tran"  # Default


class AnalysisDialog(QDialog):
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Analysis Setup")

        self.layout = QVBoxLayout(self)

        # Type Selection
        self.type_combo = QComboBox()
        self.type_combo.addItems(["DC", "AC", "Tran", "OP"])
        self.type_combo.currentIndexChanged.connect(self.on_type_changed)
        self.layout.addWidget(self.type_combo)

        # Stacked Parameters
        self.stack = QStackedWidget()
        self.layout.addWidget(self.stack)

        # DC Page
        self.dc_page = QWidget()
        self.dc_layout = QFormLayout(self.dc_page)
        self.dc_source = QLineEdit()
        self.dc_start = QLineEdit()
        self.dc_stop = QLineEdit()
        self.dc_step = QLineEdit()
        self.dc_layout.addRow("Source Name:", self.dc_source)
        self.dc_layout.addRow("Start:", self.dc_start)
        self.dc_layout.addRow("Stop:", self.dc_stop)
        self.dc_layout.addRow("Step:", self.dc_step)
        self.stack.addWidget(self.dc_page)

        # AC Page
        self.ac_page = QWidget()
        self.ac_layout = QFormLayout(self.ac_page)
        self.ac_type = QComboBox()
        self.ac_type.addItems(["LIN", "DEC", "OCT"])
        self.ac_points = QLineEdit()
        self.ac_start = QLineEdit()
        self.ac_start_freq_unit = QLineEdit("1Hz")  # Optional unit handling?
        self.ac_stop = QLineEdit()
        self.ac_layout.addRow("Type:", self.ac_type)
        self.ac_layout.addRow("Points:", self.ac_points)
        self.ac_layout.addRow("Start Freq:", self.ac_start)
        self.ac_layout.addRow("Stop Freq:", self.ac_stop)
        self.stack.addWidget(self.ac_page)

        # Tran Page
        self.tran_page = QWidget()
        self.tran_layout = QFormLayout(self.tran_page)
        self.tran_step = QLineEdit("1u")
        self.tran_stop = QLineEdit("100u")
        self.tran_start = QLineEdit()
        self.tran_save_all = QCheckBox("Save all signals (voltages + currents)")
        self.tran_save_all.setChecked(True)
        self.tran_layout.addRow("Step Time:", self.tran_step)
        self.tran_layout.addRow("Stop Time:", self.tran_stop)
        self.tran_layout.addRow("Start Time (optional):", self.tran_start)
        self.tran_layout.addRow("", self.tran_save_all)
        self.stack.addWidget(self.tran_page)

        # OP Page
        self.op_page = QWidget()
        self.op_layout = QVBoxLayout(self.op_page)
        self.op_layout.addWidget(QLabel("Operating Point Analysis (no parameters)"))
        self.stack.addWidget(self.op_page)

        # Buttons
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

        if config:
            self.load_config(config)
        else:
            self.on_type_changed(0)

    def on_type_changed(self, index):
        self.stack.setCurrentIndex(index)

    def get_config(self):
        an_type = self.type_combo.currentText()
        config = {"type": an_type}

        if an_type == "DC":
            config["source"] = self.dc_source.text()
            config["start"] = self.dc_start.text()
            config["stop"] = self.dc_stop.text()
            config["step"] = self.dc_step.text()
        elif an_type == "AC":
            config["ac_type"] = self.ac_type.currentText()
            config["points"] = self.ac_points.text()
            config["start"] = self.ac_start.text()
            config["stop"] = self.ac_stop.text()
        elif an_type == "Tran":
            config["stop"] = self.tran_stop.text()
            config["start"] = self.tran_start.text()
            config["step"] = self.tran_step.text()
            config["save_all"] = self.tran_save_all.isChecked()
        elif an_type == "OP":
            pass  # No extra params

        return config

    def load_config(self, config):
        an_type = config.get("type", "DC")
        self.type_combo.setCurrentText(an_type)

        if an_type == "DC":
            self.dc_source.setText(config.get("source", ""))
            self.dc_start.setText(config.get("start", ""))
            self.dc_stop.setText(config.get("stop", ""))
            self.dc_step.setText(config.get("step", ""))
        elif an_type == "AC":
            self.ac_type.setCurrentText(config.get("ac_type", "LIN"))
            self.ac_points.setText(config.get("points", ""))
            self.ac_start.setText(config.get("start", ""))
            self.ac_stop.setText(config.get("stop", ""))
        elif an_type == "Tran":
            self.tran_stop.setText(config.get("stop", ""))
            self.tran_start.setText(config.get("start", ""))
            self.tran_step.setText(config.get("step", ""))

            save_all = config.get("save_all", "True")
            if isinstance(save_all, str):
                save_all = save_all.lower() == "true"
            self.tran_save_all.setChecked(bool(save_all))
        elif an_type == "OP":
            pass
