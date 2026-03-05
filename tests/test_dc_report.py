import os
import pytest
import numpy as np
from opens_suite.reporting.report_generator import ReportGenerator
import shutil


@pytest.fixture
def dc_setup(tmp_path):
    # Copy dc_sim.svg to a temp location
    src_svg = os.path.abspath("tests/dc_sim.svg")
    dest_svg = tmp_path / "dc_sim.svg"
    shutil.copy(src_svg, dest_svg)

    # Ensure simulation results exist (copy from tests/simulation if present, or we can assume they exist if we run it)
    # Actually, let's just use the ones in tests/simulation since they are already there
    sim_dir = tmp_path / "simulation"
    sim_dir.mkdir()

    src_raw = os.path.abspath("tests/simulation/dc_sim.raw")
    if os.path.exists(src_raw):
        shutil.copy(src_raw, sim_dir / "dc_sim.raw")

    return str(dest_svg), str(tmp_path / "report")


def test_dc_x_axis_evaluation(qapp, dc_setup):
    svg_path, report_dir = dc_setup
    from unittest.mock import MagicMock, patch
    from opens_suite.waveform_viewer import WaveformViewer

    # Check if we have the raw file
    raw_path = os.path.join(os.path.dirname(svg_path), "simulation", "dc_sim.raw")
    if not os.path.exists(raw_path):
        pytest.skip("DC simulation raw file not found. Run simulation first.")

    # We need to mock WaveformViewer to check what x-axis is passed to plot()
    mock_viewer = MagicMock(spec=WaveformViewer)
    mock_plot_item = MagicMock()
    mock_viewer.plots = [mock_plot_item]

    # We'll patch CalculatorDialog and WaveformViewer at their source since ReportGenerator uses local imports
    from opens_suite.calculator_widget import CalculatorDialog

    with patch(
        "opens_suite.calculator_widget.WaveformViewer", return_value=mock_viewer
    ):
        calc = CalculatorDialog(raw_path)
        calc.viewer = mock_viewer
        scope = calc._create_scope()

        # Test 1: sw is correctly identified
        assert "sw" in scope
        assert len(scope["sw"]) > 0
        assert scope["sw"][1] == pytest.approx(0.1)

        # Test 2: plot() with one argument uses sw as x
        # N_2 is a vector of same length as sweep (sw)
        y_data = scope["sdc"]("N_2")
        scope["plot"](y_data)

        # Check plot call
        assert mock_viewer.plot.called
        # The last call should be our manual plot
        args, kwargs = mock_viewer.plot.call_args
        assert np.array_equal(args[0], scope["sw"])
        assert np.array_equal(args[1], y_data)

    # Test 3: ReportGenerator uses it
    gen = ReportGenerator(svg_path, report_dir)
    gen._prepare_directory()
    gen._load_and_snapshot()
    gen._find_simulation_results()

    # Patch at source modules
    with patch(
        "opens_suite.reporting.report_generator.WaveformViewer",
        return_value=mock_viewer,
        create=True,
    ):
        with patch(
            "opens_suite.reporting.report_generator.CalculatorDialog", create=True
        ) as mock_calc_cls:
            mock_calc = mock_calc_cls.return_value
            mock_calc.viewer = mock_viewer
            mock_calc._create_scope.return_value = scope

            gen._evaluate_and_plot()

            # Find plotA output
            plot_a = next((o for o in gen.outputs if o.get("name") == "plotA"), None)
            assert plot_a is not None
            assert plot_a.get("_eval_success") is True
