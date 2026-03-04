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
    assert ".dc V1 0 5 0.1" in netlist
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
