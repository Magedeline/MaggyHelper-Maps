"""
Celeste Map Binary (.bin) Parser and Writer

Implements the Celeste binary map format used by Lönn, Maple, and Everest.

Format structure:
  1. Header string ("CELESTE MAP")
  2. Package name string
  3. Lookup table (deduplicated sorted strings)
  4. Element tree (recursive: name + attributes + children)

Value type tags:
  0: bool, 1: uint8, 2: int16, 3: int32, 4: float32,
  5: lookup string, 6: raw string, 7: RLE-encoded string
"""

import struct
from pathlib import Path
from typing import Any


# ─── Binary Reader ────────────────────────────────────────────────────────────

class BinaryReader:
    """Sequential binary reader for Celeste .bin format."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read_byte(self) -> int:
        val = self._data[self._pos]
        self._pos += 1
        return val

    def read_ushort(self) -> int:
        val = struct.unpack_from('<H', self._data, self._pos)[0]
        self._pos += 2
        return val

    def read_short(self) -> int:
        val = struct.unpack_from('<h', self._data, self._pos)[0]
        self._pos += 2
        return val

    def read_int32(self) -> int:
        val = struct.unpack_from('<i', self._data, self._pos)[0]
        self._pos += 4
        return val

    def read_float(self) -> float:
        val = struct.unpack_from('<f', self._data, self._pos)[0]
        self._pos += 4
        return val

    def read_varint(self) -> int:
        result = 0
        shift = 0
        while True:
            b = self.read_byte()
            result |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break
        return result

    def read_string(self) -> str:
        length = self.read_varint()
        s = self._data[self._pos:self._pos + length].decode('utf-8')
        self._pos += length
        return s

    def read_bytes(self, n: int) -> bytes:
        data = self._data[self._pos:self._pos + n]
        self._pos += n
        return data


# ─── Binary Writer ────────────────────────────────────────────────────────────

class BinaryWriter:
    """Sequential binary writer for Celeste .bin format."""

    def __init__(self):
        self._parts: list[bytes] = []

    def write_byte(self, v: int):
        self._parts.append(bytes([v & 0xFF]))

    def write_ushort(self, v: int):
        self._parts.append(struct.pack('<H', v & 0xFFFF))

    def write_short(self, v: int):
        self._parts.append(struct.pack('<h', v))

    def write_int32(self, v: int):
        self._parts.append(struct.pack('<i', v))

    def write_float(self, v: float):
        self._parts.append(struct.pack('<f', v))

    def write_varint(self, v: int):
        while v > 127:
            self.write_byte((v & 0x7F) | 0x80)
            v >>= 7
        self.write_byte(v)

    def write_string(self, s: str):
        encoded = s.encode('utf-8')
        self.write_varint(len(encoded))
        self._parts.append(encoded)

    def write_raw(self, data: bytes):
        self._parts.append(data)

    def get_bytes(self) -> bytes:
        return b''.join(self._parts)


# ─── Run-Length Encoding ──────────────────────────────────────────────────────

def decode_rle(data: bytes) -> str:
    """Decode RLE tile data. Format: pairs of (count_byte, char_byte)."""
    chars = []
    i = 0
    while i + 1 < len(data):
        count = data[i]
        char = chr(data[i + 1])
        chars.append(char * count)
        i += 2
    return ''.join(chars)


def encode_rle(text: str) -> bytes:
    """RLE-encode a string. Format: pairs of (count_byte, char_byte)."""
    if not text:
        return b''
    parts: list[bytes] = []
    count = 1
    current = text[0]
    for ch in text[1:]:
        if ch != current or count == 255:
            parts.append(bytes([count, ord(current)]))
            count = 1
            current = ch
        else:
            count += 1
    parts.append(bytes([count, ord(current)]))
    return b''.join(parts)


# ─── Internal: Element I/O ────────────────────────────────────────────────────

# Keys that are structural metadata, not serialized as element attributes.
# NOTE: '_package' is intentionally NOT here — the root Map element stores
# _package as a real attribute in the binary (separate from the raw package
# string written before the lookup table). Skipping it would drop two strings
# from the lookup table and omit the attribute, corrupting the file.
_SKIP_KEYS = frozenset(('__name', '__children'))


def _read_value(r: BinaryReader, lookup: list[str]) -> Any:
    tag = r.read_byte()
    if tag == 0:
        return r.read_byte() != 0
    if tag == 1:
        return r.read_byte()
    if tag == 2:
        return r.read_short()
    if tag == 3:
        return r.read_int32()
    if tag == 4:
        return r.read_float()
    if tag == 5:
        idx = r.read_short()
        return lookup[idx]
    if tag == 6:
        return r.read_string()
    if tag == 7:
        rle_len = r.read_short()
        return decode_rle(r.read_bytes(rle_len))
    raise ValueError(f"Unknown value type tag: {tag}")


def _read_element(r: BinaryReader, lookup: list[str]) -> dict:
    name = lookup[r.read_ushort()]

    attr_count = r.read_byte()
    element: dict[str, Any] = {'__name': name}
    for _ in range(attr_count):
        key = lookup[r.read_ushort()]
        element[key] = _read_value(r, lookup)

    child_count = r.read_ushort()
    element['__children'] = [_read_element(r, lookup) for _ in range(child_count)]

    return element


def _collect_strings(element: dict, seen: set[str]):
    seen.add(element.get('__name', ''))
    for k, v in element.items():
        if k in _SKIP_KEYS:
            continue
        seen.add(k)
        if isinstance(v, str) and k != 'innerText':
            seen.add(v)
    for child in element.get('__children', []):
        _collect_strings(child, seen)


def _write_value(w: BinaryWriter, key: str, value: Any, lookup: dict[str, int]):
    if isinstance(value, bool):
        w.write_byte(0)
        w.write_byte(1 if value else 0)
    elif isinstance(value, float):
        w.write_byte(4)
        w.write_float(value)
    elif isinstance(value, int):
        if 0 <= value <= 255:
            w.write_byte(1)
            w.write_byte(value)
        elif -32768 <= value <= 32767:
            w.write_byte(2)
            w.write_short(value)
        elif -2147483648 <= value <= 2147483647:
            w.write_byte(3)
            w.write_int32(value)
        else:
            w.write_byte(4)
            w.write_float(float(value))
    elif isinstance(value, str):
        if key == 'innerText':
            rle = encode_rle(value)
            if len(rle) < len(value.encode('utf-8')) and len(rle) < 32767:
                w.write_byte(7)
                w.write_short(len(rle))
                w.write_raw(rle)
            else:
                w.write_byte(6)
                w.write_string(value)
        else:
            idx = lookup.get(value)
            if idx is not None:
                w.write_byte(5)
                w.write_short(idx)
            else:
                w.write_byte(6)
                w.write_string(value)
    else:
        w.write_byte(6)
        w.write_string(str(value))


def _write_element(w: BinaryWriter, element: dict, lookup: dict[str, int]):
    w.write_ushort(lookup[element.get('__name', '')])

    attrs = [(k, v) for k, v in element.items() if k not in _SKIP_KEYS]
    w.write_byte(len(attrs))
    for key, value in attrs:
        w.write_ushort(lookup[key])
        _write_value(w, key, value, lookup)

    children = element.get('__children', [])
    w.write_ushort(len(children))
    for child in children:
        _write_element(w, child, lookup)


# ─── Public API ───────────────────────────────────────────────────────────────

def read_map(path: str | Path) -> dict:
    """Read a Celeste .bin map file and return the element tree.

    Returns a dict with keys:
      __name: element name (e.g. "Map")
      __children: list of child elements
      _package: map package name
      + any attributes on the root element
    """
    data = Path(path).read_bytes()
    r = BinaryReader(data)

    header = r.read_string()
    if header != "CELESTE MAP":
        raise ValueError(f"Invalid header: '{header}' (expected 'CELESTE MAP')")

    package = r.read_string()

    lookup_count = r.read_ushort()
    lookup = [r.read_string() for _ in range(lookup_count)]

    root = _read_element(r, lookup)
    root['_package'] = package
    return root


def write_map(path: str | Path, data: dict, header: str = "CELESTE MAP"):
    """Write a Celeste .bin map file from an element tree."""
    seen: set[str] = set()
    _collect_strings(data, seen)

    strings = sorted(seen)
    lookup = {s: i for i, s in enumerate(strings)}

    w = BinaryWriter()
    w.write_string(header)
    w.write_string(data.get('_package', ''))

    w.write_ushort(len(strings))
    for s in strings:
        w.write_string(s)

    _write_element(w, data, lookup)
    Path(path).write_bytes(w.get_bytes())


# ─── Tree Navigation Helpers ──────────────────────────────────────────────────

def find_child(element: dict, name: str) -> dict | None:
    """Find the first direct child with the given __name."""
    for child in element.get('__children', []):
        if child.get('__name') == name:
            return child
    return None


def find_children(element: dict, name: str) -> list[dict]:
    """Find all direct children with the given __name."""
    return [c for c in element.get('__children', []) if c.get('__name') == name]


def get_rooms(map_data: dict) -> list[dict]:
    """Get all room (level) elements from a map."""
    levels = find_child(map_data, 'levels')
    if levels is None:
        return []
    return find_children(levels, 'level')


def get_room(map_data: dict, room_name: str) -> dict | None:
    """Find a room by name (with or without 'lvl_' prefix)."""
    for room in get_rooms(map_data):
        name = room.get('name', '')
        if name == room_name or name == f'lvl_{room_name}':
            return room
    return None
