from opens_suite.schematic_item import SchematicItem
from opens_suite.wire import Wire, Junction
from opens_suite.properties_widget import PropertiesWidget
from PyQt6.QtCore import QPointF, QLineF


class NetlistGenerator:
    def __init__(self, scene, analyses, variables=None, **kwargs):
        self.scene = scene
        self.analyses = analyses
        self.variables = variables or []
        self.nodes = {}  # id(item) or tuple -> node_name
        self.processed_items = set()

        self.is_subcircuit = kwargs.get("is_subcircuit", False)
        self.subckt_name = kwargs.get("subckt_name", "")
        self.subckt_pins = kwargs.get("subckt_pins", [])
        self.subcircuits_code = kwargs.get("subcircuits_code", {})

    def _generate_subcircuit(self, sch_path, subckt_name):
        import os
        from opens_suite.view.core import SchematicView
        from opens_suite.symbol_generator import SymbolGenerator

        pins = SymbolGenerator._extract_pins_from_schematic(sch_path)
        subckt_pins = [p["name"] for p in pins]

        view = SchematicView()
        view.filename = sch_path
        view.load_schematic(sch_path)

        gen = NetlistGenerator(
            view.scene(),
            [],
            variables=self.variables,
            is_subcircuit=True,
            subckt_name=subckt_name,
            subckt_pins=subckt_pins,
            subcircuits_code=self.subcircuits_code,
        )
        self.subcircuits_code[subckt_name] = gen.generate()

    def generate(self):
        output = []
        if not self.is_subcircuit:
            output.append("* OpenS Generated Netlist")

            # Xyce preprocessor: add high-resistance path to prevent floating nodes
            from PyQt6.QtCore import QSettings

            settings = QSettings("OpenS", "OpenS")
            nodcpath_r = settings.value("nodcpath_resistance", "1G")
            if nodcpath_r:
                output.append(f".preprocess addresistors nodcpath {nodcpath_r}")
        else:
            ports = " ".join(self.subckt_pins)
            output.append(f".subckt {self.subckt_name} {ports}")

        # 0. Global Parameters (Variables)
        if self.variables:
            for var in self.variables:
                name = var.get("name")
                value = var.get("value")
                if name and value:
                    output.append(f".param {name}={value}")
            output.append("")  # Blank line after params

        # 1. Connectivity Analysis
        # Groups of connected Wires, Pins, Junctions form a Node.
        # We need a Union-Find or Graph Traversal.

        # Collect all connectables
        connectables = []
        for item in self.scene.items():
            if isinstance(item, Wire) or isinstance(item, Junction):
                connectables.append(item)
            elif isinstance(item, SchematicItem):
                for pin_id, pin_info in item.pins.items():
                    # We treat pins as points in common with wires
                    # But we need to identify them.
                    # Simpler: The pins are effectively entry points.
                    # We can check overlaps at pin positions.
                    pass

        # Mapping: Point -> List of connected items (Wires, Junctions, Pins)
        # But wires are continuous.
        # Let's map unique Sets of connected items.

        groups = []

        # Helper to find if an item belongs to a group
        item_to_group = {}

        # Wire connectivity:
        # Check endpoints and intersections (Junctions already exist for T-intersections).
        # Actually, `recalculate_connectivity` ensures Junctions exist at intersections.
        # So we just need to trace endpoints.

        # Let's build an adjacency graph of "Net Segments"
        # Nodes in graph: Wires, Junctions, Pins (identified by (item, pin_id))

        adj = {}

        # Store Pin references: (item, pin_id) -> scene_pos
        all_pins = []
        for item in self.scene.items():
            # SVG-based schematic items: pins is a dict mapping -> {'pos': QPointF}
            if hasattr(item, "pins") and isinstance(getattr(item, "pins"), dict):
                for pin_id, pin_info in item.pins.items():
                    try:
                        pos = item.mapToScene(pin_info["pos"])
                    except Exception:
                        continue
                    pin_ref = (item, pin_id)
                    all_pins.append((pin_ref, pos))
                    adj[pin_ref] = []
            # Programmatic pcells: expose pin_items mapping of QGraphicsRectItem
            elif hasattr(item, "pin_items") and isinstance(
                getattr(item, "pin_items"), dict
            ):
                for pin_id, pin_obj in item.pin_items.items():
                    try:
                        r = pin_obj.rect()
                        pos = pin_obj.mapToScene(r.center())
                    except Exception:
                        continue
                    pin_ref = (item, pin_id)
                    all_pins.append((pin_ref, pos))
                    adj[pin_ref] = []

        wires = [i for i in self.scene.items() if isinstance(i, Wire)]
        junctions = [i for i in self.scene.items() if isinstance(i, Junction)]

        for w in wires:
            adj[w] = []
        for j in junctions:
            adj[j] = []

        # Build edges
        # 1. Wire-Wire/Junction/Pin connectivity based on geometry
        # Check endpoints of wires against others

        # Spatial hashing or brute force (small circuits)
        # Brute force for now

        def match(p1, p2):
            return (p1 - p2).manhattanLength() < 1.0

        def distance_p_to_l(p, l):
            # Vectorized distance to segment
            ap = p - l.p1()
            ab = l.p2() - l.p1()
            len_sq = ab.x() ** 2 + ab.y() ** 2
            if len_sq == 0:
                return (p - l.p1()).manhattanLength()
            t = (ap.x() * ab.x() + ap.y() * ab.y()) / len_sq
            t = max(0, min(1, t))  # Clamp to segment
            proj = l.p1() + t * ab
            return (p - proj).manhattanLength()

        for w in wires:
            lw = w.line()
            p1_scene = w.mapToScene(lw.p1())
            p2_scene = w.mapToScene(lw.p2())
            scene_line = QLineF(p1_scene, p2_scene)

            # Check against other wires
            for w2 in wires:
                if w == w2:
                    continue
                lw2 = w2.line()
                p2a = w2.mapToScene(lw2.p1())
                p2b = w2.mapToScene(lw2.p2())
                sl2 = QLineF(p2a, p2b)
                if (
                    distance_p_to_l(p1_scene, sl2) < 1
                    or distance_p_to_l(p2_scene, sl2) < 1
                ):
                    adj[w].append(w2)
                    adj[w2].append(w)
                elif (
                    distance_p_to_l(p2a, scene_line) < 1
                    or distance_p_to_l(p2b, scene_line) < 1
                ):
                    adj[w].append(w2)
                    adj[w2].append(w)

            # Check against junctions
            for j in junctions:
                jp = j.scenePos()
                if distance_p_to_l(jp, scene_line) < 1:
                    adj[w].append(j)
                    adj[j].append(w)

            # Check against pins
            for pin_ref, pos in all_pins:
                if distance_p_to_l(pos, scene_line) < 1:
                    adj[w].append(pin_ref)
                    adj[pin_ref].append(w)

        # 1.5 Pin-Pin adjacency (overlapping pins)
        for i, (pin_ref1, pos1) in enumerate(all_pins):
            for j in range(i + 1, len(all_pins)):
                pin_ref2, pos2 = all_pins[j]
                if match(pos1, pos2):
                    adj[pin_ref1].append(pin_ref2)
                    adj[pin_ref2].append(pin_ref1)

        # 2. Traverse Graph to assign Nodes
        # Visited set for components in graph
        visited = set()
        node_counter = 1

        # Map: Pin/Wire/Junction -> NodeName
        self.item_node_map = {}

        nodes_found = {}  # NodeName -> List of items

        def get_group_name(group_items):
            # Check for Pinned Nets (like GND or Global Pins)
            for item in group_items:
                if isinstance(item, tuple):  # Pin
                    sch_item, pin_id = item

                    # Special internal case for GND (backward compat)
                    if getattr(sch_item, "prefix", "") == "GND":
                        return "0"

                    # Generic metadata override (e.g., net="0" or net="{name}")
                    if hasattr(sch_item, "pins") and pin_id in sch_item.pins:
                        p_info = sch_item.pins[pin_id]
                        if "net_override" in p_info:
                            net = p_info["net_override"]
                            # Replace {name}, {index}, etc.
                            idx = sch_item.name
                            if (
                                idx
                                and sch_item.prefix
                                and idx.startswith(sch_item.prefix)
                            ):
                                idx = idx[len(sch_item.prefix) :]

                            net = net.replace("{name}", sch_item.name)
                            net = net.replace("{index}", idx)
                            net = net.replace("{fullName}", sch_item.name)

                            # Replace from parameters
                            for k, v in getattr(sch_item, "parameters", {}).items():
                                net = net.replace(f"{{{k}}}", str(v))
                                net = net.replace(f"{{{k.lower()}}}", str(v))
                                net = net.replace(f"{{{k.title()}}}", str(v))

                            return net

            # Check for User-defined Wire names
            user_names = set()
            for item in group_items:
                if isinstance(item, Wire) and item.name:
                    user_names.add(item.name)

            if user_names:
                return sorted(list(user_names))[0]

            return None

        # DFS/BFS
        all_nodes = list(adj.keys())
        for start_node in all_nodes:
            if start_node in visited:
                continue

            # New group
            group = []
            stack = [start_node]
            visited.add(start_node)

            while stack:
                curr = stack.pop()
                group.append(curr)

                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)

            # Assign Name
            name = get_group_name(group)
            if not name:
                name = f"N_{node_counter}"
                node_counter += 1

            for item in group:
                self.item_node_map[item] = name

        # 3. Generate Component Lines
        # Include both SVG-based SchematicItem and programmatic pcells (items that expose pins)
        schematic_items = [
            i
            for i in self.scene.items()
            if (hasattr(i, "pins") and isinstance(getattr(i, "pins"), dict))
            or (hasattr(i, "pin_items") and isinstance(getattr(i, "pin_items"), dict))
        ]

        # Filter out GND (it's 0 node, no netlist line needed usually if node is named 0)
        # But we need to iterate sorted by name for deterministic output
        schematic_items.sort(key=lambda x: x.name or "")

        for item in schematic_items:
            if item.prefix == "GND":
                continue

            # Skip pins and stimuli generators in the normal item loop
            if item.svg_path:
                lower_path = item.svg_path.lower()
                if (
                    "pin_" in lower_path
                    or "stimuli_generator.svg" in lower_path
                    or "stimuli_generator/symbol.svg" in lower_path
                ):
                    continue

            # Hierarchical Subcircuit Logic
            # Any item pointing to a .sch file should trigger subcircuit code generation,
            # regardless of whether it uses a template for the call line.
            model_param = item.parameters.get("MODEL")
            subckt_name = None
            if model_param and (
                model_param.endswith(".sch") or model_param.endswith(".sch.svg")
            ):
                import os

                # Default to model name from param
                subckt_name = (
                    os.path.basename(model_param)
                    .replace(".sch", "")
                    .replace(".svg", "")
                )
                # If we have a path, use the cell name (parent directory)
                if item.svg_path:
                    cell_name = os.path.basename(os.path.dirname(item.svg_path))
                    if cell_name and cell_name not in [".", ""]:
                        subckt_name = cell_name

                if subckt_name not in self.subcircuits_code:
                    if item.svg_path:
                        dir_name = os.path.dirname(item.svg_path)
                        base_sch = model_param.replace(".sch", "")
                        sch_paths_to_try = [
                            os.path.join(dir_name, f"{base_sch}.svg"),
                            os.path.join(dir_name, f"{base_sch}.sch.svg"),
                            os.path.join(dir_name, "schematic.svg"),
                            os.path.join(dir_name, "schematic.sch.svg"),
                        ]
                        if item.svg_path.endswith(".sym.svg"):
                            sch_paths_to_try.append(
                                item.svg_path.replace(".sym.svg", ".sch.svg")
                            )
                            sch_paths_to_try.append(
                                item.svg_path.replace(".sym.svg", ".svg")
                            )

                        for sch_path in sch_paths_to_try:
                            if os.path.exists(sch_path):
                                self._generate_subcircuit(sch_path, subckt_name)
                                break

            # 1. Programmatic pcells (format_netlist)
            if hasattr(item, "format_netlist") and callable(
                getattr(item, "format_netlist")
            ):
                try:
                    line = item.format_netlist(self.item_node_map)
                    if line:
                        if isinstance(line, (list, tuple)):
                            for l in line:
                                output.append(l)
                        else:
                            output.append(line)
                        continue
                except Exception as e:
                    output.append(
                        f"* Error from format_netlist of {getattr(item, 'name', '<unnamed>')}: {e}"
                    )

            # 2. Template-based formatting
            template = getattr(item, "spice_template", None)
            if template:
                idx = item.name
                if item.prefix and item.name.startswith(item.prefix):
                    idx = item.name[len(item.prefix) :]

                fmt_args = {"name": idx, "prefix": item.prefix, "full_name": item.name}
                pin_ids = list(getattr(item, "pins", {}).keys())
                for pin_id in pin_ids:
                    node = self.item_node_map.get((item, pin_id), "0")
                    fmt_args[pin_id] = node
                    fmt_args[f"pin_{pin_id}"] = node

                for k, v in item.parameters.items():
                    val = v
                    if k.upper() == "MODEL" and isinstance(v, str):
                        # Use the resolved subckt_name instead of just stripping extensions
                        if subckt_name:
                            val = subckt_name
                        else:
                            val = v.replace(".sch", "").replace(".svg", "")
                    elif k.upper() == "PYTHONPATH" and isinstance(v, str):
                        import os

                        # Resolve $SVG to the directory of the current schematic
                        sch_dir = ""
                        try:
                            view = self.scene.views()[0]
                            if hasattr(view, "filename") and view.filename:
                                sch_dir = os.path.dirname(view.filename)
                        except Exception:
                            pass

                        val = v.replace("$SVG", sch_dir)
                        val = os.path.expandvars(val)
                        val = os.path.abspath(val)

                    fmt_args[k] = val
                    fmt_args[k.lower()] = val
                    fmt_args[k.title()] = val

                try:
                    import jinja2
                    import re

                    # Backward compatibility for str.format() style placeholders
                    # Convert {var} to {{var}} if it's not already Jinja's {{var}} or {%...%}
                    jinja_template_str = re.sub(
                        r"(?<!\{)(?<!%)\{([a-zA-Z0-9_]+)\}(?!\})(?!%)",
                        r"{{\1}}",
                        template,
                    )

                    env = jinja2.Environment()
                    t = env.from_string(jinja_template_str)
                    line = t.render(**fmt_args)

                    output.append(line)
                    continue
                except Exception as e:
                    output.append(f"* Error formatting {item.name}: {e}")
                    continue

            # 3. Hierarchical Fallback (if no template/pcell generated a line yet)
            if subckt_name:
                pin_ids = list(getattr(item, "pins", {}).keys())
                node_names = []
                for pid in pin_ids:
                    node_names.append(self.item_node_map.get((item, pid), "0"))

                line = f"X_{item.name} {' '.join(node_names)} {subckt_name}"
                output.append(line)
                continue

            output.append(f"* Skipping {item.name}: No template")
            continue

            # Format: {name}, {pin_X}, {param}
            fmt_args = {}
            fmt_args["name"] = (
                item.name
            )  # e.g. "R1" -> template "R{name}" -> "RR1"? No, usually template is "R{name} ..." and item.name is "1".
            # Wait, our auto-naming sets name="R1".
            # So template "R{name}" would be "RR1".
            # User example: template="R{name} ...".
            # If item name is "1", result "R1". If item name is "R1", result "RR1".
            # Current auto-naming produces "R1".
            # We should probably strip prefix if template provides it, or just use item.name directly.
            # Let's assume template uses {name} to mean the FULL instance name if it doesn't duplicate prefix.
            # OR assume {name} is the index.
            # Looking at user example: template="R{name}".
            # If my item name is "R1", simply replacing {name} with "R1" gives "RR1".
            # Fix: If item name starts with prefix in template, handle it?
            # Or just assume {name} means the unique identifier.
            # Let's provide both {name} (full) and {index} (stripped).
            # For now, let's use item.name and user can adjust template or we check duplication.
            # Actually, `template="R{name} ..."` usually implies `name` is the numeric part.
            # But we store `name="R1"`.
            # Let's strip prefix for `name` inside template if template starts with it?
            # No, simplistic: `name` = item.name. User template should be `{name}` then?
            # User Req: `template="R{name} {pin_1} {pin_2} {R}"`. This suggests they want to prefix R themselves.
            # So we should pass index.

            idx = item.name
            if item.name.startswith(item.prefix):
                idx = item.name[len(item.prefix) :]

            fmt_args["name"] = idx

            # Pins
            # Collect pins for this item (support both SchematicItem and PCellSymbol)
            pin_ids = []
            if hasattr(item, "pins") and isinstance(getattr(item, "pins"), dict):
                pin_ids = list(item.pins.keys())
            elif hasattr(item, "pin_items") and isinstance(
                getattr(item, "pin_items"), dict
            ):
                pin_ids = list(item.pin_items.keys())

            for pin_id in pin_ids:
                pin_ref = (item, pin_id)
                node = self.item_node_map.get(pin_ref, "0")
                if pin_ref not in self.item_node_map:
                    node = f"N_float_{item.name}_{pin_id}"
                fmt_args[pin_id] = node
                fmt_args[f"pin_{pin_id}"] = node

            # Parameters
            for k, v in item.parameters.items():
                fmt_args[k] = v
                fmt_args[k.lower()] = v
                fmt_args[k.title()] = v

            try:
                line = template.format(**fmt_args)
                output.append(line)
            except KeyError as e:
                output.append(f"* Error formatting {item.name}: Missing key {e}")

        # 4. Analyses
        # In Xyce, it is best to have only one active analysis per netlist to avoid .print conflicts.
        # We process only the first enabled analysis.

        # Collect currents and nodes based on user selection
        save_current_names = []
        save_voltage_nodes = set()
        for item in schematic_items:
            if item.prefix == "GND":
                continue
            if getattr(item, "save_current", False):
                save_current_names.append(item.name)
            if getattr(item, "save_voltage", True):
                # Collect nodes connected to this item's pins
                if hasattr(item, "pins"):
                    for pin_id in item.pins:
                        node = self.item_node_map.get((item, pin_id))
                        if node and node != "0":
                            save_voltage_nodes.add(node)

        currents_str = " ".join([f"i({name})" for name in save_current_names])
        # If user wants any voltages, we'll keep v(*) for convenience or list them
        # Xyce .print tran v(*) i(*) is standard.
        # But if we want to be selective:
        voltages_str = (
            "v(*)"
            if any(getattr(item, "save_voltage", True) for item in schematic_items)
            else ""
        )

        # 3. Stimuli Generators (Custom Netlist Snippets)
        for item in schematic_items:
            if self.is_subcircuit:
                continue
            if item.svg_path and (
                "stimuli_generator.svg" in item.svg_path.lower()
                or "stimuli_generator/symbol.svg" in item.svg_path.lower()
            ):
                script_path = item.parameters.get("SCRIPT", "")
                if script_path:
                    import os
                    import json

                    # Resolve absolute path relative to current schematic
                    abs_script_path = ""
                    try:
                        view = self.scene.views()[0]
                        if hasattr(view, "filename") and view.filename:
                            abs_script_path = os.path.abspath(
                                os.path.join(
                                    os.path.dirname(view.filename), script_path
                                )
                            )
                        else:
                            abs_script_path = os.path.abspath(script_path)
                    except Exception:
                        abs_script_path = os.path.abspath(script_path)

                    json_path = os.path.splitext(abs_script_path)[0] + ".json"
                    if os.path.exists(json_path):
                        try:
                            with open(json_path, "r") as f:
                                data = json.load(f)
                            runset = data.get("runset", "")
                            if runset:
                                output.append(
                                    f"* --- Stimuli from {os.path.basename(json_path)} ---"
                                )
                                output.append(runset)
                                output.append(
                                    "* ----------------------------------------"
                                )
                        except Exception as e:
                            output.append(
                                f"* Error reading stimuli from {json_path}: {e}"
                            )

        for config in self.analyses:
            if not config.get("enabled", True):
                continue

            an_type = str(config.get("type", "")).upper()
            save_all = config.get("save_all", True)
            if isinstance(save_all, str):
                save_all = save_all.lower() == "true"

            if an_type == "DC":
                output.append(
                    f".dc {config.get('source')} {config.get('start')} {config.get('stop')} {config.get('step')}"
                )
                if save_all:
                    output.append(f".print dc {voltages_str} {currents_str}")
                # DC sweeps shouldn't generally be mixed with AC/TRAN because Xyce can complain about
                # the time/freq scale vs stepped parameters depending on how it's defined, but we'll leave it up to the user.
            elif an_type == "AC":
                output.append(
                    f".ac {config.get('ac_type')} {config.get('points')} {config.get('start')} {config.get('stop')}"
                )
                if save_all:
                    output.append(f".print ac {voltages_str} {currents_str}")
            elif an_type == "TRAN":
                step = config.get("step") or "1u"
                stop = config.get("stop") or "100u"
                line = f".tran {step} {stop}"
                if config.get("start"):
                    line += f" {config.get('start')}"
                output.append(line)
                if save_all:
                    output.append(f".print tran {voltages_str} {currents_str}")
            elif an_type == "OP":
                output.append(".op")
                if save_all:
                    # In Xyce, for .op analysis, specify .print dc to get results in the raw file
                    output.append(f".print dc {voltages_str} {currents_str}")

        if not self.is_subcircuit:
            subckts_str = "\n".join(self.subcircuits_code.values())
            if subckts_str:
                output.insert(
                    1, "\n* Subcircuits\n" + subckts_str + "\n* Main Circuit\n"
                )
            output.append(".end")
        else:
            output.append(".ends\n")

        return "\n".join(output)
