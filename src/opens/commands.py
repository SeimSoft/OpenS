from PyQt6.QtGui import QUndoCommand
from PyQt6.QtCore import QPointF
from opens.wire import Wire


class InsertItemsCommand(QUndoCommand):
    def __init__(self, scene, items, parent=None):
        super().__init__("Insert Items", parent)
        self.scene = scene
        self.items = items if isinstance(items, list) else [items]

    def redo(self):
        for item in self.items:
            if item.scene() != self.scene:
                self.scene.addItem(item)

    def undo(self):
        for item in self.items:
            self.scene.removeItem(item)


class RemoveItemsCommand(QUndoCommand):
    def __init__(self, scene, items, parent=None):
        super().__init__("Delete Items", parent)
        self.scene = scene
        self.items = items if isinstance(items, list) else [items]

    def redo(self):
        for item in self.items:
            self.scene.removeItem(item)

    def undo(self):
        for item in self.items:
            self.scene.addItem(item)


class MoveItemsCommand(QUndoCommand):
    def __init__(self, moving_items, delta, rubber_band_wires=None, parent=None):
        """
        moving_items: list of items that were moved by delta
        delta: QPointF, total translation
        rubber_band_wires: list of (wire, old_line, new_line) tuples for wires that stretched
        """
        super().__init__("Move Items", parent)
        self.moving_items = moving_items
        self.delta = delta
        self.rubber_band_wires = rubber_band_wires or []

    def redo(self):
        # Apply move
        for item in self.moving_items:
            item.moveBy(self.delta.x(), self.delta.y())

        # Apply rubber band updates
        for wire, _, new_line in self.rubber_band_wires:
            wire.setLine(new_line)

    def undo(self):
        # Revert move
        for item in self.moving_items:
            item.moveBy(-self.delta.x(), -self.delta.y())

        # Revert rubber band updates
        for wire, old_line, _ in self.rubber_band_wires:
            wire.setLine(old_line)


class CreateWireCommand(QUndoCommand):
    def __init__(self, scene, p1, p2, parent=None):
        super().__init__("Create Wire", parent)
        self.scene = scene
        self.p1 = p1
        self.p2 = p2
        self.wire = None

    def redo(self):
        if not self.wire:
            self.wire = Wire(self.p1, self.p2)
        self.scene.addItem(self.wire)

    def undo(self):
        self.scene.removeItem(self.wire)


class TransformItemsCommand(QUndoCommand):
    def __init__(self, items, old_state, new_state, parent=None):
        """Apply arbitrary transform/position changes to items.

        old_state/new_state: dict mapping item -> (pos, transform matrix tuple)
        transform matrix tuple: (m11, m12, m21, m22, dx, dy)
        """
        super().__init__("Transform Items", parent)
        self.items = items
        self.old_state = old_state
        self.new_state = new_state

    def _apply_state(self, state):
        from PyQt6.QtGui import QTransform
        from opens.wire import Wire

        for item in self.items:
            if item not in state:
                continue
            data = state[item]
            # data can be (pos, transform_vals) OR (pos, transform_vals, line)
            pos = data[0]
            tvals = data[1]
            line = data[2] if len(data) > 2 else None

            item.setPos(pos)
            if tvals is not None:
                m11, m12, m21, m22, dx, dy = tvals
                t = QTransform(m11, m12, m21, m22, dx, dy)
                item.setTransform(t)

            if line is not None and hasattr(item, "setLine"):
                item.setLine(line)

    def redo(self):
        self._apply_state(self.new_state)

    def undo(self):
        self._apply_state(self.old_state)
