import os

import pytest
from PyQt6.QtWidgets import QApplication, QTableWidgetItem

from opens_suite.variables_widget import VariablesWidget
from opens_suite.results_selection_widget import ResultsSelectionWidget
from opens_suite.main_window import MainWindow
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
