from opens_suite.waveform_viewer import WaveformViewer


class _CursorStub:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


def test_measurement_text_uses_si_suffixes(qtbot):
    viewer = WaveformViewer()
    qtbot.addWidget(viewer)

    viewer.markers_data["A"] = (1.106e-07, 0.01863)
    viewer.markers_data["B"] = (6.087e-07, 3.285)
    viewer._update_measurements()

    text = viewer.measurements_text.toPlainText()

    assert "A: x=110.6n, y=18.63m" in text
    assert "B: x=608.7n, y=3.285" in text
    assert "Delta (B-A): dx=498.1n, dy=3.266" in text


def test_cursor_status_uses_si_suffixes(qtbot):
    viewer = WaveformViewer()
    qtbot.addWidget(viewer)

    viewer.cursors["A"] = _CursorStub(1.106e-07)
    viewer.cursors["B"] = _CursorStub(6.087e-07)

    viewer._update_cursor_readouts()
    status = viewer.status.currentMessage()

    assert "A: 110.6n" in status
    assert "B: 608.7n" in status
    assert "dX: 498.1n" in status
