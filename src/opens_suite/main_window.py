import json
import xml.etree.ElementTree as ET
import qtawesome as qta
from PyQt6.QtWidgets import (
    QApplication,
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
from opens_suite.xyce_updater import XyceUpdater, XyceUpdateWorker
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
        self.play_icon = qta.icon("mdi6.play", color="#005A9C")
        self.stop_icon = qta.icon("mdi6.stop", color="#d9534f")
        self.calc_icon = qta.icon("mdi6.calculator", color="#1f1f1f")
        self.probe_icon = qta.icon("mdi6.crosshairs-gps", color="#1f1f1f")
        self.undo_icon = qta.icon("mdi6.undo", color="#1f1f1f")
        self.redo_icon = qta.icon("mdi6.redo", color="#1f1f1f")
        self.report_icon = qta.icon("mdi6.chart-bar", color="#1f1f1f")
        self.symbol_icon = qta.icon("mdi6.shape", color="#1f1f1f")
        self.labels_icon = qta.icon("mdi6.label", color="#1f1f1f")
        self.active_calculators = []
        self._probi_calc = None  # Track which calculator is probing

        self._setup_ui()
        self._create_actions()
        self._create_menus()
        self._create_toolbars()

        self.plugin_manager = PluginManager(self)
        self.plugin_manager.load_plugins()
        self._tabify_right_docks()

        # Check for Xyce updates in the background
        self._check_for_xyce_updates()

    def _check_for_xyce_updates(self, force=False):
        self._xyce_updater = XyceUpdater(self)
        self._xyce_updater.updateAvailable.connect(self._on_xyce_update_available)
        if force:
            self._xyce_updater.noUpdateAvailable.connect(
                lambda: QMessageBox.information(
                    self, "Up to date", "Xyce is already up to date."
                )
            )
            self._xyce_updater.errorOccurred.connect(
                lambda msg: QMessageBox.warning(self, "Update Error", msg)
            )
        self._xyce_updater.check_for_updates(force=force)

    def _on_xyce_update_available(self, info):
        res = QMessageBox.question(
            self,
            "Xyce Update Available",
            f"A new Xyce release ({info['version']}) is available. Do you want to download and install it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            self._install_xyce_update(info)

    def _install_xyce_update(self, info):
        self.update_status(f"Downloading Xyce {info['version']}...")
        from PyQt6.QtWidgets import QProgressDialog

        self.progress_dialog = QProgressDialog(
            "Downloading Xyce...", "Cancel", 0, 100, self
        )
        self.progress_dialog.setWindowTitle("Xyce Update")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)

        self._xyce_update_worker = XyceUpdateWorker(
            info["download_url"], self._xyce_updater.base_dir
        )
        self._xyce_update_worker.progressChanged.connect(self._on_update_progress)
        self._xyce_update_worker.finished.connect(
            lambda s, m: self._on_update_finished(s, m, info)
        )

        self.progress_dialog.canceled.connect(self._xyce_update_worker.terminate)
        self._xyce_update_worker.start()

    def _on_update_progress(self, percent, text):
        if hasattr(self, "progress_dialog"):
            self.progress_dialog.setLabelText(text)
            self.progress_dialog.setValue(percent)

    def _on_update_finished(self, success, message, info):
        if hasattr(self, "progress_dialog"):
            self.progress_dialog.close()

        if success:
            self._xyce_updater.save_local_info(info)
            self.update_status("Xyce updated successfully.")
            QMessageBox.information(
                self, "Update Complete", "Xyce update installed successfully."
            )
        else:
            self.update_status("Xyce update failed.")
            QMessageBox.critical(
                self, "Update Failed", f"Failed to install Xyce update:\n{message}"
            )

    def closeEvent(self, event):
        """Close all child windows on exit (auto-save disabled)."""
        # 1. Close all active calculator windows
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
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._on_tab_context_menu)

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
        self.save_icon = qta.icon("mdi6.content-save", color="#1f1f1f")
        self.save_action = QAction(
            self.save_icon,
            "&Save",
            self,
        )
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.setStatusTip("Save current schematic")
        self.save_action.triggered.connect(self.save_file)

        # Create Symbol Action
        self.create_symbol_action = QAction(
            self.symbol_icon,
            "Create/Update Symbol",
            self,
        )
        self.create_symbol_action.setStatusTip(
            "Generate a symbol from the current schematic"
        )
        self.create_symbol_action.triggered.connect(self.create_symbol)

        # Generate Report Action
        self.generate_report_action = QAction(
            self.report_icon,
            "Generate Report",
            self,
        )
        self.generate_report_action.setStatusTip(
            "Generate a headless HTML simulation report for this schematic"
        )
        self.generate_report_action.triggered.connect(self.generate_report)

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
        self.undo_action = QAction(self.undo_icon, "&Undo", self)
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.setStatusTip("Undo last action")
        self.undo_action.triggered.connect(self.undo)

        # Redo Action
        self.redo_action = QAction(self.redo_icon, "&Redo", self)
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
        tools_menu.addAction(self.generate_report_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.settings_action)

    def _create_toolbars(self):
        toolbar = QToolBar("File Toolbar")
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(toolbar)
        toolbar.addAction(self.save_action)

        edit_toolbar = QToolBar("Edit Toolbar")
        edit_toolbar.setIconSize(QSize(24, 24))
        edit_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(edit_toolbar)
        edit_toolbar.addAction(self.undo_action)
        edit_toolbar.addAction(self.redo_action)

        sim_toolbar = QToolBar("Simulation Toolbar")
        sim_toolbar.setIconSize(QSize(24, 24))
        sim_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(sim_toolbar)
        sim_toolbar.addAction(self.create_symbol_action)
        sim_toolbar.addAction(self.generate_report_action)
        sim_toolbar.addSeparator()
        self.show_labels_action = QAction(self.labels_icon, "Show Wire Labels", self)
        self.show_labels_action.setCheckable(True)
        self.show_labels_action.setChecked(True)
        self.show_labels_action.toggled.connect(self._on_show_labels_changed)
        sim_toolbar.addAction(self.show_labels_action)

    def _on_show_labels_changed(self, checked):
        show = checked
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
            owner_view = self.get_simulation_owner_view(view)

            # Reload all symbols in case they were modified in the symbol editor
            view.reload_symbols()

            # Sync Properties (if plugin loaded)
            self._on_selection_changed()
            self._update_action_states()

            # Ensure Analysis/Variables/Outputs dock widgets reflect the active schematic
            if hasattr(self, "analysis_dock"):
                self.analysis_dock.blockSignals(True)
                self.analysis_dock.restore_analyses(
                    getattr(owner_view, "analyses", [])
                )
                self.analysis_dock.blockSignals(False)

            if hasattr(self, "variables_dock"):
                self.variables_dock.blockSignals(True)
                self.variables_dock.set_variables(getattr(owner_view, "variables", []))
                self.variables_dock.blockSignals(False)

            if hasattr(self, "outputs_dock"):
                self.outputs_dock.blockSignals(True)
                self.outputs_dock.restore_expressions(getattr(owner_view, "outputs", []))
                self.outputs_dock.blockSignals(False)
                self.outputs_dock.hierarchy_prefix = getattr(
                    view, "hierarchy_prefix", ""
                )

            if hasattr(self, "results_selection_dock"):
                self.results_selection_dock.set_scene(view.scene())

        # Existing behavior around showing recent simulation results can remain
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

    def get_simulation_owner_view(self, view=None):
        """Return the top-level owner view used for analysis/variables/simulation.

        Subcircuit tabs inherit their owner's simulation context until they are
        explicitly promoted to top-level via the tab context menu.
        """
        if view is None:
            view = self.tabs.currentWidget()
        if not isinstance(view, SchematicView):
            return view
        owner = getattr(view, "_simulation_owner_view", None)
        if isinstance(owner, SchematicView):
            return owner
        return view

    def _update_action_states(self):
        pass

    @staticmethod
    def _full_net_name(prefix, net_name):
        if not net_name:
            return None
        net_name = str(net_name)
        if ":" in net_name:
            return net_name
        return f"{prefix}{net_name}"

    @staticmethod
    def _item_matches_instance_name(sch_item, inst_name):
        item_name = getattr(sch_item, "name", "") or ""
        if item_name == inst_name:
            return True

        # Schematic item names are often like "X3", while double-click emits
        # Xyce-style instance names like "X_3".
        prefix = getattr(sch_item, "prefix", "") or ""
        idx = item_name
        if prefix and idx.startswith(prefix):
            idx = idx[len(prefix) :]
        if idx:
            return f"X_{idx}" == inst_name
        return False

    def _derive_child_highlight_context(self, parent_view, inst_name, child_prefix):
        """Map highlighted parent nets to child context when diving into a subcircuit.

        Returns:
            (propagated_full_names, highlighted_child_pin_ids)
        """
        highlights = set(getattr(self, "_net_highlight_full_names", set()))
        if not highlights:
            return set(), set()

        propagated = {n for n in highlights if n.startswith(child_prefix)}
        pin_ids = set()
        item_map = getattr(parent_view, "last_item_to_node", {})
        parent_prefix = getattr(parent_view, "hierarchy_prefix", "")
        for key, net_name in item_map.items():
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            sch_item, pin_id = key
            if not isinstance(sch_item, SchematicItem):
                continue
            if not self._item_matches_instance_name(sch_item, inst_name):
                continue
            parent_full = self._full_net_name(parent_prefix, net_name)
            if parent_full in highlights:
                pin_ids.add(str(pin_id))
                propagated.add(f"{child_prefix}{pin_id}")
        return propagated, pin_ids

    def _derive_child_highlight_names(self, parent_view, inst_name, child_prefix):
        # Backward-compatible wrapper used by tests and callers expecting only names.
        names, _ = self._derive_child_highlight_context(
            parent_view, inst_name, child_prefix
        )
        return names

    def _derive_child_pin_parent_nets(self, parent_view, inst_name):
        """Map child pin IDs to fully-qualified parent net names for one instance."""
        pin_to_parent = {}
        item_map = getattr(parent_view, "last_item_to_node", {})
        parent_prefix = getattr(parent_view, "hierarchy_prefix", "")
        for key, net_name in item_map.items():
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            sch_item, pin_id = key
            if not isinstance(sch_item, SchematicItem):
                continue
            if not self._item_matches_instance_name(sch_item, inst_name):
                continue
            parent_full = self._full_net_name(parent_prefix, net_name)
            if parent_full:
                pin_to_parent[str(pin_id)] = parent_full
        return pin_to_parent

    def _open_subcircuit_from_view(self, parent_view, path, inst_name):
        child_prefix = parent_view.hierarchy_prefix + inst_name + ":"
        owner_view = self.get_simulation_owner_view(parent_view)
        propagated, pin_ids = self._derive_child_highlight_context(
            parent_view, inst_name, child_prefix
        )
        pin_parent_nets = self._derive_child_pin_parent_nets(parent_view, inst_name)
        if propagated:
            if not hasattr(self, "_net_highlight_full_names"):
                self._net_highlight_full_names = set()
            self._net_highlight_full_names.update(propagated)

        self.open_file(
            path,
            parent_breadcrumb=self._get_view_breadcrumb(parent_view),
            hierarchy_instance=inst_name,
            hierarchy_prefix=child_prefix,
            raw_path=getattr(parent_view, "current_raw_path", None),
            highlighted_full_names=propagated,
            highlighted_pin_ids=pin_ids,
            child_pin_parent_nets=pin_parent_nets,
            simulation_owner_view=owner_view,
        )

    def new_file(self):
        view = SchematicView()
        view.modeChanged.connect(self.update_status_mode)
        view.statusMessage.connect(self.update_status)
        view.openSubcircuitRequested.connect(
            lambda path, inst, v=view: self._open_subcircuit_from_view(v, path, inst)
        )
        view.modificationChanged.connect(lambda: self._update_tab_title_for_view(view))
        view.returnToParentRequested.connect(lambda v=view: self.close_tab(self.tabs.indexOf(v)))

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

    def open_file(
        self,
        file_name=None,
        parent_breadcrumb="",
        hierarchy_instance="",
        hierarchy_prefix="",
        raw_path=None,
        highlighted_full_names=None,
        highlighted_pin_ids=None,
        child_pin_parent_nets=None,
        simulation_owner_view=None,
    ):
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
                    if getattr(widget, "hierarchy_prefix", "") == hierarchy_prefix:
                        # Exact same instance/top-level is already open, just switch to it
                        self.tabs.setCurrentIndex(i)
                        if simulation_owner_view is not None:
                            widget._simulation_owner_view = simulation_owner_view
                        if highlighted_pin_ids is not None:
                            widget._highlight_pin_ids = set(highlighted_pin_ids)
                        if child_pin_parent_nets is not None:
                            widget._child_pin_parent_nets = dict(child_pin_parent_nets)
                        if hasattr(widget, "apply_net_highlight_full_names"):
                            widget.apply_net_highlight_full_names(
                                highlighted_full_names
                                or getattr(self, "_net_highlight_full_names", set())
                            )
                        return
                    else:
                        # File is open but user wants to view it from a different hierarchical path.
                        # Close the existing tab first to maintain single-open-tab rule per file.
                        self.close_tab(i)
                        break

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
                view.parent_breadcrumb = parent_breadcrumb
                view.hierarchy_instance = hierarchy_instance
                view.hierarchy_prefix = hierarchy_prefix
                view._highlight_pin_ids = set(highlighted_pin_ids or [])
                view._child_pin_parent_nets = dict(child_pin_parent_nets or {})
                view._simulation_owner_view = (
                    simulation_owner_view if simulation_owner_view is not None else view
                )

                view.modeChanged.connect(self.update_status_mode)
                view.statusMessage.connect(self.update_status)
                view.openSubcircuitRequested.connect(
                    lambda path, inst, v=view: self._open_subcircuit_from_view(
                        v, path, inst
                    )
                )
                view.modificationChanged.connect(
                    lambda m, v=view: self._update_tab_title_for_view(v)
                )

                # Connect Selection signals
                view.scene().selectionChanged.connect(self._on_selection_changed)

                if hasattr(self, "properties_dock"):
                    self.properties_dock.propertyChanged.connect(
                        view.recalculate_connectivity
                    )

                # Use unified loading logic
                view.load_schematic(file_name)

                # Re-apply existing hierarchical net highlights for this tab.
                active_highlights = highlighted_full_names
                if active_highlights is None:
                    active_highlights = getattr(self, "_net_highlight_full_names", set())
                if active_highlights and hasattr(view, "apply_net_highlight_full_names"):
                    view.apply_net_highlight_full_names(active_highlights)

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

                    # Load design points from JSON files into Variables dock
                    if hasattr(self, "variables_dock"):
                        from opens_suite.design_points import DesignPoints
                        from opens_suite.schematic_item import SchematicItem
                        schematic_dir = os.path.dirname(os.path.abspath(file_name))
                        json_files = []
                        for si in view.scene().items():
                            if isinstance(si, SchematicItem):
                                script_name = si.parameters.get("SCRIPT", "")
                                if script_name.endswith(".ipynb") and schematic_dir:
                                    json_name = script_name.replace(".ipynb", ".json")
                                    json_path = os.path.join(schematic_dir, json_name)
                                    if os.path.exists(json_path) and json_path not in json_files:
                                        json_files.append(json_path)
                        if json_files:
                            try:
                                dps = DesignPoints(json_files)
                                # Inject GUI variables so they show as user vars, not duplicated as DPs
                                self.variables_dock.set_design_points(dps)
                            except Exception as e:
                                print(f"Warning: Failed to load design points on open: {e}")

                except Exception:
                    pass

                # Propagate results if available
                if not raw_path and hierarchy_prefix:
                    # Try to find parent's raw path from the currently shown tab
                    parent_view = self.tabs.currentWidget()
                    if parent_view and hasattr(parent_view, "current_raw_path"):
                        raw_path = parent_view.current_raw_path
                    if not raw_path and parent_view:
                        # Fallback: compute from parent's filename
                        parent_fn = getattr(parent_view, "filename", None)
                        if parent_fn:
                            p_sim_dir = os.path.join(os.path.dirname(parent_fn), "simulation")
                            p_base = os.path.splitext(os.path.basename(parent_fn))[0]
                            candidate = os.path.join(p_sim_dir, f"{p_base}.raw")
                            if os.path.exists(candidate):
                                raw_path = candidate

                if raw_path and os.path.exists(raw_path) and hasattr(view, "load_simulation_results"):
                    view.load_simulation_results(raw_path)

                self.tabs.addTab(view, "Loading...")
                self._update_tab_title_for_view(view)
                self.tabs.setCurrentWidget(view)
                self.update_status(f"Loaded {file_name}")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open file: {e}")
                import traceback

                traceback.print_exc()

    def _get_view_breadcrumb(self, view):
        """Return the breadcrumb title for a view (without the '*' modified marker)."""
        base_title = self._get_tab_title(getattr(view, "filename", None))
        if hasattr(view, "parent_breadcrumb") and view.parent_breadcrumb:
            return f"{view.parent_breadcrumb} > {getattr(view, 'hierarchy_instance', '?')}: {base_title}"
        return base_title

    def _update_tab_title_for_view(self, view):
        index = self.tabs.indexOf(view)
        if index != -1:
            title = self._get_view_breadcrumb(view)
            if hasattr(view, "is_modified") and view.is_modified():
                title += "*"
            self.tabs.setTabText(index, title)

    def _on_tab_context_menu(self, pos):
        index = self.tabs.tabBar().tabAt(pos)
        if index == -1:
            return

        menu, actions = self._create_tab_context_menu(index)
        if menu is None:
            return

        action = menu.exec(self.tabs.tabBar().mapToGlobal(pos))
        if action == actions["save"]:
            self._save_tab(index)
        elif action == actions["copy_path"]:
            self._copy_tab_path(index)
        elif action == actions["close"]:
            self.close_tab(index)
        elif action == actions["close_others"]:
            self._close_other_tabs(index)
        elif action == actions["close_all"]:
            self._close_all_tabs()
        elif action == actions["make_top"]:
            view = self.tabs.widget(index)
            view.hierarchy_prefix = ""
            view.parent_breadcrumb = ""
            view.hierarchy_instance = ""
            view._simulation_owner_view = view
            self._update_tab_title_for_view(view)
            # Re-sync docks
            self._on_tab_changed(index)

    def _create_tab_context_menu(self, index):
        view = self.tabs.widget(index)
        if not isinstance(view, SchematicView):
            return None, None

        menu = QMenu(self)
        file_path = getattr(view, "filename", None)
        actions = {
            "save": menu.addAction("Save"),
            "copy_path": menu.addAction("Copy Path"),
            "close": menu.addAction("Close"),
            "close_others": menu.addAction("Close Others"),
            "close_all": menu.addAction("Close All"),
        }
        actions["copy_path"].setEnabled(bool(file_path))
        menu.addSeparator()
        actions["make_top"] = menu.addAction("Make Top Level")
        return menu, actions

    def _copy_tab_path(self, index):
        if index < 0 or index >= self.tabs.count():
            return

        widget = self.tabs.widget(index)
        file_path = getattr(widget, "filename", None)
        if not file_path:
            self.update_status("No file path available for this tab")
            return

        QApplication.clipboard().setText(file_path)
        self.update_status(f"Copied path: {file_path}")

    def _save_tab(self, index):
        if index < 0 or index >= self.tabs.count():
            return

        previous_index = self.tabs.currentIndex()
        self.tabs.setCurrentIndex(index)
        self.save_file()

        if previous_index != -1 and previous_index < self.tabs.count():
            self.tabs.setCurrentIndex(previous_index)

    def _close_all_tabs(self):
        for i in reversed(range(self.tabs.count())):
            self.close_tab(i)

    def _close_other_tabs(self, keep_index):
        for i in reversed(range(self.tabs.count())):
            if i != keep_index:
                self.close_tab(i)

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

                current_widget.filename = file_name
                self._update_tab_title_for_view(current_widget)
                self.update_status(f"Saved to {file_name}")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not save file: {e}")
                import traceback

                traceback.print_exc()

    def close_tab(self, index, force=False):
        widget = self.tabs.widget(index)
        if widget:
            if not force and hasattr(widget, "undo_stack") and not widget.undo_stack.isClean():
                title = getattr(widget, "filename", None) or "Untitled"
                res = QMessageBox.question(
                    self,
                    "Save Changes",
                    f"The schematic '{title}' has unsaved changes. Do you want to save before closing?",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                )
                if res == QMessageBox.StandardButton.Save:
                    self.tabs.setCurrentIndex(index)
                    self.save_file()
                elif res == QMessageBox.StandardButton.Cancel:
                    return
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

    def apply_ai_feature_state(self, enabled):
        if hasattr(self, "simulation_log") and hasattr(
            self.simulation_log, "set_ai_features_enabled"
        ):
            self.simulation_log.set_ai_features_enabled(enabled)

        pm = getattr(self, "plugin_manager", None)
        if pm is None:
            return

        for plugin in pm.plugins:
            if plugin.__class__.__name__ == "CopilotPlugin" and hasattr(plugin, "action"):
                plugin.action.setVisible(enabled)

    def generate_report(self):
        current_widget = self.tabs.currentWidget()
        if not isinstance(current_widget, SchematicView) or not getattr(
            current_widget, "filename", None
        ):
            QMessageBox.warning(
                self,
                "No file",
                "Please save your schematic before generating a report.",
            )
            return

        filename = current_widget.filename
        default_report_dir = os.path.join(os.path.dirname(filename), "report")

        reply = QMessageBox.question(
            self,
            "Generate Report",
            f"Generate HTML report into:\n{default_report_dir}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if reply == QMessageBox.StandardButton.Yes:
            from opens_suite.reporting.report_generator import ReportGenerator

            self.update_status("Generating report... please wait.")

            try:
                # Force local save so it hits disk for snapshot
                current_widget.save_schematic(
                    filename,
                    self.analysis_dock.get_all_analyses(),
                    self.outputs_dock.get_expressions_data(),
                    self.variables_dock.get_variables(),
                )

                gen = ReportGenerator(filename, default_report_dir)
                gen.generate()

                report_file = os.path.join(default_report_dir, "index.html")
                self.update_status(f"Report generated at {report_file}")

                # Auto-open in browser
                from PyQt6.QtGui import QDesktopServices
                from PyQt6.QtCore import QUrl

                QDesktopServices.openUrl(QUrl.fromLocalFile(report_file))

                # Auto-refresh library if library browser exists
                if hasattr(self, "library_dock"):
                    self.library_dock._populate_library()

            except Exception as e:
                import traceback

                QMessageBox.critical(
                    self,
                    "Report Failed",
                    f"Failed to generate report:\n{e}\n\n{traceback.format_exc()}",
                )
                self.update_status("Report generation failed.")


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(640, 540)
        self.settings = QSettings("OpenS", "OpenS")
        self._initial_ai_enabled = (
            str(self.settings.value("ai_features_enabled", "false")).lower()
            in ("1", "true", "yes", "on")
        )

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # General tab
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_form = QFormLayout()

        self.editor_edit = QLineEdit()
        self.editor_edit.setPlaceholderText("e.g. code '%s'")
        self.editor_edit.setText(self.settings.value("editor_command", "code '%s'"))
        general_form.addRow("Code Editor Command:", self.editor_edit)

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

        general_form.addRow("Library Search Paths:", self.lib_paths_list)
        general_layout.addLayout(general_form)
        tabs.addTab(general_tab, "General")

        # Simulation tab
        simulation_tab = QWidget()
        simulation_layout = QVBoxLayout(simulation_tab)
        simulation_form = QFormLayout()

        self.nodcpath_edit = QLineEdit()
        self.nodcpath_edit.setPlaceholderText("e.g. 1G (empty to disable)")
        self.nodcpath_edit.setText(self.settings.value("nodcpath_resistance", "1G"))
        simulation_form.addRow(".preprocess nodcpath R:", self.nodcpath_edit)

        self.mcp_port_edit = QLineEdit()
        self.mcp_port_edit.setPlaceholderText("8000")
        self.mcp_port_edit.setText(self.settings.value("mcp_port", "8000"))
        simulation_form.addRow("MCP Server Port:", self.mcp_port_edit)
        simulation_layout.addLayout(simulation_form)

        update_layout = QHBoxLayout()
        update_btn = QPushButton("Force Reinstall Xyce")
        update_btn.clicked.connect(self._force_update_xyce)
        update_layout.addWidget(QLabel("Manage Xyce Simulator:"))
        update_layout.addWidget(update_btn)
        update_layout.addStretch()
        simulation_layout.addLayout(update_layout)
        tabs.addTab(simulation_tab, "Simulation")

        # AI tab
        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)

        self.ai_enabled_checkbox = QCheckBox(
            "Enable AI features (experimental)"
        )
        self.ai_enabled_checkbox.setChecked(self._initial_ai_enabled)
        self.ai_enabled_checkbox.setToolTip(
            "Experimental feature: enables AI toolbar actions and FastMCP server startup."
        )
        ai_layout.addWidget(self.ai_enabled_checkbox)
        ai_hint = QLabel(
            "Experimental: when disabled, FastMCP is not started and AI buttons are hidden."
        )
        ai_hint.setStyleSheet("color: #666;")
        ai_layout.addWidget(ai_hint)

        self.ai_command_combo = QComboBox()
        self.ai_command_combo.setEditable(True)
        self.ai_command_combo.addItems(["copilot -ps '%s'", "gemini -p '%s'"])
        self.ai_command_combo.setEditText(
            self.settings.value("ai_command", "copilot -ps '%s'")
        )

        self.ai_terminal_combo = QComboBox()
        self.ai_terminal_combo.setEditable(True)
        self.ai_terminal_combo.addItems(["copilot", "gemini"])
        self.ai_terminal_combo.setEditText(
            self.settings.value("ai_terminal_command", "copilot")
        )

        ai_form = QFormLayout()
        ai_form.addRow("AI Analysis Command:", self.ai_command_combo)
        ai_form.addRow("AI Terminal Command:", self.ai_terminal_combo)
        ai_layout.addLayout(ai_form)

        mcp_layout = QVBoxLayout()
        mcp_label_layout = QHBoxLayout()
        mcp_label_layout.addWidget(QLabel("MCP Server Integration:"))
        mcp_label_layout.addStretch()
        mcp_layout.addLayout(mcp_label_layout)

        mcp_btn_layout = QHBoxLayout()
        self.mcp_export_copilot_btn = QPushButton("Export To Copilot Config")
        self.mcp_export_copilot_btn.clicked.connect(
            lambda: self._export_mcp_config("copilot")
        )

        self.mcp_export_gemini_btn = QPushButton("Export To Gemini Config")
        self.mcp_export_gemini_btn.clicked.connect(
            lambda: self._export_mcp_config("gemini")
        )

        mcp_btn_layout.addWidget(self.mcp_export_copilot_btn)
        mcp_btn_layout.addWidget(self.mcp_export_gemini_btn)
        mcp_btn_layout.addStretch()
        mcp_layout.addLayout(mcp_btn_layout)
        ai_layout.addLayout(mcp_layout)

        self.ai_enabled_checkbox.toggled.connect(self._on_ai_enabled_toggled)
        self._on_ai_enabled_toggled(self.ai_enabled_checkbox.isChecked())
        tabs.addTab(ai_tab, "AI")

        # Appearance tab
        appearance_tab = QWidget()
        appearance_layout = QVBoxLayout(appearance_tab)
        theme_layout = QHBoxLayout()
        theme_layout.addWidget(QLabel("Theme Presets:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Custom", "Bright Theme", "Dark (Virtuoso)"])
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        theme_layout.addWidget(self.preset_combo)
        appearance_layout.addLayout(theme_layout)

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

        appearance_layout.addLayout(colors_form)
        tabs.addTab(appearance_tab, "Appearance")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _force_update_xyce(self):
        if self.parent() and hasattr(self.parent(), "_check_for_xyce_updates"):
            self.parent()._check_for_xyce_updates(force=True)
            self.accept()

    def _on_ai_enabled_toggled(self, enabled):
        self.ai_command_combo.setEnabled(enabled)
        self.ai_terminal_combo.setEnabled(enabled)
        self.mcp_port_edit.setEnabled(enabled)
        self.mcp_export_copilot_btn.setEnabled(enabled)
        self.mcp_export_gemini_btn.setEnabled(enabled)

    def _export_mcp_config(self, target="copilot"):
        # Find MCP plugin
        plugin = None
        if self.parent() and hasattr(self.parent(), "plugin_manager"):
            for p in self.parent().plugin_manager.plugins:
                from opens_suite.plugins.mcp_plugin import McpPlugin
                if isinstance(p, McpPlugin):
                    plugin = p
                    break

        if plugin:
            try:
                # Save first to ensure current port is used
                self.settings.setValue("mcp_port", self.mcp_port_edit.text().strip())
                path = plugin.export_config(target=target)
                QMessageBox.information(self, "Export Successful", f"MCP configuration exported to {target.capitalize()}:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", f"Failed to export configuration: {e}")
        else:
            QMessageBox.warning(self, "Plugin Missing", "McpPlugin not found. Configuration cannot be exported.")

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
        ai_enabled = self.ai_enabled_checkbox.isChecked()
        self.settings.setValue("editor_command", self.editor_edit.text())
        self.settings.setValue("ai_command", self.ai_command_combo.currentText())
        self.settings.setValue("ai_terminal_command", self.ai_terminal_combo.currentText())
        self.settings.setValue("ai_features_enabled", ai_enabled)
        self.settings.setValue("nodcpath_resistance", self.nodcpath_edit.text().strip())
        self.settings.setValue("mcp_port", self.mcp_port_edit.text().strip())

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

        parent = self.parent()
        if parent and hasattr(parent, "apply_ai_feature_state"):
            parent.apply_ai_feature_state(ai_enabled)

        if ai_enabled != self._initial_ai_enabled:
            QMessageBox.information(
                self,
                "Restart Recommended",
                "AI feature mode changed. Please restart OpenS so plugin loading and FastMCP startup state are fully applied.",
            )
        self.accept()
