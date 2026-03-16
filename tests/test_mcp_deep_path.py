import os
import pytest
import threading
from PyQt6.QtWidgets import QApplication
from opens_suite.main_window import MainWindow
from opens_suite.plugins.mcp_plugin import McpPlugin
from unittest.mock import MagicMock

def test_mcp_get_current_view_background_thread(qapp, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    
    deep_dir = project_dir / "tests" / "grid-tie" / "grid-tie-lib" / "LLC"
    os.makedirs(deep_dir, exist_ok=True)
    
    sch_path = deep_dir / "schematic.svg"
    sch_path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"></svg>')
    
    win = MainWindow(str(project_dir))
    win.plugin_manager.load_plugins(force_load=["McpPlugin"])
    
    plugin = next(p for p in win.plugin_manager.plugins if isinstance(p, McpPlugin))
    
    # 1. Open the deep file
    win.open_file(str(sch_path))
    qapp.processEvents()
    
    # 2. Check get_current_view from a BACKGROUND thread
    results = []
    def call_mcp():
        try:
            res = plugin.invoker.run_on_main(plugin.tool_get_current_view)
            results.append(res)
        except Exception as e:
            results.append(e)

    thread = threading.Thread(target=call_mcp)
    thread.start()
    
    # Give it some time and process events on main thread to handle the signal!
    for _ in range(200):
        qapp.processEvents()
        if results:
            break
        import time
        time.sleep(0.01)

    thread.join(timeout=2.0)
    
    assert results, "Background thread should have returned a result"
    res = results[0]
    print(f"\n[TEST] get_current_view result (from bg thread): {res}")
    
    assert not isinstance(res, Exception), f"Mock call failed: {res}"
    assert res is not None
    assert res["view"] == "schematic"
    assert res["cell"] == "LLC"
    assert res["lib"] == "grid-tie-lib"
