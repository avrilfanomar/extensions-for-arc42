"""The concept modules never depend on the AsciiDoc binding."""

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "arc42ext"
CONCEPT_MODULES = ["model", "dates", "catalog", "links", "triggers"]


def imported_modules(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


class TestLayering(unittest.TestCase):

    def test_concept_modules_do_not_import_the_binding(self):
        for module in CONCEPT_MODULES:
            with self.subTest(module=module):
                names = imported_modules(PACKAGE / f"{module}.py")
                self.assertFalse(any("binding" in name for name in names), names)


if __name__ == "__main__":
    unittest.main()
