from PyQt6.QtGui import QKeySequence

from opens_suite.calculator_widget import CalculatorDialog


def test_calculator_save_shortcut_sends_to_outputs(qtbot, tmp_path):
    raw_path = tmp_path / "missing.raw"
    calc = CalculatorDialog(str(raw_path))
    qtbot.addWidget(calc)
    calc.show()

    expression = "plot(t, vt('vout'))"
    calc.script_edit.setPlainText(expression)
    calc.script_edit.setFocus()

    assert calc.send_to_outputs_action.shortcuts() == QKeySequence.keyBindings(
        QKeySequence.StandardKey.Save
    )

    with qtbot.waitSignal(calc.sendToOutputsRequested, timeout=1000) as blocker:
        calc.send_to_outputs_shortcut.activated.emit()

    assert blocker.args == [expression]
