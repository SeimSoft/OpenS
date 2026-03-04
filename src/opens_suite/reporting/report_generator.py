import os
import sys
import xml.etree.ElementTree as ET
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtCore import Qt, QSize
import shutil

from opens_suite.view.core import SchematicView
from opens_suite.netlister import NetlistGenerator
from opens_suite.xyce_runner import XyceRunner
from opens_suite.calculator_widget import CalculatorDialog


class ReportGenerator:
    def __init__(self, schematic_path, report_dir):
        self.schematic_path = os.path.abspath(schematic_path)
        self.report_dir = os.path.abspath(report_dir)
        self.view = None
        self.netlist = ""
        self.outputs = []
        self._raw_path = ""
        self._netlist_path = ""
        self._log_path = ""

    def generate(self):
        """Main execution sequence to drive reporting."""
        print(f"Generating report in {self.report_dir}...")
        self._prepare_directory()
        self._load_and_snapshot()
        self._simulate()
        self._evaluate_and_plot()
        self._build_html()
        print(
            f"Report generated successfully: {os.path.join(self.report_dir, 'index.html')}"
        )

    def _prepare_directory(self):
        os.makedirs(self.report_dir, exist_ok=True)
        # We don't wipe everything to be safe, but we will overwrite files.

    def _load_and_snapshot(self):
        print("Loading schematic and rendering snapshot...")
        self.view = SchematicView()
        self.view.filename = self.schematic_path
        self.view.load_schematic(self.schematic_path)

        # Force a refresh to resolve visual dependencies
        self.view.recalculate_connectivity()

        # Render QGraphicsScene to QImage
        scene = self.view.scene()
        rect = scene.itemsBoundingRect()
        margin = 20
        rect.adjust(-margin, -margin, margin, margin)

        # Create high-res image
        img = QImage(
            int(rect.width()),
            int(rect.height()),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.fill(Qt.GlobalColor.white)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        from PyQt6.QtCore import QRectF

        scene.render(painter, target=QRectF(img.rect()), source=rect)
        painter.end()

        img.save(os.path.join(self.report_dir, "circuit.png"))

        # Extract analyses, variables, and outputs
        tree = ET.parse(self.schematic_path)
        root = tree.getroot()

        self.analyses = [
            dict(elem.attrib)
            for elem in root.iter("{http://opens-schematic.org}analysis")
        ]
        self.variables = [
            dict(elem.attrib)
            for elem in root.iter("{http://opens-schematic.org}variable")
        ]
        self.outputs = [
            dict(elem.attrib)
            for elem in root.iter("{http://opens-schematic.org}output")
        ]

    def _simulate(self):
        print("Generating netlist and simulating...")
        gen = NetlistGenerator(
            self.view.scene(), self.analyses, variables=self.variables
        )
        self.netlist = gen.generate()

        self._netlist_path = os.path.join(self.report_dir, "simulation.net")
        self._raw_path = os.path.join(self.report_dir, "simulation.raw")
        self._log_path = os.path.join(self.report_dir, "simulation.log")

        with open(self._netlist_path, "w") as f:
            f.write(self.netlist)

        runner = XyceRunner()
        # Capture stdout to log file if possible. run_cli natively streams to terminal.
        # So we write a simple wrapper or just let XyceRunner generate the raw file.
        # Actually XyceRunner prints via Popen. We can redirect via subprocess if needed.
        import subprocess

        try:
            with open(self._log_path, "w") as log_file:
                process = subprocess.Popen(
                    ["Xyce", self._netlist_path, "-r", self._raw_path],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
                process.wait()
                if process.returncode != 0:
                    print(f"Simulation failed with code {process.returncode}")
        except FileNotFoundError:
            print("Xyce executable not found on PATH. Simulation aborting.")

    def _evaluate_and_plot(self):
        print("Evaluating outputs...")
        if not os.path.exists(self._raw_path):
            print("No raw file found. Skipping evaluation.")
            return

        from opens_suite.waveform_viewer import WaveformViewer
        import ast
        import numpy as np
        from opens_suite.design_points import DesignPoints

        # Load Calculator session
        calc = CalculatorDialog(self._raw_path)
        scope = calc._create_scope()

        # We need a headless waveform viewer to grab plots
        viewer = WaveformViewer()
        viewer.resize(800, 400)

        for i, out in enumerate(self.outputs):
            name = out.get("name", f"expr_{i}")
            expr = out.get("expression", "")
            unit = out.get("unit", "")

            if not expr:
                continue

            try:
                # Execute Expression
                tree = ast.parse(expr)
                if not tree.body:
                    continue
                last_node = tree.body[-1]

                result = None
                if isinstance(last_node, ast.Expr):
                    if len(tree.body) > 1:
                        exec_body = ast.Module(body=tree.body[:-1], type_ignores=[])
                        exec(compile(exec_body, "<string>", "exec"), scope)
                    eval_expr = ast.Expression(body=last_node.value)
                    result = eval(compile(eval_expr, "<string>", "eval"), scope)
                else:
                    exec(expr, scope)
                    continue

                # Process Result
                out["_eval_success"] = True

                if isinstance(result, (int, float, np.number, complex)):
                    # Scalar
                    if isinstance(result, complex):
                        val_str = f"{DesignPoints._format_si(result.real)} + j{DesignPoints._format_si(result.imag)}"
                    else:
                        val_str = DesignPoints._format_si(float(result))
                    out["_eval_result"] = f"{val_str} {unit}".strip()
                    out["_eval_type"] = "scalar"

                elif isinstance(result, np.ndarray) and result.size == 1:
                    # Single item array scalar
                    val_str = DesignPoints._format_si(float(result.item()))
                    out["_eval_result"] = f"{val_str} {unit}".strip()
                    out["_eval_type"] = "scalar"

                elif isinstance(result, np.ndarray):
                    # Array waveform
                    viewer.clear()

                    # Deduce X axis
                    x_axis = scope["t"] if "vt" in expr or "it" in expr else scope["f"]

                    # Need to map bode check
                    if (
                        np.array_equal(x_axis, scope.get("f", np.array([])))
                        and np.iscomplexobj(result)
                        and len(x_axis) == len(result)
                    ):
                        viewer.bode(result, label=name)
                    else:
                        viewer.plot(x_axis, result, label=name)

                    # Force render cycle headless
                    viewer.show()
                    import time
                    from PyQt6.QtWidgets import QApplication

                    QApplication.processEvents()
                    time.sleep(0.1)  # Brief pause for GL viewport draw
                    QApplication.processEvents()

                    plot_filename = f"plot_{i}.png"
                    plot_path = os.path.join(self.report_dir, plot_filename)
                    # Grab waveform image natively
                    pixmap = viewer.grab()
                    pixmap.save(plot_path)

                    out["_eval_result"] = plot_filename
                    out["_eval_type"] = "plot"

            except Exception as e:
                out["_eval_success"] = False
                out["_eval_error"] = str(e)

        viewer.close()

    def _build_html(self):
        print("Building HTML file...")
        html = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "    <meta charset='UTF-8'>",
            "    <title>OpenS Simulation Report</title>",
            "    <style>",
            "        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f4f4f9; color: #333; }",
            "        .container { max-width: 1000px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }",
            "        h1 { border-bottom: 2px solid #005A9C; padding-bottom: 10px; color: #005A9C; }",
            "        h2 { margin-top: 30px; color: #004080; }",
            "        .schematic { text-align: center; margin: 20px 0; }",
            "        .schematic img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }",
            "        table { width: 100%; border-collapse: collapse; margin-top: 20px; }",
            "        th, td { padding: 12px; border: 1px solid #ddd; text-align: left; }",
            "        th { background-color: #005A9C; color: white; }",
            "        tr:nth-child(even) { background-color: #f9f9f9; }",
            "        pre { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; overflow-x: auto; font-family: 'Courier New', Courier, monospace; }",
            "        .plot-container { text-align: center; margin: 15px 0; border: 1px solid #eee; padding: 10px; background: #fafafa; }",
            "        .plot-container img { max-width: 100%; }",
            "        .error { color: #d9534f; font-weight: bold; }",
            "    </style>",
            "</head>",
            "<body>",
            "    <div class='container'>",
            f"        <h1>Simulation Report: {os.path.basename(self.schematic_path)}</h1>",
            "        ",
            "        <h2>1. Circuit Schematic</h2>",
            "        <div class='schematic'>",
            "            <img src='circuit.png' alt='Circuit Schematic'>",
            "        </div>",
            "",
            "        <h2>2. Output Expressions</h2>",
        ]

        if not self.outputs:
            html.append("        <p>No outputs configured for this schematic.</p>")
        else:
            html.append("        <table>")
            html.append(
                "            <tr><th>Name</th><th>Expression</th><th>Result / Plot</th></tr>"
            )
            for out in self.outputs:
                name = out.get("name", "Unnamed")
                expr = out.get("expression", "")

                html.append("            <tr>")
                html.append(f"                <td>{name}</td>")
                html.append(f"                <td><code>{expr}</code></td>")

                if out.get("_eval_success"):
                    if out.get("_eval_type") == "scalar":
                        res = out.get("_eval_result")
                        html.append(f"                <td><strong>{res}</strong></td>")
                    elif out.get("_eval_type") == "plot":
                        img = out.get("_eval_result")
                        html.append(
                            f"                <td><div class='plot-container'><img src='{img}' alt='Waveform Plot'></div></td>"
                        )
                else:
                    err = out.get("_eval_error", "Unknown Error")
                    html.append(f"                <td class='error'>Error: {err}</td>")

                html.append("            </tr>")
            html.append("        </table>")

        html.extend(
            [
                "",
                "        <h2>3. Simulation Logs</h2>",
            ]
        )

        # Inject log file
        log_content = "Log file not found or simulation skipped."
        if os.path.exists(self._log_path):
            with open(self._log_path, "r") as lf:
                log_content = lf.read()

        # Ensure log isn't too massive to embed directly. Truncate if > 100k
        if len(log_content) > 100000:
            log_content = (
                log_content[:50000]
                + "\n\n... [LOG TRUNCATED] ...\n\n"
                + log_content[-50000:]
            )

        html.append(f"        <pre>{log_content}</pre>")

        html.extend(["    </div>", "</body>", "</html>"])

        with open(os.path.join(self.report_dir, "index.html"), "w") as f:
            f.write("\n".join(html))
