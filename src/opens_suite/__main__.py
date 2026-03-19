import sys
import os
import argparse
import time


def _update_splash(proc, msg=None, progress=None):
    """Send a message or progress update to the splash process via stdin."""
    if not proc or proc.poll() is not None:
        return
    try:
        if msg:
            proc.stdin.write(f"MSG:{msg}\n")
        if progress is not None:
            proc.stdin.write(f"PROGRESS:{progress}\n")
        proc.stdin.flush()
    except Exception:
        pass


def _apply_global_style(app):
    """Apply a consistent theme.

    Prefer qt-material if available, but always overlay the local stylesheet to
    ensure critical components (e.g. table text and selection) remain readable.
    """

    try:
        import qt_material

        # See: https://qt-material.readthedocs.io/en/latest/
        # Prefer a light material theme when available.
        qt_material.apply_stylesheet(app, theme="light_blue.xml")
    except Exception:
        pass

    style_path = os.path.join(os.path.dirname(__file__), "style.qss")
    if os.path.exists(style_path):
        try:
            with open(style_path, "r") as f:
                app.setStyleSheet(f.read())
        except Exception:
            pass


def _create_splash(app):
    """Create and show a centered splash screen as early as possible."""

    from PyQt6.QtWidgets import QSplashScreen
    from PyQt6.QtGui import QPainter, QFont, QColor, QPixmap
    from PyQt6.QtCore import QRect, Qt

    logo_path = os.path.join(os.path.dirname(__file__), "assets", "launcher.png")

    # Build a small, predictable splash pixmap (400x200)
    pixmap = QPixmap(400, 200)
    pixmap.fill(QColor("#f5f6fa"))

    if os.path.exists(logo_path):
        logo = QPixmap(logo_path)
        if not logo.isNull():
            logo = logo.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter = QPainter(pixmap)
            painter.drawPixmap((400 - logo.width()) // 2, 18, logo)
            painter.setPen(QColor("#1f1f1f"))
            painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
            painter.drawText(QRect(0, 130, 400, 60), Qt.AlignmentFlag.AlignCenter, "OpenS")
            painter.end()

    splash = QSplashScreen(pixmap, Qt.WindowType.WindowStaysOnTopHint)
    splash.setMask(pixmap.mask())

    # Center on primary screen.
    screen = app.primaryScreen()
    if screen:
        geo = screen.availableGeometry()
        splash.move(
            geo.x() + (geo.width() - splash.width()) // 2,
            geo.y() + (geo.height() - splash.height()) // 2,
        )

    splash.show()
    splash.showMessage(
        "Loading…",
        alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        color=QColor("#1f1f1f"),
    )

    app.processEvents()
    splash._created_at = time.monotonic()
    return splash


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

    is_gui = not (args.netlist or args.simulate or args.report)
    is_cli = not is_gui

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

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from PyQt6.QtCore import QCoreApplication

    # Subprocess splash screen initialization
    import subprocess
    splash_proc = None
    if is_gui and "PYTEST_CURRENT_TEST" not in os.environ:
        splash_script = os.path.join(os.path.dirname(__file__), "splash_tk.py")
        if os.path.exists(splash_script):
            splash_proc = subprocess.Popen(
                [sys.executable, splash_script],
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            _update_splash(splash_proc, "Initializing...", 10)

    QCoreApplication.setApplicationName("OpenS")
    QCoreApplication.setOrganizationName("OpenS")

    app = QApplication(sys.argv)
    app.setApplicationDisplayName("OpenS")
    app._splash_proc = splash_proc
    _update_splash(app._splash_proc, "Configuring application...", 30)
    app.setWindowIcon(
        QIcon(os.path.join(os.path.dirname(__file__), "assets", "launcher.png"))
    )

    if is_cli:
        # CLI modes apply style immediately since there's no GUI event loop
        _apply_global_style(app)

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

    def start_gui():
        _update_splash(app._splash_proc, "Applying styles...", 40)
        _apply_global_style(app)

        _update_splash(app._splash_proc, "Loading main interface...", 60)
        from opens_suite.main_window import MainWindow

        _update_splash(app._splash_proc, "Preparing components...", 80)
        window = MainWindow(project_dir=project_dir)
        if file_to_open:
            _update_splash(app._splash_proc, f"Opening {os.path.basename(file_to_open)}...", 90)
            window.open_file(file_to_open)
        
        _update_splash(app._splash_proc, "Ready!", 100)
        window.show()

        if hasattr(app, "_splash_proc") and app._splash_proc:
            try:
                app._splash_proc.stdin.write("QUIT\n")
                app._splash_proc.stdin.flush()
                import time
                # Wait a bit then terminate if it's still alive
                def cleanup():
                    if app._splash_proc.poll() is None:
                        app._splash_proc.terminate()
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(500, cleanup)
            except Exception:
                pass
                
        # Keep reference to prevent garbage collection
        app._main_window = window

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, start_gui)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
