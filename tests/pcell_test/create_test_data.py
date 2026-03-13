import os
import json


def create_svg(path, content):
    with open(path, "w") as f:
        f.write(content)


# Subcircuit Schematic
gain_block_sch = """<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000">
    <!-- Pins -->
    <g symbol_name="pin_in" library_path="opensLib/pin_in/symbol.svg" name="IN" transform="translate(100,100)"/>
    <g symbol_name="pin_out" library_path="opensLib/pin_out/symbol.svg" name="OUT" transform="translate(300,100)"/>
    
    <!-- Resistor R1 -->
    <g symbol_name="resistor" library_path="opensLib/resistor/symbol.svg" name="R1" transform="translate(200,100)" param_R="{gain*1k}"/>
    
    <!-- Design Script -->
    <g symbol_name="design_script" library_path="opensLib/design_script/symbol.svg" name="DS1" transform="translate(50,50)" param_SCRIPT="script.ipynb"/>
</svg>"""

# Top Schematic
top_sch = """<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000">
    <g symbol_name="gain_block" library_path="gain_block/symbol.svg" name="X1" transform="translate(100,100)" param_gain="10"/>
    <g symbol_name="gain_block" library_path="gain_block/symbol.svg" name="X2" transform="translate(100,200)" param_gain="20"/>
    <line x1="0" y1="100" x2="100" y2="100" stroke="black" stroke-width="2" net_name="IN1"/>
    <line x1="0" y1="200" x2="100" y2="200" stroke="black" stroke-width="2" net_name="IN2"/>
</svg>"""

# Notebook Content (basic JSON structure for .ipynb)
notebook = {
    "cells": [
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "import json\n",
                "import os\n",
                "from opens_suite.design_points import DesignPoints\n",
                "\n",
                "# Read parameters.json\n",
                "with open('parameters.json', 'r') as f:\n",
                "    params = json.load(f)\n",
                "\n",
                "gain = float(params.get('gain', 1.0))\n",
                "\n",
                "dps = DesignPoints()\n",
                "dps['R1.Value'] = f'{gain * 1000}'\n",
                "\n",
                "# Save results to script.json\n",
                "dps.save('script.json')",
            ],
        }
    ],
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "codemirror_mode": {"name": "ipython", "version": 3},
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython3",
            "version": "3.8.10",
        },
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

base_dir = "tests/pcell_test"
os.makedirs(os.path.join(base_dir, "gain_block"), exist_ok=True)

create_svg(os.path.join(base_dir, "gain_block/schematic.svg"), gain_block_sch)
create_svg(os.path.join(base_dir, "top.svg"), top_sch)

with open(os.path.join(base_dir, "gain_block/script.ipynb"), "w") as f:
    json.dump(notebook, f, indent=1)

print("Test data created.")
