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
        def open_view(lib: str, cell: str, view: str) -> str:
            """Open a specific view (schematic/symbol) in the editor."""
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

    # --- Tool Implementations (Internal) ---

    def tool_open_view(self, lib: str, cell: str, view: str) -> str:
        path = self._resolve_path(lib, cell, view)
        if not path:
            return f"Error: View '{view}' not found in {lib}/{cell}"
        
        if hasattr(self.main_window, "open_file"):
            self.main_window.open_file(path)
            return f"Opened {path}"
        return "Error: main_window.open_file not available"

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

    def _get_item_from_view(self, lib, cell, view, instance_name):
        """Helper to find an item in a view, considering active tabs or loading from disk."""
        path = self._resolve_path(lib, cell, view)
        if not path:
             return False, None, f"Error: View '{view}' not found in {lib}/{cell}"

        # Check if it's already open in a tab
        tabs = self.main_window.tabs
        target_view = None
        for i in range(tabs.count()):
            w = tabs.widget(i)
            if getattr(w, "filename", None) == path:
                target_view = w
                break
        
        is_temp = False
        if not target_view:
            from opens_suite.schematic_view import SchematicView
            target_view = SchematicView()
            try:
                target_view.load_schematic(path)
                is_temp = True
            except Exception as e:
                return False, None, f"Error loading schematic {path}: {e}"
            
        from opens_suite.schematic_item import SchematicItem
        for item in target_view.scene().items():
            if isinstance(item, SchematicItem) and item.name == instance_name:
                if is_temp:
                    return True, (target_view, item, True), "Found in background"
                else:
                    return True, (target_view, item, False), "Found in active tab"
        
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
