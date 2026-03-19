import os
import threading
import shutil
import logging
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal, Qt, QSettings, QThread
from fastmcp import FastMCP

from opens_suite.plugins.base import OpenSPlugin

# Configure logging for MCP
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_plugin")

class QtThreadInvoker(QObject):
    """Bridge to execute functions on the Qt main thread from background threads."""
    invoke_signal = pyqtSignal(object, object)

    def __init__(self):
        super().__init__()
        self.invoke_signal.connect(self._handle_invoke, Qt.ConnectionType.BlockingQueuedConnection)

    @pyqtSlot(object, object)
    def _handle_invoke(self, func, result_container):
        try:
            res = func()
            result_container.append(res)
        except Exception as e:
            logger.exception("Error executing function on Qt main thread")
            result_container.append(e)

    def run_on_main(self, func):
        """Runs func on main thread and returns result, blocking until done."""
        curr_thread = QThread.currentThread()
        main_thread = self.thread()
        if curr_thread == main_thread:
            return func()

        logger.info(f"[DIAG] run_on_main starting for {func} on thread {curr_thread}")
        results = []
        self.invoke_signal.emit(func, results)
        logger.info(f"[DIAG] run_on_main finished for {func}. results list: {results}")
        if not results:
            logger.error(f"[DIAG] run_on_main: ERROR: results list is empty for {func}")
            return None
        res = results[0]
        if isinstance(res, Exception):
            logger.error(f"[DIAG] run_on_main: ERROR: function raised {res}")
            raise res
        logger.info(f"[DIAG] run_on_main: returning {res}")
        return res

