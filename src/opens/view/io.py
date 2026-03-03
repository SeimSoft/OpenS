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

from opens.schematic_item import SchematicItem
from opens.wire import Wire, Junction
from opens.commands import (
    InsertItemsCommand,
    RemoveItemsCommand,
    MoveItemsCommand,
    CreateWireCommand,
    TransformItemsCommand,
)
import xml.etree.ElementTree as ET
import os
from opens.netlister import NetlistGenerator
from opens.spice_parser import SpiceRawParser


class IOMixin:
    def save_schematic(self, filename, analyses=None, outputs=None, variables=None):
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

                attribs["library_path"] = item.svg_path

                g = ET.SubElement(root, "g", attribs)
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
                label.text = f"{item.name or sym_name}"

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

    def load_schematic(self, filename):
        self.scene().clear()
        self.wire_preview_path = QGraphicsPathItem()
        self.wire_preview_path.setPen(QPen(QColor("blue"), 2, Qt.PenStyle.DashLine))
        self.scene().addItem(self.wire_preview_path)
        self.wire_preview_path.setVisible(False)

        try:
            tree = ET.parse(filename)
            root = tree.getroot()

            for elem in root:
                if elem.tag.endswith("g"):
                    # Item
                    path = elem.get("library_path")
                    # Fallback if path not found?
                    if not path or not os.path.exists(path):
                        sym_name = elem.get("symbol_name")
                        if sym_name:
                            from PyQt6.QtCore import QSettings

                            settings = QSettings("OpenS", "OpenS")
                            paths_str = settings.value("library_search_paths", "")
                            search_paths = []
                            # Note: io.py is in src/opens/view, so go up one level to src/opens
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

                            search_paths.append(
                                os.getcwd()
                            )  # For local backward compatibility

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

        except Exception as e:
            self.statusMessage.emit(f"Error loading: {e}")
            print(f"Error loading: {e}")
            import traceback

            traceback.print_exc()
