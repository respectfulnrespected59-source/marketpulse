"""The buyer packs must contain everything the app needs to actually run.

These exist because the manifest in tools/build_buyer_pack.py is a hand-kept
list, and it had already drifted: index.html loaded quickfill.js and
vendor/big.min.js, and neither shipped, so the pot tracker's amount control
and its money math were undefined in the delivered zip while working fine in
the repo. A test is the only thing that keeps a hand-kept list honest.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_buyer_pack  # noqa: E402

pytestmark = pytest.mark.unit

ALL_SHIPPED = set(build_buyer_pack.BASE) | set(build_buyer_pack.PRO_ONLY)


def _local_assets_in_index_html() -> set[str]:
    """Every same-origin src/href index.html pulls, as repo-relative paths."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    assets = set()
    for ref in refs:
        if ref.startswith(("http://", "https://", "//", "data:", "#")):
            continue
        assets.add(f"static/{ref.lstrip('/')}")
    return assets


def _local_modules_imported_by(module_path: Path) -> set[str]:
    """Top-level imports of modules that live in this repo."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module] if node.module else []
        else:
            continue
        for name in names:
            if name and (ROOT / f"{name.split('.')[0]}.py").is_file():
                found.add(f"{name.split('.')[0]}.py")
    return found


class TestManifestCoversTheApp:
    def test_every_script_index_html_loads_is_shipped(self):
        missing = sorted(a for a in _local_assets_in_index_html() if a not in ALL_SHIPPED)
        assert not missing, f"index.html references files the buyer never gets: {missing}"

    def test_every_local_module_app_imports_is_shipped(self):
        # A missing module here is worse than a missing asset: the app does not
        # start at all, it dies with ModuleNotFoundError on launch.
        imported = _local_modules_imported_by(ROOT / "app.py")
        missing = sorted(m for m in imported if m not in ALL_SHIPPED)
        assert not missing, f"app.py imports modules the buyer never gets: {missing}"

    def test_the_chart_ships(self):
        # The live chart is the headline feature of the paid edition.
        assert "static/chart.js" in build_buyer_pack.BASE

    def test_every_listed_file_actually_exists(self):
        missing = sorted(rel for rel in ALL_SHIPPED if not (ROOT / rel).exists())
        assert not missing, f"manifest lists files that are not in the repo: {missing}"


class TestEditionSeparation:
    def test_free_edition_never_carries_pro_modules(self):
        overlap = set(build_buyer_pack.BASE) & set(build_buyer_pack.PRO_ONLY)
        assert not overlap, f"Pro-only files leaked into the shared base: {overlap}"

    def test_free_only_and_pro_only_stay_disjoint(self):
        overlap = set(build_buyer_pack.FREE_ONLY) & set(build_buyer_pack.PRO_ONLY)
        assert not overlap

    def test_risk_disclosure_ships_in_both_editions(self):
        # Shipping a trading tool without its disclosures is not an option.
        assert "DISCLAIMER.md" in build_buyer_pack.BASE
