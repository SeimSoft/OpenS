import sys
import os
import xml.etree.ElementTree as ET
import pytest
from PyQt6.QtWidgets import QApplication
from opens_suite.view.core import SchematicView
from opens_suite.netlister import NetlistGenerator


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_netlist_dc_sim(qapp):

    # Path to the test file
    test_dir = os.path.dirname(__file__)
    svg_path = os.path.join(test_dir, "dc_sim.svg")

    assert os.path.exists(svg_path), f"Test file {svg_path} not found"

    # Load schematic
    view = SchematicView()
    # Ensure we set the filename so hierarchical resolution works if needed
    view.filename = svg_path
    view.load_schematic(svg_path)

    # Parse extra metadata for netlisting (analyses and variables)
    tree = ET.parse(svg_path)
    root = tree.getroot()

    analyses = []
    for elem in root.iter("{http://opens-schematic.org}analysis"):
        analyses.append(dict(elem.attrib))

    variables = []
    for elem in root.iter("{http://opens-schematic.org}variable"):
        variables.append(dict(elem.attrib))

    # Generate netlist
    gen = NetlistGenerator(view.scene(), analyses, variables=variables)
    netlist = gen.generate()

    # Basic assertions
    assert netlist is not None
    assert "* OpenS Generated Netlist" in netlist
    assert ".end" in netlist

    # Specific assertions for dc_sim.svg
    assert "V1" in netlist
    assert "M1" in netlist
    assert ".dc V1 0 1.2 0.1" in netlist
    assert "NMOS_MODEL" in netlist

    print("\nGenerated Netlist:")
    print(netlist)


def test_netlist_ac_tran(qapp):
    # Test that both AC and TRAN analyses can be emitted into the same netlist
    view = SchematicView()

    # We can just use an empty scene for this test since we're testing the analysis block
    analyses = [
        {
            "type": "AC",
            "ac_type": "DEC",
            "points": "10",
            "start": "1",
            "stop": "1Meg",
            "enabled": True,
        },
        {"type": "Tran", "step": "10n", "stop": "1u", "enabled": True},
    ]

    gen = NetlistGenerator(view.scene(), analyses)
    netlist = gen.generate()

    assert ".ac DEC 10 1 1Meg" in netlist
    assert ".tran 10n 1u" in netlist
    assert ".print ac " in netlist
    assert ".print tran " in netlist


def test_netlist_subcircuit(qapp, tmp_path):
    # Create a minimal subcircuit test programmatically
    # We will simulate a schematic item that uses a subcircuit
    from opens_suite.schematic_item import SchematicItem
    from opens_suite.netlister import NetlistGenerator

    # 1. Provide fake subcircuit code representing what _generate_subcircuit would return
    subcircuits_code = {"MY_SUBCKT": ".subckt MY_SUBCKT IN OUT\nR1 IN OUT 1k\n.ends\n"}

    # 2. Add an item referencing the subcircuit to the scene
    view = SchematicView()
    scene = view.scene()

    dummy_svg = tmp_path / "dummy.svg"
    dummy_svg.write_text("<svg></svg>")
    item = SchematicItem(str(dummy_svg))
    item.name = "X1"
    item.prefix = "X"
    item.parameters = {"MODEL": "MY_SUBCKT"}
    item.pins = {"IN": {"pos": [0, 0]}, "OUT": {"pos": [10, 0]}}
    scene.addItem(item)

    gen = NetlistGenerator(scene, [], subcircuits_code=subcircuits_code)
    # The netlister internally relies on subckt_name resolution which happens when analyzing items
    # We force the subckt resolution
    gen.subcircuits_code = subcircuits_code
    netlist = gen.generate()

    assert ".subckt MY_SUBCKT IN OUT" in netlist
    assert "X_X1" in netlist or "XX1" in netlist or "X1" in netlist
    assert "MY_SUBCKT" in netlist


