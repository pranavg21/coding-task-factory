"""What differs per test framework: where new tests go, how agents run tests, and how statuses are read.

Everything else in the factory is shared, which is what lets one pipeline serve Python, TypeScript and C++.
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from factory.onboarding import baseline
from factory.sandbox.patch_guard import TEST_CONFIG_FILES, TEST_DIR_NAMES


@dataclass(frozen=True)
class Stack:
    framework: str
    new_test_globs: tuple[str, ...]  # where the test writer may create new test files
    test_guidance: str  # conventions given to the test writer
    statuses: Callable[[Path], dict[str, str]]  # full-suite statuses of a checkout (feature tests included)

    def is_new_test_path(self, rel: str, base: Path) -> bool:
        return any(fnmatch.fnmatch(rel, g) for g in self.new_test_globs) and not (base / rel).exists()

    def run_for_agent(self, root: Path, tests: list[str]) -> str:
        """Run selected test files for an agent and return readable output (failures included)."""
        if self.framework == "pytest":
            env = {**os.environ, "PYTHONPATH": f"{root / 'src'}{os.pathsep}{root}"}
            cmd = [os.environ.get("FACTORY_PYTHON", "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   "--tb=short", *tests]
            proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=900, env=env)
            return proc.stdout + proc.stderr
        if self.framework == "vitest":
            proc = subprocess.run(["node_modules/.bin/vitest", "run", "--project", "zod", *tests], cwd=root,
                                  capture_output=True, text=True, timeout=900)
            return proc.stdout + proc.stderr
        sources = [t for t in tests if t.endswith(".cpp")]
        statuses = baseline.jsontest_statuses(root, sources)
        if not statuses:
            return "build or compilation failed (see the repository's CMake output)"
        return "\n".join(f"{s} {t}" for t, s in sorted(statuses.items()) if not sources or t.startswith("feature::"))


def implementer_can_write(rel: str) -> bool:
    """Source changes only: never tests, test directories or test configuration."""
    parts = rel.split("/")
    name = parts[-1]
    return not (TEST_DIR_NAMES & set(parts[:-1]) or name in TEST_CONFIG_FILES
                or name.startswith("test_") or ".test." in name or ".spec." in name or name.startswith("feature_"))


def stack_for(framework: str, python: str = "python", vitest_project: str = "zod") -> Stack:
    if framework == "pytest":
        return Stack("pytest", ("tests/test_*.py",),
                     "Write pytest tests in ONE new file tests/test_<feature>.py. Import the package the way the "
                     "existing tests do. Use plain asserts and pytest.mark.parametrize; for command-line behaviour "
                     "use click.testing.CliRunner like the existing tests.",
                     partial(baseline.pytest_statuses, python=python))
    if framework == "vitest":
        return Stack("vitest", ("packages/*/src/**/tests/*.test.ts",),
                     "Write Vitest tests in ONE new file next to the existing tests, e.g. "
                     "packages/zod/src/v4/classic/tests/<feature>.test.ts. Start with "
                     '`import { expect, expectTypeOf, test } from "vitest";` and `import * as z from "zod/v4";`. '
                     "Type checks run too, so the file must type-check once the feature exists.",
                     partial(baseline.vitest_statuses, project=vitest_project))
    if framework == "jsontest":
        return Stack("jsontest", ("src/test_lib_json/feature_*.cpp",),
                     "Write ONE new file src/test_lib_json/feature_<name>.cpp. It is compiled as its own program with "
                     "jsontest.cpp and the jsoncpp library, so it must contain everything it needs: "
                     '`#include "jsontest.h"`, `#include <json/json.h>`, '
                     "`static std::deque<JsonTest::TestCaseFactory> local_;`, the macro "
                     "`#define JSONTEST_FIXTURE_LOCAL(FixtureType, name) JSONTEST_FIXTURE_V2(FixtureType, name, local_)`, "
                     "fixtures deriving from JsonTest::TestCase, and a main() that adds every entry of local_ to a "
                     "JsonTest::Runner and returns runner.runCommandLine(argc, argv). Use JSONTEST_ASSERT, "
                     "JSONTEST_ASSERT_EQUAL and JSONTEST_ASSERT_STRING_EQUAL.",
                     lambda repo: baseline.jsontest_statuses(
                         repo, [p.relative_to(repo).as_posix() for p in (repo / "src" / "test_lib_json").glob("feature_*.cpp")]))
    raise ValueError(f"unknown framework {framework}")
