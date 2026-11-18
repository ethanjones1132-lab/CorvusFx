"""Resolve APVTS defaults backed by the FX factory preset table (CV-070)."""
import re


def factory_default(code, member):
    """Read the `p.<member>` default from comment-stripped PluginProcessor.cpp."""
    startup = re.search(
        r"::createParameterLayout\s*\(\s*\)\s*\{\s*"
        r"const\s+auto\s*&\s*p\s*=\s*factoryPreset\s*\(\s*(\d+)\s*\)\s*;", code)
    schema = re.search(r"\bstruct\s+P\s*\{\s*float\s+([^;{}]+);\s*\}", code)
    table = re.search(
        r"\bconst\s+P\s*&\s*factoryPreset\s*\(\s*int\s+index\s*\)\s*\{\s*"
        r"static\s+const\s+P\s+presets\s*\[\s*\d+\s*\]\s*=\s*\{(.*?)\}\s*;"
        r"\s*return\s+presets\s*\[\s*index\s*\]\s*;", code, re.S)
    if not (startup and schema and table):
        raise ValueError("could not read the layout's factory preset binding, fields or table")

    index = int(startup.group(1))
    fields = [field.strip() for field in schema.group(1).split(",")]
    rows = re.findall(r"\{([^{}]*)\}", table.group(1))
    if index >= len(rows):
        raise ValueError(f"factory preset {index} has no explicit row")
    values = [value.strip() for value in rows[index].split(",")]
    if len(values) != len(fields) or fields.count(member) != 1:
        raise ValueError(f"could not locate field {member!r} in factory preset {index}")

    value = values[fields.index(member)]
    try:
        return float(value.rstrip("fF"))
    except ValueError:
        raise ValueError(
            f"factory preset {index} field {member!r} is not numeric: {value!r}") from None
