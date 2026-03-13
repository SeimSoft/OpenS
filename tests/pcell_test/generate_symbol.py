import sys
import os

# Add src to path
sys.path.append(os.path.abspath("src"))

from opens_suite.symbol_generator import SymbolGenerator

sch_path = "tests/pcell_test/gain_block/schematic.svg"
sym_path = "tests/pcell_test/gain_block/symbol.svg"

SymbolGenerator.generate_symbol(sch_path, sym_path)
