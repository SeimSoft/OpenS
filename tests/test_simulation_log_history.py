from PyQt6.QtCore import Qt

from opens_suite.view.simulation_log_widget import SimulationLogWidget


def _submit_command(qtbot, widget, command):
    widget.input_edit.setText(command)
    qtbot.keyClick(widget.input_edit, Qt.Key.Key_Return)


def test_simulation_log_history_up_down_navigation(qtbot):
    widget = SimulationLogWidget()
    qtbot.addWidget(widget)
    widget.show()

    _submit_command(qtbot, widget, "first")
    _submit_command(qtbot, widget, "second")

    widget.input_edit.setText("draft")

    qtbot.keyClick(widget.input_edit, Qt.Key.Key_Up)
    assert widget.input_edit.text() == "second"

    qtbot.keyClick(widget.input_edit, Qt.Key.Key_Up)
    assert widget.input_edit.text() == "first"

    qtbot.keyClick(widget.input_edit, Qt.Key.Key_Down)
    assert widget.input_edit.text() == "second"

    qtbot.keyClick(widget.input_edit, Qt.Key.Key_Down)
    assert widget.input_edit.text() == "draft"
