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
