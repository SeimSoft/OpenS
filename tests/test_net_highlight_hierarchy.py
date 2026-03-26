from types import SimpleNamespace

from PyQt6.QtCore import QPointF

from opens_suite.main_window import MainWindow
from opens_suite.schematic_item import SchematicItem
from opens_suite.wire import Wire
from opens_suite.view.events import EventsMixin


class _DummyMainWindow:
    _full_net_name = staticmethod(MainWindow._full_net_name)
    _item_matches_instance_name = staticmethod(MainWindow._item_matches_instance_name)
    _derive_child_highlight_context = MainWindow._derive_child_highlight_context
    _derive_child_pin_parent_nets = MainWindow._derive_child_pin_parent_nets


class _DummyEvents(EventsMixin):
    def __init__(self):
        self.last_item_to_node = {}
        self._scene = SimpleNamespace(items=lambda: [])

    def scene(self):
        return self._scene


def test_derive_child_highlight_names_maps_parent_net_to_child_pin(tmp_path):
    svg_path = tmp_path / "symbol.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    inst_item = SchematicItem(str(svg_path))
    inst_item.name = "XU1"

    parent_view = SimpleNamespace(
        hierarchy_prefix="",
        last_item_to_node={(inst_item, "IN"): "VIN"},
    )

    mw = _DummyMainWindow()
    mw._net_highlight_full_names = {"VIN"}

    out = MainWindow._derive_child_highlight_names(mw, parent_view, "XU1", "XU1:")

    assert "XU1:IN" in out


def test_derive_child_highlight_names_respects_parent_hierarchy_prefix(tmp_path):
    svg_path = tmp_path / "symbol.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    inst_item = SchematicItem(str(svg_path))
    inst_item.name = "XCHILD"

    parent_view = SimpleNamespace(
        hierarchy_prefix="TOP:",
        last_item_to_node={(inst_item, "OUT"): "NET_A"},
    )

    mw = _DummyMainWindow()
    mw._net_highlight_full_names = {"TOP:NET_A"}

    out = MainWindow._derive_child_highlight_names(
        mw, parent_view, "XCHILD", "TOP:XCHILD:"
    )

    assert "TOP:XCHILD:OUT" in out


def test_derive_child_highlight_context_includes_pin_ids(tmp_path):
    svg_path = tmp_path / "symbol.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    inst_item = SchematicItem(str(svg_path))
    inst_item.name = "XU5"

    parent_view = SimpleNamespace(
        hierarchy_prefix="",
        last_item_to_node={(inst_item, "P2"): "N_BUS"},
    )

    mw = _DummyMainWindow()
    mw._net_highlight_full_names = {"N_BUS"}

    names, pin_ids = MainWindow._derive_child_highlight_context(
        mw, parent_view, "XU5", "XU5:"
    )

    assert "XU5:P2" in names
    assert "P2" in pin_ids


def test_get_wire_net_name_prefers_wire_name_over_instance_pin_mapping():
    ev = _DummyEvents()
    w = Wire(QPointF(0, 0), QPointF(10, 0))
    w.name = "VIN"
    ev.last_item_to_node[w] = "X_3:P2"

    assert ev._get_wire_net_name(w) == "VIN"


def test_resolve_probe_net_from_pin_rejects_instance_pin_pseudo_name(tmp_path):
    svg_path = tmp_path / "symbol.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    ev = _DummyEvents()
    item = SchematicItem(str(svg_path))
    item.name = "X_3"
    ev.last_item_to_node[(item, "P2")] = "X_3:P2"

    out = ev._resolve_probe_net_from_pin(item, "P2", QPointF(0, 0))

    # Should not return the pseudo instance-pin token.
    assert out != "X_3:P2"


def test_canonical_probe_name_bridges_instance_pin_to_parent_net():
    ev = _DummyEvents()
    ev._child_pin_parent_nets = {"P2": "VIN_TOP"}

    assert ev._canonical_probe_net_name("X_3:P2") == "VIN_TOP"


def test_derive_child_pin_parent_nets_maps_instance_pins(tmp_path):
    svg_path = tmp_path / "symbol.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    inst_item = SchematicItem(str(svg_path))
    inst_item.name = "X_3"
    parent_view = SimpleNamespace(
        hierarchy_prefix="",
        last_item_to_node={(inst_item, "P2"): "VIN_TOP"},
    )

    mw = _DummyMainWindow()
    pin_map = MainWindow._derive_child_pin_parent_nets(mw, parent_view, "X_3")

    assert pin_map["P2"] == "VIN_TOP"


def test_instance_name_matching_accepts_x3_and_x_3(tmp_path):
    svg_path = tmp_path / "symbol.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    inst_item = SchematicItem(str(svg_path))
    inst_item.prefix = "X"
    inst_item.name = "X3"

    assert MainWindow._item_matches_instance_name(inst_item, "X_3")
