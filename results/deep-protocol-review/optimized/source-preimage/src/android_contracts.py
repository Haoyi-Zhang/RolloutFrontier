"""Declaration-only bridge from a pinned, data-only AOSP API-history blob.

No Android code is executed. Presence of a selected class is not a behavioral
contract, device feature, or permission guarantee. Evaluation is limited to
API levels 1..25; the pinned history does not justify later-release absence.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

SOURCE = "https://android.googlesource.com/platform/development/+/a278b15cda8a07a97686370cb5e944fb4f6bc824/sdk/api-versions.xml"
BLOB = "16316e39d865c417a0fcd9c630861d9c8cc75efb"
SIZE = 3539324
SELECTED = {
    "api.base64": "android/util/Base64",
    "api.download-manager": "android/app/DownloadManager",
    "api.fragment": "android/app/Fragment",
    "api.camera-manager": "android/hardware/camera2/CameraManager",
}


def extract(raw: bytes) -> dict:
    """Authenticate exact Git object bytes before parsing selected class rows."""
    if not isinstance(raw, bytes) or len(raw) != SIZE:
        raise ValueError("pinned history byte length mismatch")
    digest = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    if digest != BLOB:
        raise ValueError("pinned history Git blob mismatch")
    # Digest verification admits one known document, not arbitrary XML/DTD.
    root = ET.fromstring(raw)
    if root.tag != "api" or root.attrib != {"version": "2"}:
        raise ValueError("unsupported history schema")
    rows = []
    for atom, name in sorted(SELECTED.items()):
        matches = [node for node in root.findall("class") if node.get("name") == name]
        if len(matches) != 1:
            raise ValueError("selected class absent/duplicate; absence is not a negative contract")
        node = matches[0]
        rows.append(dict(atom=atom, class_name=name, since=int(node.attrib["since"]),
                         removed=int(node.attrib["removed"]) if "removed" in node.attrib else None))
    return dict(source_url=SOURCE, git_blob=BLOB, source_bytes=SIZE,
                evaluation_api_range=[1, 25], contracts=rows)


def profile(declarations: dict, api_level: int) -> list[str]:
    """Project selected declaration availability only; never extrapolate."""
    if type(api_level) is not int or not 1 <= api_level <= 25:
        raise ValueError("API level outside pinned evaluation range 1..25")
    if (not isinstance(declarations, dict)
            or set(declarations) != {"source_url", "git_blob", "source_bytes", "evaluation_api_range", "contracts"}
            or declarations["source_url"] != SOURCE or declarations["git_blob"] != BLOB
            or type(declarations["source_bytes"]) is not int or declarations["source_bytes"] != SIZE
            or not isinstance(declarations["evaluation_api_range"], list)
            or any(type(value) is not int for value in declarations["evaluation_api_range"])
            or declarations["evaluation_api_range"] != [1, 25]):
        raise ValueError("invalid declaration provenance")
    rows = declarations["contracts"]
    if not isinstance(rows, list) or len(rows) != len(SELECTED):
        raise ValueError("invalid selected class inventory")
    seen, result = set(), []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"atom", "class_name", "since", "removed"}
                or not isinstance(row["atom"], str) or row["atom"] in seen
                or SELECTED.get(row["atom"]) != row["class_name"]
                or type(row["since"]) is not int or not 1 <= row["since"] <= 25
                or (row["removed"] is not None and
                    (type(row["removed"]) is not int or row["removed"] <= row["since"]))):
            raise ValueError("invalid declaration row")
        seen.add(row["atom"])
        if row["since"] <= api_level and (row["removed"] is None or api_level < row["removed"]):
            result.append(row["atom"])
    return sorted(result)