class McpPlugin(OpenSPlugin):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mcp = FastMCP("OpenS")
        self.invoker = QtThreadInvoker()
        self._setup_tools()
        logger.info("[DIAG] McpPlugin initialized. Version: 2026-03-13-1640")

    def setup(self):
        """Start the MCP server in a background thread."""
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app and hasattr(app, "_splash_proc"):
            from opens_suite.__main__ import _update_splash
            _update_splash(app._splash_proc, "Starting MCP server...", 85)

        # Skip server startup in tests to avoid port collisions
        if "PYTEST_CURRENT_TEST" in os.environ:
            logger.info("Skipping MCP server startup in test environment")
            return

        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        logger.info("McpPlugin server thread started")

    def _run_server(self):
        try:
            settings = QSettings("OpenS", "OpenS")
            port = int(settings.value("mcp_port", 8000))
            # transport='sse' uses SSE for communication
            self.mcp.run(transport='sse', port=port)
        except Exception as e:
            logger.exception("FastMCP server exited unexpectedly")

    def export_config(self):
        """Export the MCP config to ~/.copilot/mcp-config.json"""
        import json
        settings = QSettings("OpenS", "OpenS")
        port = int(settings.value("mcp_port", 8000))

        config = {
            "mcpServers": {
                "OpenS": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "@modelcontextprotocol/inspector",
                        f"http://localhost:{port}/sse"
                    ]
                }
            }
        }

        # Note: The user specifically asked for ~/.copilot/mcp-config.json
        # which is likely for github copilot extension
        target_dir = os.path.expanduser("~/.copilot")
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        target_path = os.path.join(target_dir, "mcp-config.json")

        # Merge if exists? Or overwrite? User said 'export the mcp setup to ...'
        # Usually these files are JSON objects with 'mcpServers' key.
        existing_config = {}
        if os.path.exists(target_path):
            try:
                with open(target_path, "r") as f:
                    existing_config = json.load(f)
            except Exception:
                pass

        if "mcpServers" not in existing_config:
            existing_config["mcpServers"] = {}

        existing_config["mcpServers"]["OpenS"] = {
            "type": "sse",
            "url": f"http://localhost:{port}/sse"
        }

        # Wait, if it's SSE, some clients use "url", some use "command" for stdio.
        # For SSE it should usually be "url".
        # Let's provide both or follow a standard.
        # Copilot/VSCode MCP typically supports "url" for SSE.

        with open(target_path, "w") as f:
            json.dump(existing_config, f, indent=4)

        return target_path

    def _setup_tools(self):
        # 1. opening a view
        @self.mcp.tool()
        def open_view(lib: str, cell: str, view: str = "schematic") -> str:
            """
            Open an existing schematic or symbol and bring it to the front.
            'view' defaults to 'schematic' if not specified.
            """
            return self.invoker.run_on_main(lambda: self.tool_open_view(lib, cell, view))

        # 2. copying a view
        @self.mcp.tool()
        def copy_view(src_lib: str, src_cell: str, src_view: str,
                      dest_lib: str, dest_cell: str, dest_view: str) -> str:
            """Copy a view to a new destination."""
            return self.invoker.run_on_main(lambda: self.tool_copy_view(src_lib, src_cell, src_view, dest_lib, dest_cell, dest_view))

        # 3. iterating all symbols on a schematic
        @self.mcp.tool()
        def iterate_symbols(lib: str, cell: str, view: str) -> List[Dict[str, Any]]:
            """Get a list of all symbols placed in the specified schematic."""
            return self.invoker.run_on_main(lambda: self.tool_iterate_symbols(lib, cell, view))

        # 4. getting the currently opened lib/cell/view
        @self.mcp.tool()
        def get_current_view() -> Optional[Dict[str, str]]:
            """Return information about the currently active tab."""
            res = self.invoker.run_on_main(lambda: self.tool_get_current_view())
            logger.info(f"[DIAG] tool wrapper get_current_view returning to MCP: {res}")
            return res

        # 5. ask for the connection of one symbol
        @self.mcp.tool()
        def get_connected_nets(lib: str, cell: str, view: str, instance_name: str) -> Dict[str, str]:
            """Get net names connected to each pin of a specific instance."""
            return self.invoker.run_on_main(lambda: self.tool_get_connected_nets(lib, cell, view, instance_name))

        # 6. getting the current netlist
        @self.mcp.tool()
        def get_current_netlist() -> str:
            """Generate and return the netlist for the currently active schematic."""
            return self.invoker.run_on_main(self.tool_get_current_netlist)

        # 7. adding expressions to the output browser
        @self.mcp.tool()
        def add_output_expression(expression: str):
            """
            Add a new mathematical expression to the Outputs dock.

            Format: Use Python syntax with built-in functions:
            - v('node'): Voltage of a node (generic)
            - vt('node'): Transient voltage
            - it('branch'): Transient current
            - vf('node'): AC voltage (complex)
            - db(x), ph(x), mag(x): Signal processing
            - mean(t, x, start, stop): Average value

            See mcp://docs/expressions for the full documentation.
            """
            return self.invoker.run_on_main(lambda: self.tool_add_output_expression(expression))

        @self.mcp.resource("mcp://docs/expressions")
        def get_expression_docs() -> str:
            """Provide detailed documentation on output expression syntax and available functions."""
            return """
# OpenS Output Expression Documentation

The OpenS calculator and outputs dock allow you to define expressions using Python syntax.
The following functions and variables are available in the evaluation scope:

## Signal Access
- `v(name)`: Generic voltage fetcher. Tries Transient, then DC, then AC.
- `vt(name)` / `it(name)`: Transient voltage/current for the given node or branch.
- `vf(name)` / `ifc(name)`: AC (frequency domain) voltage/current. Returns complex values.
- `vdc(name)`: DC sweep voltage.
- `op(name)`: Operating point value (returns a scalar).

## Mathematical Functions
- `mag(x)`: Magnitude of a complex signal.
- `db(x)` or `dB(x)`: Decibels (20 * log10(abs(x))).
- `ph(x)`: Phase of a complex signal in degrees.
- `mean(t, x, [start, stop])`: Calculates the average of `x` over the time vector `t`.
- `rms(t, x, [start, stop])`: Calculates the Root-Mean-Square value.
- `p2p(t, x, [start, stop])`: Calculates peak-to-peak value.
- `value(t, x, at)`: Interpolates the value of `x` at a specific point `at`.
- `f3db(x)`: Calculates the 3dB bandwidth of a complex frequency response.

## Variables
- `t`: The time vector from the transient simulation.
- `f`: The frequency vector from the AC simulation.
- `sw`: The sweep vector from a DC analysis.
- `np`: Full access to NumPy (e.g., `np.sin(t * 2 * np.pi * 1k)`).

## Examples
- `dB(vf('vout'))`: Plot gain in dB for AC analysis.
- `mean(t, it('v1'), 1m, 2m)`: Calculate average input current between 1ms and 2ms.
- `v('net1') - v('net2')`: Differential voltage.
- `mag(vf('out')) / mag(vf('in'))`: Manual gain calculation.
            """.strip()

        # 8. debug tab state
        @self.mcp.tool()
        def debug_mcp_state() -> Dict[str, Any]:
            """Return internal state of the MCP plugin and tabs for debugging."""
            return self.invoker.run_on_main(self.tool_debug_mcp_state)

        # 9. get instance parameters
        @self.mcp.tool()
        def get_instance_parameters(lib: str, cell: str, view: str, instance_name: str) -> Dict[str, str]:
            """Get all parameters of a specific instance."""
            return self.invoker.run_on_main(lambda: self.tool_get_instance_parameters(lib, cell, view, instance_name))

        # 10. update instance parameters
        @self.mcp.tool()
        def update_instance_parameters(lib: str, cell: str, view: str, instance_name: str, parameters: Dict[str, str] = None) -> str:
            """Update parameters of a specific instance."""
            if not parameters:
                return "Error: 'parameters' argument is required as a dictionary of {name: value}"
            return self.invoker.run_on_main(lambda: self.tool_update_instance_parameters(lib, cell, view, instance_name, parameters))

        # 11. run simulation
        @self.mcp.tool()
        def run_simulation(lib: str, cell: str, view: str) -> str:
            """Start a Xyce simulation for the specified schematic."""
            return self.invoker.run_on_main(lambda: self.tool_run_simulation(lib, cell, view))

        # 12. get simulation signals
        @self.mcp.tool()
        def get_simulation_signals(lib: str, cell: str, view: str) -> List[str]:
            """Retrieve a list of all available signal names from the latest simulation results."""
            return self.invoker.run_on_main(lambda: self.tool_get_simulation_signals(lib, cell, view))

        # 13. get all output expressions
        @self.mcp.tool()
        def get_output_expressions() -> List[Dict[str, Any]]:
            """Return all existing output expressions with their full metadata."""
            return self.invoker.run_on_main(self.tool_get_output_expressions)

        # 14. update an existing output expression
        @self.mcp.tool()
        def update_output_expression(index: int,
                                     name: Optional[str] = None,
                                     expression: Optional[str] = None,
                                     unit: Optional[str] = None,
                                     min_spec: Optional[str] = None,
                                     max_spec: Optional[str] = None,
                                     description: Optional[str] = None) -> str:
            """
            Update an existing output expression by its index.
            Only provided fields will be modified.
            """
            kwargs = {}
            if name is not None: kwargs["name"] = name
            if expression is not None: kwargs["expression"] = expression
            if unit is not None: kwargs["unit"] = unit
            if min_spec is not None: kwargs["min"] = min_spec
            if max_spec is not None: kwargs["max"] = max_spec
            if description is not None: kwargs["description"] = description

            return self.invoker.run_on_main(lambda: self.tool_update_output_expression(index, **kwargs))

        # 15. create a new empty schematic
        @self.mcp.tool()
        def create_schematic(lib: str, cell: str, view: str = "schematic") -> str:
            """
            Create a new empty schematic view in the specified library and cell.
            If the cell or library doesn't exist, they will be created in the project directory.
            """
            return self.invoker.run_on_main(lambda: self.tool_create_schematic(lib, cell, view))

        # 16. add input/output pins
        @self.mcp.tool()
        def add_pins(lib: str, cell: str, view: str, pins: List[Dict[str, str]]) -> str:
            """
            Add multiple input/output pins to a schematic.
            'pins' is a list of dicts: {"name": "PIN1", "direction": "input"|"output"}
            Inputs are placed on the left, outputs on the right.
            """
            return self.invoker.run_on_main(lambda: self.tool_add_pins(lib, cell, view, pins))

        # 17. list all libraries and cells
        @self.mcp.tool()
        def list_libraries() -> Dict[str, List[str]]:
            """Return a list of all available libraries and their cells."""
            return self.invoker.run_on_main(self.tool_list_libraries)

        # 18. remove a symbol
        @self.mcp.tool()
        def remove_symbol(lib: str, cell: str, view: str, name: str) -> str:
            """Remove a symbol or pin from a schematic by its instance name or pin label."""
            return self.invoker.run_on_main(lambda: self.tool_remove_symbol(lib, cell, view, name))

        # 19. get instance pins
        @self.mcp.tool()
        def get_instance_pins(lib: str, cell: str, view: str, instance_name: str) -> Dict[str, Dict[str, float]]:
            """Get the x,y coordinates (scene space) for all pins of a symbol instance."""
            return self.invoker.run_on_main(lambda: self.tool_get_instance_pins(lib, cell, view, instance_name))

        # 20. connect by wire
        @self.mcp.tool()
        def connect_by_wire(lib: str, cell: str, view: str, p1: List[float], op: str, p2: List[float], net_name: Optional[str] = None) -> str:
            """
            Connect two points with a wire using routing operators:
            '--' : direct straight line
            '|-' : vertical segment then horizontal segment
            '-|' : horizontal segment then vertical segment
            p1, p2 are [x, y] coordinate lists.
            """
            return self.invoker.run_on_main(lambda: self.tool_connect_by_wire(lib, cell, view, p1, op, p2, net_name))

        # 21. add a symbol
        @self.mcp.tool()
        def add_symbol(lib: str, cell: str, view: str, symbol_lib: str, symbol_cell: str, x: float, y: float, name: Optional[str] = None, parameters: Optional[Dict[str, str]] = None) -> str:
            """
            Place a symbol instance at specific (x,y) coordinates.
            'parameters' is an optional dict of parameter values.
            """
            return self.invoker.run_on_main(lambda: self.tool_add_symbol(lib, cell, view, symbol_lib, symbol_cell, x, y, name, parameters))

        # 22. change view category
        @self.mcp.tool()
        def set_view_category(lib: str, cell: str, view: str, category: str) -> str:
            """Change the category of a schematic or symbol view."""
            return self.invoker.run_on_main(lambda: self.tool_set_view_category(lib, cell, view, category))

        # 23. get API documentation
        @self.mcp.tool()
        def get_api_documentation(class_name: str) -> str:
            """
            Get the API documentation for classes used in notebooks (e.g., 'Stimuli', 'DesignPoints').
            """
            return self.tool_get_api_documentation(class_name)

        # 24. read notebook
        @self.mcp.tool()
        def read_notebook(lib: str, cell: str, view: str, notebook_path: str) -> str:
            """Read the content of a Jupyter Notebook (*.ipynb) in a cell."""
            return self.invoker.run_on_main(lambda: self.tool_read_notebook(lib, cell, view, notebook_path))

        # 25. append notebook code
        @self.mcp.tool()
        def append_notebook_code(lib: str, cell: str, view: str, notebook_path: str, code: str) -> str:
            """Append a new code cell to a Jupyter Notebook (*.ipynb) in a cell."""
            return self.invoker.run_on_main(lambda: self.tool_append_notebook_code(lib, cell, view, notebook_path, code))

        # 26. update notebook cell
        @self.mcp.tool()
        def update_notebook_cell(lib: str, cell: str, view: str, notebook_path: str, index: int, code: str) -> str:
            """Update a specific cell's content in a Jupyter Notebook (*.ipynb)."""
            return self.invoker.run_on_main(lambda: self.tool_update_notebook_cell(lib, cell, view, notebook_path, index, code))

    # --- Tool Implementations (Internal) ---

    def tool_list_libraries(self) -> Dict[str, List[str]]:
        """Scan all library search paths and return a mapping of lib name to cell list."""
        search_paths = []
        default_lib = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "libraries")
        if os.path.exists(default_lib):
            search_paths.append(default_lib)

        from PyQt6.QtCore import QSettings
        settings = QSettings("OpenS", "OpenS")
        paths_str = settings.value("library_search_paths", "")
        for p in paths_str.split(","):
            p = p.strip()
            if p and os.path.exists(p):
                search_paths.append(p)

        project_dir = getattr(self.main_window, "project_dir", os.getcwd())
        if project_dir and os.path.exists(project_dir) and project_dir not in search_paths:
            search_paths.append(project_dir)

        libraries = {}
        for base in search_paths:
            if not os.path.isdir(base):
                continue
            try:
                for lib in os.listdir(base):
                    lib_path = os.path.join(base, lib)
                    if os.path.isdir(lib_path) and not lib.startswith("."):
                        if lib not in libraries:
                            libraries[lib] = set()
                        for cell in os.listdir(lib_path):
                            cell_path = os.path.join(lib_path, cell)
                            if os.path.isdir(cell_path) and not cell.startswith("."):
                                libraries[lib].add(cell)
            except Exception as e:
                logger.error(f"Error scanning library path {base}: {e}")

        return {lib: sorted(list(cells)) for lib, cells in libraries.items()}

    def tool_remove_symbol(self, lib: str, cell: str, view: str, name: str) -> str:
        success, res, msg = self._get_view_obj(lib, cell, view)
        if not success:
            return msg
        view_obj, is_new = res

        from opens_suite.schematic_item import SchematicItem
        from opens_suite.commands import RemoveItemsCommand

        scene = view_obj.scene()
        items_to_remove = []

        # Search for item by instance name or net_name parameter (for pins)
        for item in scene.items():
            if isinstance(item, SchematicItem):
                # Check instance name
                if item.name == name:
                    items_to_remove.append(item)
                # Check net_name parameter (case-insensitive because it's normalized to NET_NAME)
                elif item.parameters.get("NET_NAME") == name.upper() or item.parameters.get("NET_NAME") == name:
                    items_to_remove.append(item)
                elif item.parameters.get("name") == name:
                     items_to_remove.append(item)

        if not items_to_remove:
            return f"Error: No item found with name or label '{name}'"

        cmd = RemoveItemsCommand(scene, items_to_remove)
        view_obj.undo_stack.push(cmd)

        return f"Removed {len(items_to_remove)} item(s) matches '{name}'"

    def tool_get_instance_pins(self, lib: str, cell: str, view: str, instance_name: str) -> Dict[str, Dict[str, float]]:
        success, res, msg = self._get_view_obj(lib, cell, view)
        if not success:
            return {"error": msg}
        view_obj, _ = res

        from opens_suite.schematic_item import SchematicItem
        scene = view_obj.scene()

        target_item = None
        for item in scene.items():
            if isinstance(item, SchematicItem):
                # Match by instance name or net_name (for pins)
                if item.name == instance_name:
                    target_item = item
                    break
                elif item.parameters.get("NET_NAME") == instance_name or item.parameters.get("NET_NAME") == instance_name.upper():
                    target_item = item
                    break

        if not target_item:
            return {"error": f"Instance '{instance_name}' not found"}

        pins_info = {}
        for pin_id, info in target_item.pins.items():
            # pos in pin_info is relative to the item
            scene_pos = target_item.mapToScene(info["pos"])
            pins_info[pin_id] = {"x": scene_pos.x(), "y": scene_pos.y()}

        return pins_info

    def tool_connect_by_wire(self, lib: str, cell: str, view: str, p1: List[float], op: str, p2: List[float], net_name: Optional[str] = None) -> str:
        success, res, msg = self._get_view_obj(lib, cell, view)
        if not success:
            return msg
        view_obj, _ = res

        from opens_suite.wire import Wire
        from opens_suite.commands import InsertItemsCommand
        from PyQt6.QtCore import QPointF

        x1, y1 = p1[0], p1[1]
        x2, y2 = p2[0], p2[1]

        segments = []
        if op == "--":
            segments.append(Wire(QPointF(x1, y1), QPointF(x2, y2)))
        elif op == "|-":
            # Vertical then horizontal
            if y1 != y2:
                segments.append(Wire(QPointF(x1, y1), QPointF(x1, y2)))
            if x1 != x2:
                segments.append(Wire(QPointF(x1, y2), QPointF(x2, y2)))
        elif op == "-|":
            # Horizontal then vertical
            if x1 != x2:
                segments.append(Wire(QPointF(x1, y1), QPointF(x2, y1)))
            if y1 != y2:
                segments.append(Wire(QPointF(x2, y1), QPointF(x2, y2)))
        else:
            return f"Error: Unknown operator '{op}'. Use '--', '|-', or '-|'."

        if not segments:
            return "Warning: Points are identical, no wire created."

        if net_name:
            for w in segments:
                w.name = net_name

        cmd = InsertItemsCommand(view_obj.scene(), segments)
        view_obj.undo_stack.push(cmd)

        return f"Connected ({x1},{y1}) to ({x2},{y2}) with {len(segments)} segments using '{op}'"

    def tool_add_symbol(self, lib: str, cell: str, view: str, symbol_lib: str, symbol_cell: str, x: float, y: float, name: Optional[str] = None, parameters: Optional[Dict[str, str]] = None) -> str:
        success, res, msg = self._get_view_obj(lib, cell, view)
        if not success:
            return msg
        view_obj, _ = res

        symbol_path = self._resolve_path(symbol_lib, symbol_cell, "symbol")
        if not symbol_path:
            return f"Error: Symbol {symbol_lib}/{symbol_cell} not found"

        from opens_suite.schematic_item import SchematicItem
        from opens_suite.commands import InsertItemsCommand

        item = SchematicItem(symbol_path)
        item.setPos(x, y)

        if name:
            item.set_name(name)
        elif hasattr(view_obj, "_assign_name"):
            view_obj._assign_name(item)

        if parameters:
            for k, v in parameters.items():
                item.set_parameter(k, v)

        cmd = InsertItemsCommand(view_obj.scene(), item)
        view_obj.undo_stack.push(cmd)

        return f"Added symbol {symbol_lib}/{symbol_cell} at ({x},{y})"

    def tool_set_view_category(self, lib: str, cell: str, view: str, category: str) -> str:
        path = self._resolve_path(lib, cell, view)
        if not path:
            return f"Error: View '{view}' not found in {lib}/{cell}"

        import xml.etree.ElementTree as ET
        ET.register_namespace("opens", "http://opens-schematic.org")

        try:
            tree = ET.parse(path)
            root = tree.getroot()

            # 1. Find or create <defs>
            defs = root.find("{http://www.w3.org/2000/svg}defs")
            if defs is None:
                defs = root.find("defs")
            if defs is None:
                defs = ET.Element("defs")
                root.insert(0, defs)

            # 2. Find or create <opens:symbol>
            symbol_meta = None
            for elem in defs.iter():
                if elem.tag.endswith("}symbol") or elem.tag == "opens:symbol":
                    symbol_meta = elem
                    break

            if symbol_meta is None:
                symbol_meta = ET.SubElement(defs, "{http://opens-schematic.org}symbol")

            symbol_meta.set("category", category)

            # 3. Save
            if hasattr(ET, "indent"):
                ET.indent(root, space="  ", level=0)
            tree.write(path, encoding="utf-8", xml_declaration=True)

            # 4. Refresh Library Browser if available
            library_widget = self._find_widget("LibraryWidget")
            if library_widget:
                library_widget._populate_library()

            return f"Category of {lib}/{cell}/{view} changed to '{category}'"

        except Exception as e:
            logger.exception(f"Error updating category for {path}")
            return f"Error: {str(e)}"

    def _find_widget(self, class_name):
        """Find a docked widget by its class name."""
        from PyQt6.QtWidgets import QDockWidget
        for dock in self.main_window.findChildren(QDockWidget):
            if dock.__class__.__name__ == class_name:
                return dock
            # Also check if the content widget matches
            if dock.widget() and dock.widget().__class__.__name__ == class_name:
                return dock.widget()
        return None



    def tool_open_view(self, lib: str, cell: str, view: str) -> str:
        path = self._resolve_path(lib, cell, view)
        if not path:
            return f"Error: View '{view}' not found in {lib}/{cell}"

        if hasattr(self.main_window, "open_file"):
            self.main_window.open_file(path)
            return f"Opened {path}"
        return "Error: main_window.open_file not available"

    def tool_add_pins(self, lib: str, cell: str, view: str, pins: List[Dict[str, str]]) -> str:
        success, res, info = self._get_view_obj(lib, cell, view)
        if not success:
            return info

        view_obj, is_temp = res

        # Resolve symbols
        pin_in_path = self._resolve_path("opensLib", "pin_in", "symbol")
        pin_out_path = self._resolve_path("opensLib", "pin_out", "symbol")

        if not pin_in_path or not pin_out_path:
            return "Error: Could not find pin symbols in opensLib"

        inputs = [p for p in pins if p.get("direction", "input") == "input"]
        outputs = [p for p in pins if p.get("direction") == "output"]

        from opens_suite.schematic_item import SchematicItem
        from opens_suite.commands import InsertItemsCommand

        new_items = []

        # Left side (inputs)
        x_in = 100
        y_start = 100
        for i, p in enumerate(inputs):
            item = SchematicItem(pin_in_path)
            item.setPos(x_in, y_start + i * 40)
            item.set_parameter("net_name", p["name"])
            if hasattr(view_obj, "_assign_name"):
                view_obj._assign_name(item)
            new_items.append(item)

        # Right side (outputs)
        x_out = 700
        for i, p in enumerate(outputs):
            item = SchematicItem(pin_out_path)
            item.setPos(x_out, y_start + i * 40)
            item.set_parameter("net_name", p["name"])
            if hasattr(view_obj, "_assign_name"):
                view_obj._assign_name(item)
            new_items.append(item)

        if not new_items:
            return "No pins added."

        if is_temp:
            for item in new_items:
                view_obj.scene().addItem(item)
            path = self._resolve_path(lib, cell, view)
            view_obj.save_schematic(path)
            return f"Added {len(new_items)} pins to {lib}/{cell}/{view} (background)"
        else:
            # Use undo command for active tabs
            cmd = InsertItemsCommand(view_obj.scene(), new_items)
            view_obj.undo_stack.push(cmd)
            return f"Added {len(new_items)} pins to active tab"

    def tool_create_schematic(self, lib: str, cell: str, view: str) -> str:
        cell_path = self._resolve_cell_path(lib, cell)
        if not cell_path:
            return f"Error: Could not resolve cell path for {lib}/{cell}"

        if not os.path.exists(cell_path):
            os.makedirs(cell_path)

        filename = view
        if not filename.endswith(".svg"):
            filename += ".svg"

        path = os.path.join(cell_path, filename)
        if os.path.exists(path):
            return f"Error: View already exists at {path}"

        try:
            # Create default schematic SVG
            with open(path, "w") as f:
                f.write('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600"></svg>')

            # Refresh library dock
            if hasattr(self.main_window, "library_dock"):
                self.main_window.library_dock._populate_library()

            # Open the new schematic
            if hasattr(self.main_window, "open_file"):
                self.main_window.open_file(path)
                return f"Created and opened empty schematic at {path}"

            return f"Created empty schematic at {path}"
        except Exception as e:
            return f"Error creating schematic: {e}"

    def tool_copy_view(self, src_lib, src_cell, src_view, dest_lib, dest_cell, dest_view):
        src_path = self._resolve_path(src_lib, src_cell, src_view)
        if not src_path:
            return f"Error: Source view not found"

        dest_cell_path = self._resolve_cell_path(dest_lib, dest_cell)
        if not dest_cell_path:
            return f"Error: Destination library '{dest_lib}' not found"

        if not os.path.exists(dest_cell_path):
            os.makedirs(dest_cell_path)

        dest_ext = os.path.splitext(src_view)[1] or (".svg" if src_view in ["schematic", "symbol"] else "")
        dest_filename = dest_view
        if not dest_filename.endswith(dest_ext) and dest_ext:
            dest_filename += dest_ext

        dest_path = os.path.join(dest_cell_path, dest_filename)
        shutil.copy2(src_path, dest_path)

        if hasattr(self.main_window, "library_dock"):
            self.main_window.library_dock._populate_library()

        return f"Copied {src_view} to {dest_lib}/{dest_cell}/{dest_view}"

    def tool_iterate_symbols(self, lib, cell, view):
        path = self._resolve_path(lib, cell, view)
        if not path:
            return []

        from opens_suite.schematic_view import SchematicView
        temp_view = SchematicView()
        temp_view.load_schematic(path)

        symbols = []
        from opens_suite.schematic_item import SchematicItem
        for item in temp_view.scene().items():
            if isinstance(item, SchematicItem) and item.prefix != "GND":
                symbols.append({
                    "name": item.name,
                    "prefix": item.prefix,
                    "svg_path": item.svg_path,
                    "parameters": item.parameters
                })
        return symbols

    def tool_get_current_view(self):
        # We can try to infer from filename of current tab
        tabs = self.main_window.tabs
        count = tabs.count()
        index = tabs.currentIndex()
        view = tabs.currentWidget()

        logger.info(f"[DIAG] tool_get_current_view: count={count}, index={index}, view={view}")

        if view is None:
            logger.info("[DIAG] tool_get_current_view: No current widget in tabs")
            # If no current widget, maybe we can check the first tab if count > 0?
            if count > 0:
                view = tabs.widget(0)
                logger.info(f"[DIAG] Falling back to widget 0: {view}")
            else:
                return None

        path = getattr(view, "filename", None)
        view_type = type(view).__name__
        logger.info(f"[DIAG] tool_get_current_view: view_type={view_type}, filename={path}")

        if not path:
            logger.info("[DIAG] get_current_view: No path found on current widget")
            # Log all tabs' filenames for debugging
            for i in range(count):
                w = tabs.widget(i)
                logger.info(f"[DIAG] Tab {i}: type={type(w).__name__}, filename={getattr(w, 'filename', None)}")
            return None

        res = self._parse_path(path)
        logger.info(f"[DIAG] get_current_view returning result: {res}")
        return res

    def tool_get_instance_parameters(self, lib: str, cell: str, view: str, instance_name: str) -> Dict[str, str]:
        success, res, info = self._get_item_from_view(lib, cell, view, instance_name)
        if not success:
             logger.warning(f"get_instance_parameters: {info}")
             return {}

        view_obj, item, is_temp = res
        return getattr(item, "parameters", {})

    def tool_update_instance_parameters(self, lib: str, cell: str, view: str, instance_name: str, parameters: Dict[str, str]) -> str:
        success, res, info = self._get_item_from_view(lib, cell, view, instance_name)
        if not success:
             return info

        view_obj, item, is_temp = res

