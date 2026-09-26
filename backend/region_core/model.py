"""Coordinates are unrotated, CropBox-relative MuPDF points unless specified."""
import hashlib
import json
import math


def area(b):
    return max(0, b[2]-b[0])*max(0, b[3]-b[1])


def union(boxes):
    boxes = list(boxes)
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def intersect(a, b):
    return [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]


def expand(b, v):
    return [b[0]-v, b[1]-v, b[2]+v, b[3]+v]


def gap(a, b):
    return math.hypot(max(a[0]-b[2], b[0]-a[2], 0), max(a[1]-b[3], b[1]-a[3], 0))


def coverage(a, b):
    return area(intersect(a, b))/max(area(b), 1e-9)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def plain(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if type(value).__module__.startswith(('pymupdf', 'fitz')):
        return list(value)
    return value
