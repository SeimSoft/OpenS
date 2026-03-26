import os
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from opens_suite.library import LibraryWidget
from opens_suite.schematic_view import SchematicView
from opens_suite.schematic_item import SchematicItem
import xml.etree.ElementTree as ET


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_bindkey_population(qapp, tmp_path):
    # Setup a dummy library structure
    lib_dir = tmp_path / "test_lib"
    lib_dir.mkdir()

    cell_dir = lib_dir / "test_cell"
    cell_dir.mkdir()

    symbol_content = """
<svg xmlns="http://www.w3.org/2000/svg" width="60" height="40" viewBox="0 0 60 40">
  <defs>
    <opens:symbol xmlns:opens="http://opens-schematic.org" prefix="X" bindkey="k" category="Test" />
  </defs>
</svg>
"""
    symbol_path = cell_dir / "symbol.svg"
    symbol_path.write_text(symbol_content)

    # Initialize LibraryWidget
    widget = LibraryWidget()

    # We need to ensure _populate_library looks into our tmp_path
    # LibraryWidget._populate_library uses settings and project_dir
    widget.project_dir = str(tmp_path)

    # Trigger population
    widget._populate_library()

    # Verify bindkey_map
    # The key should be lowercase 'k'
    assert "k" in widget.bindkey_map
    assert widget.bindkey_map["k"] == str(symbol_path)

    # Verify uppercase 'K' also maps to the same (since we use bk.lower())
    assert widget.get_symbol_by_bindkey("K") == str(symbol_path)


def test_bindkey_repopulation(qapp, tmp_path):
    # Verify that refreshing/re-populating works and clears old keys
    lib_dir = tmp_path / "test_lib"
    lib_dir.mkdir()

    cell_dir1 = lib_dir / "cell1"
    cell_dir1.mkdir()
    (cell_dir1 / "symbol.svg").write_text(
        '<svg><defs><opens:symbol xmlns:opens="http://opens-schematic.org" bindkey="a" /></defs></svg>'
    )

    widget = LibraryWidget()
    widget.project_dir = str(tmp_path)
    widget._populate_library()

    assert "a" in widget.bindkey_map

    # Change bindkey and re-populate
    (cell_dir1 / "symbol.svg").write_text(
        '<svg><defs><opens:symbol xmlns:opens="http://opens-schematic.org" bindkey="b" /></defs></svg>'
    )
    widget._populate_library()

    assert "a" not in widget.bindkey_map
    assert "b" in widget.bindkey_map


def test_shift_c_bindkey_places_symbol_without_scope_error(qapp, qtbot, tmp_path, monkeypatch):
    symbol_path = tmp_path / "capacitor.svg"
    symbol_path.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>")

    class DummyLibraryDock:
        def __init__(self, path):
            self._path = str(path)

        def get_symbol_by_bindkey(self, key):
            if key == "c":
                return self._path
            return None

    from PyQt6.QtWidgets import QWidget
    import opens_suite.main_window as main_window_module

    class DummyMainWindow(QWidget):
        def __init__(self, path):
            super().__init__()
            self.library_dock = DummyLibraryDock(path)

    monkeypatch.setattr(main_window_module, "MainWindow", DummyMainWindow)

    host = DummyMainWindow(symbol_path)
    view = SchematicView(host)
    qtbot.addWidget(host)
    qtbot.addWidget(view)

    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_C,
        Qt.KeyboardModifier.ShiftModifier,
        "C",
    )

    view.keyPressEvent(event)

    assert any(isinstance(item, SchematicItem) for item in view.scene().items())
