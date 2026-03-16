import pytest
from unittest.mock import MagicMock
from opens_suite.main_window import MainWindow
from opens_suite.plugins.mcp_plugin import McpPlugin
import asyncio

@pytest.fixture
def mcp_plugin(qapp, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    win = MainWindow(str(project_dir))
    win.plugin_manager.load_plugins(force_load=["McpPlugin"])
    plugin = next(p for p in win.plugin_manager.plugins if isinstance(p, McpPlugin))
    return plugin

def test_mcp_expression_docs_resource(mcp_plugin):
    import asyncio
    async def run_test():
        # Verify the resource exists in the FastMCP instance
        res_list = mcp_plugin.mcp.list_resources()
        if hasattr(res_list, "__await__"):
            res_list = await res_list
            
        resource_uris = [str(r.uri) for r in res_list]
        assert "mcp://docs/expressions" in resource_uris
        
        # Verify the content
        content_res = mcp_plugin.mcp.read_resource("mcp://docs/expressions")
        if hasattr(content_res, "__await__"):
            content_res = await content_res
        
        # FastMCP read_resource returns a ResourceResult
        if hasattr(content_res, 'contents') and len(content_res.contents) > 0:
            c = content_res.contents[0]
            # Use __dict__ or getattr to avoid Pydantic __getattr__ issues if possible
            content = getattr(c, 'text', None) or getattr(c, 'blob', None) or str(c)
        else:
            content = str(content_res)
        
        assert "OpenS Output Expression Documentation" in content
        assert "Signal Access" in content
        assert "Mathematical Functions" in content
        assert "v(name)" in content
        assert "dB(x)" in content

    asyncio.run(run_test())

def test_mcp_tool_docstrings(mcp_plugin):
    import asyncio
    async def run_test():
        # Verify the tool docstring was updated
        tool_list = mcp_plugin.mcp.list_tools()
        if hasattr(tool_list, "__await__"):
            tool_list = await tool_list
            
        tools = {t.name: t for t in tool_list}
        tool = tools["add_output_expression"]
        
        assert "See mcp://docs/expressions" in tool.description
        assert "vt('node')" in tool.description
        assert "Signal processing" in tool.description

    asyncio.run(run_test())
