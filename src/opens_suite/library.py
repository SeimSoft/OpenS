import os
import xml.etree.ElementTree as ET
from PyQt6.QtWidgets import (
    QDockWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QFrame,
    QMenu,
    QInputDialog,
    QMessageBox,
    QHBoxLayout,
    QPushButton,
    QStyle,
)
from PyQt6.QtCore import Qt, QMimeData, QSize, QRectF, QUrl
from PyQt6.QtGui import (
    QDrag,
    QIcon,
    QPixmap,
    QPainter,
    QColor,
    QBrush,
    QPen,
    QDesktopServices,
)
from PyQt6.QtSvg import QSvgRenderer


class LibraryWidget(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Library Browser", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.project_dir = (
            getattr(parent, "project_dir", os.getcwd()) if parent else os.getcwd()
        )
        self.bindkey_map = {}

        container = QWidget()
        layout = QVBoxLayout(container)

        search_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.textChanged.connect(self.filter_items)
        search_layout.addWidget(self.search_bar)

        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.refresh_btn.setToolTip("Reload Libraries")
        self.refresh_btn.clicked.connect(self._populate_library)
        search_layout.addWidget(self.refresh_btn)

        layout.addLayout(search_layout)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Libraries"])
        self.tree_widget.setDragEnabled(True)
        self.tree_widget.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree_widget.itemSelectionChanged.connect(self._update_preview)
        self.tree_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.tree_widget.startDrag = self.start_drag
        layout.addWidget(self.tree_widget)

        preview_container = QFrame()
        preview_container.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        preview_container.setMinimumHeight(150)
        preview_layout = QVBoxLayout(preview_container)

        self.preview_label = QLabel("Select a view")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.preview_label)

        layout.addWidget(QLabel("Preview:"))
        layout.addWidget(preview_container)

        self.setWidget(container)
        self._populate_library()

    def filter_items(self, text):
        search_text = text.lower()

        def apply_filter(item):
            match = search_text in item.text(0).lower()
            child_match = False
            for i in range(item.childCount()):
                child = item.child(i)
                if apply_filter(child):
                    child_match = True

            is_visible = match or child_match
            if not search_text:
                is_visible = True

            item.setHidden(not is_visible)

            if search_text and child_match:
                item.setExpanded(True)

            return is_visible

        for i in range(self.tree_widget.topLevelItemCount()):
            apply_filter(self.tree_widget.topLevelItem(i))

    def _update_preview(self):
        selected = self.tree_widget.selectedItems()
        if not selected:
            self.preview_label.setText("Select a view")
            self.preview_label.setPixmap(QPixmap())
            return

        item = selected[0]
        path = item.data(0, Qt.ItemDataRole.UserRole)
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        node_path = item.data(0, Qt.ItemDataRole.UserRole + 2)

        if node_type == "REPORT":
            self.preview_label.setText("HTML Report")
            self.preview_label.setPixmap(QPixmap())
            return

        # If it's a CELL, try to find a symbol view for preview
        if node_type == "CELL" and node_path and os.path.isdir(node_path):
            sym_path = os.path.join(node_path, "symbol.svg")
            if os.path.exists(sym_path):
                path = sym_path
            else:
                # Try any svg in the folder
                for f in os.listdir(node_path):
                    if f.endswith(".svg"):
                        path = os.path.join(node_path, f)
                        break

        if not path or not os.path.exists(path) or os.path.isdir(path):
            self.preview_label.setText(item.text(0))
            self.preview_label.setPixmap(QPixmap())
            return

        renderer = QSvgRenderer(path)
        if renderer.isValid():
            pixmap = QPixmap(140, 140)
            pixmap.fill(Qt.GlobalColor.white)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            self.preview_label.setPixmap(pixmap)
            self.preview_label.setText("")
        else:
            self.preview_label.setText("Invalid preview")

    def _get_or_create_node(
        self, parent_item, text, path_data=None, node_type=None, node_path=None
    ):
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            if child.text(0) == text:
                if path_data and not child.data(0, Qt.ItemDataRole.UserRole):
                    child.setData(0, Qt.ItemDataRole.UserRole, path_data)
                return child
        item = QTreeWidgetItem(parent_item, [text])
        if path_data:
            item.setData(0, Qt.ItemDataRole.UserRole, path_data)
        if node_type:
            item.setData(0, Qt.ItemDataRole.UserRole + 1, node_type)
        if node_path:
            item.setData(0, Qt.ItemDataRole.UserRole + 2, node_path)
        return item

    def _populate_library(self):
        self.tree_widget.clear()

        # Placeholder for new library
        self.new_lib_item = QTreeWidgetItem(
            self.tree_widget, ["[+ Create New Library...]"]
        )
        self.new_lib_item.setData(0, Qt.ItemDataRole.UserRole + 1, "NEW_LIB")
        font = self.new_lib_item.font(0)
        font.setItalic(True)
        self.new_lib_item.setFont(0, font)

        from PyQt6.QtCore import QSettings

        settings = QSettings("OpenS", "OpenS")
        paths_str = settings.value("library_search_paths", "")
        search_paths = []

        default_lib = os.path.join(os.path.dirname(__file__), "assets", "libraries")
        if os.path.exists(default_lib):
            search_paths.append(default_lib)

        for p in paths_str.split(","):
            p = p.strip()
            if p and os.path.exists(p) and p not in search_paths:
                search_paths.append(p)

        if os.path.exists(self.project_dir) and self.project_dir not in search_paths:
            search_paths.append(self.project_dir)

        # Iterate all search paths
        for base_path in search_paths:
            for lib_name in sorted(os.listdir(base_path)):
                lib_path = os.path.join(base_path, lib_name)
                # Ignore common non-library folders
                if (
                    lib_name.startswith(".")
                    or lib_name == "simulation"
                    or not os.path.isdir(lib_path)
                    or lib_name == "src"
                ):
                    continue

                if os.path.exists(os.path.join(lib_path, "index.html")):
                    report_item = QTreeWidgetItem(
                        self.tree_widget, [f"📝 {lib_name} (Report)"]
                    )
                    report_item.setData(0, Qt.ItemDataRole.UserRole + 1, "REPORT")
                    report_item.setData(0, Qt.ItemDataRole.UserRole + 2, lib_path)
                    report_item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        os.path.join(lib_path, "index.html"),
                    )
                    font = report_item.font(0)
                    font.setBold(True)
                    report_item.setFont(0, font)
                    report_item.setForeground(0, QBrush(QColor("#005A9C")))
                    continue

                lib_item = QTreeWidgetItem(self.tree_widget, [lib_name])
                lib_item.setData(0, Qt.ItemDataRole.UserRole + 1, "LIB")
                lib_item.setData(0, Qt.ItemDataRole.UserRole + 2, lib_path)
                lib_item.setExpanded(lib_name == "opensLib")

                for root, dirs, files in os.walk(lib_path):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]

                    # Handle empty cell directories natively so they appear before files are added
                    if root == lib_path:
                        for d in dirs:
                            cell_path = os.path.join(root, d)
                            if not os.listdir(cell_path):  # if directory is empty
                                self._get_or_create_node(
                                    lib_item,
                                    d,
                                    node_type="CELL",
                                    node_path=cell_path,
                                    path_data=cell_path,  # Keep a reference path even if it's just a dir to avoid None issues
                                )

                    for file in sorted(files):
                        if file.endswith(".svg"):
                            svg_path = os.path.join(root, file)
                            rel_path = os.path.relpath(svg_path, lib_path)
                            parts = rel_path.split(os.sep)

                            # We expect at least Cell/View.svg or Category/Cell/View.svg
                            if len(parts) >= 2:
                                view_filename = parts[-1]
                                view_name = view_filename.replace(".svg", "").replace(
                                    ".sym", ""
                                )
                                cell_name = parts[-2]
                                cell_path = os.path.dirname(svg_path)

                                category_from_xml = None
                                try:
                                    tree = ET.parse(svg_path)
                                    root_xml = tree.getroot()
                                    for elem in root_xml.iter():
                                        if (
                                            elem.tag.endswith("}symbol")
                                            or elem.tag == "opens:symbol"
                                        ):
                                            bind = elem.get("bindkey")
                                            if bind:
                                                self.bindkey_map[bind.lower()] = (
                                                    svg_path
                                                )
                                            if svg_path.endswith("symbol.svg"):
                                                category_from_xml = elem.get("category")
                                                if category_from_xml == "Uncategorized":
                                                    category_from_xml = None
                                            break

                                    # Always fetch category from symbol.svg if not this file
                                    if not category_from_xml and not svg_path.endswith(
                                        "symbol.svg"
                                    ):
                                        symbol_path = os.path.join(
                                            cell_path, "symbol.svg"
                                        )
                                        if os.path.exists(symbol_path):
                                            try:
                                                tree_sym = ET.parse(symbol_path)
                                                for elem in tree_sym.getroot().iter():
                                                    if (
                                                        elem.tag.endswith("}symbol")
                                                        or elem.tag == "opens:symbol"
                                                    ):
                                                        cat = elem.get("category")
                                                        if (
                                                            cat
                                                            and cat != "Uncategorized"
                                                        ):
                                                            category_from_xml = cat
                                                        break
                                            except Exception:
                                                pass

                                except Exception:
                                    pass

                                category_name = None
                                if len(parts) > 2:
                                    category_name = "/".join(parts[:-2])
                                elif category_from_xml:
                                    category_name = category_from_xml

                                parent_node = lib_item
                                # Prefer XML category if one level deep
                                if category_name:
                                    for cat_part in category_name.split("/"):
                                        parent_node = self._get_or_create_node(
                                            parent_node, cat_part, node_type="CATEGORY"
                                        )

                                cell_item = self._get_or_create_node(
                                    parent_node,
                                    cell_name,
                                    node_type="CELL",
                                    node_path=cell_path,
                                    path_data=svg_path,
                                )
                                view_item = self._get_or_create_node(
                                    cell_item, view_name, svg_path, node_type="VIEW"
                                )
                                view_item.setToolTip(0, svg_path)

                            elif len(parts) == 1:
                                # Top level SVG in library treated as a cell with the same name
                                cell_name = file.replace(".svg", "").replace(".sym", "")
                                view_name = (
                                    "schematic"
                                    if "schematic" in file.lower()
                                    else "symbol"
                                )
                                cell_item = self._get_or_create_node(
                                    lib_item,
                                    cell_name,
                                    node_type="CELL",
                                    node_path=svg_path,
                                )
                                view_item = self._get_or_create_node(
                                    cell_item, view_name, svg_path, node_type="VIEW"
                                )

    def _on_item_double_clicked(self, item, column):
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if node_type == "NEW_LIB":
            self._create_new_library()
            return
        elif node_type == "REPORT":
            index_path = item.data(0, Qt.ItemDataRole.UserRole)
            QDesktopServices.openUrl(QUrl.fromLocalFile(index_path))
            return

        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            main_window = self.window()
            if hasattr(main_window, "open_file"):
                main_window.open_file(path)

    def _create_new_library(self):
        name, ok = QInputDialog.getText(self, "New Library", "Library Name:")
        if ok and name:
            lib_path = os.path.join(self.project_dir, name)
            if not os.path.exists(lib_path):
                try:
                    os.makedirs(lib_path)
                    self._populate_library()
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to create library: {e}")
            else:
                QMessageBox.warning(self, "Error", "Library already exists!")

    def _on_context_menu(self, pos):
        item = self.tree_widget.itemAt(pos)
        if not item:
            return

        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        node_path = item.data(0, Qt.ItemDataRole.UserRole + 2)

        menu = QMenu(self.tree_widget)

        if node_type == "LIB":
            action = menu.addAction("Create New Cell...")
            action.triggered.connect(lambda: self._create_new_cell(node_path))
        elif node_type == "CELL":
            sch_action = menu.addAction("Create Schematic View...")
            sch_action.triggered.connect(
                lambda: self._create_new_view(node_path, "schematic")
            )
            sym_action = menu.addAction("Create Symbol View...")
            sym_action.triggered.connect(
                lambda: self._create_new_view(node_path, "symbol")
            )

        if node_path or item.data(0, Qt.ItemDataRole.UserRole):
            p = node_path or item.data(0, Qt.ItemDataRole.UserRole)
            if p and os.path.exists(p):
                menu.addSeparator()
                browse_action = menu.addAction(
                    "Show in Finder"
                    if os.uname().sysname == "Darwin"
                    else "Open in File Browser"
                )
                browse_action.triggered.connect(lambda: self._open_in_finder(p))

        if not menu.isEmpty():
            menu.exec(self.tree_widget.viewport().mapToGlobal(pos))

    def _open_in_finder(self, path):
        if os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _create_new_cell(self, lib_path):
        name, ok = QInputDialog.getText(self, "New Cell", "Cell Name:")
        if ok and name:
            cell_path = os.path.join(lib_path, name)
            if not os.path.exists(cell_path):
                try:
                    os.makedirs(cell_path)
                    self._populate_library()
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to create cell: {e}")
            else:
                QMessageBox.warning(self, "Error", "Cell already exists!")

    def _create_new_view(self, cell_path, view_type):
        view_name, ok = QInputDialog.getText(
            self, f"New {view_type.capitalize()} View", "View Name:", text=view_type
        )
        if ok and view_name:
            if not view_name.endswith(".svg"):
                view_name += ".svg"

            view_path = os.path.join(cell_path, view_name)
            if not os.path.exists(view_path):
                try:
                    # Create empty SVG structure
                    with open(view_path, "w") as f:
                        if view_type == "schematic":
                            f.write(
                                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600"></svg>'
                            )
                        else:
                            f.write(
                                '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"></svg>'
                            )

                    self._populate_library()
                    main_window = self.window()
                    if hasattr(main_window, "open_file"):
                        main_window.open_file(view_path)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to create view: {e}")
            else:
                QMessageBox.warning(self, "Error", "View already exists!")

    def start_drag(self, supported_actions):
        selected = self.tree_widget.selectedItems()
        if not selected:
            return
        item = selected[0]
        path = item.data(0, Qt.ItemDataRole.UserRole)
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        node_path = item.data(0, Qt.ItemDataRole.UserRole + 2)

        # If it's a CELL, check for symbol.svg
        if node_type == "CELL" and node_path and os.path.isdir(node_path):
            sym_path = os.path.join(node_path, "symbol.svg")
            if os.path.exists(sym_path):
                path = sym_path
            else:
                # Cannot drag cell without symbol
                return

        if not path:
            return

        mime_data = QMimeData()
        mime_data.setText(path)

        drag = QDrag(self.tree_widget)
        drag.setMimeData(mime_data)

        pixmap = QPixmap(40, 40)
        pixmap.fill(Qt.GlobalColor.lightGray)
        painter = QPainter(pixmap)
        painter.drawText(0, 20, item.text(0)[:5])
        painter.end()
        drag.setPixmap(pixmap)

        drag.exec(Qt.DropAction.CopyAction)

    def get_symbol_by_bindkey(self, key):
        return self.bindkey_map.get(key.lower())
