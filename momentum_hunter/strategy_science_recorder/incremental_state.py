"""Small immutable views for process-local, rebuildable Science state."""
from collections.abc import Mapping, Sequence
from copy import deepcopy


def _height(node):
    return node[4] if node else 0


def _size(node):
    return node[5] if node else 0


def _node(key, value, left=None, right=None):
    return (key, value, left, right, 1 + max(_height(left), _height(right)), 1 + _size(left) + _size(right))


def _right(tree):
    pivot = tree[2]
    return _node(pivot[0], pivot[1], pivot[2], _node(tree[0], tree[1], pivot[3], tree[3]))


def _left(tree):
    pivot = tree[3]
    return _node(pivot[0], pivot[1], _node(tree[0], tree[1], tree[2], pivot[2]), pivot[3])


def _set(tree, key, value):
    if tree is None:
        return _node(key, value)
    old_key, old_value, left, right, _h, _n = tree
    if key == old_key:
        return _node(key, value, left, right)
    if key < old_key:
        left = _set(left, key, value)
    else:
        right = _set(right, key, value)
    result = _node(old_key, old_value, left, right)
    balance = _height(left) - _height(right)
    if balance > 1:
        if _height(left[2]) < _height(left[3]):
            result = _node(old_key, old_value, _left(left), right)
        return _right(result)
    if balance < -1:
        if _height(right[3]) < _height(right[2]):
            result = _node(old_key, old_value, left, _right(right))
        return _left(result)
    return result


class StreamHeads(Mapping):
    """Persistent AVL map: immutable snapshots, O(log streams) point updates."""
    def __init__(self, root=None):
        self._root = root

    def set(self, key, value):
        if not isinstance(key, str) or not isinstance(value, tuple):
            raise TypeError('Stream heads require immutable string/tuple entries.')
        return StreamHeads(_set(self._root, key, value))

    def __getitem__(self, key):
        node = self._root
        while node:
            if key == node[0]:
                return node[1]
            node = node[2] if key < node[0] else node[3]
        raise KeyError(key)

    def __iter__(self):
        stack = []
        node = self._root
        while node or stack:
            while node:
                stack.append(node)
                node = node[2]
            node = stack.pop()
            yield node[0]
            node = node[3]

    def __len__(self):
        return _size(self._root)


class PublicHistory(Sequence):
    """Read-only length-frozen history; explicit access pays materialization cost.

    Normal poll receipts expose this view, not a growing copied list. Use
    list(view) or the full historical coverage API for JSON/export/audit.
    """
    def __init__(self, items):
        self._items = items
        self._length = len(items)

    def __len__(self):
        return self._length

    def __getitem__(self, key):
        if isinstance(key, slice):
            return [self[i] for i in range(*key.indices(self._length))]
        if key < 0:
            key += self._length
        if not 0 <= key < self._length:
            raise IndexError(key)
        return deepcopy(self._items[key])

    def __eq__(self, other):
        if not isinstance(other, Sequence):
            return False
        return len(self) == len(other) and all(a == b for a, b in zip(self, other))
