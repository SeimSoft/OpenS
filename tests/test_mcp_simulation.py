import os
import pytest
from unittest.mock import MagicMock, patch
from opens_suite.main_window import MainWindow
from opens_suite.plugins.mcp_plugin import McpPlugin

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
    
    # Create simulation directory and dummy .raw file
    sim_dir = cell_dir / "simulation"
    sim_dir.mkdir()
    raw_path = sim_dir / "schematic.raw"
    raw_path.write_bytes(b"Title: Dummy\nPlotname: Transient Analysis\nFlags: real\nNo. Variables: 2\nNo. Points: 1\nVariables:\n 0 time time\n 1 v(1) voltage\nBinary:\n" + (b"\x00"*16))

    win = MainWindow(str(project_dir))
    win.plugin_manager.load_plugins(force_load=["McpPlugin"])
    return win

def test_mcp_tool_run_simulation(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # Mock XycePlugin by creating a class with the right name
    class XycePlugin:
        def run_simulation(self): pass
    
    mock_xyce = XycePlugin()
    mock_xyce.run_simulation = MagicMock()
    
    # We need to manually inject it into the main_window's plugins
    # Insert at the START to override real plugin
    main_win.plugin_manager.plugins.insert(0, mock_xyce)
    
    # Trigger run_simulation
    res = plugin.invoker.run_on_main(lambda: plugin.tool_run_simulation("testLib", "testCell", "schematic"))
    
    assert "Simulation started" in res
    mock_xyce.run_simulation.assert_called_once()

def test_mcp_tool_get_simulation_signals(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # Mock SpiceRawParser.parse to return something predictable
    with patch('opens_suite.spice_parser.SpiceRawParser.parse', return_value={"Plot1": {"time": [0], "v(1)": [1]}}):
        # Trigger get_simulation_signals
        signals = plugin.invoker.run_on_main(lambda: plugin.tool_get_simulation_signals("testLib", "testCell", "schematic"))
        
        assert "time" in signals
        assert "v(1)" in signals

def test_mcp_tool_update_parameters_robustness(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # We test the inner tool implementation directly for the logic, 
    # but the robustness is in the wrapper.
    # Since we can't easily wait for async, we'll just verify the logic works.
    
    # Mock a schematic item
    from opens_suite.schematic_item import SchematicItem
    mock_item = MagicMock(spec=SchematicItem)
    mock_item.name = "R1"
    
    with patch('opens_suite.plugins.mcp_plugin.McpPlugin._get_item_from_view', return_value=(True, (MagicMock(), mock_item, False), "Found")):
        res = plugin.invoker.run_on_main(lambda: plugin.tool_update_instance_parameters("testLib", "testCell", "schematic", "R1", {"value": "2k"}))
        assert "Updated" in res
        mock_item.set_parameter.assert_called_with("value", "2k")
