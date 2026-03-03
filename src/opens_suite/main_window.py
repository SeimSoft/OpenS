import json
import xml.etree.ElementTree as ET
from PyQt6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QToolBar,
    QMenuBar,
    QMenu,
    QFileDialog,
    QMessageBox,
    QWidget,
    QVBoxLayout,
    QDialog,
    QTextEdit,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QColorDialog,
    QFrame,
    QLabel,
    QHBoxLayout,
    QComboBox,
    QCheckBox,
    QStyle,
    QListWidget,
    QListWidgetItem,
)
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtCore import Qt, QPointF, QProcess, QSettings, QSize
from opens_suite.properties_widget import PropertiesWidget
from opens_suite.analysis_widget import AnalysisWidget
from opens_suite.schematic_view import SchematicView, SchematicScene
from opens_suite.library import LibraryWidget
from opens_suite.schematic_item import SchematicItem
from opens_suite.wire import Wire, Junction
from opens_suite.netlister import NetlistGenerator
from opens_suite.symbol_generator import SymbolGenerator
from opens_suite.symbol_editor import SymbolView
from opens_suite.calculator_widget import CalculatorDialog
from opens_suite.outputs_widget import OutputsWidget
from opens_suite.results_selection_widget import ResultsSelectionWidget
from opens_suite.plugin_manager import PluginManager
import os
import subprocess
from opens_suite.theme import theme_manager


