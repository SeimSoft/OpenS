import sys
import os
import argparse
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from opens_suite.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description="OpenS - Schematic Entry")
    parser.add_argument(
        "path", nargs="?", help="Project directory or schematic file to open"
    )
    parser.add_argument(
        "--netlist", action="store_true", help="Generate netlist and print to stdout"
    )
    parser.add_argument("--simulate", action="store_true", help="Run Xyce simulation")
    parser.add_argument(
        "--report",
        type=str,
        metavar="DIR",
        help="Generate an HTML simulation report in the specified directory",
    )
    args = parser.parse_args()

    project_dir = os.getcwd()
    file_to_open = None

    if args.path:
        if args.path.endswith(".svg") or (
            os.path.exists(args.path) and os.path.isfile(args.path)
        ):
            file_to_open = os.path.abspath(args.path)
            # Assume structure: project_dir / lib / cell / view.svg
            cell_dir = os.path.dirname(file_to_open)
            lib_dir = os.path.dirname(cell_dir)
            project_dir = os.path.dirname(lib_dir)
        else:
            project_dir = os.path.abspath(args.path)
            if not os.path.exists(project_dir):
                os.makedirs(project_dir, exist_ok=True)
                print(f"Created project directory: {project_dir}")

    app = QApplication(sys.argv)
    app.setApplicationName("OpenS")
    app.setWindowIcon(
        QIcon(os.path.join(os.path.dirname(__file__), "assets", "launcher.png"))
    )

    if args.report:
        if not file_to_open:
            print("Error: Specify a schematic file.")
            sys.exit(1)
        try:
            from opens_suite.reporting.report_generator import ReportGenerator

            generator = ReportGenerator(file_to_open, args.report)
            generator.generate()
        except Exception as e:
            print(f"Error during report generation: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)
        sys.exit(0)

    if args.netlist or args.simulate:
        if not file_to_open:
            print("Error: Specify a schematic or netlist file.")
            sys.exit(1)

        is_netlist = file_to_open.lower().endswith((".net", ".cir", ".spice"))

        if is_netlist:
            if args.netlist:
                with open(file_to_open, "r") as f:
                    print(f.read())

            if args.simulate:
                print(f"Starting Xyce simulation for netlist {file_to_open}...")
                sim_dir = os.path.dirname(file_to_open)
                base = os.path.splitext(os.path.basename(file_to_open))[0]
                raw_path = os.path.join(sim_dir, f"{base}.raw")

                from opens_suite.xyce_runner import XyceRunner

                runner = XyceRunner()
                returncode = runner.run_cli(file_to_open, raw_path)

                if returncode == 0:
                    print(f"\nSimulation finished successfully. Results in {raw_path}")
                else:
                    print(f"\nSimulation failed with exit code {returncode}")
                    sys.exit(returncode)
            sys.exit(0)

        # Schematic handling
        from opens_suite.view.core import SchematicView
        from opens_suite.netlister import NetlistGenerator
        import xml.etree.ElementTree as ET

        view = SchematicView()
        # Ensure we set the filename so hierarchical resolution works
        view.filename = file_to_open
        view.load_schematic(file_to_open)

        # Parse extra metadata for netlisting
        try:
            tree = ET.parse(file_to_open)
            root = tree.getroot()
            analyses = []
            for elem in root.iter("{http://opens-schematic.org}analysis"):
                analyses.append(dict(elem.attrib))
            variables = []
            for elem in root.iter("{http://opens-schematic.org}variable"):
                variables.append(dict(elem.attrib))

            gen = NetlistGenerator(view.scene(), analyses, variables=variables)
            netlist = gen.generate()

            if args.netlist:
                print(netlist)

            if args.simulate:
                sim_dir = os.path.join(os.path.dirname(file_to_open), "simulation")
                os.makedirs(sim_dir, exist_ok=True)
                base = os.path.splitext(os.path.basename(file_to_open))[0]
                netlist_path = os.path.join(sim_dir, f"{base}.net")
                raw_path = os.path.join(sim_dir, f"{base}.raw")

                with open(netlist_path, "w") as f:
                    f.write(netlist)

                print(f"Starting Xyce simulation for {file_to_open}...")

                from opens_suite.xyce_runner import XyceRunner

                runner = XyceRunner()
                returncode = runner.run_cli(netlist_path, raw_path)

                if returncode == 0:
                    print(f"\nSimulation finished successfully. Results in {raw_path}")
                else:
                    print(f"\nSimulation failed with exit code {returncode}")
                    sys.exit(returncode)

        except Exception as e:
            print(f"Error during CLI operation: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)
        sys.exit(0)

    window = MainWindow(project_dir=project_dir)
    if file_to_open:
        window.open_file(file_to_open)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
