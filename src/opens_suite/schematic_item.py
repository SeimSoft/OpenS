import xml.etree.ElementTree as ET
from PyQt6.QtWidgets import (
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsObject,
    QGraphicsItem,
    QDialog,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QByteArray, pyqtSignal
from PyQt6.QtGui import QBrush, QPen, QColor, QFont
from PyQt6.QtSvg import QSvgRenderer
from opens_suite.theme import theme_manager


class SchematicItem(QGraphicsObject):
    openSubcircuitRequested = pyqtSignal(str)

    def __init__(self, svg_path, parent=None):
        super().__init__(parent)
        self.svg_path = svg_path
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

        self.pins = {}  # id -> QPointF (relative to item)
        self.parameters = {}  # name -> value_str
        self.name = ""
        self.prefix = "X"
        self.connected_pins = []
        self.buttons = {}  # action -> QRectF

        # Simulation export settings
        self.save_voltage = True
        self.save_current = False

        # Template-based Text
        with open(svg_path, "r") as f:
            self.svg_template = f.read()

        # Instance-specific renderer
        self._renderer = QSvgRenderer()

        self.text_anchors = {}  # 'name': QPointF, 'value': QPointF
        self.label_items = {}  # template_str -> QGraphicsSimpleTextItem
        self.simulation_results = {}  # key -> float

        self._parse_pins()
        self._parse_labels()
        self._parse_parameters()
        self._parse_buttons()
        self._update_svg()

        theme_manager.themeChanged.connect(self.apply_theme)

    def reload_symbol(self):
        """Re-reads the SVG and updates pins/labels/visuals."""
        # 1. Cleanup existing generated children
        # Pins
        for pin_info in self.pins.values():
            if "item" in pin_info and pin_info["item"] in self.childItems():
                pin_info["item"].setParentItem(None)
                if self.scene():
                    self.scene().removeItem(pin_info["item"])
        self.pins.clear()

        # Labels
        for label_item in self.label_items.values():
            if label_item in self.childItems():
                label_item.setParentItem(None)
                if self.scene():
                    self.scene().removeItem(label_item)
        self.label_items.clear()

        # 2. Re-read and Re-parse
        try:
            with open(self.svg_path, "r") as f:
                self.svg_template = f.read()
            self._parse_pins()
            self._parse_labels()
            self._parse_parameters(overwrite=False)
            self._parse_buttons()
            self._update_svg()
            self._update_labels()
        except Exception as e:
            print(f"Error reloading symbol {self.svg_path}: {e}")

        self.update()

    def apply_theme(self):
        self._update_label_styles()
        self._update_labels()
        self._update_svg()
        self.update()

    def _update_label_styles(self):
        for item in self.label_items.values():
            cls = item.data(0)
            if cls == "label":
                item.setBrush(QBrush(theme_manager.get_color("font_label")))
            elif cls in ["value", "voltage"]:
                item.setBrush(QBrush(theme_manager.get_color("font_voltage")))
            else:
                item.setBrush(QBrush(theme_manager.get_color("font_default")))

    def boundingRect(self):
        if self._renderer.isValid():
            viewbox = self._renderer.viewBoxF()
            if not viewbox.isNull():
                return viewbox
            return QRectF(self._renderer.defaultSize())
        return QRectF(0, 0, 50, 50)

    def paint(self, painter, option, widget):
        # Draw Sanitized SVG
        if self._renderer.isValid():
            viewbox = self._renderer.viewBoxF()
            if viewbox.isNull():
                viewbox = QRectF(self._renderer.defaultSize())
            # Render SVG onto its native bounds (not the enlarged bounding box)
            self._renderer.render(painter, viewbox)

        # Draw Bounding Box if selected
        if self.isSelected():
            painter.setPen(
                QPen(theme_manager.get_color("selection"), 1, Qt.PenStyle.DashLine)
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())

    def set_name(self, name):
        self.name = name
        self._update_labels()

    def set_parameter(self, name, value):
        # Accept case-insensitive parameter names. If a matching key exists
        # (any case), update that entry. Otherwise add the parameter using
        # the provided name so newly-created parameters are preserved.
        if name in self.parameters:
            self.parameters[name] = value
            self._update_labels()
            return

        # Try case-insensitive match
        lname = name.lower()
        for k in list(self.parameters.keys()):
            if k.lower() == lname:
                self.parameters[k] = value
                self._update_labels()
                return

        # No existing parameter found: add it
        self.parameters[name] = value
        self._update_labels()

        # If it was a NET_NAME change, we might need to refresh pins
        if name.upper() == "NET_NAME":
            self._update_svg()
            self._parse_pins()

    def _update_labels(self):
        # Update independent text items
        # Compute "index" which is name without prefix (e.g. "R1" -> "1")
        idx = self.name or ""
        if idx and self.prefix and idx.startswith(self.prefix):
            idx = idx[len(self.prefix) :]

        full_name = self.name or ""
        for template, item in self.label_items.items():
            text = template
            # Provide {name} (full name, e.g. R1) and {index} (e.g. 1)
            text = text.replace("{name}", full_name)
            text = text.replace("{index}", idx)
            text = text.replace("{fullName}", full_name)
            text = text.replace("{Name}", full_name)
            # Replace parameter placeholders case-insensitively. Parameters
            # are stored normalized (upper-case) by _parse_parameters, but
            # templates may use any case like {modelname} or {MODELNAME}.
            import re

            for k, v in self.parameters.items():
                try:
                    pattern = re.compile(
                        r"\{" + re.escape(k) + r"\}", flags=re.IGNORECASE
                    )
                    text = pattern.sub(str(v), text)
                except re.error:
                    # Fallback to simple replace if regex fails for some reason
                    text = text.replace(f"{{{k}}}", str(v))
            # Normalized placeholder
            # Replace generic {value} placeholder (case-insensitive)
            if self.parameters:
                try:
                    val_pattern = re.compile(r"\{value\}", flags=re.IGNORECASE)
                    text = val_pattern.sub(str(list(self.parameters.values())[0]), text)
                except re.error:
                    if "{value}" in text:
                        text = text.replace(
                            "{value}", str(list(self.parameters.values())[0])
                        )

            # Back-annotation placeholders (e.g., {i(v1)}, {@r1[i]})
            from opens_suite.spice_parser import SpiceRawParser

            placeholders = re.findall(r"\{(.*?)\}", text)
            for p in placeholders:
                # Resolve using smart helper
                hint = (
                    "i"
                    if p.lower().endswith(":i") or p.lower().startswith("i(")
                    else "v"
                )
                val = SpiceRawParser.find_signal(
                    self.simulation_results, p, type_hint=hint
                )

                if val is not None:
                    # Format with unit
                    formatted = self._format_value(val)
                    text = text.replace(f"{{{p}}}", formatted)
                elif "(" in p or "@" in p or ":" in p:
                    # If it looks like a simulation variable but we don't have it yet,
                    # just keep the placeholder or clear it?
                    # Keep it for now.
                    pass
                    # we could hide it or show empty. Let's show empty or "?"
                    text = text.replace(f"{{{p}}}", "--")

            item.setText(text)

            # Apply alignment based on stored metadata
            orig_x = item.data(1)
            orig_y = item.data(2)
            anchor = item.data(3)

            if orig_x is not None and orig_y is not None:
                # SVG y is baseline, Qt SimpleTextItem y is top.
                rect = item.boundingRect()

                new_x = orig_x
                if anchor == "end":
                    new_x = orig_x - rect.width()
                elif anchor == "middle":
                    new_x = orig_x - rect.width() / 2

                # Baseline correction: Shift up by roughly 75% of the height
                # to make the text appear on the baseline.
                item.setPos(new_x, orig_y - rect.height() * 0.75)

    def _format_value(self, val):
        unit = "A"  # Default for currents
        abs_val = abs(val)
        if abs_val == 0:
            return "0"

        if abs_val >= 1e6:
            return f"{val/1e6:.2f}Meg{unit}"
        elif abs_val >= 1e3:
            return f"{val/1e3:.2f}k{unit}"
        elif abs_val >= 1:
            return f"{val:.2f}{unit}"
        elif abs_val >= 1e-3:
            return f"{val*1e3:.2f}m{unit}"
        elif abs_val >= 1e-6:
            return f"{val*1e6:.2f}u{unit}"
        elif abs_val >= 1e-9:
            return f"{val*1e9:.2f}n{unit}"
        elif abs_val >= 1e-12:
            return f"{val*1e12:.2f}p{unit}"
        else:
            return f"{val:.2e}{unit}"

    def _update_svg(self):
        # Remove <text> elements from template to avoid doubling/clipping.
        # Use ET to be robust vs. structure and namespaces.
        try:
            root = ET.fromstring(self.svg_template)
            line_color = theme_manager.get_color("line_default").name()

            import re

            def replace_black(s):
                if not s:
                    return s
                # Replace 'black' as a whole word
                s = re.sub(r"\bblack\b", line_color, s, flags=re.IGNORECASE)
                # Replace #000000 and #000 precisely (not followed by another hex digit)
                s = re.sub(
                    r"#000000(?![0-9a-fA-F])", line_color, s, flags=re.IGNORECASE
                )
                s = re.sub(r"#000(?![0-9a-fA-F])", line_color, s, flags=re.IGNORECASE)
                return s

            for elem in root.iter():
                # 1. Handle <style> tags
                if elem.tag.split("}")[-1] == "style":
                    if elem.text:
                        elem.text = replace_black(elem.text)

                # 2. Handle inline attributes
                for attr in ["stroke", "fill", "style"]:
                    if attr in elem.attrib:
                        elem.attrib[attr] = replace_black(elem.attrib[attr])

                # 3. Remove <text> elements
                to_remove = []
                for child in elem:
                    if child.tag.split("}")[-1] == "text":
                        to_remove.append(child)
                for child in to_remove:
                    elem.remove(child)

            content = ET.tostring(root, encoding="unicode")

            self.prepareGeometryChange()
            success = self._renderer.load(QByteArray(content.encode("utf-8")))
            if not success:
                # Fallback
                self._renderer.load(QByteArray(self.svg_template.encode("utf-8")))
        except Exception as e:
            print(f"DEBUG: SVG Update Error: {e}")
            self._renderer.load(QByteArray(self.svg_template.encode("utf-8")))

        self._update_labels()
        self.update()

    def rotate_item(self):
        self.setRotation(self.rotation() + 90)

    def _parse_parameters(self, overwrite=True):
        try:
            tree = ET.parse(self.svg_path)
            root = tree.getroot()

            for elem in root.iter():
                # Params
                if "param" in elem.tag:
                    name = elem.get("name")
                    value = elem.get("value")
                    if name:
                        # Normalize parameter keys to upper-case to have a
                        # consistent internal representation.
                        name_up = name.upper()
                        if overwrite or name_up not in self.parameters:
                            self.parameters[name_up] = value or ""

                elif "symbol" in elem.tag:
                    prefix = elem.get("prefix")
                    if prefix:
                        self.prefix = prefix

                elif "spice" in elem.tag or "xyce" in elem.tag:
                    template = elem.get("template")
                    if template:
                        self.spice_template = template

        except Exception as e:
            print(f"Error parsing SVG parameters for {self.svg_path}: {e}")

    def set_connected_pins(self, pin_ids):
        self.connected_pins = pin_ids
        for pid, info in self.pins.items():
            if "item" in info:
                info["item"].setVisible(pid not in pin_ids)
        self.update()

    def _parse_labels(self):
        try:
            tree = ET.parse(self.svg_path)
            root = tree.getroot()

            for elem in root.iter():
                # Check for <text> tags
                if elem.tag.endswith("text"):
                    template = elem.text or ""
                    if not template:
                        continue

                    x = float(elem.get("x", 0))
                    y = float(elem.get("y", 0))
                    cls = elem.get("class", "")

                    # Create independent text item
                    item = QGraphicsSimpleTextItem(self)
                    item.setPos(x, y)

                    # Style parsing
                    font_size = 8
                    fill_color = None

                    # 1. Check direct attributes
                    if elem.get("font-size"):
                        try:
                            font_size = int(float(elem.get("font-size")))
                        except:
                            pass
                    if elem.get("fill"):
                        fill_color = QColor(elem.get("fill"))

                    # 2. Check style attribute (e.g., style="font-size: 12px; fill: red;")
                    style = elem.get("style", "")
                    if style:
                        import re

                        fs_match = re.search(r"font-size:\s*(\d+)px", style)
                        if fs_match:
                            try:
                                font_size = int(fs_match.group(1))
                            except:
                                pass
                        fill_match = re.search(r"fill:\s*([^;]+)", style)
                        if fill_match:
                            try:
                                fill_color = QColor(fill_match.group(1).strip())
                            except:
                                pass

                    # Apply font
                    item.setFont(QFont("Arial", font_size))

                    # 3. Store metadata for alignment in _update_labels
                    anchor = elem.get("text-anchor", "start")
                    item.setData(1, x)  # orig_x
                    item.setData(2, y)  # orig_y
                    item.setData(3, anchor)

                    # Apply color: prefer explicit SVG fill, then theme-by-class
                    if fill_color and fill_color.isValid():
                        item.setBrush(QBrush(fill_color))
                    else:
                        if cls == "label":
                            item.setBrush(QBrush(theme_manager.get_color("font_label")))
                        elif cls == "value" or cls == "voltage":
                            item.setBrush(
                                QBrush(theme_manager.get_color("font_voltage"))
                            )
                        else:
                            item.setBrush(
                                QBrush(theme_manager.get_color("font_default"))
                            )

                    item.setData(0, cls)  # Store class for theme updates
                    self.label_items[template] = item

        except Exception as e:
            print(f"Error parsing SVG labels for {self.svg_path}: {e}")

    def _parse_pins(self):
        try:
            # Parse from the TEMPLATE which has params already substituted
            root = ET.fromstring(self.svg_template)

            # Namespace map for finding elements
            ns = {
                "svg": "http://www.w3.org/2000/svg",
                "opens": "http://opens-schematic.org",
            }

            # Cleanup existing visual pins if any
            for pin_info in self.pins.values():
                if "item" in pin_info and pin_info["item"] in self.childItems():
                    pin_info["item"].setParentItem(None)
                    if self.scene():
                        self.scene().removeItem(pin_info["item"])
            self.pins.clear()

            # Find all circles with class='pin'
            for elem in root.iter():
                # Check for class="pin"
                if elem.get("class") == "pin":
                    pin_id = elem.get("id")
                    cx = float(elem.get("cx", 0))
                    cy = float(elem.get("cy", 0))
                    net_override = elem.get("net")

                    # Create visual pin (Red Rectangle)
                    pin_size = 6
                    rect = QGraphicsRectItem(
                        cx - pin_size / 2, cy - pin_size / 2, pin_size, pin_size, self
                    )
                    rect.setBrush(QBrush(QColor("red")))
                    rect.setPen(QPen(Qt.PenStyle.NoPen))
                    rect.setData(Qt.ItemDataRole.UserRole, pin_id)  # Identify the pin

                    self.pins[pin_id] = {"pos": QPointF(cx, cy), "item": rect}
                    if net_override is not None:
                        self.pins[pin_id]["net_override"] = net_override

            # Legacy/Namespace check for opens:pin overrides
            for elem in root.iter():
                if elem.tag.split("}")[-1] == "pin":
                    pin_id = elem.get("id")
                    net_override = elem.get("net")
                    if pin_id in self.pins and net_override is not None:
                        self.pins[pin_id]["net_override"] = net_override

        except Exception as e:
            print(f"Error parsing SVG pins for {self.svg_path}: {e}")

    def _parse_buttons(self):
        try:
            tree = ET.parse(self.svg_path)
            root = tree.getroot()
            for elem in root.iter():
                action = elem.get("{http://opens-schematic.org}action")
                if action:
                    x = float(elem.get("x", 0))
                    y = float(elem.get("y", 0))
                    w = float(elem.get("width", 0))
                    h = float(elem.get("height", 0))
                    self.buttons[action] = QRectF(x, y, w, h)
        except Exception as e:
            print(f"Error parsing SVG buttons for {self.svg_path}: {e}")

    def mousePressEvent(self, event):
        pos = event.pos()
        for action, rect in self.buttons.items():
            if rect.contains(pos):
                self._handle_button_click(action)
                event.accept()
                return
        super().mousePressEvent(event)

    def _handle_button_click(self, action):
        if action == "run":
            from opens_suite.design_script_dialog import DesignScriptDialog

            DesignScriptDialog.execute_and_apply(self)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Snap to grid
            grid_size = 10
            new_pos = value
            x = round(new_pos.x() / grid_size) * grid_size
            y = round(new_pos.y() / grid_size) * grid_size
            return QPointF(x, y)

        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        """Open a dedicated model editor when this is a model symbol.

        Detect model symbols by filename or presence of ARGS parameter.
        """
        try:
            # Special case for Python Model: Resolve PYTHONPATH/MODULE and open script
            if self.svg_path and "python_model" in self.svg_path.lower():
                import os

                ppath = self.parameters.get("PYTHONPATH", ".")
                module = self.parameters.get("MODULE", "controller")
                cls_name = self.parameters.get("CLASS", "Controller")

                # Resolve $SVG to the directory of the current schematic
                sch_dir = ""
                try:
                    view = self.scene().views()[0]
                    if hasattr(view, "filename") and view.filename:
                        sch_dir = os.path.dirname(view.filename)
                except Exception:
                    pass

                ppath = ppath.replace("$SVG", sch_dir)
                ppath = os.path.expandvars(ppath)
                abs_ppath = os.path.abspath(ppath)
                script_path = os.path.join(abs_ppath, f"{module}.py")

                if not os.path.exists(script_path):
                    # Ensure directory exists
                    os.makedirs(abs_ppath, exist_ok=True)
                    # Create template
                    template = f"""#
# Python Model (16 Pins available)
#

class {cls_name}:
    def __init__(self):
        \"\"\"Setup input/outputs\"\"\"
        self.VDD = Input(0)  # 3.3 volt
        self.VSS = Input(15)

        self.VOUT = ResistorOutput(10, 10.0, self.VDD, self.VSS)
        self.VOUT.set_pwm(0.5, 1 / 100e3)

    def update(self, time):
        # Update each time point
        pass
"""
                    with open(script_path, "w") as f:
                        f.write(template)

                # Open with configured editor
                from PyQt6.QtCore import QSettings

                settings = QSettings("OpenS", "OpenS")
                editor_cmd = settings.value("editor_command", "code '%s'")

                try:
                    import shlex
                    import subprocess

                    if "%s" in editor_cmd:
                        cmd_str = editor_cmd.replace("%s", script_path)
                    else:
                        cmd_str = f"{editor_cmd} '{script_path}'"
                    args = shlex.split(cmd_str)
                    subprocess.Popen(args)
                except Exception as e:
                    from PyQt6.QtWidgets import QMessageBox

                    QMessageBox.critical(None, "Error", f"Failed to open script: {e}")
                return

            is_model = False
            if self.svg_path and self.svg_path.lower().endswith("model.svg"):
                is_model = True
            if not is_model and "ARGS" in self.parameters:
                is_model = True

            if is_model:
                # Lazy import to avoid cycles / startup cost
                from opens_suite.model_editor import ModelEditorDialog

                # Build case-insensitive initial parameter map
                param_map = {k.lower(): v for k, v in self.parameters.items()}
                initial = {
                    "MODELNAME": param_map.get("modelname", ""),
                    "TYPE": param_map.get("type", "NMOS"),
                    "ARGS": param_map.get("args", ""),
                }
                dlg = ModelEditorDialog(None, initial=initial)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    res = dlg.get_result()
                    # Apply results to parameters
                    # Use set_parameter to update labels/UI
                    self.set_parameter("MODELNAME", res.get("MODELNAME", ""))
                    self.set_parameter("TYPE", res.get("TYPE", ""))
                    self.set_parameter("ARGS", res.get("ARGS", ""))

            is_script = False
            is_stimuli = False

            if self.svg_path:
                lower_path = self.svg_path.lower()
                if (
                    "design_script.svg" in lower_path
                    or "design_script/symbol.svg" in lower_path
                ):
                    is_script = True
                elif (
                    "stimuli_generator.svg" in lower_path
                    or "stimuli_generator/symbol.svg" in lower_path
                ):
                    is_stimuli = True

            if not is_script and not is_stimuli and "SCRIPT" in self.parameters:
                is_script = True  # fallback if they use an arbitrary script symbol

            if is_script or is_stimuli:
                from opens_suite.design_script_dialog import DesignScriptDialog

                DesignScriptDialog.open_notebook(self)

            # drill down into subcircuits
            model_param = self.parameters.get("MODEL")
            if model_param and (
                model_param.endswith(".sch") or model_param.endswith(".sch.svg")
            ):
                import os

                dir_name = os.path.dirname(self.svg_path)
                base_sch = model_param.replace(".sch", "")
                sch_paths_to_try = [
                    os.path.join(dir_name, f"{base_sch}.svg"),
                    os.path.join(dir_name, f"{base_sch}.sch.svg"),
                    os.path.join(dir_name, "schematic.svg"),
                    os.path.join(dir_name, "schematic.sch.svg"),
                ]
                if self.svg_path.endswith(".sym.svg"):
                    sch_paths_to_try.append(
                        self.svg_path.replace(".sym.svg", ".sch.svg")
                    )
                    sch_paths_to_try.append(self.svg_path.replace(".sym.svg", ".svg"))

                for sch_path in sch_paths_to_try:
                    if os.path.exists(sch_path):
                        self.openSubcircuitRequested.emit(sch_path)
                        return

        except Exception as e:
            print(f"Item editor failed: {e}")