class MainWindow(QMainWindow):
    def __init__(self, project_dir=None):
        super().__init__()
        self.setWindowTitle("OpenS - Schematic Entry")
        self.setWindowIcon(
            QIcon(os.path.join(os.path.dirname(__file__), "assets", "launcher.png"))
        )
        self.setGeometry(100, 100, 1920, 1080)
        self.project_dir = project_dir or os.getcwd()

        self.output_console = None  # Placeholder for future
        self.simulation_process = None
        self.current_simulation_view = None
        self.current_raw_path = None
        self.waveform_viewer = None

        # Load Icons
        self.play_icon = QIcon(
            os.path.join(os.path.dirname(__file__), "assets", "icons", "play.svg")
        )
        self.stop_icon = QIcon(
            os.path.join(os.path.dirname(__file__), "assets", "icons", "stop.svg")
        )
        self.calc_icon = QIcon(
            os.path.join(os.path.dirname(__file__), "assets", "icons", "calculator.svg")
        )
        self.probe_icon = QIcon(
            os.path.join(os.path.dirname(__file__), "assets", "icons", "probe.svg")
        )
        self.active_calculators = []
        self._probi_calc = None  # Track which calculator is probing

        self._setup_ui()
        self._create_actions()
        self._create_menus()
        self._create_toolbars()

        self.plugin_manager = PluginManager(self)
        self.plugin_manager.load_plugins()
        self._tabify_right_docks()

    def closeEvent(self, event):
        """Auto-save all tabs and close all child windows on exit."""
        # 1. Save all open schematic/symbol tabs
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            file_name = getattr(widget, "filename", None)
            if file_name:
                try:
                    if isinstance(widget, SymbolView):
                        widget.save_symbol(file_name)
                    elif isinstance(widget, SchematicView):
                        analyses = (
                            self.analysis_dock.get_all_analyses()
                            if hasattr(self, "analysis_dock")
                            else getattr(widget, "analyses", [])
                        )
                        outputs = (
                            self.outputs_dock.get_expressions_data()
                            if hasattr(self, "outputs_dock")
                            else getattr(widget, "outputs", [])
                        )
                        variables = (
                            self.variables_dock.get_variables()
                            if hasattr(self, "variables_dock")
                            else getattr(widget, "variables", [])
                        )
                        widget.save_schematic(
                            file_name,
                            analyses=analyses,
                            outputs=outputs,
                            variables=variables,
                        )
                    print(f"Auto-saved: {file_name}")
                except Exception as e:
                    print(f"Warning: Could not auto-save {file_name}: {e}")

        # 2. Close all active calculator windows
        for calc in list(self.active_calculators):
            try:
                calc.close()
            except (RuntimeError, AttributeError):
                pass
        self.active_calculators.clear()

        # 3. Terminate any running simulation process
        if (
            self.simulation_process
            and self.simulation_process.state() != QProcess.ProcessState.NotRunning
        ):
            self.simulation_process.kill()
            self.simulation_process.waitForFinished(3000)

        # 4. Close all matplotlib figures
        import matplotlib.pyplot as plt

        plt.close("all")

        event.accept()

    def _setup_ui(self):
        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        # Enable dock nesting and tabify support
        self.setDockNestingEnabled(True)
        self.setTabPosition(
            Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.South
        )

        # Status Bar
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")

    def _create_actions(self):
        # New Action
        self.new_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            "&New",
            self,
        )
        self.new_action.setShortcut("Ctrl+N")
        self.new_action.setStatusTip("Create a new schematic")
        self.new_action.triggered.connect(self.new_file)

        # Save Action
        self.save_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "&Save",
            self,
        )
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.setStatusTip("Save current schematic")
        self.save_action.triggered.connect(self.save_file)

        # Create Symbol Action
        self.create_symbol_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            "Create/Update Symbol",
            self,
        )
        self.create_symbol_action.setStatusTip(
            "Generate a symbol from the current schematic"
        )
        self.create_symbol_action.triggered.connect(self.create_symbol)

        # Exit Action
        self.exit_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton),
            "E&xit",
            self,
        )
        self.exit_action.setShortcut("Ctrl+Q")
        self.exit_action.setStatusTip("Exit application")
        self.exit_action.triggered.connect(self.close)

        # Undo Action
        self.undo_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack), "&Undo", self
        )
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.setStatusTip("Undo last action")
        self.undo_action.triggered.connect(self.undo)

        # Redo Action
        self.redo_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward),
            "&Redo",
            self,
        )
        self.redo_action.setShortcut("Ctrl+Shift+Z")
        self.redo_action.setStatusTip("Redo last undone action")
        self.redo_action.triggered.connect(self.redo)

        self.settings_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
            "&Settings...",
            self,
        )
        self.settings_action.setStatusTip("Configure application settings")
        self.settings_action.triggered.connect(self.show_settings)

    def _create_menus(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)

        view_menu = menubar.addMenu("&View")

        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(self.create_symbol_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.settings_action)

    def _create_toolbars(self):
        toolbar = QToolBar("File Toolbar")
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(toolbar)
        toolbar.addAction(self.new_action)
        toolbar.addAction(self.save_action)

        edit_toolbar = QToolBar("Edit Toolbar")
        edit_toolbar.setIconSize(QSize(16, 16))
        edit_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(edit_toolbar)
        edit_toolbar.addAction(self.undo_action)
        edit_toolbar.addAction(self.redo_action)

        sim_toolbar = QToolBar("Simulation Toolbar")
        sim_toolbar.setIconSize(QSize(16, 16))
        sim_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(sim_toolbar)
        sim_toolbar.addAction(self.create_symbol_action)
        sim_toolbar.addSeparator()
        self.show_labels_cb = QCheckBox("Show Wire Labels")
        self.show_labels_cb.setChecked(True)
        self.show_labels_cb.stateChanged.connect(self._on_show_labels_changed)
        sim_toolbar.addWidget(self.show_labels_cb)

    def _on_show_labels_changed(self, state):
        show = state == 2  # Qt.CheckState.Checked
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if hasattr(widget, "scene"):
                scene = widget.scene()
                if scene:
                    for item in scene.items():
                        if hasattr(item, "show_label"):
                            item.show_label = show
                            item.update()

    def update_status(self, message):
        self.status_bar.showMessage(message)

    def undo(self):
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, SchematicView):
            current_widget.undo_stack.undo()

    def redo(self):
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, SchematicView):
            current_widget.undo_stack.redo()

    def _on_selection_changed(self):
        view = self.tabs.currentWidget()
        if isinstance(view, (SchematicView, SymbolView)):
            try:
                scene = view.scene()
                if scene:
                    selection = scene.selectedItems()
                    if hasattr(self, "properties_dock"):
                        self.properties_dock.update_selection(selection)
                    if selection:
                        if hasattr(self, "properties_dock"):
                            self.properties_dock.show()
                            self.properties_dock.raise_()
                    else:
                        if hasattr(self, "library_dock"):
                            self.library_dock.show()
                            self.library_dock.raise_()
            except (RuntimeError, AttributeError):
                pass

    def _tabify_right_docks(self):
        # Find all dock widgets that have been placed in the right area
        right_docks = []
        # Specifically gather the known docks in a preferred order if possible,
        # or just gather all from RightDockWidgetArea
        for dock in self.findChildren(QDockWidget):
            if self.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea:
                right_docks.append(dock)

        if len(right_docks) > 1:
            # Tabify them all together
            for i in range(len(right_docks) - 1):
                self.tabifyDockWidget(right_docks[i], right_docks[i + 1])

            # Start with Library visible if it exists
            if hasattr(self, "library_dock"):
                self.library_dock.show()
                self.library_dock.raise_()

    def _on_tab_changed(self, index):
        if index < 0:
            return
        view = self.tabs.widget(index)
        if isinstance(view, SchematicView):
            # Reload all symbols in case they were modified in the symbol editor
            view.reload_symbols()

            # Sync Properties (if plugin loaded)
            self._on_selection_changed()
            self._update_action_states()
            if hasattr(self, "results_selection_dock"):
                self.results_selection_dock.set_scene(view.scene())

        pass
        view = self.tabs.currentWidget()
        has_results = False
        if isinstance(view, SchematicView):
            filename = getattr(view, "filename", None)
            if filename:
                sim_dir = os.path.join(os.path.dirname(filename), "simulation")
                base = os.path.splitext(os.path.basename(filename))[0]
                raw_path = os.path.join(sim_dir, f"{base}.raw")
                if os.path.exists(raw_path):
                    has_results = True

    def _update_action_states(self):
        pass

    def new_file(self):
        view = SchematicView()
        view.modeChanged.connect(self.update_status_mode)
        view.statusMessage.connect(self.update_status)
        view.openSubcircuitRequested.connect(self.open_file)

        # Connect Selection signals
        view.scene().selectionChanged.connect(self._on_selection_changed)

        if hasattr(self, "properties_dock"):
            self.properties_dock.propertyChanged.connect(view.recalculate_connectivity)

        index = self.tabs.addTab(view, "Untitled")
        self.tabs.setCurrentIndex(index)
        self.update_status(f"Mode: {view.current_mode}")

    def _get_tab_title(self, file_path):
        if not file_path:
            return "Untitled"
        import os

        basename = os.path.basename(file_path)
        cell = os.path.basename(os.path.dirname(os.path.abspath(file_path)))
        if cell and cell not in [".", ""]:
            return f"{cell}/{basename}"
        return basename

    def update_status_mode(self, mode):
        # Compatibility slot if needed, or just rely on statusMessage
        pass

    def open_file(self, file_name=None):
        if not file_name:
            file_name, _ = QFileDialog.getOpenFileName(
                self, "Open Schematic", "", "SVG Files (*.svg);;All Files (*)"
            )
        if file_name:
            import os

            file_name = os.path.abspath(file_name)

            # Check if file is already open
            for i in range(self.tabs.count()):
                widget = self.tabs.widget(i)
                if (
                    hasattr(widget, "filename")
                    and widget.filename
                    and os.path.abspath(widget.filename) == file_name
                ):
                    self.tabs.setCurrentIndex(i)
                    return

            try:
                if (
                    file_name.endswith(".sym.svg")
                    or os.path.basename(file_name) == "symbol.svg"
                ):
                    view = SymbolView()
                    view.filename = file_name
                    view.load_symbol(file_name)
                    view.statusMessage.connect(self.update_status)
                    view.symbol_scene.selectionChanged.connect(
                        self._on_selection_changed
                    )
                    self.tabs.addTab(view, self._get_tab_title(file_name))
                    self.tabs.setCurrentWidget(view)
                    self.update_status(f"Loaded symbol {file_name}")
                    return

                view = SchematicView()
                view.filename = file_name  # Track filename
                view.modeChanged.connect(self.update_status_mode)
                view.statusMessage.connect(self.update_status)
                view.openSubcircuitRequested.connect(self.open_file)

                # Connect Selection signals
                view.scene().selectionChanged.connect(self._on_selection_changed)

                if hasattr(self, "properties_dock"):
                    self.properties_dock.propertyChanged.connect(
                        view.recalculate_connectivity
                    )

                # Use unified loading logic
                view.load_schematic(file_name)

                # Load extra data (handled by plugins or view if needed, but for now we can read them)
                try:
                    tree = ET.parse(file_name)
                    root = tree.getroot()
                    analyses = []
                    for elem in root.iter("{http://opens-schematic.org}analysis"):
                        analyses.append(dict(elem.attrib))
                    view.analyses = analyses

                    if hasattr(self, "analysis_dock"):
                        self.analysis_dock.blockSignals(True)
                        self.analysis_dock.restore_analyses(analyses)
                        self.analysis_dock.blockSignals(False)

                    outputs = []
                    for elem in root.iter("{http://opens-schematic.org}output"):
                        if elem.text:
                            outputs.append(
                                {
                                    "expression": elem.text,
                                    "name": elem.attrib.get("name", ""),
                                    "unit": elem.attrib.get("unit", ""),
                                    "min": elem.attrib.get("min", ""),
                                    "max": elem.attrib.get("max", ""),
                                }
                            )
                    view.outputs = outputs

                    if hasattr(self, "outputs_dock"):
                        self.outputs_dock.blockSignals(True)
                        self.outputs_dock.restore_expressions(outputs)
                        self.outputs_dock.blockSignals(False)

                    variables = []
                    for elem in root.iter("{http://opens-schematic.org}variable"):
                        variables.append(dict(elem.attrib))
                    view.variables = variables

                    if hasattr(self, "variables_dock"):
                        self.variables_dock.blockSignals(True)
                        self.variables_dock.set_variables(variables)
                        self.variables_dock.blockSignals(False)
                except Exception:
                    pass

                self.tabs.addTab(view, self._get_tab_title(file_name))
                self.tabs.setCurrentWidget(view)
                self.update_status(f"Loaded {file_name}")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open file: {e}")
                import traceback

                traceback.print_exc()

    def save_file(self):
        current_widget = self.tabs.currentWidget()
        if not current_widget:
            return

        # Check for duplicate names
        if isinstance(current_widget, SchematicView):
            names = set()
            for item in current_widget.scene().items():
                if isinstance(item, SchematicItem) and getattr(item, "name", None):
                    if item.name in names:
                        QMessageBox.warning(
                            self,
                            "Validation Error",
                            f"Cannot save. Duplicate component name found: {item.name}",
                        )
                        return
                    names.add(item.name)

        file_name = getattr(current_widget, "filename", None)
        if not file_name:
            file_name, _ = QFileDialog.getSaveFileName(
                self, "Save Schematic", "", "SVG Files (*.svg);;All Files (*)"
            )

        if file_name:
            if not file_name.endswith(".svg"):
                file_name += ".svg"

            try:
                if isinstance(current_widget, SymbolView):
                    current_widget.save_symbol(file_name)
                else:
                    analyses = (
                        self.analysis_dock.get_all_analyses()
                        if hasattr(self, "analysis_dock")
                        else getattr(current_widget, "analyses", [])
                    )
                    outputs = (
                        self.outputs_dock.get_expressions_data()
                        if hasattr(self, "outputs_dock")
                        else getattr(current_widget, "outputs", [])
                    )
                    variables = (
                        self.variables_dock.get_variables()
                        if hasattr(self, "variables_dock")
                        else getattr(current_widget, "variables", [])
                    )
                    current_widget.save_schematic(
                        file_name,
                        analyses=analyses,
                        outputs=outputs,
                        variables=variables,
                    )

                index = self.tabs.currentIndex()
                self.tabs.setTabText(index, self._get_tab_title(file_name))
                self.update_status(f"Saved to {file_name}")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not save file: {e}")
                import traceback

                traceback.print_exc()

    def close_tab(self, index):
        widget = self.tabs.widget(index)
        if widget:
            widget.deleteLater()
            self.tabs.removeTab(index)

    def create_symbol(self):
        view = self.tabs.currentWidget()
        if not isinstance(view, SchematicView):
            return

        # 1. Ensure File is Saved
        filename = getattr(view, "filename", None)

        if not filename:
            res = QMessageBox.question(
                self,
                "Save Schematic",
                "The schematic must be saved before creating a symbol. Save now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res == QMessageBox.StandardButton.Yes:
                self.save_file()
                filename = getattr(view, "filename", None)
                if not filename:
                    return
            else:
                return

        # 2. Save current state
        view.save_schematic(filename)

        # Compute expected symbol path
        if filename.endswith(".sch.svg"):
            base_path = filename[:-8]
        elif filename.endswith(".svg"):
            base_path = filename[:-4]
        else:
            base_path = filename
        symbol_path = base_path + ".sym.svg"

        if os.path.exists(symbol_path):
            res = QMessageBox.question(
                self,
                "Overwrite Symbol",
                f"A symbol already exists at {symbol_path}.\nDo you want to overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return

        # 3. Generate Symbol
        try:
            symbol_path = SymbolGenerator.generate_symbol(filename, symbol_path)
            if symbol_path:
                QMessageBox.information(
                    self, "Success", f"Symbol saved to {symbol_path}"
                )

                # 4. Refresh Library
                self.library_dock._populate_library()  # Re-scan

                # 5. Open in Editor
                self.open_file(symbol_path)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate symbol: {e}")
            import traceback

            traceback.print_exc()

    def show_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(500, 450)
        self.settings = QSettings("OpenS", "OpenS")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Code Editor
        self.editor_edit = QLineEdit()
        self.editor_edit.setPlaceholderText("e.g. code '%s'")
        self.editor_edit.setText(self.settings.value("editor_command", "code '%s'"))
        form.addRow("Code Editor Command:", self.editor_edit)

        # Xyce: nodcpath resistance
        self.nodcpath_edit = QLineEdit()
        self.nodcpath_edit.setPlaceholderText("e.g. 1G (empty to disable)")
        self.nodcpath_edit.setText(self.settings.value("nodcpath_resistance", "1G"))
        form.addRow(".preprocess nodcpath R:", self.nodcpath_edit)

        # Library Search Paths
        self.lib_paths_list = QListWidget()
        self.lib_paths_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lib_paths_list.customContextMenuRequested.connect(
            self._show_lib_paths_menu
        )

        # Default internal path
        default_lib = os.path.join(os.path.dirname(__file__), "assets", "libraries")
        item = QListWidgetItem(default_lib)
        item.setData(Qt.ItemDataRole.UserRole, "default")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.lib_paths_list.addItem(item)

        # Project Dir path
        if parent and hasattr(parent, "project_dir"):
            item = QListWidgetItem(parent.project_dir)
            item.setData(Qt.ItemDataRole.UserRole, "default")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.lib_paths_list.addItem(item)

        custom_paths_str = self.settings.value("library_search_paths", "")
        for p in custom_paths_str.split(","):
            p = p.strip()
            if p:
                item = QListWidgetItem(p)
                item.setData(Qt.ItemDataRole.UserRole, "custom")
                self.lib_paths_list.addItem(item)

        form.addRow("Library Search Paths:", self.lib_paths_list)

        layout.addLayout(form)

        # Separator Line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Theme Presets
        theme_layout = QHBoxLayout()
        theme_layout.addWidget(QLabel("Theme Presets:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Custom", "Bright Theme", "Dark (Virtuoso)"])
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        theme_layout.addWidget(self.preset_combo)
        layout.addLayout(theme_layout)

        # Colors
        self.color_buttons = {}
        colors_form = QFormLayout()
        color_labels = {
            "background_schematic": "Schematic Background",
            "grid_dots": "Grid Dots",
            "line_default": "Component/Wire Lines",
            "line_mode": "Line Mode Color",
            "font_label": "Instance Label Font",
            "font_voltage": "Op Voltage Font",
            "font_default": "Default Font",
            "junction": "Wire Junctions",
        }

        for key, text in color_labels.items():
            btn = QPushButton()
            btn.setFixedWidth(100)
            initial_color = theme_manager.colors[key]
            self._update_button_color(btn, initial_color)
            btn._color = initial_color  # Initialize
            btn.clicked.connect(lambda checked, k=key, b=btn: self._pick_color(k, b))
            self.color_buttons[key] = btn
            colors_form.addRow(text + ":", btn)

        layout.addLayout(colors_form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_lib_paths_menu(self, pos):
        menu = QMenu(self)
        add_action = menu.addAction("Add Path...")
        remove_action = menu.addAction("Remove Selected")

        action = menu.exec(self.lib_paths_list.mapToGlobal(pos))
        if action == add_action:
            path = QFileDialog.getExistingDirectory(self, "Select Library Directory")
            if path:
                item = QListWidgetItem(path)
                item.setData(Qt.ItemDataRole.UserRole, "custom")
                self.lib_paths_list.addItem(item)
        elif action == remove_action:
            for item in self.lib_paths_list.selectedItems():
                if item.data(Qt.ItemDataRole.UserRole) == "custom":
                    self.lib_paths_list.takeItem(self.lib_paths_list.row(item))

    def _update_button_color(self, btn, color_name):
        btn.setStyleSheet(f"background-color: {color_name}; border: 1px solid #777;")

    def _pick_color(self, key, btn):
        current_color = theme_manager.get_color(key)
        color = QColorDialog.getColor(current_color, self, f"Pick {key}")
        if color.isValid():
            self._update_button_color(btn, color.name())
            self.color_buttons[key]._color = color.name()  # Temp storage
            self.preset_combo.setCurrentIndex(0)  # Switch to custom

    def _on_preset_changed(self, index):
        if index == 1:  # Bright
            self._apply_preset_to_ui(theme_manager.BRIGHT_THEME)
        elif index == 2:  # Dark
            self._apply_preset_to_ui(theme_manager.DARK_THEME)

    def _apply_preset_to_ui(self, preset):
        for key, val in preset.items():
            if key in self.color_buttons:
                self._update_button_color(self.color_buttons[key], val)
                self.color_buttons[key]._color = val

    def save(self):
        self.settings.setValue("editor_command", self.editor_edit.text())
        self.settings.setValue("nodcpath_resistance", self.nodcpath_edit.text().strip())

        custom_paths = []
        for i in range(self.lib_paths_list.count()):
            item = self.lib_paths_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == "custom":
                custom_paths.append(item.text().strip())
        self.settings.setValue("library_search_paths", ",".join(custom_paths))
        # Save colors
        for key, btn in self.color_buttons.items():
            if hasattr(btn, "_color"):
                theme_manager.set_color(key, btn._color)
        self.accept()
