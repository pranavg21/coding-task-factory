"""Enforces patch safety rules: forbids touching existing tests, test configuration or forbidden paths.

Every path a patch touches is checked, including the old side of deletions and renames, because a
patch that deletes or moves a test file changes which tests run without ever naming a new path.
This guard is defence in depth: the proof runner must still confirm that every PASS_TO_PASS test
actually ran and passed, since a test can also be hidden by code the guard cannot interpret.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch

FORBIDDEN_PATTERNS = [
    ".git/*",
    ".github/workflows/*",
    "tests/*",
    "test/*",
    "__tests__/*",
    "*_test.py",
    "test_*.py",
    "*.test.ts",
    "*.test.js",
    "*.spec.ts",
    "*.spec.js",
]

# Files that decide which tests are collected or how they run, at any depth.
TEST_CONFIG_FILES = {
    "conftest.py",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "noxfile.py",
    "jest.config.js",
    "jest.config.ts",
    "jest.config.cjs",
    "jest.config.mjs",
    "vitest.config.js",
    "vitest.config.ts",
    "vitest.config.mjs",
}

DANGEROUS_DIFF_MARKERS = [
    "pytest.mark.skip",
    "@unittest.skip",
    ".skip(",
    "it.skip",
    "describe.skip",
    "collect_ignore",
    "--ignore",
    "--deselect",
    "testPathIgnorePatterns",
    "os.system(",
    "curl http",
    "wget http",
]

# Directory names that hold tests at any depth (backend/tests/fixtures.py is protected too).
TEST_DIR_NAMES = {"tests", "test", "__tests__", "testing"}

# Shared manifests may legitimately change (a new dependency), so only their test settings are guarded.
MANIFEST_TEST_MARKERS = {
    "pyproject.toml": ("[tool.pytest", "testpaths", "addopts", "python_files", "norecursedirs", "[tool.coverage"),
    "package.json": ('"jest"', '"vitest"', '"test":', '"testMatch"', '"testPathIgnorePatterns"'),
}

_PATH_LINE = re.compile(r"^(?:---|\+\+\+)\s+(?:[ab]/)?(\S.*?)\s*$")
_GIT_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)$")
_RENAME = re.compile(r"^(?:rename|copy) (?:from|to) (\S.*)$")


@dataclass
class PatchGuardResult:
    passed: bool
    touched_files: list[str]
    violations: list[str]


def _add(files: list[str], path: str) -> None:
    path = path.replace("\\", "/").strip()
    if path and path != "/dev/null" and path not in files:
        files.append(path)


def extract_diff_files(patch_text: str) -> list[str]:
    """Every path on either side of the diff: added, modified, deleted, renamed or copied."""
    files: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith(("--- ", "+++ ")):
            match = _PATH_LINE.match(line)
            if match:
                _add(files, match.group(1).split("\t")[0])
        elif header := _GIT_HEADER.match(line):
            _add(files, header.group(1))
            _add(files, header.group(2))
        elif rename := _RENAME.match(line):
            _add(files, rename.group(1))
    return files


def _path_violation(path: str, existing_tests: set[str]) -> str | None:
    name = path.split("/")[-1]
    if path in existing_tests:
        return f"Forbidden change to existing test file: {path}"
    if name in TEST_CONFIG_FILES:
        return f"Patch changes test configuration: {path}"
    if TEST_DIR_NAMES & set(path.split("/")[:-1]):
        return f"Patch touches a test directory: {path}"
    for pattern in FORBIDDEN_PATTERNS:
        if fnmatch(path, pattern) or fnmatch(name, pattern):
            return f"Patch modifies protected path ({pattern}): {path}"
    return None


def _manifest_violations(patch_text: str) -> list[str]:
    """Test settings changed inside pyproject.toml or package.json (any added or removed line)."""
    violations: list[str] = []
    current: str | None = None
    for line in patch_text.splitlines():
        if line.startswith(("+++ ", "--- ")):
            match = _PATH_LINE.match(line)
            name = match.group(1).split("\t")[0].split("/")[-1] if match else ""
            if line.startswith("+++ ") or name in MANIFEST_TEST_MARKERS:
                current = name if name in MANIFEST_TEST_MARKERS else None
            continue
        if current and line[:1] in "+-" and any(m in line for m in MANIFEST_TEST_MARKERS[current]):
            violations.append(f"Patch changes test settings in {current}: {line[1:].strip()}")
    return violations


def validate_reference_patch(
    patch_text: str,
    existing_test_paths: list[str] | None = None,
    allowed_prefixes: list[str] | None = None,
) -> PatchGuardResult:
    touched = extract_diff_files(patch_text)
    violations: list[str] = []
    existing = {p.replace("\\", "/") for p in existing_test_paths or []}

    if not touched:
        violations.append("Patch touches zero files or is not a valid unified diff.")
    for path in touched:
        if problem := _path_violation(path, existing):
            violations.append(problem)
        if allowed_prefixes and not any(path.startswith(prefix) for prefix in allowed_prefixes):
            violations.append(f"Patch touches path outside allowed prefixes: {path}")

    violations.extend(_manifest_violations(patch_text))

    added = [ln[1:] for ln in patch_text.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    for marker in DANGEROUS_DIFF_MARKERS:
        if any(marker in ln for ln in added):
            violations.append(f"Suspicious/forbidden marker in added lines: {marker}")

    return PatchGuardResult(passed=not violations, touched_files=touched, violations=violations)
