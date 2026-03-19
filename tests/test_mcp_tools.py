import os
import pytest
import shutil
from PyQt6.QtWidgets import QApplication
from opens_suite.main_window import MainWindow
from opens_suite.plugins.mcp_plugin import McpPlugin
from PyQt6.QtCore import QPointF
from unittest.mock import MagicMock, patch

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

@pytest.fixture
def mcp_plugin(main_win):
    return next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))

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

def test_mcp_tool_open_view_default(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    main_win.open_file = MagicMock()
    
    # We test if tool_open_view handles the view string correctly.
    res = plugin.invoker.run_on_main(lambda: plugin.tool_open_view("testLib", "testCell", "schematic"))
    assert "Opened" in res
    assert main_win.open_file.called

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

def test_mcp_tool_update_instance_parameters_validation(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    mock_view = MagicMock()
    from opens_suite.schematic_item import SchematicItem
    item = MagicMock(spec=SchematicItem)
    item.parameters = {"R": "100"}
    item.set_parameter = MagicMock() # Ensure set_parameter is mocked for this test
    
    plugin._get_item_from_view = MagicMock(return_value=(True, (mock_view, item, False), "Found"))
    
    # 1. Valid update
    res = plugin.invoker.run_on_main(lambda: plugin.tool_update_instance_parameters("testLib", "testCell", "schematic", "R1", {"R": "1k"}))
    assert "Updated parameters" in res
    item.set_parameter.assert_called_with("R", "1k")
    
    # 2. Invalid update
    res = plugin.invoker.run_on_main(lambda: plugin.tool_update_instance_parameters("testLib", "testCell", "schematic", "R1", {"value": "1k"}))
    assert "Error: Cannot set new parameters: value" in res
    assert "Available parameters for this instance are: R" in res

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

def test_mcp_tool_create_schematic(main_win, tmp_path):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    main_win.open_file = MagicMock()
    
    # Use a new library and cell
    lib = "newLib"
    cell = "newCell"
    view = "my_schematic"
    
    res = plugin.invoker.run_on_main(lambda: plugin.tool_create_schematic(lib, cell, view))
    assert "Created" in res
    
    # Verify file existence
    expected_path = os.path.join(tmp_path, "project", lib, cell, f"{view}.svg")
    assert os.path.exists(expected_path)
    
    # Verify content
    with open(expected_path, "r") as f:
        content = f.read()
        assert '<svg' in content
        assert '800' in content
    
    # Verify open_file was called
    main_win.open_file.assert_called_with(expected_path)

def test_mcp_tool_add_pins(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # 1. Mock a current view
    mock_view = MagicMock()
    mock_view.filename = os.path.join(main_win.project_dir, "testLib", "testCell", "schematic.svg")
    mock_view.undo_stack = MagicMock()
    
    # Mock _get_view_obj to return our mock_view
    plugin._get_view_obj = MagicMock(return_value=(True, (mock_view, False), "Found in active tab"))
    
    # 2. Call add_pins
    pins = [
        {"name": "IN1", "direction": "input"},
        {"name": "OUT1", "direction": "output"}
    ]
    
    res = plugin.invoker.run_on_main(lambda: plugin.tool_add_pins("testLib", "testCell", "schematic", pins))
    assert "Added 2 pins" in res
    
    # 3. Verify undo_stack.push was called with InsertItemsCommand
    mock_view.undo_stack.push.assert_called_once()
    cmd = mock_view.undo_stack.push.call_args[0][0]
    from opens_suite.commands import InsertItemsCommand
    assert isinstance(cmd, InsertItemsCommand)
    
    # Verify items
    items = cmd.items
    assert len(items) == 2
    from opens_suite.schematic_item import SchematicItem
    assert all(isinstance(it, SchematicItem) for it in items)
    
    # Check positions (simplified check)
    # IN1 should be on left (x=100)
    # OUT1 should be on right (x=700)
    assert any(it.prefix == "PIN" and it.pos().x() == 100 for it in items)
    assert any(it.prefix == "PIN" and it.pos().x() == 700 for it in items)
    
    # Check parameters
    assert any(it.parameters.get("NET_NAME") == "IN1" for it in items)
    assert any(it.parameters.get("NET_NAME") == "OUT1" for it in items)

def test_mcp_tool_list_libraries(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # We already have testLib/testCell from the fixture
    res = plugin.invoker.run_on_main(plugin.tool_list_libraries)
    assert "testLib" in res
    assert "testCell" in res["testLib"]

def test_mcp_tool_remove_symbol(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # 1. Mock a current view with items
    mock_view = MagicMock()
    mock_view.filename = os.path.join(main_win.project_dir, "testLib", "testCell", "schematic.svg")
    mock_view.undo_stack = MagicMock()
    
    from opens_suite.schematic_item import SchematicItem
    item1 = MagicMock(spec=SchematicItem)
    item1.name = "R1"
    item1.parameters = {}
    
    item2 = MagicMock(spec=SchematicItem)
    item2.name = "PIN1"
    item2.parameters = {"NET_NAME": "MYPIN"}
    
    mock_view.scene.return_value.items.return_value = [item1, item2]
    
    # Mock _get_view_obj
    plugin._get_view_obj = MagicMock(return_value=(True, (mock_view, False), "Found"))
    
    # 2. Test removal by instance name
    res = plugin.invoker.run_on_main(lambda: plugin.tool_remove_symbol("testLib", "testCell", "schematic", "R1"))
    assert "Removed 1 item(s)" in res
    mock_view.undo_stack.push.assert_called_once()
    
    # 3. Test removal by net_name (for pins)
    mock_view.undo_stack.push.reset_mock()
    res = plugin.invoker.run_on_main(lambda: plugin.tool_remove_symbol("testLib", "testCell", "schematic", "MYPIN"))
    assert "Removed 1 item(s)" in res
    mock_view.undo_stack.push.assert_called_once()
    
    # 4. Test error case
    res = plugin.invoker.run_on_main(lambda: plugin.tool_remove_symbol("testLib", "testCell", "schematic", "NONEXISTENT"))
    assert "Error: No item found" in res

def test_mcp_tool_get_instance_pins(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # Mock view and items
    mock_view = MagicMock()
    from opens_suite.schematic_item import SchematicItem
    item = MagicMock(spec=SchematicItem)
    item.name = "R1"
    item.parameters = {}
    item.pins = {"p1": {"pos": QPointF(0, 0)}, "p2": {"pos": QPointF(20, 0)}}
    # mapToScene logic: let's say item is at (100, 100)
    item.mapToScene.side_effect = lambda p: p + QPointF(100, 100)
    
    mock_view.scene.return_value.items.return_value = [item]
    plugin._get_view_obj = MagicMock(return_value=(True, (mock_view, False), "Found"))
    
    res = plugin.invoker.run_on_main(lambda: plugin.tool_get_instance_pins("testLib", "testCell", "schematic", "R1"))
    assert "p1" in res
    assert res["p1"]["x"] == 100
    assert res["p1"]["y"] == 100
    assert res["p2"]["x"] == 120
    assert res["p2"]["y"] == 100

def test_mcp_tool_connect_by_wire(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    mock_view = MagicMock()
    mock_view.undo_stack = MagicMock()
    plugin._get_view_obj = MagicMock(return_value=(True, (mock_view, False), "Found"))
    
    # Test |- operator
    res = plugin.invoker.run_on_main(lambda: plugin.tool_connect_by_wire("testLib", "testCell", "schematic", [10, 10], "|-", [50, 50], "MYNET"))
    assert "Connected" in res
    mock_view.undo_stack.push.assert_called_once()
    cmd = mock_view.undo_stack.push.call_args[0][0]
    from opens_suite.commands import InsertItemsCommand
    assert isinstance(cmd, InsertItemsCommand)
    assert len(cmd.items) == 2 # Vertical + Horizontal
    assert cmd.items[0].name == "MYNET"

def test_mcp_tool_add_symbol(main_win):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    mock_view = MagicMock()
    mock_view.undo_stack = MagicMock()
    mock_view.project_dir = main_win.project_dir
    plugin._get_view_obj = MagicMock(return_value=(True, (mock_view, False), "Found"))
    
    # Mock _resolve_path since we don't want to rely on real library files in unit test
    plugin._resolve_path = MagicMock(return_value="/some/path/to/symbol.svg")
    
    with patch("opens_suite.schematic_item.SchematicItem") as MockItem:
        MockItem.return_value = MagicMock()
        res = plugin.invoker.run_on_main(lambda: plugin.tool_add_symbol("testLib", "testCell", "schematic", "opensLib", "resistor", 200, 300, name="R10", parameters={"R": "10k"}))
        assert "Added symbol" in res
        MockItem.assert_called_once_with("/some/path/to/symbol.svg")
        MockItem.return_value.setPos.assert_called_once_with(200, 300)
        MockItem.return_value.set_name.assert_called_once_with("R10")
        MockItem.return_value.set_parameter.assert_called_once_with("R", "10k")

def test_mcp_tool_set_view_category(main_win, tmp_path):
    plugin = next(p for p in main_win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # Create a dummy schematic file
    lib_dir = tmp_path / "testLib"
    lib_dir.mkdir(exist_ok=True)
    cell_dir = lib_dir / "testCell"
    cell_dir.mkdir(exist_ok=True)
    sch_path = cell_dir / "schematic.svg"
    sch_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><defs/></svg>')
    
    # We need to mock _resolve_path to return this temp file
    plugin._resolve_path = MagicMock(return_value=str(sch_path))
    # Mock _find_widget to avoid UI dependency
    plugin._find_widget = MagicMock(return_value=None)
    
    res = plugin.invoker.run_on_main(lambda: plugin.tool_set_view_category("testLib", "testCell", "schematic", "MyNewCategory"))
    assert "changed to 'MyNewCategory'" in res
    
    # Verify file content
    content = sch_path.read_text()
    assert 'category="MyNewCategory"' in content
    assert 'opens:symbol' in content or 'symbol' in content

def test_notebook_template_generation(tmp_path):
    from opens_suite.design_script_dialog import DesignScriptDialog
    from unittest.mock import MagicMock
    
    # 1. Test Stimuli template
    item_stim = MagicMock()
    item_stim.svg_path = "some/path/stimuli_generator.svg"
    item_stim.parameters = {"SCRIPT": "stimuli.ipynb"}
    item_stim.scene().views.return_value = [MagicMock(filename=str(tmp_path / "schematic.svg"))]
    
    DesignScriptDialog.open_notebook(item_stim)
    
    nb_path = tmp_path / "stimuli.ipynb"
    assert nb_path.exists()
    import json
    with open(nb_path, "r") as f:
        nb_data = json.load(f)
    assert "from opens_suite import Stimuli" in nb_data["cells"][1]["source"][0]

    # 2. Test Design Script template fix
    item_ds = MagicMock()
    item_ds.svg_path = "some/path/design_script.svg"
    item_ds.parameters = {"SCRIPT": "design.ipynb"}
    item_ds.scene().views.return_value = [MagicMock(filename=str(tmp_path / "schematic.svg"))]
    
    # We need a real template file for this one since it reads from disk
    # But since we are in a test, let's just assume the logic works or mock the read
    # Actually, the template exists in the repo, so if we run in the repo it should find it.
    DesignScriptDialog.open_notebook(item_ds)
    nb_path_ds = tmp_path / "design.ipynb"
    assert nb_path_ds.exists()
    with open(nb_path_ds, "r") as f:
        nb_data_ds = json.load(f)
    
    # Check if 'opens' was replaced with 'opens_suite'
    source = str(nb_data_ds["cells"][1]["source"])
    assert "from opens_suite import DesignPoints" in source

def test_mcp_api_documentation(qtbot, mcp_plugin):
    # Test Stimuli docs
    stim_docs = mcp_plugin.tool_get_api_documentation("Stimuli")
    assert "Stimuli helper class" in stim_docs
    assert "vdc" in stim_docs
    assert "vsin" in stim_docs
    
    # Test DesignPoints docs
    dp_docs = mcp_plugin.tool_get_api_documentation("DesignPoints")
    assert "DesignPoints" in dp_docs
    assert "E24" in dp_docs
    
    # Test invalid class
    err = mcp_plugin.tool_get_api_documentation("Unknown")
    assert "No documentation found" in err

def test_mcp_notebook_tools(tmp_path, mcp_plugin):
    # Setup a mock cell environment
    lib_dir = tmp_path / "myLib"
    cell_dir = lib_dir / "myCell"
    cell_dir.mkdir(parents=True)
    (cell_dir / "schematic.svg").write_text("<svg></svg>")
    
    # Mock resolve_path to use our tmp_path
    plugin_dir = getattr(mcp_plugin.main_window, "project_dir", "")
    mcp_plugin.main_window.project_dir = str(tmp_path)
    
    nb_name = "test.ipynb"
    lib, cell, view = "myLib", "myCell", "schematic"
    
    # 1. Append code to a new notebook
    code1 = "print('hello')"
    res = mcp_plugin.tool_append_notebook_code(lib, cell, view, nb_name, code1)
    assert "Appended" in res
    
    # 2. Read notebook
    content = mcp_plugin.tool_read_notebook(lib, cell, view, nb_name)
    assert "print('hello')" in content
    
    # 3. Append another cell
    code2 = "x = 1"
    mcp_plugin.tool_append_notebook_code(lib, cell, view, nb_name, code2)
    
    # 4. Update a cell
    code3 = "x = 2"
    res = mcp_plugin.tool_update_notebook_cell(lib, cell, view, nb_name, 1, code3)
    assert "Updated cell 1" in res
    
    # Verify content
    content = mcp_plugin.tool_read_notebook(lib, cell, view, nb_name)
    assert "x = 2" in content
    assert "x = 1" not in content
    
    # Cleanup
    mcp_plugin.main_window.project_dir = plugin_dir
