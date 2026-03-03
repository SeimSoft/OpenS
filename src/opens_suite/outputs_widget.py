from PyQt6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QTableView,
    QMenu,
    QMessageBox,
    QAbstractItemView,
    QHeaderView,
    QStyledItemDelegate,
    QStyle,
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor, QBrush
import traceback
import numpy as np
import os
from opens_suite.design_points import DesignPoints


class ValueColumnDelegate(QStyledItemDelegate):
    """Delegate to prevent selection highlight from obscuring the background color."""

    def paint(self, painter, option, index):
        # Clear selected state so background color always shows
        option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, option, index)


class OutputsWidget(QDockWidget):
    expressionPlotTriggered = pyqtSignal(str)
    expressionCalculatorTriggered = pyqtSignal(str)
    expressionsChanged = pyqtSignal()
    bulkPlotTriggered = pyqtSignal(list)

    COL_NAME = 0
    COL_EXPR = 1
    COL_VALUE = 2
    COL_UNIT = 3
    COL_MIN = 4
    COL_MAX = 5

    def __init__(self, parent=None):
        super().__init__("Output Expressions", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        container = QWidget()
        layout = QVBoxLayout(container)

        self.table_view = QTableView()
        self.model = QStandardItemModel(0, 6)
        self.model.setHorizontalHeaderLabels(
            ["Name", "Expression", "Value", "Unit", "Min Spec", "Max Spec"]
        )

        self.table_view.setModel(self.model)
        self.table_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_context_menu)
        self.table_view.doubleClicked.connect(self._on_item_double_clicked)

        # Apply delegate to Value column
        self.value_delegate = ValueColumnDelegate()
        self.table_view.setItemDelegateForColumn(self.COL_VALUE, self.value_delegate)

        # Adjust headers
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_EXPR, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_VALUE, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_UNIT, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_MIN, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_MAX, QHeaderView.ResizeMode.Interactive)

        layout.addWidget(self.table_view)
        layout.setContentsMargins(2, 2, 2, 2)
        self.setWidget(container)

        self.model.itemChanged.connect(self._on_item_changed)
        self._last_raw_path = None
        self._results_cache = {}  # name -> result_object

    def add_expression(self, expression, min_spec="", max_spec="", name="", unit=""):
        if not expression and not name:
            return

        row = self.model.rowCount()
        item_name = QStandardItem(str(name))
        item_expr = QStandardItem(str(expression))
        item_value = QStandardItem("")
        item_value.setEditable(False)
        # Make value cell non-selectable so selection highlight doesn't override its background
        item_value.setFlags(item_value.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        item_unit = QStandardItem(str(unit))

        item_min = QStandardItem(str(min_spec))
        item_max = QStandardItem(str(max_spec))

        self.model.appendRow(
            [item_name, item_expr, item_value, item_unit, item_min, item_max]
        )

        if self._last_raw_path:
            self.evaluate_row(row, self._last_raw_path)

        self.expressionsChanged.emit()

    def get_expressions_data(self):
        """Returns complex data including specs."""
        data = []
        for i in range(self.model.rowCount()):
            data.append(
                {
                    "name": self.model.item(i, self.COL_NAME).text(),
                    "expression": self.model.item(i, self.COL_EXPR).text(),
                    "unit": self.model.item(i, self.COL_UNIT).text(),
                    "min": self.model.item(i, self.COL_MIN).text(),
                    "max": self.model.item(i, self.COL_MAX).text(),
                }
            )
        return data

    def get_expressions(self):
        """Legacy support for simple string list."""
        return [
            self.model.item(i, self.COL_EXPR).text()
            for i in range(self.model.rowCount())
        ]

    def clear(self):
        self.model.removeRows(0, self.model.rowCount())

    def restore_expressions(self, expressions):
        self.clear()
        for expr in expressions:
            if isinstance(expr, dict):
                self.add_expression(
                    expr.get("expression", ""),
                    expr.get("min", ""),
                    expr.get("max", ""),
                    expr.get("name", ""),
                    expr.get("unit", ""),
                )
            else:
                self.add_expression(expr)

    def evaluate_all(self, raw_path):
        self._last_raw_path = raw_path
        if not raw_path or not os.path.exists(raw_path):
            return

        from opens_suite.calculator_widget import CalculatorDialog

        try:
            temp_calc = CalculatorDialog(raw_path)
            scope = temp_calc._create_scope()
            self._results_cache.clear()

            rows_to_eval = list(range(self.model.rowCount()))

            # Iterative evaluation to resolve inter-expression dependencies
            for pass_num in range(10):
                if not rows_to_eval:
                    break

                # Add current cache to scope at the start of each pass
                scope.update(self._results_cache)

                newly_evaluated = []
                for row in rows_to_eval:
                    success, result, val_str, val_float = self._evaluate_row_internal(
                        row, raw_path, scope
                    )
                    if success:
                        newly_evaluated.append(row)
                        # Update UI
                        item_value = self.model.item(row, self.COL_VALUE)
                        item_value.setText(val_str)
                        self._apply_spec_coloring(row, val_float)

                        # Inject into scope and cache if name is valid identifier
                        name = self.model.item(row, self.COL_NAME).text().strip()
                        if name and name.isidentifier():
                            self._results_cache[name] = result
                            scope[name] = result

                if not newly_evaluated:
                    # No progress - circular dependency or actual errors
                    break

                for row in newly_evaluated:
                    rows_to_eval.remove(row)

            # Mark remaining failed rows
            for row in rows_to_eval:
                self.model.item(row, self.COL_VALUE).setText("Eval Error")
                self.model.item(row, self.COL_VALUE).setBackground(QBrush())

        except Exception as e:
            print(f"Error evaluating outputs: {e}")

    def evaluate_row(self, row, raw_path, scope=None):
        """Wrapper for single-row evaluation (e.g. on item change)."""
        if scope is None:
            from opens_suite.calculator_widget import CalculatorDialog

            try:
                temp_calc = CalculatorDialog(raw_path)
                scope = temp_calc._create_scope()
                # Include existing results from other rows
                scope.update(self._results_cache)
            except Exception:
                return

        success, result, val_str, val_float = self._evaluate_row_internal(
            row, raw_path, scope
        )
        item_value = self.model.item(row, self.COL_VALUE)
        if success:
            item_value.setText(val_str)
            self._apply_spec_coloring(row, val_float)

            # Update cache
            name = self.model.item(row, self.COL_NAME).text().strip()
            if name and name.isidentifier():
                self._results_cache[name] = result
        else:
            item_value.setText(f"Error: {result}")
            item_value.setBackground(QBrush())

    def _evaluate_row_internal(self, row, raw_path, scope):
        """Returns (success, result_obj, val_str, val_float)"""
        import ast

        expression = self.model.item(row, self.COL_EXPR).text()
        if not expression:
            return False, None, "", None

        try:
            # Helper to execute multi-line and get last value
            def exec_get_last(code, l_scope):
                tree = ast.parse(code)
                if not tree.body:
                    return None

                last_node = tree.body[-1]
                if isinstance(last_node, ast.Expr):
                    if len(tree.body) > 1:
                        exec_body = ast.Module(body=tree.body[:-1], type_ignores=[])
                        exec(compile(exec_body, "<string>", "exec"), l_scope)

                    eval_expr = ast.Expression(body=last_node.value)
                    return eval(compile(eval_expr, "<string>", "eval"), l_scope)
                else:
                    exec(code, l_scope)
                    return None

            result = exec_get_last(expression, scope)

            # Format result
            val_str = ""
            val_float = None

            if isinstance(result, (int, float, np.number)):
                val_float = float(result)
                val_str = DesignPoints._format_si(val_float)
            elif isinstance(result, np.ndarray) and result.size == 1:
                val_float = float(result.item())
                val_str = DesignPoints._format_si(val_float)
            else:
                val_str = str(result)

            return True, result, val_str, val_float

        except Exception as e:
            return False, e, str(e), None

    def get_results_scope(self):
        """Returns a copy of the current results cache for use in calculator."""
        return dict(self._results_cache)

    def _apply_spec_coloring(self, row, val_float):
        item_value = self.model.item(row, self.COL_VALUE)
        if val_float is None:
            item_value.setBackground(QBrush())  # No color if not numeric
            return

        min_str = self.model.item(row, self.COL_MIN).text()
        max_str = self.model.item(row, self.COL_MAX).text()

        try:
            low_str = min_str.strip()
            high_str = max_str.strip()

            if not low_str and not high_str:
                item_value.setBackground(QBrush())
                return

            low = float(low_str) if low_str else -float("inf")
            high = float(high_str) if high_str else float("inf")

            if low <= val_float <= high:
                item_value.setBackground(QColor("#ccffcc"))  # Light green
            else:
                item_value.setBackground(QColor("#ffcccc"))  # Light red
        except Exception:
            item_value.setBackground(QBrush())

    def _on_item_changed(self, item):
        column = item.column()
        row = item.row()

        if column in [self.COL_MIN, self.COL_MAX]:
            # Re-check current value against new specs
            val_item = self.model.item(row, self.COL_VALUE)
            if val_item and self._last_raw_path:
                # Re-evaluate all because specs might depend on other rows too in future?
                # For now just re-eval all to be safe and consistent.
                self.evaluate_all(self._last_raw_path)

        if (
            column == self.COL_EXPR
            or column == self.COL_NAME
            or column == self.COL_UNIT
        ):
            if self._last_raw_path:
                self.evaluate_all(self._last_raw_path)
            self.expressionsChanged.emit()

    def _show_context_menu(self, position):
        selection = self.table_view.selectionModel().selectedRows()
        if not selection:
            return

        menu = QMenu()
        if len(selection) == 1:
            row = selection[0].row()
            expr = self.model.item(row, self.COL_EXPR).text()

            plot_action = menu.addAction("Plot")
            send_action = menu.addAction("Send to Calculator")
            menu.addSeparator()
            remove_action = menu.addAction("Remove")
        else:
            plot_all_action = menu.addAction(f"Plot Selected ({len(selection)})")
            menu.addSeparator()
            remove_all_action = menu.addAction(f"Remove Selected ({len(selection)})")

        action = menu.exec(self.table_view.viewport().mapToGlobal(position))
        if not action:
            return

        if len(selection) == 1:
            row = selection[0].row()
            expr = self.model.item(row, self.COL_EXPR).text()
            if action.text() == "Plot":
                self.expressionPlotTriggered.emit(expr)
            elif action.text() == "Send to Calculator":
                self.expressionCalculatorTriggered.emit(expr)
            elif action.text() == "Remove":
                self.model.removeRow(row)
                self.expressionsChanged.emit()
        else:
            if action.text().startswith("Plot Selected"):
                expressions = [
                    self.model.item(idx.row(), self.COL_EXPR).text()
                    for idx in selection
                ]
                self.bulkPlotTriggered.emit(expressions)
            elif action.text().startswith("Remove Selected"):
                rows = sorted([idx.row() for idx in selection], reverse=True)
                for row in rows:
                    self.model.removeRow(row)
                self.expressionsChanged.emit()

    def _on_item_double_clicked(self, index: QModelIndex):
        if index.isValid() and index.column() == self.COL_EXPR:
            self.expressionPlotTriggered.emit(index.data())
