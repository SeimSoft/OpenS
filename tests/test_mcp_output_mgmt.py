import pytest
from opens_suite.main_window import MainWindow
from opens_suite.plugins.mcp_plugin import McpPlugin

@pytest.fixture
def mcp_plugin(qapp, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    win = MainWindow(str(project_dir))
    win.plugin_manager.load_plugins(force_load=["McpPlugin"])
    plugin = next(p for p in win.plugin_manager.plugins if isinstance(p, McpPlugin))
    return plugin

def test_mcp_output_expression_management(mcp_plugin):
    # 1. Add an expression
    mcp_plugin.tool_add_output_expression("vt('net1')")
    
    # 2. Get expressions and verify
    exprs = mcp_plugin.tool_get_output_expressions()
    assert len(exprs) == 1
    assert exprs[0]["expression"] == "vt('net1')"
    assert exprs[0]["name"] == ""
    
    # 3. Update fields
    mcp_plugin.tool_update_output_expression(
        0, 
        name="V_NET1", 
        unit="V", 
        description="Transient voltage at net1",
        min_spec="0",
        max_spec="5"
    )
    
    # 4. Verify updates
    exprs = mcp_plugin.tool_get_output_expressions()
    assert len(exprs) == 1
    assert exprs[0]["name"] == "V_NET1"
    assert exprs[0]["unit"] == "V"
    assert exprs[0]["description"] == "Transient voltage at net1"
    assert exprs[0]["min"] == "0"
    assert exprs[0]["max"] == "5"
    assert exprs[0]["expression"] == "vt('net1')" # Unchanged

    # 5. Partial update
    mcp_plugin.tool_update_output_expression(0, unit="mV")
    exprs = mcp_plugin.tool_get_output_expressions()
    assert exprs[0]["unit"] == "mV"
    assert exprs[0]["name"] == "V_NET1" # Still there

    # 6. Error handling
    res = mcp_plugin.tool_update_output_expression(99, name="fail")
    assert "Error: Expression index 99 out of range" in res
