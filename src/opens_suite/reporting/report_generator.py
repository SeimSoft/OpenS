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
        self.hierarchy_images = []  # [(label, filename), ...]

    def generate(self):
        """Main execution sequence to drive reporting."""
        print(f"Generating report in {self.report_dir}...")
        self._prepare_directory()
        self._load_and_snapshot()
        self._export_hierarchy()
        self._find_simulation_results()
        self._evaluate_and_plot()
        self._build_html()
        print(
            f"Report generated successfully: {os.path.join(self.report_dir, 'index.html')}"
        )

    def _prepare_directory(self):
        os.makedirs(self.report_dir, exist_ok=True)
        # Copy the OpenS logo for the footer
        logo_src = os.path.join(
            os.path.dirname(__file__), "..", "assets", "launcher.png"
        )
        if os.path.exists(logo_src):
            shutil.copy2(logo_src, os.path.join(self.report_dir, "launcher.png"))

    def _render_scene_to_image(self, view, output_path):
        """Render a SchematicView's scene to a PNG file."""
        scene = view.scene()
        rect = scene.itemsBoundingRect()
        margin = 20
        rect.adjust(-margin, -margin, margin, margin)

        # High-res: scale up by 2x for retina-quality
        scale = 2
        img = QImage(
            int(rect.width() * scale),
            int(rect.height() * scale),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.fill(Qt.GlobalColor.white)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        from PyQt6.QtCore import QRectF

        scene.render(painter, target=QRectF(img.rect()), source=rect)
        painter.end()

        img.save(output_path)

    def _load_and_snapshot(self):
        print("Loading schematic and rendering snapshot...")
        self.view = SchematicView()
        self.view.filename = self.schematic_path
        self.view.load_schematic(self.schematic_path)
        self.view.recalculate_connectivity()

        self._render_scene_to_image(
            self.view, os.path.join(self.report_dir, "circuit.png")
        )

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
        self.outputs = []
        for elem in root.iter("{http://opens-schematic.org}output"):
            out_data = dict(elem.attrib)
            out_data["expression"] = elem.text.strip() if elem.text else ""
            self.outputs.append(out_data)

    def _export_hierarchy(self):
        """Walk scene items to find subcircuit references and export their schematics."""
        print("Exporting hierarchy schematics...")
        from opens_suite.schematic_item import SchematicItem

        scene = self.view.scene()
        visited = set()

        for item in scene.items():
            if not isinstance(item, SchematicItem):
                continue
            if not getattr(item, "prefix", "") == "X":
                continue

            model_param = item.parameters.get("MODEL", "")
            if not model_param:
                continue

            # Resolve the schematic path for this subcircuit
            sch_path = self._resolve_subcircuit_path(item)
            if not sch_path or sch_path in visited:
                continue

            visited.add(sch_path)
            label = os.path.splitext(os.path.basename(sch_path))[0]
            filename = f"subcircuit_{label}.png"

            try:
                sub_view = SchematicView()
                sub_view.filename = sch_path
                sub_view.load_schematic(sch_path)
                sub_view.recalculate_connectivity()
                self._render_scene_to_image(
                    sub_view, os.path.join(self.report_dir, filename)
                )
                self.hierarchy_images.append((label, filename))
                print(f"  Exported subcircuit: {label}")

                # Recurse: check subcircuits within this subcircuit
                self._export_sub_hierarchy(sub_view, visited)
            except Exception as e:
                print(f"  Warning: Could not export subcircuit {label}: {e}")

    def _export_sub_hierarchy(self, parent_view, visited):
        """Recursively export subcircuit schematics from a parent view."""
        from opens_suite.schematic_item import SchematicItem

        scene = parent_view.scene()
        for item in scene.items():
            if not isinstance(item, SchematicItem):
                continue
            if not getattr(item, "prefix", "") == "X":
                continue

            sch_path = self._resolve_subcircuit_path(item)
            if not sch_path or sch_path in visited:
                continue

            visited.add(sch_path)
            label = os.path.splitext(os.path.basename(sch_path))[0]
            filename = f"subcircuit_{label}.png"

            try:
                sub_view = SchematicView()
                sub_view.filename = sch_path
                sub_view.load_schematic(sch_path)
                sub_view.recalculate_connectivity()
                self._render_scene_to_image(
                    sub_view, os.path.join(self.report_dir, filename)
                )
                self.hierarchy_images.append((label, filename))
                print(f"  Exported subcircuit: {label}")
                self._export_sub_hierarchy(sub_view, visited)
            except Exception as e:
                print(f"  Warning: Could not export subcircuit {label}: {e}")

    def _resolve_subcircuit_path(self, item):
        """Resolve the schematic .svg path for a subcircuit item."""
        model_param = item.parameters.get("MODEL", "")
        if not model_param:
            return None

        sym_dir = os.path.dirname(item.svg_path) if item.svg_path else ""
        base_sch = model_param.replace(".sch", "").replace(".svg", "")

        candidates = [
            os.path.join(sym_dir, f"{base_sch}.svg"),
            os.path.join(sym_dir, f"{base_sch}.sch.svg"),
            os.path.join(sym_dir, "schematic.svg"),
            os.path.join(sym_dir, "schematic.sch.svg"),
        ]

        if item.svg_path and item.svg_path.endswith(".sym.svg"):
            candidates.append(item.svg_path.replace(".sym.svg", ".sch.svg"))
            candidates.append(item.svg_path.replace(".sym.svg", ".svg"))

        for path in candidates:
            if os.path.exists(path):
                return os.path.abspath(path)

        return None

    def _find_simulation_results(self):
        print("Checking for existing simulation results...")
        sim_dir = os.path.join(os.path.dirname(self.schematic_path), "simulation")
        base = os.path.splitext(os.path.basename(self.schematic_path))[0]

        raw_target = os.path.join(sim_dir, f"{base}.raw")
        log_target = os.path.join(sim_dir, f"{base}.log")

        if os.path.exists(raw_target):
            self._raw_path = raw_target
        else:
            print("No existing simulation raw file found.")
            self._raw_path = None

        if os.path.exists(log_target):
            self._log_path = log_target
        else:
            self._log_path = None

    def _evaluate_and_plot(self):
        print("Evaluating outputs...")
        from opens_suite.waveform_viewer import WaveformViewer
        import ast
        import numpy as np
        from opens_suite.design_points import DesignPoints

        calc = None
        scope = {}
        viewer = None

        if self._raw_path and os.path.exists(self._raw_path):
            calc = CalculatorDialog(self._raw_path)
            viewer = WaveformViewer()
            viewer.resize(800, 400)
            calc.viewer = viewer
            scope = calc._create_scope()

        for i, out in enumerate(self.outputs):
            name = out.get("name", f"expr_{i}")
            expr = out.get("expression", "")
            unit = out.get("unit", "")

            if not expr:
                continue

            if not self._raw_path:
                out["_eval_success"] = False
                out["_eval_error"] = "No simulation results available"
                continue

            try:
                if viewer:
                    viewer.clear()

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

                out["_eval_success"] = True

                if isinstance(result, (int, float, np.number, complex)):
                    if isinstance(result, complex):
                        val_str = f"{DesignPoints._format_si(result.real)} + j{DesignPoints._format_si(result.imag)}"
                    else:
                        val_str = DesignPoints._format_si(float(result))
                    out["_eval_scalar"] = val_str

                elif isinstance(result, np.ndarray) and result.size == 1:
                    val_str = DesignPoints._format_si(float(result.item()))
                    out["_eval_scalar"] = val_str

                elif isinstance(result, np.ndarray):
                    # Smart x-axis selection
                    x_axis = np.array([])
                    # Use more specific hints to avoid matching 't' in 'plot' or 'out'
                    if any(h in expr for h in ["vt(", "it(", "st(", ".t"]):
                        x_axis = scope.get("t", x_axis)
                    elif any(h in expr for h in ["vf(", "ifc(", "sf(", ".f"]):
                        x_axis = scope.get("f", x_axis)
                    elif any(h in expr for h in ["vdc(", "sdc(", "sw"]):
                        x_axis = scope.get("sw", x_axis)

                    if len(x_axis) != len(result):
                        # Fallback: find any default vector with matching length
                        # Prioritize sw if it matches, then t, then f
                        for cand in ["sw", "t", "f"]:
                            vec = scope.get(cand, [])
                            if len(vec) == len(result) and len(vec) > 0:
                                x_axis = vec
                                break

                    x_label, x_unit = None, None
                    if np.array_equal(x_axis, scope.get("sw", np.array([1]))):
                        x_label, x_unit = "Sweep", ""
                    elif np.array_equal(x_axis, scope.get("t", np.array([1]))):
                        x_label, x_unit = "Time", "s"
                    elif np.array_equal(x_axis, scope.get("f", np.array([1]))):
                        x_label, x_unit = "Frequency", "Hz"

                    if (
                        np.array_equal(x_axis, scope.get("f", np.array([])))
                        and np.iscomplexobj(result)
                        and len(x_axis) == len(result)
                    ):
                        viewer.bode(result, label=name)
                    else:
                        viewer.plot(x_axis, result, label=name)
                        if x_label:
                            for p in viewer.plots:
                                p.setLabel("bottom", x_label, x_unit)

                if viewer and len(viewer.signals) > 0:
                    from PyQt6.QtWidgets import QApplication
                    import pyqtgraph.exporters as exporters

                    QApplication.processEvents()

                    plot_filename = f"plot_{i}.png"
                    plot_path = os.path.join(self.report_dir, plot_filename)

                    exporter = exporters.ImageExporter(viewer.glw.scene())
                    exporter.parameters()["width"] = 1600
                    exporter.export(plot_path)

                    out["_eval_plot"] = plot_filename

            except Exception as e:
                import traceback

                print(f"Error evaluating {name}: {e}\n{traceback.format_exc()}")
                out["_eval_success"] = False
                out["_eval_error"] = str(e)

        if viewer:
            viewer.close()

    def _build_html(self):
        print("Building HTML file...")

        # Section numbering
        sect = 1

        html = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "    <meta charset='UTF-8'>",
            "    <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
            "    <title>OpenS Simulation Report</title>",
            "    <style>",
            "        * { box-sizing: border-box; }",
            "        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f4f4f9; color: #333; }",
            "        .container { max-width: 1000px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }",
            "        h1 { border-bottom: 2px solid #005A9C; padding-bottom: 10px; color: #005A9C; }",
            "        h2 { margin-top: 30px; color: #004080; }",
            "        .schematic { text-align: center; margin: 20px 0; }",
            "        .schematic img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); cursor: pointer; }",
            "        table { width: 100%; border-collapse: collapse; margin-top: 20px; }",
            "        th, td { padding: 12px; border: 1px solid #ddd; text-align: left; vertical-align: top; }",
            "        th { background-color: #005A9C; color: white; }",
            "        tr:nth-child(even) { background-color: #f9f9f9; }",
            "        pre { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; overflow-x: auto; font-family: 'Courier New', Courier, monospace; }",
            "        .plot-container { text-align: center; margin: 15px 0; border: 1px solid #eee; padding: 10px; background: #fafafa; }",
            "        .plot-container img { max-width: 100%; cursor: pointer; }",
            "        .error { color: #d9534f; font-weight: bold; }",
            # TOC Styles
            "        .toc { background: #f0f4f8; border: 1px solid #d0d8e0; border-radius: 6px; padding: 20px; margin: 20px 0; }",
            "        .toc h3 { margin-top: 0; color: #004080; }",
            "        .toc ul { list-style: none; padding-left: 0; margin: 0; }",
            "        .toc li { padding: 4px 0; }",
            "        .toc a { text-decoration: none; color: #005A9C; }",
            "        .toc a:hover { text-decoration: underline; }",
            # Lightbox Styles
            "        .lightbox-overlay { display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.92); z-index: 9999; justify-content: center; align-items: center; cursor: zoom-out; }",
            "        .lightbox-overlay.active { display: flex; }",
            "        .lightbox-overlay img { max-width: 95vw; max-height: 95vh; object-fit: contain; touch-action: none; transform-origin: center center; transition: transform 0.1s ease; }",
            "        .lightbox-close { position: fixed; top: 15px; right: 25px; color: white; font-size: 35px; cursor: pointer; z-index: 10000; font-weight: bold; line-height: 1; }",
            "    </style>",
            "</head>",
            "<body>",
            "    <div class='container'>",
            f"        <h1>Simulation Report: {os.path.basename(self.schematic_path)}</h1>",
            "",
        ]

        # --- Table of Contents ---
        toc_items = []

        toc_items.append((f"sect-{sect}", f"{sect}. Top-Level Schematic"))
        schematic_sect = sect
        sect += 1

        if self.hierarchy_images:
            toc_items.append((f"sect-{sect}", f"{sect}. Subcircuit Schematics"))
            hierarchy_sect = sect
            sect += 1
        else:
            hierarchy_sect = None

        toc_items.append(("sect-outputs", f"{sect}. Output Expressions"))
        outputs_sect = sect
        sect += 1

        # Check if any plots exist
        has_plots = any(out.get("_eval_plot") for out in self.outputs)
        if has_plots:
            toc_items.append(("sect-plots", f"{sect}. Waveform Plots"))
            plots_sect = sect
            sect += 1
        else:
            plots_sect = None

        toc_items.append(("sect-logs", f"{sect}. Simulation Logs"))
        logs_sect = sect
        sect += 1

        html.append("        <div class='toc'>")
        html.append("            <h3>Table of Contents</h3>")
        html.append("            <ul>")
        for anchor, label in toc_items:
            html.append(f"                <li><a href='#{anchor}'>{label}</a></li>")
        html.append("            </ul>")
        html.append("        </div>")
        html.append("")

        # --- Section: Top-Level Schematic ---
        html.append(
            f"        <h2 id='sect-{schematic_sect}'>{schematic_sect}. Top-Level Schematic</h2>"
        )
        html.append("        <div class='schematic'>")
        html.append(
            "            <img src='circuit.png' alt='Circuit Schematic' onclick='openLightbox(this)'>"
        )
        html.append("        </div>")
        html.append("")

        # --- Section: Subcircuit Schematics ---
        if hierarchy_sect is not None:
            html.append(
                f"        <h2 id='sect-{hierarchy_sect}'>{hierarchy_sect}. Subcircuit Schematics</h2>"
            )
            for label, filename in self.hierarchy_images:
                html.append(f"        <h3>{label}</h3>")
                html.append("        <div class='schematic'>")
                html.append(
                    f"            <img src='{filename}' alt='{label}' onclick='openLightbox(this)'>"
                )
                html.append("        </div>")
            html.append("")

        # --- Section: Output Expressions ---
        html.append(
            f"        <h2 id='sect-outputs'>{outputs_sect}. Output Expressions</h2>"
        )

        if not self.outputs:
            html.append("        <p>No outputs configured for this schematic.</p>")
        else:
            html.append("        <table>")
            html.append(
                "            <tr><th>Name</th><th>Expression</th><th>Unit</th><th>Min</th><th>Value</th><th>Max</th><th>Description</th></tr>"
            )
            for out in self.outputs:
                if "_eval_scalar" not in out and not out.get("_eval_error"):
                    continue

                name = out.get("name", "Unnamed")
                expr = out.get("expression", "")
                unit = out.get("unit", "")
                spec_min = out.get("min", "")
                spec_max = out.get("max", "")
                description = out.get("description", "")

                html.append("            <tr>")
                html.append(f"                <td>{name}</td>")
                html.append(
                    f"                <td><details><summary>show</summary><code>{expr}</code></details></td>"
                )
                html.append(f"                <td>{unit}</td>")
                html.append(f"                <td>{spec_min}</td>")

                # Value column with spec coloring
                if out.get("_eval_success") and "_eval_scalar" in out:
                    scalar_val = out["_eval_scalar"]
                    cell_color = self._spec_color(scalar_val, spec_min, spec_max)
                    html.append(
                        f"                <td style='background-color: {cell_color}; font-weight: bold; white-space: nowrap;'>{scalar_val}</td>"
                    )
                elif out.get("_eval_success"):
                    html.append("                <td>\u2014</td>")
                else:
                    err = out.get("_eval_error", "Unknown Error")
                    html.append(f"                <td class='error'>{err}</td>")

                html.append(f"                <td>{spec_max}</td>")
                html.append(f"                <td>{description}</td>")

                html.append("            </tr>")
            html.append("        </table>")

        # --- Section: Waveform Plots ---
        if plots_sect is not None:
            html.append("")
            html.append(
                f"        <h2 id='sect-plots'>{plots_sect}. Waveform Plots</h2>"
            )
            for out in self.outputs:
                if not out.get("_eval_plot"):
                    continue
                name = out.get("name", "Unnamed")
                expr = out.get("expression", "")
                description = out.get("description", "")
                html.append(f"        <h3>{name}</h3>")
                html.append(
                    f"        <p style='color: #666; font-size: 0.9em;'><code>{expr}</code></p>"
                )
                html.append("        <div class='schematic'>")
                html.append(
                    f"            <img src='{out['_eval_plot']}' alt='{name}' onclick='openLightbox(this)'>"
                )
                html.append("        </div>")
                if description:
                    html.append(
                        f"        <p style='margin-bottom: 30px;'>{description}</p>"
                    )

        # --- Section: Simulation Logs ---
        html.append("")
        html.append(f"        <h2 id='sect-logs'>{logs_sect}. Simulation Logs</h2>")

        if self._log_path and os.path.exists(self._log_path):
            with open(self._log_path, "r") as lf:
                log_content = lf.read()

            if len(log_content) > 100000:
                log_content = (
                    log_content[:50000]
                    + "\n\n... [LOG TRUNCATED] ...\n\n"
                    + log_content[-50000:]
                )

            html.append("        <details>")
            html.append("            <summary>Click to view simulation log</summary>")
            html.append(f"            <pre>{log_content}</pre>")
            html.append("        </details>")
        else:
            html.append("        <p><em>No simulation log available.</em></p>")

        html.append("    </div>")
        html.append("")

        # --- Footer Banner ---
        html.append(
            "    <div style='text-align: center; margin: 30px auto 10px; padding: 15px; opacity: 0.7;'>"
        )
        html.append(
            "        <a href='https://seimsoft.github.io/OpenS/' target='_blank' style='text-decoration: none; color: #666; display: inline-flex; align-items: center; gap: 8px;'>"
        )
        html.append(
            "            <img src='launcher.png' alt='OpenS' style='height: 24px; width: 24px;'>"
        )
        html.append(
            "            <span style='font-size: 12px;'>Created by OpenS</span>"
        )
        html.append("        </a>")
        html.append("    </div>")
        html.append("")

        # --- Lightbox overlay ---
        html.append(
            "    <div class='lightbox-overlay' id='lightbox' onclick='closeLightbox(event)'>"
        )
        html.append(
            "        <span class='lightbox-close' onclick='closeLightbox(event)'>&times;</span>"
        )
        html.append("        <img id='lightbox-img' src='' alt='Fullscreen'>")
        html.append("    </div>")
        html.append("")

        # --- Lightbox JavaScript with pinch-zoom ---
        html.append("    <script>")
        html.append(
            """
        const overlay = document.getElementById('lightbox');
        const lbImg = document.getElementById('lightbox-img');

        let scale = 1;
        let translateX = 0, translateY = 0;
        let isDragging = false;
        let startX, startY;
        let initialPinchDist = null;
        let initialScale = 1;

        function openLightbox(img) {
            lbImg.src = img.src;
            scale = 1; translateX = 0; translateY = 0;
            applyTransform();
            overlay.classList.add('active');
            document.body.style.overflow = 'hidden';
        }

        function closeLightbox(e) {
            if (e.target === overlay || e.target.classList.contains('lightbox-close')) {
                overlay.classList.remove('active');
                document.body.style.overflow = '';
            }
        }

        function applyTransform() {
            lbImg.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
        }

        // Mouse wheel zoom
        overlay.addEventListener('wheel', function(e) {
            e.preventDefault();
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            scale = Math.min(Math.max(0.2, scale * delta), 20);
            applyTransform();
        }, { passive: false });

        // Mouse drag
        lbImg.addEventListener('mousedown', function(e) {
            e.preventDefault();
            isDragging = true;
            startX = e.clientX - translateX;
            startY = e.clientY - translateY;
            lbImg.style.cursor = 'grabbing';
        });

        window.addEventListener('mousemove', function(e) {
            if (!isDragging) return;
            translateX = e.clientX - startX;
            translateY = e.clientY - startY;
            applyTransform();
        });

        window.addEventListener('mouseup', function() {
            isDragging = false;
            lbImg.style.cursor = 'grab';
        });

        // Touch: pinch zoom + drag
        lbImg.addEventListener('touchstart', function(e) {
            if (e.touches.length === 2) {
                initialPinchDist = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
                initialScale = scale;
            } else if (e.touches.length === 1) {
                isDragging = true;
                startX = e.touches[0].clientX - translateX;
                startY = e.touches[0].clientY - translateY;
            }
        }, { passive: true });

        lbImg.addEventListener('touchmove', function(e) {
            if (e.touches.length === 2 && initialPinchDist) {
                e.preventDefault();
                const dist = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
                scale = Math.min(Math.max(0.2, initialScale * (dist / initialPinchDist)), 20);
                applyTransform();
            } else if (e.touches.length === 1 && isDragging) {
                translateX = e.touches[0].clientX - startX;
                translateY = e.touches[0].clientY - startY;
                applyTransform();
            }
        }, { passive: false });

        lbImg.addEventListener('touchend', function(e) {
            if (e.touches.length < 2) initialPinchDist = null;
            if (e.touches.length === 0) isDragging = false;
        });

        // ESC to close
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                overlay.classList.remove('active');
                document.body.style.overflow = '';
            }
        });
        """
        )
        html.append("    </script>")
        html.append("</body>")
        html.append("</html>")

        with open(os.path.join(self.report_dir, "index.html"), "w") as f:
            f.write("\n".join(html))

    @staticmethod
    def _spec_color(scalar_str, spec_min, spec_max):
        """Return a CSS background color based on spec compliance."""
        try:
            # Parse numeric value from SI-formatted string
            val_str = scalar_str.strip()
            # Remove any trailing unit text
            parts = val_str.split()
            num_str = parts[0] if parts else val_str

            si_suffixes = {
                "y": 1e-24,
                "z": 1e-21,
                "a": 1e-18,
                "f": 1e-15,
                "p": 1e-12,
                "n": 1e-9,
                "u": 1e-6,
                "µ": 1e-6,
                "m": 1e-3,
                "k": 1e3,
                "K": 1e3,
                "M": 1e6,
                "G": 1e9,
                "T": 1e12,
            }

            multiplier = 1.0
            clean = num_str
            if clean and clean[-1] in si_suffixes:
                multiplier = si_suffixes[clean[-1]]
                clean = clean[:-1]

            val = float(clean) * multiplier

            has_min = spec_min and spec_min.strip()
            has_max = spec_max and spec_max.strip()

            if not has_min and not has_max:
                return "transparent"

            in_spec = True
            if has_min:
                if val < float(spec_min):
                    in_spec = False
            if has_max:
                if val > float(spec_max):
                    in_spec = False

            return "#d4edda" if in_spec else "#f8d7da"  # green / red

        except (ValueError, TypeError, IndexError):
            return "transparent"
