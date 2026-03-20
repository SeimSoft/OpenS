from PyQt6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
)
from PyQt6.QtCore import (
    Qt,
    QPointF,
    QRectF,
    QLineF,
    QProcess,
    QMimeData,
    pyqtSignal,
    QThread,
    QSettings,
)
import math
from PyQt6.QtGui import (
    QPainter,
    QPen,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QCursor,
    QUndoStack,
    QPainterPath,
    QTransform,
)

from opens_suite.schematic_item import SchematicItem
from opens_suite.wire import Wire, Junction
from opens_suite.commands import (
    InsertItemsCommand,
    RemoveItemsCommand,
    MoveItemsCommand,
    CreateWireCommand,
    TransformItemsCommand,
)
import xml.etree.ElementTree as ET
import os
from opens_suite.netlister import NetlistGenerator
from opens_suite.spice_parser import SpiceRawParser


class IOMixin:
    def _get_relative_lib_path(self, abs_path):
        if not abs_path:
            return ""

        from PyQt6.QtCore import QSettings

        settings = QSettings("OpenS", "OpenS")
        paths_str = settings.value("library_search_paths", "")
        search_paths = []
        default_lib = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "assets",
            "libraries",
        )
        if os.path.exists(default_lib):
            search_paths.append(default_lib)

        for p in paths_str.split(","):
            p = p.strip()
            if p and os.path.exists(p) and p not in search_paths:
                search_paths.append(p)

        # Also include project dir if it exists
        if hasattr(self, "filename") and self.filename:
            search_paths.append(os.path.dirname(os.path.abspath(self.filename)))

        for sp in search_paths:
            try:
                rel = os.path.relpath(abs_path, sp)
                if not rel.startswith("..") and not os.path.isabs(rel):
                    # For windows compat, replace backslashes
                    return rel.replace("\\", "/")
            except ValueError:
                pass

        # Fallback: just return the last 3 parts (lib/cell/view)
        parts = abs_path.replace("\\", "/").split("/")
        if len(parts) >= 3:
            return "/".join(parts[-3:])
        return abs_path

    def save_schematic(self, filename, analyses=None, outputs=None, variables=None):
        from opens_suite.design_points import DesignPoints
        import os
        import numpy as np

        json_files = []
        free_text_items = []
        schematic_dir = ""
        if filename:
            schematic_dir = os.path.dirname(os.path.abspath(filename))

        # Logger helper
        main_win = self.window()
        def log_msg(msg):
            if hasattr(main_win, "simulation_text"):
                main_win.simulation_text.append(msg)
            print(msg)

        # 1. Extract JSON design scripts and evaluatable texts
        for item in self.scene().items():
            if not isinstance(item, SchematicItem):
                continue

            script_name = item.parameters.get("SCRIPT", "")
            if script_name.endswith(".ipynb") and schematic_dir:
                json_name = script_name.replace(".ipynb", ".json")
                json_path = os.path.join(schematic_dir, json_name)
                if os.path.exists(json_path) and json_path not in json_files:
                    json_files.append(json_path)

            svg_path = getattr(item, "svg_path", "")
            if svg_path and "free_text" in svg_path.lower():
                evaluate_val = str(item.parameters.get("EVALUATE", "False")).strip().lower()
                if evaluate_val == "true":
                    free_text_items.append(item)

        # 2. Merge existing mapped design points
        dps = DesignPoints(json_files)
        
        # Inject GUI variables into dps so that evaluated scripts can access them
        gui_variables = []
        if hasattr(main_win, "variables_dock"):
            gui_variables = main_win.variables_dock.get_variables()
        elif hasattr(self, "variables"):
            gui_variables = getattr(self, "variables", [])
            
        for var in gui_variables:
            name = var.get("name", "").strip()
            val = var.get("value", "").strip()
            unit = var.get("unit", "").strip()
            if name and val:
                key = f"{name} [{unit}]" if unit else name
                try:
                    dps[key] = val
                except Exception as e:
                    log_msg(f"Could not parse variable '{name}'='{val}': {e}")

        # 3. Dynamic payload execution
        errors_encountered = False
        if free_text_items:
            local_context = {"dps": dps, "DesignPoints": DesignPoints, "np": np}
            for fti in free_text_items:
                code = fti.parameters.get("TEXT", "")
                if code and not code.startswith("* Enter code here"):
                    try:
                        exec(code, globals(), local_context)
                    except Exception as e:
                        errors_encountered = True
                        log_msg(f"Error evaluating free text '{getattr(fti, 'name', '')}': {e}")
                        import traceback
                        for line in traceback.format_exc().split("\n")[-4:]:
                            if line.strip(): log_msg(line)

        # 4. Map resulting points to active UI SchematicItem targets
        updated_params = []
        if dps._length > 0:
            first_row = dps.to_dict(0)
            items_by_name = {
                item.name: item
                for item in self.scene().items()
                if isinstance(item, SchematicItem) and getattr(item, "name", "")
            }
            
            changed_params = []
            unchanged_count = 0
            for key, val in first_row.items():
                parsed_name, _ = dps._parse_key(key)
                if "." in parsed_name:
                    comp_name, param_name = parsed_name.split(".", 1)
                    if comp_name in items_by_name:
                        comp = items_by_name[comp_name]
                        if param_name in comp.parameters:
                            old_val = comp.parameters[param_name]
                            val_fmt = DesignPoints._format_si(val)
                            if str(old_val) != str(val) and str(old_val) != val_fmt:
                                comp.set_parameter(param_name, val)
                                changed_params.append(f"{parsed_name} = {val_fmt} (was {old_val})")
                            else:
                                unchanged_count += 1
                                
            updated_params = changed_params  # for the dock-show check below
            if changed_params:
                log_msg(f"DesignPoints: Updated {len(changed_params)} parameter(s) ({unchanged_count} unchanged):")
                for u in changed_params:
                    log_msg("  + " + u)
            elif unchanged_count > 0:
                log_msg(f"DesignPoints: {unchanged_count} parameter(s) all unchanged.")
                    
        # Force log dock open if updates occurred OR if execution errors were encountered
        if (updated_params or errors_encountered) and hasattr(main_win, "simulation_dock"):
            if not main_win.simulation_dock.isVisible():
                main_win.simulation_dock.show()
                    
        if hasattr(main_win, "variables_dock"):
            main_win.variables_dock.set_design_points(dps)

        # Ensure connectivity is up to date before saving
        if hasattr(self, "recalculate_connectivity"):
            self.recalculate_connectivity()

        # Register namespace for extra data
        ET.register_namespace("opens", "http://opens-schematic.org")

        # Calculate ViewBox with margin
        rect = self.scene().itemsBoundingRect()
        margin = 100
        rect.adjust(-margin, -margin, margin, margin)
        vb = f"{rect.x()} {rect.y()} {rect.width()} {rect.height()}"

        root = ET.Element(
            "svg",
            dict(
                width=str(rect.width()),
                height=str(rect.height()),
                viewBox=vb,
                xmlns="http://www.w3.org/2000/svg",
            ),
        )

        # Save Drawing (Wires and Items)
        # Only export top-level items to avoid duplicating child items (like pin markers)
        items = [item for item in self.scene().items() if item.parentItem() is None]

        for item in reversed(items):
            # Do not serialize UI items like zoom box or wire preview
            if getattr(self, "zoom_rect_item", None) is item:
                continue
            if getattr(self, "wire_preview_path", None) is item:
                continue

            # Programmatic pcells (items that expose pin_items) need to be
            # serialized so they survive saving/loading. Handle them before
            # the regular SchematicItem branch.
            if hasattr(item, "pin_items") and isinstance(
                getattr(item, "pin_items"), dict
            ):
                # Decompose transform matrix to extract scale and rotation reliably
                # QTransform: m11=sx*cos(a), m12=sx*sin(a), m21=-sy*sin(a), m22=sy*cos(a)
                import math

                t = item.transform()
                sx_mat = math.sqrt(t.m11() ** 2 + t.m12() ** 2)
                sy_mat = math.sqrt(t.m21() ** 2 + t.m22() ** 2)
                if sx_mat < 1e-6:
                    sx_mat = 1.0
                if sy_mat < 1e-6:
                    sy_mat = 1.0

                total_rot = item.rotation()
                if sx_mat > 1e-6:
                    total_rot += math.degrees(math.atan2(t.m12(), t.m11()))

                sp = item.scenePos()
                transforms = f"translate({sp.x()},{sp.y()}) rotate({total_rot})"
                if sx_mat != 1.0 or sy_mat != 1.0:
                    transforms += f" scale({sx_mat},{sy_mat})"

                attribs = {"transform": transforms, "name": getattr(item, "name", "")}
                # Write parameters as param_<key>
                for k, v in getattr(item, "parameters", {}).items():
                    attribs[f"param_{k}"] = str(v)
                # Prefer storing the registry key for the pcell so loading is
                # robust across class renames. Find the registry key if present.
                try:
                    from opens import pcell as _pcell

                    registry_key = None
                    for k, cls in _pcell.PCELL_REGISTRY.items():
                        try:
                            if isinstance(item, cls):
                                registry_key = k
                                break
                        except Exception:
                            continue
                    if registry_key:
                        attribs["{http://opens-schematic.org}pcell_class"] = (
                            registry_key
                        )
                    else:
                        # Fallback to class name (legacy)
                        attribs["{http://opens-schematic.org}pcell_class"] = (
                            item.__class__.__name__
                        )
                except Exception:
                    attribs["{http://opens-schematic.org}pcell_class"] = (
                        item.__class__.__name__
                    )

                ET.SubElement(root, "g", attribs)
            elif isinstance(item, SchematicItem):
                sym_name = (
                    os.path.basename(item.svg_path)
                    .replace(".svg", "")
                    .replace(".sym", "")
                )

                # Decompose transform matrix to extract scale and rotation reliably
                # QTransform: m11=sx*cos(a), m12=sx*sin(a), m21=-sy*sin(a), m22=sy*cos(a)
                import math

                t = item.transform()
                sx = math.sqrt(t.m11() ** 2 + t.m12() ** 2)
                sy = math.sqrt(t.m21() ** 2 + t.m22() ** 2)

                # If scale is effectively zero, it's likely a bug or singular matrix
                if sx < 1e-6:
                    sx = 1.0
                if sy < 1e-6:
                    sy = 1.0

                # Combine property rotation with matrix rotation
                total_rot = item.rotation()
                if sx > 1e-6:
                    total_rot += math.degrees(math.atan2(t.m12(), t.m11()))

                sp = item.scenePos()
                transforms = f"translate({sp.x()},{sp.y()}) rotate({total_rot})"
                if abs(sx - 1.0) > 1e-6 or abs(sy - 1.0) > 1e-6:
                    transforms += f" scale({sx},{sy})"

                attribs = {
                    "transform": transforms,
                    "symbol_name": sym_name,
                    "name": item.name,
                    "save_v": str(getattr(item, "save_voltage", True)),
                    "save_i": str(getattr(item, "save_current", False)),
                }

                # Parameters
                for k, v in item.parameters.items():
                    attribs[f"param_{k}"] = str(v)

                attribs["library_path"] = (
                    self._get_relative_lib_path(item.svg_path) if item.svg_path else ""
                )

                g = ET.SubElement(root, "g", attribs)
                
                # Embed symbol directly for external SVG viewers
                try:
                    symbol_root = ET.fromstring(item.svg_template)
                    
                    full_name = getattr(item, "name", "") or ""
                    idx = full_name
                    prefix = getattr(item, "prefix", "")
                    if idx and prefix and idx.startswith(prefix):
                        idx = idx[len(prefix):]
                        
                    for elem in symbol_root.iter():
                        # Remove namespace to prevent <ns0: prefix issues
                        if '}' in elem.tag:
                            elem.tag = elem.tag.split('}', 1)[1]
                            
                        # Replace text placeholders
                        if elem.tag == "text" and elem.text:
                            text = elem.text
                            text = text.replace("{name}", full_name)
                            text = text.replace("{index}", idx)
                            text = text.replace("{fullName}", full_name)
                            text = text.replace("{Name}", full_name)
                            
                            if hasattr(item, "parameters"):
                                import re
                                for k, v in item.parameters.items():
                                    try:
                                        pattern = re.compile(r"\{" + re.escape(k) + r"\}", flags=re.IGNORECASE)
                                        text = pattern.sub(str(v), text)
                                    except re.error:
                                        text = text.replace(f"{{{k}}}", str(v))
                                if item.parameters:
                                    try:
                                        val_pattern = re.compile(r"\{value\}", flags=re.IGNORECASE)
                                        text = val_pattern.sub(str(list(item.parameters.values())[0]), text)
                                    except re.error:
                                        if "{value}" in text:
                                            text = text.replace("{value}", str(list(item.parameters.values())[0]))
                            elem.text = text
                            
                    g.append(symbol_root)
                except Exception as e:
                    print(f"Failed to embed symbol preview for {getattr(item, 'name', 'unknown')}: {e}")
                    # Fallback visuals for external viewers
                    ET.SubElement(
                        g,
                        "rect",
                        {
                            "width": "40",
                            "height": "40",
                            "rx": "5",
                            "fill": "none",
                            "stroke": "blue",
                            "stroke-width": "0.5",
                            "style": "stroke-dasharray: 2,2;",
                        },
                    )
                    label = ET.SubElement(
                        g,
                        "text",
                        {
                            "y": "35",
                            "fill": "blue",
                            "style": "font-size: 6px; font-family: sans-serif;",
                        },
                    )
                    label.text = f"{getattr(item, 'name', '') or sym_name}"

            elif isinstance(item, Wire):
                line = item.line()
                p1 = item.mapToScene(line.p1())
                p2 = item.mapToScene(line.p2())
                attribs = {
                    "x1": str(p1.x()),
                    "y1": str(p1.y()),
                    "x2": str(p2.x()),
                    "y2": str(p2.y()),
                    "stroke": "black",
                    "stroke-width": "2",
                    "stroke-linecap": "round",
                }
                if item.name:
                    attribs["net_name"] = item.name
                ET.SubElement(root, "line", attribs)

            elif isinstance(item, Junction):
                center = item.mapToScene(item.rect().center())
                attribs = {
                    "cx": str(center.x()),
                    "cy": str(center.y()),
                    "r": "3",
                    "fill": "black",
                }
                ET.SubElement(root, "circle", attribs)

            elif isinstance(item, QGraphicsRectItem):
                rect = item.rect()
                sp = item.scenePos()
                attribs = {
                    "x": str(rect.x() + sp.x()),
                    "y": str(rect.y() + sp.y()),
                    "width": str(rect.width()),
                    "height": str(rect.height()),
                    "rx": "5",
                    "fill": "none",
                    "stroke": "black",
                    "stroke-width": "2",
                }
                ET.SubElement(root, "rect", attribs)

            elif isinstance(item, QGraphicsTextItem):
                sp = item.scenePos()
                attribs = {"x": str(sp.x()), "y": str(sp.y()), "fill": "black"}
                elem = ET.SubElement(root, "text", attribs)
                elem.text = item.toPlainText()

            elif isinstance(item, QGraphicsLineItem):
                line = item.line()
                p1 = item.mapToScene(line.p1())
                p2 = item.mapToScene(line.p2())
                attribs = {
                    "x1": str(p1.x()),
                    "y1": str(p1.y()),
                    "x2": str(p2.x()),
                    "y2": str(p2.y()),
                    "stroke": "black",
                    "stroke-width": "2",
                    "stroke-linecap": "round",
                    "class": "annotation",
                }
                ET.SubElement(root, "line", attribs)

        # Save Analysis if provided
        if analyses is not None:
            save_analyses = analyses
        else:
            save_analyses = self.analyses

        if save_analyses:
            for config in save_analyses:
                # Convert all values to strings for ET.SubElement (prevents TypeError with bools)
                str_config = {k: str(v) for k, v in config.items()}
                ET.SubElement(root, "{http://opens-schematic.org}analysis", str_config)

        # Save Outputs if provided
        if outputs is not None:
            save_outputs = outputs
        else:
            save_outputs = self.outputs

        if save_outputs:
            for out in save_outputs:
                elem = ET.SubElement(root, "{http://opens-schematic.org}output")
                if isinstance(out, dict):
                    elem.text = out.get("expression", "")
                    min_val = out.get("min")
                    max_val = out.get("max")
                    name_val = out.get("name")
                    unit_val = out.get("unit")
                    if min_val is not None and str(min_val).strip() != "":
                        elem.set("min", str(min_val))
                    if max_val is not None and str(max_val).strip() != "":
                        elem.set("max", str(max_val))
                    if name_val is not None and str(name_val).strip() != "":
                        elem.set("name", str(name_val))
                    if unit_val is not None and str(unit_val).strip() != "":
                        elem.set("unit", str(unit_val))
                    desc_val = out.get("description")
                    if desc_val is not None and str(desc_val).strip() != "":
                        elem.set("description", str(desc_val))
                else:
                    elem.text = str(out)

        # Save Variables if provided
        if variables is not None:
            save_variables = variables
        else:
            save_variables = getattr(self, "variables", [])

        if save_variables:
            for var in save_variables:
                str_var = {k: str(v) for k, v in var.items()}
                ET.SubElement(root, "{http://opens-schematic.org}variable", str_var)

        if hasattr(ET, "indent"):
            ET.indent(root, space="  ", level=0)
        tree = ET.ElementTree(root)
        tree.write(filename, encoding="utf-8", xml_declaration=True)
        self.statusMessage.emit(f"Saved to {filename}")
        
        # Reset modified flag if it's a SchematicView
        if hasattr(self, "set_modified"):
            self.set_modified(False)

    def load_schematic(self, filename):
        self.scene().clear()
        self.wire_preview_path = QGraphicsPathItem()
        self.wire_preview_path.setPen(QPen(QColor("blue"), 2, Qt.PenStyle.DashLine))
        self.scene().addItem(self.wire_preview_path)
        self.wire_preview_path.setVisible(False)

        try:
            if os.path.isdir(filename):
                raise IsADirectoryError(f"'{filename}' is a directory.")
            tree = ET.parse(filename)
            root = tree.getroot()

            for elem in root:
                if elem.tag.endswith("g"):
                    # Item
                    path = elem.get("library_path")

                    from PyQt6.QtCore import QSettings

                    settings = QSettings("OpenS", "OpenS")
                    paths_str = settings.value("library_search_paths", "")
                    search_paths = []
                    # Note: io.py is in src/opens_suite/view, so go up one level
                    default_lib = os.path.join(
                        os.path.dirname(os.path.dirname(__file__)),
                        "assets",
                        "libraries",
                    )
                    if os.path.exists(default_lib):
                        search_paths.append(default_lib)

                    for p in paths_str.split(","):
                        p = p.strip()
                        if p and os.path.exists(p) and p not in search_paths:
                            search_paths.append(p)

                    search_paths.append(os.getcwd())  # For local backward compatibility
                    if getattr(self, "filename", None):
                        cell_dir = os.path.dirname(os.path.abspath(self.filename))
                        search_paths.append(cell_dir)
                        # Assume structure: project_dir / lib / cell / view.svg
                        lib_dir = os.path.dirname(cell_dir)
                        proj_dir = os.path.dirname(lib_dir)
                        if proj_dir not in search_paths:
                            search_paths.append(proj_dir)

                    # If path is relative, attempt to resolve through search paths
                    if path and not os.path.isabs(path):
                        for sp in search_paths:
                            candidate = os.path.join(sp, path)
                            if os.path.exists(candidate):
                                path = candidate
                                break

                    # Fallback if path not found
                    if not path or not os.path.exists(path):
                        sym_name = elem.get("symbol_name")
                        if sym_name:
                            for sp in search_paths:
                                # Try the new standard opensLib location first
                                check = os.path.join(
                                    sp, "opensLib", sym_name, "symbol.svg"
                                )
                                if os.path.exists(check):
                                    path = check
                                    break

                                # Legacy direct SVG file format
                                check_legacy = os.path.join(sp, sym_name + ".svg")
                                if os.path.exists(check_legacy):
                                    path = check_legacy
                                    break

                    # Parse transform (translate/rotate) for all <g> elements so
                    # both SVG-based symbols and programmatic pcells can reuse it.
                    trans = elem.get("transform", "")
                    # Parse translate(x,y) rotate(r)
                    tx = 0
                    ty = 0
                    rot = 0
                    sx = 1.0
                    sy = 1.0

                    if "translate" in trans:
                        try:
                            parts = trans.split("translate(")[1].split(")")[0]
                            if "," in parts:
                                parts = parts.split(",")
                            else:
                                parts = parts.split()
                            if len(parts) >= 2:
                                tx = float(parts[0])
                                ty = float(parts[1])
                        except Exception:
                            pass

                    if "rotate" in trans:
                        try:
                            r = float(trans.split("rotate(")[1].split(")")[0])
                            rot = r
                        except Exception:
                            pass

                    if "scale" in trans:
                        try:
                            s = trans.split("scale(")[1].split(")")[0]
                            if "," in s:
                                parts = s.split(",")
                            else:
                                parts = s.split()
                            if len(parts) == 1:
                                sx = float(parts[0])
                                sy = sx
                            elif len(parts) >= 2:
                                sx = float(parts[0])
                                sy = float(parts[1])

                            # Sanity check: Scale of 0 makes items invisible and is usually a bug
                            if abs(sx) < 1e-6:
                                sx = 1.0
                            if abs(sy) < 1e-6:
                                sy = 1.0
                        except Exception:
                            pass

                    if path and os.path.exists(path):
                        item = SchematicItem(path)
                        item.setPos(tx, ty)
                        # Apply scale+rotation if scale was stored, otherwise use rotation
                        if sx != 1.0 or sy != 1.0:
                            from PyQt6.QtGui import QTransform

                            t = QTransform()
                            if rot:
                                t.rotate(rot)
                            t.scale(sx, sy)
                            item.setTransform(t)
                        else:
                            item.setRotation(rot)

                        if "name" in elem.attrib:
                            item.name = elem.attrib["name"]

                        # Load simulation selection
                        # Default is True for voltage, False for current
                        save_v = elem.get("save_v", "True").lower() == "true"
                        save_i = elem.get("save_i", "False").lower() == "true"
                        item.save_voltage = save_v
                        item.save_current = save_i

                        item._update_svg()  # Visual fix

                        # Params
                        for k, v in elem.attrib.items():
                            if k.startswith("param_"):
                                pname = k.replace("param_", "")
                                item.set_parameter(pname, v)

                        self._connect_item(item)
                        self.scene().addItem(item)
                    else:
                        # Maybe this is a saved programmatic pcell (opens:pcell_class)
                        pcell_key = elem.get("{http://opens-schematic.org}pcell_class")
                        if pcell_key:
                            try:
                                from opens import pcell as _pcell

                                # If the stored value is a registry key, use it. Fall
                                # back to class-name matching for legacy files.
                                cls = None
                                if pcell_key in _pcell.PCELL_REGISTRY:
                                    cls = _pcell.PCELL_REGISTRY[pcell_key]
                                else:
                                    # Legacy: class name stored, find matching class
                                    for k, c in _pcell.PCELL_REGISTRY.items():
                                        if c.__name__ == pcell_key:
                                            cls = c
                                            break

                                if cls:
                                    # Collect parameters from param_* attributes
                                    params = {}
                                    for ak, av in elem.attrib.items():
                                        if ak.startswith("param_"):
                                            pname = ak.replace("param_", "")
                                            params[pname] = av

                                    item = cls(parameters=params)
                                    item.setPos(tx, ty)
                                    if sx != 1.0 or sy != 1.0:
                                        from PyQt6.QtGui import QTransform

                                        t = QTransform()
                                        if rot:
                                            t.rotate(rot)
                                        t.scale(sx, sy)
                                        item.setTransform(t)
                                    else:
                                        item.setRotation(rot)
                                    if "name" in elem.attrib:
                                        item.name = elem.attrib["name"]
                                    self.scene().addItem(item)
                            except Exception:
                                pass

                elif elem.tag.endswith("line"):
                    # Wire or Annotation
                    cls = elem.get("class")
                    x1 = float(elem.get("x1", 0))
                    y1 = float(elem.get("y1", 0))
                    x2 = float(elem.get("x2", 0))
                    y2 = float(elem.get("y2", 0))

                    if cls == "annotation":
                        line_item = QGraphicsLineItem(QLineF(x1, y1, x2, y2))
                        line_item.setFlags(
                            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                        )
                        pen = QPen(Qt.GlobalColor.black)
                        pen.setWidth(2)
                        line_item.setPen(pen)
                        self.scene().addItem(line_item)
                    else:
                        p1 = QPointF(x1, y1)
                        p2 = QPointF(x2, y2)
                        wire = Wire(p1, p2)
                        net_name = elem.get("net_name")
                        if net_name:
                            wire.name = net_name
                        self.scene().addItem(wire)

                elif elem.tag.endswith("circle"):
                    # Junction or Pin?
                    cx = float(elem.get("cx", 0))
                    cy = float(elem.get("cy", 0))
                    r = float(elem.get("r", 2))
                    cls = elem.get("class")

                    if cls == "pin":
                        # Draw as pin circle?
                        # In editor, might just be a visual marker.
                        j = Junction(QPointF(cx, cy))
                        self.scene().addItem(j)
                    else:
                        j = Junction(QPointF(cx, cy))
                        self.scene().addItem(j)

                elif elem.tag.endswith("rect"):
                    x = float(elem.get("x", 0))
                    y = float(elem.get("y", 0))
                    w = float(elem.get("width", 0))
                    h = float(elem.get("height", 0))
                    rx = float(elem.get("rx", 0))
                    rect_item = QGraphicsRectItem(x, y, w, h)
                    rect_item.setFlags(
                        QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                        | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    )
                    pen = QPen(Qt.GlobalColor.black)
                    pen.setWidth(2)
                    rect_item.setPen(pen)
                    self.scene().addItem(rect_item)

                elif elem.tag.endswith("text"):
                    x = float(elem.get("x", 0))
                    y = float(elem.get("y", 0))
                    content = elem.text or ""
                    text_item = QGraphicsTextItem(content)
                    text_item.setFlags(
                        QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                        | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    )
                    text_item.setPos(x, y)
                    self.scene().addItem(text_item)

            self.recalculate_connectivity()

            # Fit in View
            self.fitInView(
                self.scene().itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
            self.scale(0.9, 0.9)

            # Reset modified flag after loading
            if hasattr(self, "set_modified"):
                self.set_modified(False)

        except Exception as e:
            self.statusMessage.emit(f"Error loading: {e}")
            print(f"Error loading: {e}")
            import traceback

            traceback.print_exc()
