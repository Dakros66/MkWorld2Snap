"""Extract a lightweight render scene from a built 3MF archive."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


PROJECT_SETTINGS = "Metadata/project_settings.config"
MODEL_SETTINGS = "Metadata/model_settings.config"
MODEL_3D = "3D/3dmodel.model"
DEFAULT_COLOR = "#d8d5ce"


def build_preview_scene(path: Path, *, max_triangles: int = 700_000) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        project = _read_project_settings(archive)
        model_settings = _read_text(archive, MODEL_SETTINGS)
        plate_groups = _plate_object_groups(model_settings)
        object_meta = _object_metadata(model_settings)
        colors = _normalise_colors(project.get("filament_colour") or project.get("extruder_colour") or [])
        items = _build_items(archive)

        meshes: list[dict[str, Any]] = []
        total_triangles = 0
        truncated = False
        object_to_plate = {
            object_id: plate_id
            for plate_id, object_ids in plate_groups
            for object_id in object_ids
        }

        for item in items:
            meta = object_meta.get(item["id"], {})
            extruder = _int_or_none(meta.get("extruder"))
            base_color = _filament_color(colors, extruder)
            vertices, triangles, triangle_colors = _resolved_mesh(
                archive,
                MODEL_3D,
                item["id"],
                item["transform"],
                colors,
                base_color,
                {},
            )
            if not vertices or not triangles:
                continue
            if total_triangles + len(triangles) > max_triangles:
                remaining = max(0, max_triangles - total_triangles)
                triangles = triangles[:remaining]
                triangle_colors = triangle_colors[:remaining]
                truncated = True
            if not triangles:
                break
            total_triangles += len(triangles)
            meshes.append(
                {
                    "id": item["id"],
                    "name": meta.get("name") or f"Object {item['id']}",
                    "plate_id": object_to_plate.get(item["id"], 1),
                    "extruder": extruder,
                    "color": base_color,
                    "vertices": _flatten_vertices(vertices),
                    "indices": _flatten_triangles(triangles),
                    "triangle_colors": triangle_colors,
                }
            )
            if truncated:
                break

        bed = _bed_from_project(project)
        plates = _preview_plates(plate_groups, meshes, bed)
        bounds = _scene_bounds(meshes, plates)
        return {
            "printer_model": project.get("printer_model") or "Snapmaker U1",
            "print_settings_id": project.get("print_settings_id") or "",
            "bed": bed,
            "plates": plates,
            "meshes": meshes,
            "stats": {
                "objects": len(meshes),
                "triangles": total_triangles,
                "truncated": truncated,
                "max_triangles": max_triangles,
            },
            "bounds": bounds,
        }


def _read_text(archive: zipfile.ZipFile, name: str) -> str | None:
    if name not in archive.namelist():
        return None
    return archive.read(name).decode("utf-8", errors="replace")


def _read_project_settings(archive: zipfile.ZipFile) -> dict[str, Any]:
    text = _read_text(archive, PROJECT_SETTINGS)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_xml(text: str | None) -> ET.Element | None:
    if not text:
        return None
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return None


def _plate_object_groups(model_settings_xml: str | None) -> list[tuple[int, list[str]]]:
    root = _parse_xml(model_settings_xml)
    if root is None:
        return [(1, [])]
    groups: list[tuple[int, list[str]]] = []
    for fallback_id, plate in enumerate(root.findall(".//plate"), start=1):
        plate_id = fallback_id
        ids: list[str] = []
        for metadata in plate.findall("./metadata"):
            if metadata.get("key") == "plater_id":
                plate_id = _int_or_none(metadata.get("value")) or fallback_id
        for instance in plate.findall("./model_instance"):
            for metadata in instance.findall("./metadata"):
                if metadata.get("key") == "object_id" and metadata.get("value"):
                    ids.append(metadata.get("value", ""))
        groups.append((plate_id, ids))
    return groups or [(1, [])]


def _object_metadata(model_settings_xml: str | None) -> dict[str, dict[str, str]]:
    root = _parse_xml(model_settings_xml)
    if root is None:
        return {}
    result: dict[str, dict[str, str]] = {}
    for obj in root.findall(".//object"):
        object_id = obj.get("id")
        if not object_id:
            continue
        entry: dict[str, str] = {}
        for metadata in obj.findall("./metadata"):
            key = metadata.get("key")
            value = metadata.get("value")
            if key and value is not None:
                entry[key] = value
        result[object_id] = entry
    return result


def _normalise_colors(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return [DEFAULT_COLOR]
    colors = [value for value in values if isinstance(value, str) and value.startswith("#")]
    return colors or [DEFAULT_COLOR]


def _filament_color(colors: list[str], extruder: int | None) -> str:
    if extruder is not None and 1 <= extruder <= len(colors):
        return colors[extruder - 1]
    return colors[0] if colors else DEFAULT_COLOR


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _parse_transform(value: str | None) -> list[float]:
    if not value:
        return _identity()
    try:
        parts = [float(part) for part in value.split()]
    except ValueError:
        return _identity()
    return parts if len(parts) == 12 else _identity()


def _identity() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]


def _transform_point(point: tuple[float, float, float], matrix: list[float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        matrix[0] * x + matrix[3] * y + matrix[6] * z + matrix[9],
        matrix[1] * x + matrix[4] * y + matrix[7] * z + matrix[10],
        matrix[2] * x + matrix[5] * y + matrix[8] * z + matrix[11],
    )


def _compose(first: list[float], second: list[float]) -> list[float]:
    values: list[float] = []
    for col in range(3):
        x, y, z = second[col * 3], second[col * 3 + 1], second[col * 3 + 2]
        values.extend(
            [
                first[0] * x + first[3] * y + first[6] * z,
                first[1] * x + first[4] * y + first[7] * z,
                first[2] * x + first[5] * y + first[8] * z,
            ]
        )
    tx, ty, tz = _transform_point((second[9], second[10], second[11]), first)
    values.extend([tx, ty, tz])
    return values


def _build_items(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    root = ET.fromstring(archive.read(MODEL_3D))
    items: list[dict[str, Any]] = []
    for item in root.iter():
        if _xml_name(item.tag) != "item" or not item.get("objectid"):
            continue
        items.append({"id": item.get("objectid", ""), "transform": _parse_transform(item.get("transform"))})
    return items


def _model_objects(
    archive: zipfile.ZipFile,
    model_name: str,
    cache: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    if model_name in cache:
        return cache[model_name]
    try:
        root = ET.fromstring(archive.read(model_name))
    except Exception:
        cache[model_name] = {}
        return {}
    objects: dict[str, dict[str, Any]] = {}
    for obj in root.iter():
        if _xml_name(obj.tag) != "object" or not obj.get("id"):
            continue
        vertices: list[tuple[float, float, float]] = []
        triangles: list[tuple[int, int, int, str | None]] = []
        components: list[tuple[str | None, str | None, list[float]]] = []
        for child in obj.iter():
            if _xml_name(child.tag) == "vertex":
                try:
                    vertices.append((float(child.get("x", "0")), float(child.get("y", "0")), float(child.get("z", "0"))))
                except ValueError:
                    continue
            elif _xml_name(child.tag) == "triangle":
                try:
                    triangles.append(
                        (
                            int(child.get("v1", "0")),
                            int(child.get("v2", "0")),
                            int(child.get("v3", "0")),
                            _paint_color(child),
                        )
                    )
                except ValueError:
                    continue
            elif _xml_name(child.tag) == "component":
                path = None
                for key, value in child.attrib.items():
                    if key.endswith("path"):
                        path = value.lstrip("/")
                        break
                components.append((path, child.get("objectid"), _parse_transform(child.get("transform"))))
        objects[obj.get("id", "")] = {"vertices": vertices, "triangles": triangles, "components": components}
    cache[model_name] = objects
    return objects


def _paint_color(triangle: ET.Element) -> str | None:
    for key, value in triangle.attrib.items():
        if _xml_name(key) == "paint_color" and value:
            return value
    return None


def _resolved_mesh(
    archive: zipfile.ZipFile,
    model_name: str,
    object_id: str,
    transform: list[float],
    colors: list[str],
    fallback_color: str,
    cache: dict[str, dict[str, dict[str, Any]]],
    seen: set[tuple[str, str]] | None = None,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[str]]:
    visited = seen or set()
    if (model_name, object_id) in visited:
        return ([], [], [])
    visited.add((model_name, object_id))
    obj = _model_objects(archive, model_name, cache).get(object_id)
    if obj is None:
        return ([], [], [])

    vertices = [_transform_point(vertex, transform) for vertex in obj["vertices"]]
    triangles = [(a, b, c) for a, b, c, _paint in obj["triangles"]]
    triangle_colors = [_paint_to_color(paint, colors, fallback_color) for _a, _b, _c, paint in obj["triangles"]]

    for path, component_id, component_transform in obj["components"]:
        if not component_id:
            continue
        component_model = path or model_name
        nested_vertices, nested_triangles, nested_colors = _resolved_mesh(
            archive,
            component_model,
            component_id,
            _compose(transform, component_transform),
            colors,
            fallback_color,
            cache,
            visited,
        )
        offset = len(vertices)
        vertices.extend(nested_vertices)
        triangles.extend((a + offset, b + offset, c + offset) for a, b, c in nested_triangles)
        triangle_colors.extend(nested_colors)
    return (vertices, triangles, triangle_colors)


def _paint_to_color(value: str | None, colors: list[str], fallback: str) -> str:
    if not value:
        return fallback
    for token in value.split():
        index = _int_or_none(token)
        if index is None:
            continue
        if 0 <= index < len(colors):
            return colors[index]
        if 1 <= index <= len(colors):
            return colors[index - 1]
    return fallback


def _flatten_vertices(vertices: list[tuple[float, float, float]]) -> list[float]:
    return [coord for vertex in vertices for coord in vertex]


def _flatten_triangles(triangles: list[tuple[int, int, int]]) -> list[int]:
    return [index for triangle in triangles for index in triangle]


def _bed_from_project(project: dict[str, Any]) -> dict[str, float]:
    area = project.get("printable_area")
    xs: list[float] = []
    ys: list[float] = []
    if isinstance(area, list):
        for point in area:
            if not isinstance(point, str) or "x" not in point:
                continue
            x_text, y_text = point.split("x", 1)
            try:
                xs.append(float(x_text))
                ys.append(float(y_text))
            except ValueError:
                continue
    if not xs or not ys:
        return {"min_x": 0.0, "min_y": 0.0, "width": 270.0, "depth": 270.0}
    return {"min_x": min(xs), "min_y": min(ys), "width": max(xs) - min(xs), "depth": max(ys) - min(ys)}


def _preview_plates(groups: list[tuple[int, list[str]]], meshes: list[dict[str, Any]], bed: dict[str, float]) -> list[dict[str, Any]]:
    by_object = {mesh["id"]: _mesh_bounds(mesh) for mesh in meshes}
    plates: list[dict[str, Any]] = []
    for index, (plate_id, object_ids) in enumerate(groups or [(1, [])]):
        boxes = [by_object[object_id] for object_id in object_ids if object_id in by_object]
        if boxes and len(groups) > 1:
            min_x = min(box[0] for box in boxes)
            min_y = min(box[1] for box in boxes)
            max_x = max(box[3] for box in boxes)
            max_y = max(box[4] for box in boxes)
            origin_x = (min_x + max_x) / 2 - bed["width"] / 2
            origin_y = (min_y + max_y) / 2 - bed["depth"] / 2
        else:
            origin_x = bed["min_x"] + index * (bed["width"] + 36.0)
            origin_y = bed["min_y"]
        plates.append(
            {
                "id": plate_id,
                "origin": [origin_x, origin_y, 0.0],
                "size": [bed["width"], bed["depth"]],
                "object_ids": object_ids,
            }
        )
    return plates


def _mesh_bounds(mesh: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    vertices = mesh["vertices"]
    xs = vertices[0::3]
    ys = vertices[1::3]
    zs = vertices[2::3]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _scene_bounds(meshes: list[dict[str, Any]], plates: list[dict[str, Any]]) -> dict[str, list[float]]:
    boxes = [_mesh_bounds(mesh) for mesh in meshes]
    for plate in plates:
        x, y, z = plate["origin"]
        width, depth = plate["size"]
        boxes.append((x, y, z, x + width, y + depth, z))
    if not boxes:
        return {"min": [0, 0, 0], "max": [270, 270, 0]}
    return {
        "min": [min(box[0] for box in boxes), min(box[1] for box in boxes), min(box[2] for box in boxes)],
        "max": [max(box[3] for box in boxes), max(box[4] for box in boxes), max(box[5] for box in boxes)],
    }
