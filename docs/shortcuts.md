# Keyboard & Mouse Shortcuts

OpenS is designed for high-efficiency schematic entry and simulation. Mastering these shortcuts will significantly speed up your design workflow.

## Navigation & View

| Action | Shortcut |
| :--- | :--- |
| **Zoom In/Out** | `Ctrl` + `Mouse Wheel` (or `Cmd` on Mac) |
| **Zoom In/Out (Native)** | `Pinch Gesture` |
| **Pan View** | `Middle Mouse Click` + `Drag` |
| **Zoom to Rectangle** | `Right Mouse Click` + `Drag` |
| **Zoom to Fit** | `F` |

## Editor Modes

| Mode | Shortcut | Description |
| :--- | :--- | :--- |
| **Select Mode** | `Esc` | Default mode. Used for selecting, moving, and editing items. |
| **Wire Mode** | `W` | Start drawing electrical connections between pins. |
| **Move Mode** | `M` | Quickly move components or wire segments. |
| **Copy Mode** | `C` | Create copies of selected items. |
| **Line Mode** | `L` | Add non-electrical annotation lines (graphics). |
| **Probe Mode** | `Space` | Select a net and send its name to the [Calculator](calculator.md). |

## Item Transformations

First, select one or more items in the schematic.

| Action | Shortcut |
| :--- | :--- |
| **Rotate (90°)** | `R` |
| **Horizontal Mirror** | `E` |
| **Delete Selection** | `Delete` or `Backspace` |
| **Undo** | `Ctrl + Z` |
| **Redo** | `Ctrl + Shift + Z` |

## Simulation & Tools

| Action | Shortcut |
| :--- | :--- |
| **Netlist Generation** | `F4` |
| **Run Simulation (Xyce)** | `F5` |
| **Open Calculator** | `?` |

## File Operations

| Action | Shortcut |
| :--- | :--- |
| **New Schematic** | `Ctrl + N` |
| **Save Schematic** | `Ctrl + S` |
| **Exit Application** | `Ctrl + Q` |

## Component Quick-Placement (Bindkeys)

You can quickly place common components by pressing `Shift` + `Letter`. These are defined in the symbol metadata:

- **Resistor**: `Shift + R` (Default)
- **Capacitor**: `Shift + C` (Default)
- **Ground**: `Shift + G` (Default)

*Note: Custom symbols in your libraries can define their own bindkeys.*
