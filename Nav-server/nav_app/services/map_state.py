"""Active map metadata helpers."""
from pathlib import Path

from nav_app.settings import ACTIVE_MAP_YAML
from nav_app.util.time import utc_now as _utc_now

def read_simple_yaml(path: Path):
    data = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def parse_yaml_scalar(value: str):
    value = value.strip().strip('"').strip("'")
    if value.startswith("[") and value.endswith("]"):
        return [float(part.strip()) for part in value[1:-1].split(",") if part.strip()]
    try:
        if any(ch in value for ch in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value


def read_pgm_size(path: Path):
    if not path.exists():
        return None, None
    tokens = []
    with path.open("rb") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith(b"#"):
                continue
            tokens.extend(line.split())
            if len(tokens) >= 3:
                break
    if len(tokens) < 3 or tokens[0] not in (b"P2", b"P5"):
        return None, None
    return int(tokens[1]), int(tokens[2])


def map_state_payload():
    yaml_path = ACTIVE_MAP_YAML
    yaml_data = read_simple_yaml(yaml_path)
    image = parse_yaml_scalar(yaml_data.get("image", "")) if yaml_data else None
    image_path = (yaml_path.parent / image).resolve() if image else None
    width, height = read_pgm_size(image_path) if image_path else (None, None)
    return {
        "active_map_id": yaml_path.stem,
        "frame_id": "map",
        "source": "nav2_map_server",
        "map_yaml": str(yaml_path),
        "map_yaml_exists": yaml_path.exists(),
        "image": image,
        "image_path": str(image_path) if image_path else None,
        "image_exists": bool(image_path and image_path.exists()),
        "resolution": parse_yaml_scalar(yaml_data.get("resolution", "")) if yaml_data.get("resolution") else None,
        "origin": parse_yaml_scalar(yaml_data.get("origin", "")) if yaml_data.get("origin") else None,
        "width": width,
        "height": height,
        "mode": parse_yaml_scalar(yaml_data.get("mode", "")) if yaml_data.get("mode") else None,
        "occupied_thresh": parse_yaml_scalar(yaml_data.get("occupied_thresh", "")) if yaml_data.get("occupied_thresh") else None,
        "free_thresh": parse_yaml_scalar(yaml_data.get("free_thresh", "")) if yaml_data.get("free_thresh") else None,
        "reported_at": _utc_now(),
    }
