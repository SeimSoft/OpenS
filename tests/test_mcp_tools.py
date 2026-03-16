import os
import pytest
import shutil
from PyQt6.QtWidgets import QApplication
from opens_suite.main_window import MainWindow
from opens_suite.plugins.mcp_plugin import McpPlugin
from unittest.mock import MagicMock

@pytest.fixture
def main_win(qapp, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    
    # Create a dummy library structure
    lib_dir = project_dir / "testLib"
    lib_dir.mkdir()
    cell_dir = lib_dir / "testCell"
    cell_dir.mkdir()
    
    sch_path = cell_dir / "schematic.svg"
    sch_path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"></svg>')
    
    sym_path = cell_dir / "symbol.svg"
    sym_path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>')

    win = MainWindow(str(project_dir))
    win.plugin_manager.load_plugins(force_load=["McpPlugin"])
    return win

def test_mcp_invoker(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    def test_func():
        return "hello"
    res = plugin.invoker.run_on_main(test_func)
    assert res == "hello"

def test_mcp_resolve_path(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    path = plugin._resolve_path("testLib", "testCell", "schematic")
    assert path is not None
    assert path.endswith("schematic.svg")
    path = plugin._resolve_path("testLib", "testCell", "symbol")
    assert path is not None
    assert path.endswith("symbol.svg")
    assert plugin._resolve_path("testLib", "testCell", "nonexistent") is None

def test_mcp_parse_path(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    path = os.path.join("some", "base", "myLib", "myCell", "schematic.svg")
    info = plugin._parse_path(path)
    assert info["lib"] == "myLib"
    assert info["cell"] == "myCell"
    assert info["view"] == "schematic"

def test_mcp_tool_open_view(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    main_win.open_file = MagicMock()
    
    res = plugin.invoker.run_on_main(lambda: plugin.tool_open_view("testLib", "testCell", "schematic"))
    assert "Opened" in res
    main_win.open_file.assert_called_once()

def test_mcp_tool_copy_view(main_win, tmp_path):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    res = plugin.invoker.run_on_main(lambda: plugin.tool_copy_view("testLib", "testCell", "schematic", "testLib", "destCell", "schematic_copy"))
    assert "Copied" in res
    assert os.path.exists(os.path.join(tmp_path, "project", "testLib", "destCell", "schematic_copy.svg"))

def test_mcp_tool_add_expression(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    main_win.outputs_dock.add_expression = MagicMock()
    
    res = plugin.invoker.run_on_main(lambda: plugin.tool_add_output_expression("v('in')"))
    assert res == "Added expression: v('in')"
    main_win.outputs_dock.add_expression.assert_called_with("v('in')")

def test_mcp_tool_get_current_view(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # Mock a current widget with a filename
    mock_view = MagicMock()
    mock_view.filename = os.path.join(main_win.project_dir, "testLib", "testCell", "schematic.svg")
    main_win.tabs.currentWidget = MagicMock(return_value=mock_view)
    
    # This should now work without CalculatorPlugin!
    res = plugin.invoker.run_on_main(plugin.tool_get_current_view)
    assert res is not None
    assert res["lib"] == "testLib"
    assert res["cell"] == "testCell"
    assert res["view"] == "schematic"

def test_mcp_tool_get_instance_parameters(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # 1. Setup a mock schematic item in a mock view
    from opens_suite.schematic_item import SchematicItem
    mock_item = MagicMock(spec=SchematicItem)
    mock_item.name = "R1"
    mock_item.parameters = {"value": "1k", "model": "RES"}
    
    mock_view = MagicMock()
    mock_view.filename = os.path.join(main_win.project_dir, "testLib", "testCell", "schematic.svg")
    mock_view.scene.return_value.items.return_value = [mock_item]
    
    # Mock currentWidget to return our mock_view
    main_win.tabs.currentWidget = MagicMock(return_value=mock_view)
    main_win.tabs.count = MagicMock(return_value=1)
    main_win.tabs.widget = MagicMock(return_value=mock_view)
    
    # 2. Test get_instance_parameters
    res = plugin.invoker.run_on_main(lambda: plugin.tool_get_instance_parameters("testLib", "testCell", "schematic", "R1"))
    assert res == {"value": "1k", "model": "RES"}

def test_mcp_tool_update_instance_parameters(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # 1. Setup a mock schematic item in a mock view
    from opens_suite.schematic_item import SchematicItem
    mock_item = MagicMock(spec=SchematicItem)
    mock_item.name = "R1"
    mock_item.parameters = {"value": "1k"}
    mock_item.set_parameter = MagicMock()
    
    mock_view = MagicMock()
    mock_view.filename = os.path.join(main_win.project_dir, "testLib", "testCell", "schematic.svg")
    mock_view.scene.return_value.items.return_value = [mock_item]
    
    # Mock currentWidget to return our mock_view
    main_win.tabs.currentWidget = MagicMock(return_value=mock_view)
    main_win.tabs.count = MagicMock(return_value=1)
    main_win.tabs.widget = MagicMock(return_value=mock_view)
    
    # 2. Test update_instance_parameters
    res = plugin.invoker.run_on_main(lambda: plugin.tool_update_instance_parameters("testLib", "testCell", "schematic", "R1", {"value": "2k"}))
    assert "Updated" in res
    assert "active tab" in res
    mock_item.set_parameter.assert_called_with("value", "2k")
