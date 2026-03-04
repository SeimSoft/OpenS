import os
import xml.etree.ElementTree as ET
import pytest

from opens_suite.view.core import SchematicView
from opens_suite.netlister import NetlistGenerator
from opens_suite.xyce_runner import XyceRunner


def test_simulation_dc_sim(qapp, tmp_path):
    """
    End-to-end test stringing together schematic loading,
    netlist generation, and Xyce simulation cleanly.
    """
    test_dir = os.path.dirname(__file__)
    svg_path = os.path.join(test_dir, "dc_sim.svg")
    assert os.path.exists(svg_path), f"Test schematic missing at {svg_path}"

    # Load Schematic
    view = SchematicView()
    view.load_schematic(svg_path)

    # Parse metadata
    tree = ET.parse(svg_path)
    root = tree.getroot()

    analyses = []
    for elem in root.iter("{http://opens-schematic.org}analysis"):
        analyses.append(dict(elem.attrib))

    variables = []
    for elem in root.iter("{http://opens-schematic.org}variable"):
        variables.append(dict(elem.attrib))

    # Generate Netlist
    gen = NetlistGenerator(view.scene(), analyses, variables=variables)
    netlist = gen.generate()
    assert netlist is not None

    # Write netlist to temporary file
    netlist_file = tmp_path / "test_sim.net"
    netlist_file.write_text(netlist)

    raw_file = tmp_path / "test_sim.raw"

    runner = XyceRunner()

    # We skip physical execution conditionally if the executable isn't on the CI path?
    # No, we want to try explicitly to ensure it works.
    # If Xyce isn't installed locally (like on GitHub Actions right now maybe?),
    # XyceRunner throws FileNotFound. For this test to pass we'll assume Xyce is present
    # or skip if it throws.
    try:
        ret_code = runner.run_cli(str(netlist_file), str(raw_file))
        assert ret_code == 0, "Xyce simulation failed with non-zero exit code"
    except FileNotFoundError:
        pytest.skip(
            f"Xyce backend not available for end-to-end test execution at {runner.get_executable_path()}."
        )


def test_reporting_headless(qapp, tmp_path):
    """
    Test the complete headless reporting automation pipeline natively.
    """
    from opens_suite.reporting.report_generator import ReportGenerator

    test_dir = os.path.dirname(__file__)
    svg_path = os.path.join(test_dir, "dc_sim.svg")
    assert os.path.exists(svg_path), f"Test schematic missing at {svg_path}"

    report_dir = str(tmp_path / "report")
    gen = ReportGenerator(svg_path, report_dir)
    gen.generate()

    assert os.path.exists(report_dir)
    assert os.path.exists(os.path.join(report_dir, "index.html")), "HTML missing"
    assert os.path.exists(
        os.path.join(report_dir, "circuit.png")
    ), "Circuit PNG missing"
    assert os.path.exists(os.path.join(report_dir, "simulation.net")), "Netlist missing"
