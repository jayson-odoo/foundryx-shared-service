"""Magic-byte sniffing for every file Planner 3D stores. The stored type is the
sniffed one, never the client's claim. Pure functions; no I/O."""

from __future__ import annotations

import json
import re
import struct
from typing import Optional

MIME_PNG = "image/png"
MIME_JPEG = "image/jpeg"
MIME_WEBP = "image/webp"
MIME_GLB = "model/gltf-binary"
MIME_GLTF = "model/gltf+json"
MIME_OBJ = "model/obj"
MIME_MTL = "model/mtl"
MIME_STL = "model/stl"
MIME_FBX = "application/octet-stream"
MIME_JSON = "application/json"

IMAGE_EXT = {MIME_PNG: "png", MIME_JPEG: "jpg", MIME_WEBP: "webp"}

_PNG = b"\x89PNG\r\n\x1a\n"
_FBX_BINARY = b"Kaydara FBX Binary  \x00"
_OBJ_LINE = re.compile(r"^(v|f)\s", re.MULTILINE)
_MTL_LINE = re.compile(r"^newmtl\s", re.MULTILINE)


def _text(data: bytes) -> Optional[str]:
    if not data or b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def is_png(data: bytes) -> bool:
    return data.startswith(_PNG)


def is_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff"


def is_webp(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def is_glb(data: bytes) -> bool:
    if len(data) < 20 or data[:4] != b"glTF":
        return False
    version, length = struct.unpack("<II", data[4:12])
    return version == 2 and length == len(data)


def is_gltf(data: bytes) -> bool:
    body = _text(data)
    if body is None:
        return False
    try:
        doc = json.loads(body)
    except ValueError:
        return False
    return isinstance(doc, dict) and isinstance(doc.get("asset"), dict)


def is_obj(data: bytes) -> bool:
    body = _text(data)
    return body is not None and _OBJ_LINE.search(body) is not None


def is_mtl(data: bytes) -> bool:
    body = _text(data)
    return body is not None and _MTL_LINE.search(body) is not None


def is_stl(data: bytes) -> bool:
    if len(data) > 84:
        triangles = struct.unpack("<I", data[80:84])[0]
        if len(data) == 84 + 50 * triangles:
            return True
    body = _text(data)
    return body is not None and body.lstrip().startswith("solid") and "facet" in body


def is_fbx(data: bytes) -> bool:
    return data.startswith(_FBX_BINARY) or data[:64].lstrip().startswith(b"; FBX")


def is_json(data: bytes) -> bool:
    body = _text(data)
    if body is None:
        return False
    try:
        return isinstance(json.loads(body), (dict, list))
    except ValueError:
        return False


def sniff_image(data: bytes) -> Optional[str]:
    """The mime of a PNG / JPEG / WebP, else None."""
    if is_png(data):
        return MIME_PNG
    if is_jpeg(data):
        return MIME_JPEG
    if is_webp(data):
        return MIME_WEBP
    return None


_CHECKS = {
    "glb": (is_glb, MIME_GLB),
    "gltf": (is_gltf, MIME_GLTF),
    "obj": (is_obj, MIME_OBJ),
    "mtl": (is_mtl, MIME_MTL),
    "stl": (is_stl, MIME_STL),
    "fbx": (is_fbx, MIME_FBX),
    "json": (is_json, MIME_JSON),
    "png": (is_png, MIME_PNG),
}


def sniff_for_name(name: str, data: bytes) -> Optional[str]:
    """The mime when ``data`` really is the type ``name``'s extension claims."""
    check = _CHECKS.get(name.rsplit(".", 1)[-1].lower())
    if check is None:
        return None
    ok, mime = check
    return mime if ok(data) else None
