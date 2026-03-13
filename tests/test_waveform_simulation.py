import os
import pytest
from PyQt6.QtWidgets import QApplication
from opens_suite.main_window import MainWindow
from opens_suite.schematic_view import SchematicView
from opens_suite.calculator_widget import CalculatorDialog
from opens_suite.waveform_viewer import WaveformViewer
from unittest.mock import MagicMock


@pytest.fixture
def main_window(qapp, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    win = MainWindow(str(project_dir))
    return win


def test_waveform_viewer_simulation_trigger(main_window, tmp_path):
    win = main_window

    # 1. Setup a schematic with dummy results
    sch_path = tmp_path / "test.svg"
    sch_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"></svg>'
    )
    win.open_file(str(sch_path))

    sim_dir = tmp_path / "simulation"
    sim_dir.mkdir()
    raw_path = sim_dir / "test.raw"
    raw_path.write_text("Binary data placeholder")

    # 2. Open Calculator
    calc = CalculatorDialog(str(raw_path), win)
    calc.isHidden = MagicMock(return_value=False)
    win.active_calculators = [calc]

    # Set a script so evaluate creates a viewer
    calc.script_edit.setPlainText("plot(t, vt('v1'))")

    # Mock evaluate to avoid real data parsing but let it create viewer
    # We'll mock the internal _create_scope instead
    calc._create_scope = MagicMock(return_value={"t": [1], "vt": lambda x: [1]})
    calc.evaluate()

    viewer = calc.viewer
    assert isinstance(viewer, WaveformViewer)
    assert viewer.sim_action is not None

    # Mock the simulate action trigger
    win.simulate_action = MagicMock()

    # 3. Trigger simulation from viewer
    viewer.sim_action.trigger()

    # CHECK: MainWindow's simulate action should be triggered
    win.simulate_action.trigger.assert_called_once()


def test_calculator_automatic_replot_on_finish(main_window, tmp_path):
    win = main_window

    # 1. Setup
    sim_dir = tmp_path / "simulation"
    sim_dir.mkdir()
    raw_path = sim_dir / "test.raw"
    raw_path.write_text("Binary data placeholder")

    calc = CalculatorDialog(str(raw_path), win)
    calc.isHidden = MagicMock(return_value=False)
    win.active_calculators = [calc]

    # Mock evaluate and refresh
    calc.refresh = MagicMock()
    calc.evaluate = MagicMock()

    # 2. Trigger simulationFinished signal from a view
    plugin = None
    from opens_suite.plugins.calculator_plugin import CalculatorPlugin

    for p in win.plugin_manager.plugins:
        if isinstance(p, CalculatorPlugin):
            plugin = p
            break

    assert plugin is not None

    # Simulate simulation finished
    plugin.refresh_calculators()

    # CHECK: calc._refresh_and_replot() should be called, which calls refresh and evaluate
    calc.refresh.assert_called_once()
    calc.evaluate.assert_called_once()
