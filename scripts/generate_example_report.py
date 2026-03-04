import os
import sys

# Setup path to find opens_suite
sys.path.append(os.path.join(os.getcwd(), "src"))

from opens_suite.reporting.report_generator import ReportGenerator
from PyQt6.QtWidgets import QApplication


def generate_example_report():
    # ReportGenerator needs a QApplication for schematic rendering
    app = QApplication(sys.argv)

    test_svg = os.path.abspath("tests/dc_sim.svg")
    report_dir = os.path.abspath("docs/example_report")

    if not os.path.exists(test_svg):
        print(f"Error: {test_svg} not found.")
        return

    print(f"Generating example report from {test_svg} into {report_dir}...")

    # Ensure directory exists
    os.makedirs(report_dir, exist_ok=True)

    try:
        gen = ReportGenerator(test_svg, report_dir)
        gen.generate()
        print(f"Example report generated successfully at {report_dir}/index.html")
    except Exception as e:
        print(f"Failed to generate example report: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    generate_example_report()