# Validation: Only allow existing parameters if the item has parameters.
        # If the item does not expose parameters (e.g. mocked item), allow any updates.
        existing_params = getattr(item, "parameters", None)
        if existing_params is not None:
            existing_keys = [k.lower() for k in existing_params.keys()]
            invalid_params = [k for k in parameters.keys() if k.lower() not in existing_keys]
            if invalid_params:
                available = ", ".join(sorted(existing_params.keys()))
                return f"Error: Cannot set new parameters: {', '.join(invalid_params)}. Available parameters for this instance are: {available}"
        else:
            # Create parameters dict if missing
            try:
                item.parameters = {}
            except Exception:
                pass

        for k, v in parameters.items():
            item.set_parameter(k, v)

        if is_temp:
            # Save the schematic if it was loaded in background
            path = self._resolve_path(lib, cell, view)
            view_obj.save_schematic(path)
            return f"Updated parameters for {instance_name} and saved to {path}"
        else:
            # It's in an active tab, just update labels
            item._update_labels()
            return f"Updated parameters for {instance_name} in active tab"

    def tool_run_simulation(self, lib: str, cell: str, view: str) -> str:
        # 1. Open the view (ensure it's active)
        msg = self.tool_open_view(lib, cell, view)
        if "Error" in msg:
            return msg

        # 2. Find XycePlugin
        xyce_plugin = self._find_plugin("XycePlugin")
        if not xyce_plugin:
            return "Error: XycePlugin not found"

        # 3. Trigger simulation
        xyce_plugin.run_simulation()
        return f"Simulation started for {lib}/{cell}/{view}"

    def _find_plugin(self, name):
        """Find a plugin by its class name."""
        for p in self.main_window.plugin_manager.plugins:
            if p.__class__.__name__ == name or type(p).__name__ == name:
                return p
        return None

    def tool_get_simulation_signals(self, lib: str, cell: str, view: str) -> List[str]:
        path = self._resolve_path(lib, cell, view)
        if not path:
            return []

        sim_dir = os.path.join(os.path.dirname(path), "simulation")
        base = os.path.splitext(os.path.basename(path))[0]
        raw_path = os.path.join(sim_dir, f"{base}.raw")

        if not os.path.exists(raw_path):
            logger.warning(f"get_simulation_signals: Result file not found at {raw_path}")
            return []

        from opens_suite.spice_parser import SpiceRawParser
        try:
            parser = SpiceRawParser(raw_path)
            plots = parser.parse()
            if not plots:
                return []

            signals = set()
            for plot_data in plots.values():
                signals.update(plot_data.keys())

            return sorted(list(signals))
        except Exception as e:
            logger.error(f"Error parsing simulation signals: {e}")
            return []

    def _get_view_obj(self, lib, cell, view):
        """Helper to find an active view or load one in background."""
        path = self._resolve_path(lib, cell, view)
        if not path:
            return False, None, f"Error: View '{view}' not found in {lib}/{cell}"

        # Check if it's already open in a tab
        tabs = self.main_window.tabs
        for i in range(tabs.count()):
            w = tabs.widget(i)
            if getattr(w, "filename", None) == path:
                return True, (w, False), "Found in active tab"

        from opens_suite.schematic_view import SchematicView
        target_view = SchematicView()
        try:
            target_view.load_schematic(path)
            return True, (target_view, True), "Loaded in background"
        except Exception as e:
            return False, None, f"Error loading schematic {path}: {e}"

    def _get_item_from_view(self, lib, cell, view, instance_name):
        """Helper to find an item in a view, considering active tabs or loading from disk."""
        success, res, info = self._get_view_obj(lib, cell, view)
        if not success:
            return False, None, info

        view_obj, is_temp = res

        from opens_suite.schematic_item import SchematicItem
        for item in view_obj.scene().items():
            if isinstance(item, SchematicItem) and item.name == instance_name:
                return True, (view_obj, item, is_temp), "Found item"

        return False, None, f"Error: Instance '{instance_name}' not found in {lib}/{cell}/{view}"

    def tool_debug_mcp_state(self) -> Dict[str, Any]:
        tabs = self.main_window.tabs
        count = tabs.count()
        index = tabs.currentIndex()

        tab_info = []
        for i in range(count):
            w = tabs.widget(i)
            tab_info.append({
                "index": i,
                "title": tabs.tabText(i),
                "type": type(w).__name__,
                "filename": getattr(w, "filename", None),
                "is_current": (i == index)
            })

        return {
            "version": "2026-03-13-1640",
            "project_dir": getattr(self.main_window, "project_dir", "None"),
            "tabs_count": count,
            "current_index": index,
            "tabs": tab_info,
            "active_calculators": len(getattr(self.main_window, "active_calculators", []))
        }

    def tool_get_connected_nets(self, lib, cell, view, instance_name):
        path = self._resolve_path(lib, cell, view)
        if not path:
            return {}

        from opens_suite.schematic_view import SchematicView
        from opens_suite.netlister import NetlistGenerator

        temp_view = SchematicView()
        temp_view.load_schematic(path)

        analyses = []
        if hasattr(self.main_window, "analysis_dock"):
            analyses = self.main_window.analysis_dock.get_all_analyses()

        variables = []
        if hasattr(self.main_window, "variables_dock"):
            variables = self.main_window.variables_dock.get_variables()

        gen = NetlistGenerator(temp_view.scene(), analyses, variables=variables)
        gen.generate()

        from opens_suite.schematic_item import SchematicItem
        target_item = None
        for item in temp_view.scene().items():
            if isinstance(item, SchematicItem) and item.name == instance_name:
                target_item = item
                break

        if not target_item:
            return {}

        connections = {}
        for pin_id in target_item.pins:
            node = gen.item_node_map.get((target_item, pin_id), "0")
            connections[pin_id] = node

        return connections

    def tool_get_current_netlist(self):
        view = self.main_window.tabs.currentWidget()
        if not hasattr(view, "scene"):
            return "Error: Current tab is not a schematic"

        from opens_suite.netlister import NetlistGenerator

        analyses = []
        if hasattr(self.main_window, "analysis_dock"):
            analyses = self.main_window.analysis_dock.get_all_analyses()

        outputs = []
        if hasattr(self.main_window, "outputs_dock"):
            outputs = self.main_window.outputs_dock.get_expressions_data()

        variables = []
        if hasattr(self.main_window, "variables_dock"):
            variables = self.main_window.variables_dock.get_variables()

        logger.info(f"[DIAG] tool_get_current_netlist: analyses={len(analyses)}, outputs={len(outputs)}, variables={len(variables)}")
        gen = NetlistGenerator(view.scene(), analyses, outputs=outputs, variables=variables)
        return gen.generate()

    def tool_add_output_expression(self, expression):
        if hasattr(self.main_window, "outputs_dock"):
            self.main_window.outputs_dock.add_expression(expression)
            return f"Added expression: {expression}"
        return "Error: Outputs dock not available"

    def tool_get_output_expressions(self) -> List[Dict[str, Any]]:
        if hasattr(self.main_window, "outputs_dock"):
            return self.main_window.outputs_dock.get_expressions_data()
        return []

    def tool_update_output_expression(self, index, **kwargs) -> str:
        if not hasattr(self.main_window, "outputs_dock"):
            return "Error: Outputs dock not available"

        dock = self.main_window.outputs_dock
        if 0 <= index < dock.model.rowCount():
            # Translate min_spec/max_spec from tool to min/max in widget
            if "min_spec" in kwargs: kwargs["min"] = kwargs.pop("min_spec")
            if "max_spec" in kwargs: kwargs["max"] = kwargs.pop("max_spec")

            changed = dock.update_expression(index, **kwargs)
            if changed:
                return f"Updated expression at index {index}"
            else:
                return f"No changes made to expression at index {index}"
        return f"Error: Expression index {index} out of range (0-{dock.model.rowCount()-1})"

    def _resolve_path(self, lib: str, cell: str, view: str) -> Optional[str]:
        # Logic to find the actual file path from lib/cell/view
        # Check library search paths
        search_paths = []
        default_lib = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "libraries")
        if os.path.exists(default_lib):
            search_paths.append(default_lib)

        from PyQt6.QtCore import QSettings
        settings = QSettings("OpenS", "OpenS")
        paths_str = settings.value("library_search_paths", "")
        for p in paths_str.split(","):
            p = p.strip()
            if p and os.path.exists(p):
                search_paths.append(p)

        project_dir = getattr(self.main_window, "project_dir", os.getcwd())
        if project_dir not in search_paths:
            search_paths.append(project_dir)

        # Basic view name to filename mapping
        view_map = {
            "schematic": ["schematic.svg", "schematic.sch.svg"],
            "symbol": ["symbol.svg", "symbol.sym.svg"]
        }

        for base in search_paths:
            lib_path = os.path.join(base, lib)
            if os.path.isdir(lib_path):
                cell_path = os.path.join(lib_path, cell)
                if os.path.isdir(cell_path):
                    # Try direct filename
                    v_path = os.path.join(cell_path, view)
                    if os.path.exists(v_path) and not os.path.isdir(v_path):
                        return v_path

                    # Try mapped names
                    if view in view_map:
                        for candidate in view_map[view]:
                            v_path = os.path.join(cell_path, candidate)
                            if os.path.exists(v_path):
                                return v_path

                    # Try view with .svg
                    v_path = os.path.join(cell_path, f"{view}.svg")
                    if os.path.exists(v_path):
                        return v_path
        return None

    def _resolve_cell_path(self, lib: str, cell: str) -> Optional[str]:
        # Find where the library is to get the cell path
        project_dir = getattr(self.main_window, "project_dir", os.getcwd())
        # We generally write new cells to project_dir or existing libs
        # For simplicity, let's assume we copy into project_dir if it's a new library or existing one there

        search_paths = [project_dir]
        from PyQt6.QtCore import QSettings
        settings = QSettings("OpenS", "OpenS")
        paths_str = settings.value("library_search_paths", "")
        for p in paths_str.split(","):
            p = p.strip()
            if p and os.path.exists(p):
                search_paths.append(p)

        for base in search_paths:
            lib_path = os.path.join(base, lib)
            if os.path.isdir(lib_path):
                return os.path.join(lib_path, cell)

        # If library doesn't exist, create it in project_dir?
        lib_path = os.path.join(project_dir, lib)
        if not os.path.exists(lib_path):
            os.makedirs(lib_path)
        return os.path.join(lib_path, cell)

    def tool_get_api_documentation(self, class_name: str) -> str:
        """Expose API documentation for key classes."""
        import opens_suite.stimuli.stimuli as stimuli_mod
        import opens_suite.design_points as dp_mod
        import inspect

        docs = {
            "Stimuli": stimuli_mod.Stimuli.__doc__,
            "DesignPoints": dp_mod.DesignPoints.__doc__
        }

        if class_name not in docs:
            return f"No documentation found for '{class_name}'. Available: {list(docs.keys())}"

        # Enhance with method list
        cls = stimuli_mod.Stimuli if class_name == "Stimuli" else dp_mod.DesignPoints
        method_docs = []

        # Get instance methods
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
             if not name.startswith("_"):
                 try:
                     sig = inspect.signature(member)
                     method_docs.append(f"- `{name}{sig}`: {member.__doc__ or 'No docstring'}")
                 except Exception:
                     method_docs.append(f"- `{name}(...)`: {member.__doc__ or 'No docstring'}")

        # Get static methods
        for name, member in inspect.getmembers(cls, predicate=lambda x: isinstance(x, staticmethod)):
             func = member.__func__
             if not name.startswith("_"):
                 try:
                     sig = inspect.signature(func)
                     method_docs.append(f"- `static {name}{sig}`: {func.__doc__ or 'No docstring'}")
                 except Exception:
                     method_docs.append(f"- `static {name}(...)`: {func.__doc__ or 'No docstring'}")

        api_doc = f"## {class_name} API\n\n{docs[class_name] or 'No class docstring'}\n\n### Methods\n" + "\n".join(method_docs)
        return api_doc

    def tool_read_notebook(self, lib: str, cell: str, view: str, notebook_path: str) -> str:
        """Read a notebook's content."""
        abs_path = self._resolve_path(lib, cell, view)
        if not abs_path:
            return f"Error: Could not find cell {lib}/{cell}/{view}"

        nb_file = os.path.join(os.path.dirname(abs_path), notebook_path)
        if not os.path.exists(nb_file):
            return f"Error: Notebook {notebook_path} not found in {lib}/{cell}"

        try:
            with open(nb_file, 'r') as f:
                return f.read()
        except Exception as e:
            return f"Error reading notebook: {e}"

    def tool_append_notebook_code(self, lib: str, cell: str, view: str, notebook_path: str, code: str) -> str:
        """Append a code cell to a notebook."""
        import json
        abs_path = self._resolve_path(lib, cell, view)
        if not abs_path:
            return f"Error: Could not find cell {lib}/{cell}/{view}"

        nb_file = os.path.join(os.path.dirname(abs_path), notebook_path)

        nb_data = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
        if os.path.exists(nb_file):
            try:
                with open(nb_file, 'r') as f:
                    nb_data = json.load(f)
            except Exception as e:
                return f"Error reading existing notebook: {e}"

        new_cell = {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": code.splitlines(keepends=True) if "\n" in code else [code]
        }
        nb_data["cells"].append(new_cell)

        try:
            with open(nb_file, "w") as f:
                json.dump(nb_data, f, indent=1)
            return f"Appended new code cell to {notebook_path}"
        except Exception as e:
            return f"Error writing notebook: {e}"

    def tool_update_notebook_cell(self, lib: str, cell: str, view: str, notebook_path: str, index: int, code: str) -> str:
        """Update a specific cell in a notebook."""
        import json
        abs_path = self._resolve_path(lib, cell, view)
        if not abs_path:
            return f"Error: Could not find cell {lib}/{cell}/{view}"

        nb_file = os.path.join(os.path.dirname(abs_path), notebook_path)
        if not os.path.exists(nb_file):
            return f"Error: Notebook {notebook_path} not found"

        try:
            with open(nb_file, 'r') as f:
                nb_data = json.load(f)
        except Exception as e:
            return f"Error reading notebook: {e}"

        if index < 0 or index >= len(nb_data.get("cells", [])):
            return f"Error: Cell index {index} out of range (total cells: {len(nb_data.get('cells', []))})"

        nb_data["cells"][index]["source"] = code.splitlines(keepends=True) if "\n" in code else [code]

        try:
            with open(nb_file, "w") as f:
                json.dump(nb_data, f, indent=1)
            return f"Updated cell {index} in {notebook_path}"
        except Exception as e:
            return f"Error writing notebook: {e}"

    def _parse_path(self, path: str) -> Dict[str, str]:
        # Reverse of resolve_path
        # path is /some/where/lib/cell/view.svg
        logger.info(f"[DIAG] _parse_path input: {path}")
        parts = path.split(os.sep)
        if len(parts) >= 3:
            view_file = parts[-1]
            cell = parts[-2]
            lib = parts[-3]

            view = view_file
            if view_file in ["schematic.svg", "schematic.sch.svg"]:
                view = "schematic"
            elif view_file in ["symbol.svg", "symbol.sym.svg"]:
                view = "symbol"
            else:
                view = os.path.splitext(view_file)[0]

            res = {"lib": lib, "cell": cell, "view": view, "path": path}
            logger.info(f"[DIAG] _parse_path returning: {res}")
            return res

        res = {"path": path}
        logger.info(f"[DIAG] _parse_path (fallback) returning: {res}")
        return res
