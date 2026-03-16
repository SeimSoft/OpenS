import pytest
import os
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QUndoCommand
from opens_suite.main_window import MainWindow
from opens_suite.view.core import SchematicView
from opens_suite.plugins.xyce_plugin import XycePlugin

@pytest.fixture
def main_window(qtbot, tmp_path):
    """Fixture for MainWindow with a temporary project directory."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    win = MainWindow(str(project_dir))
    # Load necessary plugins
    win.plugin_manager.load_plugins(force_load=["XycePlugin"])
    qtbot.addWidget(win)
    return win

@pytest.fixture
def view(qtbot):
    """Fixture for SchematicView."""
    v = SchematicView()
    qtbot.addWidget(v)
    return v

def test_modification_state_logic(view):
    """Basic logic for modification state in SchematicView."""
    assert not view.is_modified()
    
    # 1. Mode change triggers modification
    view.set_mode(SchematicView.MODE_WIRE)
    assert view.is_modified()
    
    # 2. Reset modified
    view.set_modified(False)
    assert not view.is_modified()
    
    # 3. Undo stack triggers modification
    class DummyCommand(QUndoCommand):
        def redo(self): pass
        def undo(self): pass
    view.undo_stack.push(DummyCommand())
    assert view.is_modified()

def test_connectivity_deferral(view):
    """Verify that connectivity recalculation is deferred to save."""
    view.recalculate_connectivity = MagicMock()
    
    # Mode change should NOT trigger recalculate_connectivity
    view.set_mode(SchematicView.MODE_WIRE)
    view.recalculate_connectivity.assert_not_called()
    
    # Save SHOULD trigger recalculate_connectivity
    with patch('xml.etree.ElementTree.ElementTree.write'):
        view.save_schematic("dummy.svg")
        view.recalculate_connectivity.assert_called()
    
    # After save, modification flag is reset
    assert not view.is_modified()

def test_auto_save_before_simulation(main_window):
    """Verify that simulation forces a save if the schematic is modified."""
    # Create a new file so we have a SchematicView
    main_window.new_file()
    view = main_window.tabs.currentWidget()
    view.filename = os.path.join(main_window.project_dir, "test.svg")
    
    # Mock save_file
    main_window.save_file = MagicMock()
    
    xyce_plugin = next(p for p in main_window.plugin_manager.plugins if isinstance(p, XycePlugin))
    
    # 1. If NOT modified, save_file should NOT be called by run_simulation
    view.set_modified(False)
    with patch('opens_suite.plugins.xyce_plugin.NetlistGenerator'), \
         patch('builtins.open', create=True):
        xyce_plugin.run_simulation()
    main_window.save_file.assert_not_called()
    
    # 2. If modified, save_file SHOULD be called
    view.set_modified(True)
    with patch('opens_suite.plugins.xyce_plugin.NetlistGenerator'), \
         patch('builtins.open', create=True):
        xyce_plugin.run_simulation()
    main_window.save_file.assert_called_once()

def test_tab_title_indicator(main_window):
    """Verify that the tab title indicates the modified state with an asterisk."""
    main_window.new_file()
    view = main_window.tabs.currentWidget()
    index = main_window.tabs.indexOf(view)
    
    # Initial state (Untitled)
    assert main_window.tabs.tabText(index) == "Untitled"
    
    # 1. Modify -> Asterisk appears
    view.set_modified(True)
    assert main_window.tabs.tabText(index) == "Untitled*"
    
    # 2. Save -> Asterisk disappears
    with patch.object(view, 'recalculate_connectivity'), \
         patch('xml.etree.ElementTree.ElementTree.write'), \
         patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName', return_value=("test.svg", "")):
        main_window.save_file()
    
    # After save, title should be updated to filename (basenamed) and NO asterisk
    assert "test.svg" in main_window.tabs.tabText(index)
    assert not view.is_modified()
    assert "*" not in main_window.tabs.tabText(index)
