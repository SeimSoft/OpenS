import os
import json
import pytest
from PyQt6.QtWidgets import QApplication
from opens_suite.view.core import SchematicView
from opens_suite.netlister import NetlistGenerator
from opens_suite.symbol_generator import SymbolGenerator


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_pcell_variant_generation(qapp, tmp_path):
    # 1. Setup PCell directory structure
    pcell_dir = tmp_path / "my_pcell"
    pcell_dir.mkdir()

    # Subcircuit Schematic
    sch_content = """<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000">
        <!-- Pins -->
        <g symbol_name="pin_in" library_path="opensLib/pin_in/symbol.svg" name="IN" transform="translate(100,100)"/>
        <g symbol_name="pin_out" library_path="opensLib/pin_out/symbol.svg" name="OUT" transform="translate(300,100)"/>
        
        <!-- Resistor R1 referencing a PCell parameter -->
        <g symbol_name="resistor" library_path="opensLib/resistor/symbol.svg" name="R1" transform="translate(200,100)" param_R="{gain*1k}"/>
    </svg>"""
    sch_path = pcell_dir / "schematic.svg"
    sch_path.write_text(sch_content)

    # Default parameters.json
    params_json = pcell_dir / "parameters.json"
    params_json.write_text(json.dumps({"gain": 10}))

    # Generate symbol
    sym_path = pcell_dir / "symbol.svg"
    SymbolGenerator.generate_symbol(str(sch_path), str(sym_path))

    # 2. Setup Top Schematic
    top_sch_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000">
        <g symbol_name="my_pcell" library_path="{pcell_dir}/symbol.svg" name="X1" transform="translate(100,100)" param_gain="100"/>
        <g symbol_name="my_pcell" library_path="{pcell_dir}/symbol.svg" name="X2" transform="translate(100,200)" param_gain="200"/>
    </svg>"""
    top_sch_path = tmp_path / "top.svg"
    top_sch_path.write_text(top_sch_content)

    # 3. Load and Generate Netlist
    view = SchematicView()
    view.filename = str(top_sch_path)
    view.load_schematic(str(top_sch_path))

    gen = NetlistGenerator(view.scene(), [])
    netlist = gen.generate()

    # 4. Assertions
    assert "my_pcell_" in netlist, "Should generate hashed subcircuit variant"

    # Check for two distinct variants
    import re

    variants = set(re.findall(r"my_pcell_[a-f0-9]{8}", netlist))
    assert len(variants) == 2, f"Should have 2 unique variants, found: {variants}"

    # Check .param injection
    assert ".param gain=100" in netlist
    assert ".param gain=200" in netlist

    # Check expression propagation
    assert "{gain*1k}" in netlist


def test_pcell_design_script_headless(qapp, tmp_path):
    # Testing that design scripts are executed headlessly during netlisting
    pcell_dir = tmp_path / "scripted_pcell"
    pcell_dir.mkdir()

    # Subcircuit with design_script
    sch_content = """<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000">
        <g symbol_name="pin_in" library_path="opensLib/pin_in/symbol.svg" name="IN" transform="translate(100,100)"/>
        <g symbol_name="pin_out" library_path="opensLib/pin_out/symbol.svg" name="OUT" transform="translate(300,100)"/>
        <g symbol_name="resistor" library_path="opensLib/resistor/symbol.svg" name="R1" transform="translate(200,100)" param_R="1k"/>
        <g symbol_name="design_script" library_path="opensLib/design_script/symbol.svg" name="DS1" transform="translate(50,50)" param_SCRIPT="calc.ipynb"/>
    </svg>"""
    sch_path = pcell_dir / "schematic.svg"
    sch_path.write_text(sch_content)

    params_json = pcell_dir / "parameters.json"
    params_json.write_text(json.dumps({"mult": 5}))

    # Notebook that multiplies a value
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import json\n",
                    "from opens_suite.design_points import DesignPoints\n",
                    "with open('parameters.json', 'r') as f:\n",
                    "    params = json.load(f)\n",
                    "mult = float(params.get('mult', 1))\n",
                    "dps = DesignPoints()\n",
                    "dps['R1.R'] = f'{mult * 1000}'\n",
                    "dps.save('calc.json')",
                ],
            }
        ],
        "metadata": {"kernelspec": {"display_name": "Python 3", "name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    with open(pcell_dir / "calc.ipynb", "w") as f:
        json.dump(notebook, f)

    # Symbol
    sym_path = pcell_dir / "symbol.svg"
    SymbolGenerator.generate_symbol(str(sch_path), str(sym_path))

    # Top
    top_sch_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000">
        <g symbol_name="scripted_pcell" library_path="{pcell_dir}/symbol.svg" name="X1" transform="translate(100,100)" param_mult="10"/>
    </svg>"""
    top_sch_path = tmp_path / "top_script.svg"
    top_sch_path.write_text(top_sch_content)

    view = SchematicView()
    view.filename = str(top_sch_path)
    view.load_schematic(str(top_sch_path))

    gen = NetlistGenerator(view.scene(), [])
    netlist = gen.generate()

    # Verification
    # multiplier was 10, so R1 should be 10k (from 10 * 1000, formatted via SI suffix)
    assert "R1" in netlist
    assert "10k" in netlist