def test_jinja2_optional_template_blocks(qapp, tmp_path):
    from opens_suite.schematic_item import SchematicItem
    from opens_suite.netlister import NetlistGenerator

    view = SchematicView()
    scene = view.scene()

    dummy_svg = tmp_path / "dummy.svg"
    dummy_svg.write_text("<svg></svg>")

    item1 = SchematicItem(str(dummy_svg))
    item1.name = "L1"
    item1.prefix = "L"
    item1.parameters = {"L": "1m", "IC": ""}
    item1.spice_template = "L{name} {pin_1} {pin_2} {L}{% if IC %} IC={{IC}}{% endif %}"
    item1.pins = {"1": {"pos": [0, 0]}, "2": {"pos": [10, 0]}}
    scene.addItem(item1)

    item2 = SchematicItem(str(dummy_svg))
    item2.name = "L2"
    item2.prefix = "L"
    item2.parameters = {"L": "2m", "IC": "5V"}
    item2.spice_template = "L{name} {pin_1} {pin_2} {L}{% if IC %} IC={{IC}}{% endif %}"
    item2.pins = {"1": {"pos": [0, 20]}, "2": {"pos": [10, 20]}}
    scene.addItem(item2)

    gen = NetlistGenerator(scene, [])
    netlist = gen.generate()

    assert "L1 0 0 1m" in netlist
    assert "IC=5V" in netlist
    assert "L2 0 0 2m IC=5V" in netlist


def test_vcvs_netlisting_does_not_break_on_nested_jinja(qapp, tmp_path):
    import opens_suite
    from opens_suite.schematic_item import SchematicItem
    from opens_suite.netlister import NetlistGenerator
    from opens_suite.xyce_runner import XyceRunner

    # Use the built-in VCVS symbol which contains an expression with braces
    svg_path = os.path.join(
        os.path.dirname(opens_suite.__file__),
        "assets",
        "libraries",
        "opensLib",
        "vcvs",
        "symbol.svg",
    )
    assert os.path.exists(svg_path), f"VCVS symbol not found at {svg_path}"

    view = SchematicView()
    scene = view.scene()

    item = SchematicItem(svg_path)
    item.name = "B2"
    # Ensure the prefix matches the symbol's declared prefix
    item.prefix = "B"
    scene.addItem(item)

    gen = NetlistGenerator(scene, [])
    netlist = gen.generate()

    # Ensure netlist generation succeeded and no template parsing errors occurred
    assert "Error formatting B2" not in netlist
    # Netlist line should contain the correct prefix and value expression
    assert "B2" in netlist
    assert "V=" in netlist
    # Ensure no unrendered braces remain in output
    assert "{{" not in netlist and "}}" not in netlist

    # Write netlist to a file and attempt a minimal Xyce simulation (if Xyce is available).
    # Add a minimal analysis so Xyce has something to run.
    # Xyce requires at least one .op/.tran/.ac/.dc/etc statement.
    # Ensure the netlist is solvable by adding basic DC paths for all generated nodes.
    if netlist.strip().endswith(".end"):
        netlist = netlist.strip()

        # Add dummy resistors to give each node a DC path to ground.
        # The netlist generator assigns nodes like N_1..N_4 for the VCVS pins.
        netlist_lines = netlist.splitlines()
        # Insert before the final .end
        if netlist_lines[-1] == ".end":
            netlist_lines.insert(-1, "R_N1 N_1 0 1k")
            netlist_lines.insert(-1, "R_N2 N_2 0 1k")
            netlist_lines.insert(-1, "R_N3 N_3 0 1k")
            netlist_lines.insert(-1, "R_N4 N_4 0 1k")
            netlist_lines.insert(-1, ".op")
        netlist = "\n".join(netlist_lines) + "\n"

    netlist_path = tmp_path / "vcvs_test.net"
    netlist_path.write_text(netlist)
    raw_path = tmp_path / "vcvs_test.raw"

    xyce_path = XyceRunner.get_executable_path()
    if not os.path.exists(xyce_path):
        pytest.skip("Xyce is not available; skipping actual simulation")

    runner = XyceRunner()
    returncode = runner.run_cli(str(netlist_path), str(raw_path))
    assert returncode == 0, "Xyce simulation failed for generated VCVS netlist"
