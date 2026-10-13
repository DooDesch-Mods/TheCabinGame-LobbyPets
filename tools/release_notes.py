"""Use the selected CHANGELOG section for release bodies and Discord notes."""
from pathlib import Path
import re


def section(version, root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8-sig")
    headings = list(re.finditer(r"^## (?:\[([^]\n]+)\]|([^ \n]+))[^\n]*$", text, re.M))
    matches = [index for index, heading in enumerate(headings) if (heading.group(1) or heading.group(2)) == version]
    if len(matches) != 1:
        raise ValueError(f"CHANGELOG.md has {len(matches)} sections for {version}; expected exactly one")
    index = matches[0]
    end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
    notes = text[headings[index].end():end].strip()
    if not notes or not re.search(r"^- \S", notes, re.M):
        raise ValueError(f"CHANGELOG.md has no user changes for {version}")
    return notes


def body(version, root=None):
    return f"## Changes in {version}\n\n{section(version, root)}\n\n" + (
        "For manual installation and requirements, see README.md in the ZIP."
        "\n"
    )


def nexus(version, root=None):
    notes = section(version, root)
    notes = re.sub(r"^### (.+)$", r"[b]\1[/b]", notes, flags=re.M)
    lines = []
    in_list = False
    for line in notes.splitlines():
        if line.startswith("- "):
            if not in_list:
                lines.append("[list]")
                in_list = True
            lines.append("[*]" + line[2:])
        else:
            if in_list:
                lines.append("[/list]")
                in_list = False
            lines.append(line)
    if in_list:
        lines.append("[/list]")
    return "\n".join(lines)
