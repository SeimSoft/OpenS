import os
import xml.etree.ElementTree as ET
from xml.dom import minidom


class SymbolGenerator:
    @staticmethod
    def generate_symbol(schematic_path, symbol_path):
        """
        Generates a fresh .sym.svg file for the given schematic .svg.
        All input pins go to the left, output pins to the right.
        Bidirectional pins go to the left as well or wherever they fit.
        """
        if not schematic_path.endswith(".svg"):
            print("Error: Input must be a .svg file")
            return None

        if schematic_path.endswith(".sch.svg"):
            schematic_name = os.path.basename(schematic_path[:-8])
        else:
            schematic_name = os.path.basename(schematic_path[:-4])

        # If the file is just called 'schematic', use the parent directory name
        if schematic_name == "schematic":
            parent_dir = os.path.basename(
                os.path.dirname(os.path.abspath(schematic_path))
            )
            if parent_dir and parent_dir not in [".", ""]:
                schematic_name = parent_dir

        dir_name = os.path.dirname(schematic_path)
        symbol_path = os.path.join(dir_name, "symbol.svg")

        pins = SymbolGenerator._extract_pins_from_schematic(schematic_path)
        print(f"Found pins in schematic: {pins}")

        in_pins = [p for p in pins if p["type"] == "in"]
        out_pins = [p for p in pins if p["type"] == "out"]
        bi_pins = [p for p in pins if p["type"] == "bi"]

        # Put bi pins on the left below in_pins
        left_pins = in_pins + bi_pins
        right_pins = out_pins

        num_left = len(left_pins)
        num_right = len(right_pins)
        max_pins = max(num_left, num_right, 1)

        # Layout metrics
        grid = 10
        pin_spacing = 20
        box_x = 20
        box_width = 80
        box_right = box_x + box_width

        box_height = max_pins * pin_spacing + 20
        total_width = 120
        total_height = box_height

        ET.register_namespace("", "http://www.w3.org/2000/svg")
        ET.register_namespace("opens", "http://opens-schematic.org")

        root = ET.Element(
            "svg",
            dict(
                xmlns="http://www.w3.org/2000/svg",
                width=str(total_width),
                height=str(total_height),
                viewBox=f"0 0 {total_width} {total_height}",
            ),
        )

        # Definitions and style
        defs = ET.SubElement(root, "defs")
        style = ET.SubElement(defs, "style")
        style.text = """
            .pin { fill: none; stroke: none; }
            .symbol { fill: none; stroke: black; stroke-width: 2; stroke-linecap: round; }
            .label { font-family: Arial; font-size: 8px; fill: blue; }
            .value { font-family: Arial; font-size: 8px; fill: black; }
            .pin-label { font-family: Arial; font-size: 8px; fill: black; }
        """

        # Parameters and metadata
        ET.SubElement(
            defs,
            "{http://opens-schematic.org}param",
            {"name": "Model", "value": f"{schematic_name}.sch"},
        )
        ET.SubElement(
            defs,
            "{http://opens-schematic.org}symbol",
            {"prefix": "X", "category": "Subcircuits"},
        )

        # We also need a template for the netlister to resolve the subcircuit call automatically
        pin_order_str = " ".join([f"{{pin_{p['name']}}}" for p in pins])
        template_str = f"X_{{name}} {pin_order_str} {{Model}}"
        ET.SubElement(
            defs, "{http://opens-schematic.org}xyce", {"template": template_str}
        )

        # Background Rect
        ET.SubElement(
            root,
            "rect",
            {
                "x": str(box_x),
                "y": "10",
                "width": str(box_width),
                "height": str(box_height - 20),
                "rx": "2",
                "class": "symbol",
                "fill": "#fcfcfc",
                "stroke": "black",
                "stroke-width": "2",
            },
        )

        # Place Left Pins
        y_cursor = 20
        for p in left_pins:
            name = p["name"]
            ET.SubElement(
                root,
                "line",
                {
                    "x1": "0",
                    "y1": str(y_cursor),
                    "x2": str(box_x),
                    "y2": str(y_cursor),
                    "class": "symbol",
                    "stroke": "black",
                    "stroke-width": "2",
                },
            )
            ET.SubElement(
                root,
                "circle",
                {
                    "id": name,
                    "cx": "0",
                    "cy": str(y_cursor),
                    "r": "2",
                    "class": "pin",
                    "fill": "red",
                    "stroke": "none",
                },
            )
            ET.SubElement(
                root,
                "text",
                {
                    "x": str(box_x + 3),
                    "y": str(y_cursor),
                    "class": "pin-label",
                    "dominant-baseline": "central",
                    "fill": "black",
                },
            ).text = name
            y_cursor += pin_spacing

        # Place Right Pins
        y_cursor = 20
        for p in right_pins:
            name = p["name"]
            ET.SubElement(
                root,
                "line",
                {
                    "x1": str(box_right),
                    "y1": str(y_cursor),
                    "x2": str(total_width),
                    "y2": str(y_cursor),
                    "class": "symbol",
                    "stroke": "black",
                    "stroke-width": "2",
                },
            )
            ET.SubElement(
                root,
                "circle",
                {
                    "id": name,
                    "cx": str(total_width),
                    "cy": str(y_cursor),
                    "r": "2",
                    "class": "pin",
                    "fill": "red",
                    "stroke": "none",
                },
            )
            ET.SubElement(
                root,
                "text",
                {
                    "x": str(box_right - 3),
                    "y": str(y_cursor),
                    "class": "pin-label",
                    "text-anchor": "end",
                    "dominant-baseline": "central",
                    "fill": "black",
                },
            ).text = name
            y_cursor += pin_spacing

        # Labels
        # Name Placeholder
        ET.SubElement(
            root,
            "text",
            {
                "x": str(box_x + box_width / 2),
                "y": "8",
                "class": "label",
                "style": "text-anchor: middle;",
                "fill": "blue",
            },
        ).text = "{name}"

        # Model Placeholder
        ET.SubElement(
            root,
            "text",
            {
                "x": str(box_x + box_width / 2),
                "y": str(box_height - 2),
                "class": "value",
                "style": "text-anchor: middle;",
                "fill": "black",
            },
        ).text = "{Model}"

        xml_bytes = ET.tostring(root, encoding="utf-8")
        xmlstr = minidom.parseString(xml_bytes).toprettyxml(indent="  ")
        xmlstr = "\n".join([line for line in xmlstr.split("\n") if line.strip()])

        with open(symbol_path, "w") as f:
            f.write(xmlstr)

        print(f"Saved symbol to {symbol_path}")
        return symbol_path

    @staticmethod
    def _extract_pins_from_schematic(path):
        """
        Parses schematic SVG looking for library items that are pins.
        Returns list of dicts: {'name': 'P1', 'type': 'in'|'out'|'bi'}
        """
        pins = []
        try:
            tree = ET.parse(path)
            root = tree.getroot()

            for elem in root.iter():
                sym = elem.get("symbol_name", "")
                lib_path = elem.get("library_path", "")

                # Handle old way or programmatic pins
                if sym.startswith("pin_"):
                    name = elem.get("name") or elem.get("param_Name", "Unknown")
                    type_ = sym.replace("pin_", "")
                    pins.append({"name": name, "type": type_})
                # Handle new library paths
                elif "pin_in" in lib_path or "/pin/" in lib_path:
                    name = elem.get("name") or elem.get("param_Name", "Unknown")
                    pins.append({"name": name, "type": "in"})
                elif "pin_out" in lib_path:
                    name = elem.get("name") or elem.get("param_Name", "Unknown")
                    pins.append({"name": name, "type": "out"})
                elif "pin_bi" in lib_path:
                    name = elem.get("name") or elem.get("param_Name", "Unknown")
                    pins.append({"name": name, "type": "bi"})

        except Exception as e:
            print(f"Error parse schematic: {e}")

        # ensure stable order
        pins.sort(key=lambda x: x["name"])
        return pins
