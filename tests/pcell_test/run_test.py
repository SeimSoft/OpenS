import sys
import os

# Add src to path
sys.path.append(os.path.abspath("src"))

from opens_suite.netlister import NetlistGenerator
from opens_suite.schematic_item import SchematicItem
from opens_suite.wire import Wire

from PyQt6.QtWidgets import QApplication
from opens_suite.view.core import SchematicView

# Must have a QApplication for QSvgRenderer and other UI elements
app = QApplication(sys.path)

top_sch = os.path.abspath("tests/pcell_test/top.svg")

view = SchematicView()
view.filename = top_sch
view.load_schematic(top_sch)

print(f"Scene items: {len(view.scene().items())}")
for item in view.scene().items():
    if isinstance(item, SchematicItem):
        print(f"  Item: {item.name}, SVG: {item.svg_path}, Params: {item.parameters}")
    elif isinstance(item, Wire):
        print(f"  Wire: {item.name or 'unnamed'} at {item.line()}")

gen = NetlistGenerator(view.scene(), [])
netlist = gen.generate()

print("--- Generated Netlist ---")
print(netlist)
print("-------------------------")

# Basic checks
success = True
if "gain_block_" in netlist:
    print("SUCCESS: PCell variant found.")
else:
    print("FAILURE: No PCell variant found.")
    success = False

# Check if parameters are correctly applied (either as .param or substituted)
if "{gain*1k}" in netlist or "10k" in netlist:
    print("SUCCESS: Parameter applied in subcircuit.")
else:
    print("FAILURE: Parameter not applied correctly.")
    success = False

# Check if .param lines exist in subcircuits
if ".param gain=10" in netlist and ".param gain=20" in netlist:
    print("SUCCESS: PCell parameters passed as .param.")
else:
    print("FAILURE: .param lines missing or incorrect.")
    success = False

if not success:
    sys.exit(1)
