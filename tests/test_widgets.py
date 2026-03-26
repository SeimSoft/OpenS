import os
import sys
import types

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QTableWidgetItem, QTabWidget

from opens_suite import plugin_manager as plugin_manager_mod
from opens_suite.variables_widget import VariablesWidget
from opens_suite.results_selection_widget import ResultsSelectionWidget
from opens_suite.main_window import MainWindow, SettingsDialog
from opens_suite.schematic_view import SchematicView
from opens_suite.schematic_item import SchematicItem


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_variables_widget_has_placeholder_row(qapp):
    widget = VariablesWidget()

    # Initially should have one empty row for the placeholder
    assert widget.table.rowCount() >= 1
    assert widget.table.item(0, 0) is None or widget.table.item(0, 0).text() == ""

    # Add a real variable by editing the placeholder row
    widget.table.setItem(0, 0, widget.table.item(0, 0) or QTableWidgetItem())
    widget.table.setItem(0, 0, widget.table.item(0, 0))
    widget.table.item(0, 0).setText("MYVAR")
    widget.table.setItem(0, 1, QTableWidgetItem("123"))
    widget._on_item_changed(widget.table.item(0, 0))

    # Placeholder row should still exist at the end
    assert widget.table.rowCount() >= 2
    assert widget.get_variables() == [{"name": "MYVAR", "value": "123"}]


def test_analysis_dock_synchronizes_on_tab_switch(qapp):
    mw = MainWindow()

    view1 = SchematicView()
    view1.analyses = [{"type": "OP", "enabled": True}]

    view2 = SchematicView()
    view2.analyses = [
        {"type": "DC", "source": "V1", "start": "0", "stop": "1", "step": "0.1", "enabled": True}
    ]

    mw.tabs.addTab(view1, "v1")
    mw.tabs.addTab(view2, "v2")

    mw.tabs.setCurrentWidget(view1)
    assert any(a.get("type") == "OP" for a in mw.analysis_dock.get_all_analyses())

    mw.tabs.setCurrentWidget(view2)
    assert any(a.get("type") == "DC" for a in mw.analysis_dock.get_all_analyses())


def test_analysis_dock_uses_owner_view_for_subcircuit_tabs(qapp):
    mw = MainWindow()

    top = SchematicView()
    top.analyses = [{"type": "OP", "enabled": True}]

    child = SchematicView()
    child.analyses = [{"type": "DC", "enabled": True}]
    child._simulation_owner_view = top

    mw.tabs.addTab(top, "top")
    mw.tabs.addTab(child, "child")

    mw.tabs.setCurrentWidget(child)
    assert any(a.get("type") == "OP" for a in mw.analysis_dock.get_all_analyses())
    assert not any(a.get("type") == "DC" for a in mw.analysis_dock.get_all_analyses())


def test_analysis_owner_inherited_across_three_hierarchy_levels(qapp):
    mw = MainWindow()

    top = SchematicView()
    top.analyses = [{"type": "Tran", "enabled": True}]

    lvl2 = SchematicView()
    lvl2.analyses = [{"type": "DC", "enabled": True}]
    lvl2._simulation_owner_view = top

    lvl3 = SchematicView()
    lvl3.analyses = [{"type": "AC", "enabled": True}]
    lvl3._simulation_owner_view = top

    mw.tabs.addTab(top, "top")
    mw.tabs.addTab(lvl2, "lvl2")
    mw.tabs.addTab(lvl3, "lvl3")

    mw.tabs.setCurrentWidget(lvl3)
    assert any(a.get("type") == "Tran" for a in mw.analysis_dock.get_all_analyses())
    assert not any(a.get("type") == "AC" for a in mw.analysis_dock.get_all_analyses())


def test_make_top_level_switches_analysis_back_to_tab_itself(qapp):
    mw = MainWindow()

    top = SchematicView()
    top.analyses = [{"type": "OP", "enabled": True}]

    child = SchematicView()
    child.analyses = [{"type": "DC", "enabled": True}]
    child._simulation_owner_view = top

    mw.tabs.addTab(top, "top")
    child_idx = mw.tabs.addTab(child, "child")

    mw.tabs.setCurrentWidget(child)
    assert any(a.get("type") == "OP" for a in mw.analysis_dock.get_all_analyses())

    child.hierarchy_prefix = "X_1:"
    child.parent_breadcrumb = "top"
    child.hierarchy_instance = "X_1"
    child._simulation_owner_view = child
    mw._on_tab_changed(child_idx)

    assert any(a.get("type") == "DC" for a in mw.analysis_dock.get_all_analyses())


def test_results_selection_lists_only_current_capable_items(qapp, tmp_path):
    view = SchematicView()
    scene = view.scene()

    dummy_svg = tmp_path / "dummy.svg"
    dummy_svg.write_text("<svg></svg>")

    item1 = SchematicItem(str(dummy_svg))
    item1.name = "R1"
    item1.parameters = {"SUPPORTS_CURRENT": "True"}
    scene.addItem(item1)

    item2 = SchematicItem(str(dummy_svg))
    item2.name = "G1"
    item2.parameters = {"SUPPORTS_CURRENT": "False"}
    scene.addItem(item2)

    widget = ResultsSelectionWidget()
    widget.set_scene(scene)

    # Only item1 should appear since it supports current.
    assert any(widget.table.item(row, 0).text() == "R1" for row in range(widget.table.rowCount()))
    assert not any(widget.table.item(row, 0).text() == "G1" for row in range(widget.table.rowCount()))


def test_settings_dialog_uses_tabs_and_ai_default_disabled(qapp):
    settings = QSettings("OpenS", "OpenS")
    settings.remove("ai_features_enabled")

    dlg = SettingsDialog()
    assert not dlg.ai_enabled_checkbox.isChecked()

    tabs = dlg.findChild(QTabWidget)
    assert tabs is not None
    names = [tabs.tabText(i) for i in range(tabs.count())]
    assert "General" in names
    assert "Simulation" in names
    assert "AI" in names
    assert "Appearance" in names


def test_plugin_manager_respects_ai_feature_toggle(qapp, monkeypatch):
    settings = QSettings("OpenS", "OpenS")
    settings.setValue("ai_features_enabled", False)

    class _DummyPlugin:
        def __init__(self, main_window):
            self.main_window = main_window

        def setup(self):
            return None

    for name in [
        "LibraryPlugin",
        "PropertiesPlugin",
        "AnalysisPlugin",
        "OutputsPlugin",
        "SimulationLogPlugin",
        "CalculatorPlugin",
        "XycePlugin",
        "VariablesPlugin",
        "ResultsSelectionPlugin",
        "CopilotPlugin",
    ]:
        monkeypatch.setattr(plugin_manager_mod, name, type(name, (_DummyPlugin,), {}))

    dummy_module = types.SimpleNamespace(McpPlugin=type("McpPlugin", (_DummyPlugin,), {}))
    monkeypatch.setitem(sys.modules, "opens_suite.plugins.mcp_plugin", dummy_module)

    manager = plugin_manager_mod.PluginManager(main_window=object())
    manager.load_plugins()
    plugin_names = {p.__class__.__name__ for p in manager.plugins}
    assert "CopilotPlugin" not in plugin_names
    assert "McpPlugin" not in plugin_names

    manager.load_plugins(force_load=["McpPlugin"])
    plugin_names = {p.__class__.__name__ for p in manager.plugins}
    assert "McpPlugin" in plugin_names
