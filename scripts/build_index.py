"""Validate catalog records and regenerate catalog/INDEX.md."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "tool.schema.json"
TOOLS_DIR = ROOT / "catalog" / "tools"
INDEX_PATH = ROOT / "catalog" / "INDEX.md"
README_PATH = ROOT / "README.md"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def expect_type(value, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def validate_node(value, schema: dict, path: str, errors: list[str]) -> None:
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is outside {schema['enum']}")
        return
    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(expect_type(value, item) for item in expected):
            errors.append(f"{path}: expected {' or '.join(expected)}")
        return
    if expected and not expect_type(value, expected):
        errors.append(f"{path}: expected {expected}")
        return
    if expected == "string":
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            errors.append(f"{path}: shorter than {minimum}")
        pattern = schema.get("pattern")
        if pattern:
            import re

            if re.fullmatch(pattern, value) is None:
                errors.append(f"{path}: does not match {pattern}")
    if expected == "integer" or expected == "number":
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above {schema['maximum']}")
    if expected == "array":
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            errors.append(f"{path}: fewer than {minimum} items")
        if schema.get("uniqueItems") and len(value) != len(set(map(repr, value))):
            errors.append(f"{path}: duplicate items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_node(item, item_schema, f"{path}[{index}]", errors)
    if expected == "object":
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            for key in extra:
                errors.append(f"{path}.{key}: unexpected field")
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: missing")
        for key, item in value.items():
            if key in properties:
                validate_node(item, properties[key], f"{path}.{key}", errors)


def validate_record(record: dict, schema: dict, filename: str) -> list[str]:
    errors: list[str] = []
    validate_node(record, schema, filename, errors)
    package_id = record.get("package_id")
    if package_id and Path(filename).stem != package_id:
        errors.append(f"{filename}: file name must match package_id {package_id}")
    registration = record.get("registration")
    if isinstance(registration, list) and "none" in registration and len(registration) > 1:
        errors.append(f"{filename}: registration 'none' cannot be combined with other methods")
    return errors


def load_records(schema: dict) -> list[dict]:
    paths = sorted(TOOLS_DIR.glob("*.yaml"))
    if not paths:
        raise SystemExit(f"No records in {TOOLS_DIR}")
    records = []
    errors: list[str] = []
    seen: set[str] = set()
    for path in paths:
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            errors.append(f"{path.name}: record must be a mapping")
            continue
        errors.extend(validate_record(record, schema, path.name))
        package_id = record.get("package_id")
        if isinstance(package_id, str):
            if package_id in seen:
                errors.append(f"{path.name}: duplicate package_id")
            seen.add(package_id)
        records.append(record)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        raise SystemExit(1)
    return records


def display_name(record: dict, name_counts: Counter) -> str:
    title = record["play_store_name"]
    installed = record["installed_name"]
    if name_counts[title] > 1 and installed != title:
        return f"{title} ({installed})"
    return title


def html_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def tool_table(records: list[dict]) -> str:
    name_counts = Counter(record["play_store_name"] for record in records)
    ordered = sorted(records, key=lambda item: display_name(item, name_counts).casefold())
    rows = []
    for record in ordered:
        icon = record.get("icon_url")
        icon_html = (
            f'<img src="{html_text(icon)}" alt="" width="64" height="64">'
            if icon
            else ""
        )
        name = html_text(display_name(record, name_counts))
        url = html_text(record["play_store_url"])
        rows.append(
            "<tr>"
            f'<td width="64">{icon_html}</td>'
            f"<td>{name}</td>"
            f'<td><a href="{url}">{url}</a></td>'
            "</tr>"
        )
    return "\n".join(
        [
            "<table>",
            "<thead>",
            "<tr>",
            '<th width="64"></th>',
            '<th align="left">App Name</th>',
            '<th align="left">URL</th>',
            "</tr>",
            "</thead>",
            "<tbody>",
            *rows,
            "</tbody>",
            "</table>",
        ]
    )


def render_index(records: list[dict]) -> str:
    lines = [
        "# Caller OSINT",
        "",
        "Caller-ID and reverse-phone apps for OSINT investigators.",
        "",
        "## Mobile tools",
        "",
        tool_table(records),
        "",
    ]
    return "\n".join(lines)


def render_readme(records: list[dict]) -> str:
    lines = [
        "# Caller OSINT",
        "",
        "Caller-ID and reverse-phone apps for OSINT investigators.",
        "",
        "## Mobile tools",
        "",
        tool_table(records),
        "",
        "Test notes stay in [`catalog/tools/`](catalog/tools/). After editing a record, run `python scripts/build_index.py`.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    schema = load_schema()
    records = load_records(schema)
    INDEX_PATH.write_text(render_index(records), encoding="utf-8")
    README_PATH.write_text(render_readme(records), encoding="utf-8")
    print(f"Validated {len(records)} records and wrote the GitHub pages")


if __name__ == "__main__":
    main()
