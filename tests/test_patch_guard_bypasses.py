"""Patches that would change which existing tests run must be rejected, even mixed with real changes."""
import pytest

from factory.sandbox.patch_guard import extract_diff_files, validate_reference_patch

SOURCE_CHANGE = "--- a/shop/pricing.py\n+++ b/shop/pricing.py\n@@ -1 +1,2 @@\n x = 1\n+y = 2\n"
EXISTING = ["tests/test_cart.py"]

BYPASSES = {
    "deletes an existing test": "--- a/tests/test_cart.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def test_x():\n-    assert True\n",
    "renames a test away (git)": (
        "diff --git a/tests/test_cart.py b/src/old.py\nsimilarity index 100%\n"
        "rename from tests/test_cart.py\nrename to src/old.py\n"
    ),
    "edits root conftest.py": "--- a/conftest.py\n+++ b/conftest.py\n@@ -1 +1,2 @@\n x = 1\n+y = 2\n",
    "edits pytest.ini": "--- a/pytest.ini\n+++ b/pytest.ini\n@@ -1 +1,2 @@\n [pytest]\n+markers = slow\n",
    "ignores tests from source": "--- a/shop/__init__.py\n+++ b/shop/__init__.py\n@@ -0,0 +1 @@\n+collect_ignore = ['tests']\n",
}


@pytest.mark.parametrize("name", sorted(BYPASSES))
def test_bypass_is_blocked_even_alongside_a_source_change(name):
    result = validate_reference_patch(SOURCE_CHANGE + BYPASSES[name], existing_test_paths=EXISTING)
    assert not result.passed, name


def test_deleted_and_renamed_paths_are_reported():
    files = extract_diff_files(BYPASSES["deletes an existing test"] + BYPASSES["renames a test away (git)"])
    assert "tests/test_cart.py" in files and "src/old.py" in files


def test_plain_source_change_still_passes():
    assert validate_reference_patch(SOURCE_CHANGE, existing_test_paths=EXISTING).passed


def test_nested_test_directories_are_protected():
    nested = "--- a/backend/tests/fixtures.py\n+++ b/backend/tests/fixtures.py\n@@ -1 +1,2 @@\n x = 1\n+y = 2\n"
    assert not validate_reference_patch(SOURCE_CHANGE + nested, existing_test_paths=EXISTING).passed


def test_pytest_settings_in_pyproject_are_blocked_but_dependencies_are_not():
    settings = (
        "--- a/pyproject.toml\n+++ b/pyproject.toml\n@@ -1,2 +1,3 @@\n [tool.pytest.ini_options]\n"
        '-testpaths = ["tests"]\n+testpaths = ["src"]\n'
    )
    dependency = (
        "--- a/pyproject.toml\n+++ b/pyproject.toml\n@@ -1,2 +1,3 @@\n dependencies = [\n"
        '+    "python-dateutil>=2.9",\n ]\n'
    )
    assert not validate_reference_patch(SOURCE_CHANGE + settings, existing_test_paths=EXISTING).passed
    assert validate_reference_patch(SOURCE_CHANGE + dependency, existing_test_paths=EXISTING).passed


def test_test_script_in_package_json_is_blocked():
    script = '--- a/package.json\n+++ b/package.json\n@@ -1 +1 @@\n-  "test": "vitest run"\n+  "test": "echo ok"\n'
    assert not validate_reference_patch(SOURCE_CHANGE + script, existing_test_paths=EXISTING).passed
