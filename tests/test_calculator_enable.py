import os
import pytest
from PyQt6.QtWidgets import QApplication, QMainWindow
from opens_suite.main_window import MainWindow
from opens_suite.schematic_view import SchematicView
from opens_suite.plugins.calculator_plugin import CalculatorPlugin


@pytest.fixture
def main_window(qapp, tmp_path):
    # Setup a mock project and MainWindow
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # We need to initialize the plugin manually if we want to test it in isolation or via MainWindow
    win = MainWindow(str(project_dir))

    # Ensure CalculatorPlugin is loaded (usually it is via PluginManager)
    plugin = None
    for p in win.plugin_manager.plugins:
        if isinstance(p, CalculatorPlugin):
            plugin = p
            break

    if not plugin:
        plugin = CalculatorPlugin(win)
        plugin.setup()
        win.plugin_manager.plugins.append(plugin)

    return win, plugin


def test_calculator_button_enabling(main_window, tmp_path):
    win, plugin = main_window

    # 1. Create a new schematic
    sch_path = tmp_path / "test.svg"
    sch_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"></svg>'
    )

    win.open_file(str(sch_path))
    view = win.tabs.currentWidget()
    assert isinstance(view, SchematicView)

    # Initially, calculator should be disabled
    assert plugin.calc_action.isEnabled() == False

    # 2. Simulate simulation results appearing
    sim_dir = tmp_path / "simulation"
    sim_dir.mkdir()
    raw_path = sim_dir / "test.raw"
    raw_path.write_text("Binary data placeholder")

    # Emit simulationFinished signal
    view.simulationFinished.emit()

    # CHECK: It should now be enabled!
    # Currently this will fail as we identified the bug
    assert plugin.calc_action.isEnabled() == True
