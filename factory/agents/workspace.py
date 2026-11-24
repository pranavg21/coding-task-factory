"""File tools for an agent, confined to its own copy of the repository.

Each agent gets a fresh copy of the base repository. Paths are resolved inside that copy; `.git`,
dependency folders and anything outside the copy are refused. Write access is limited by a policy
function, so the test writer can only create new test files and can never edit source code.
The implementer's workspace is a git repository created at the start, so its change is exactly
`git diff` against the untouched base.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

HIDDEN = {".git", "node_modules", "build-factory", ".venv", "__pycache__"}
MAX_READ_CHARS = 60_000
MAX_LIST = 400


class ToolError(Exception):
    """A tool call the agent may correct (bad path, refused write); returned as an error result."""


@dataclass
class Workspace:
    root: Path
    can_write: Callable[[str], bool] = lambda rel: False
    run_tests: Callable[[Path, list[str]], str] | None = None  # (root, test paths) -> output
    written: dict[str, str] = field(default_factory=dict)

    def _resolve(self, rel: str) -> Path:
        rel = rel.strip().lstrip("/").replace("\\", "/")
        path = (self.root / rel).resolve()
        if path != self.root.resolve() and self.root.resolve() not in path.parents:
            raise ToolError(f"path outside the repository: {rel}")
        if HIDDEN & set(Path(rel).parts):
            raise ToolError(f"path not available: {rel}")
        return path

    # ---- tools -----------------------------------------------------------------------------------
    def list_files(self, path: str = ".", pattern: str = "*") -> str:
        base = self._resolve(path)
        found = []
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(self.root).as_posix()
            if p.is_file() and not (HIDDEN & set(p.relative_to(self.root).parts)) and fnmatch.fnmatch(p.name, pattern):
                found.append(rel)
            if len(found) >= MAX_LIST:
                found.append(f"... (truncated at {MAX_LIST})")
                break
        return "\n".join(found) or "(no files)"

    def read_file(self, path: str, start_line: int = 1, end_line: int = 0) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError(f"no such file: {path}")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        end = end_line or len(lines)
        text = "\n".join(f"{n:>5}  {line}" for n, line in enumerate(lines[start_line - 1:end], start=start_line))
        return text[:MAX_READ_CHARS] + ("\n... (truncated)" if len(text) > MAX_READ_CHARS else "")

    def search(self, pattern: str, path: str = ".", glob: str = "*") -> str:
        regex = re.compile(pattern)
        hits = []
        for p in sorted(self._resolve(path).rglob(glob)):
            if not p.is_file() or HIDDEN & set(p.relative_to(self.root).parts):
                continue
            try:
                for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if regex.search(line):
                        hits.append(f"{p.relative_to(self.root).as_posix()}:{n}: {line.strip()[:200]}")
            except OSError:
                continue
            if len(hits) >= 200:
                hits.append("... (truncated at 200 matches)")
                break
        return "\n".join(hits) or "(no matches)"

    def write_file(self, path: str, content: str) -> str:
        rel = path.strip().lstrip("/").replace("\\", "/")
        if not self.can_write(rel):
            raise ToolError(f"writing {rel} is not allowed for this role")
        target = self._resolve(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        self.written[rel] = content
        return f"wrote {rel} ({len(content)} characters)"

    def run(self, tests: list[str]) -> str:
        if self.run_tests is None:
            raise ToolError("running tests is not available for this role")
        return self.run_tests(self.root, tests)[-12_000:]

    # ---- diff for the implementer ---------------------------------------------------------------
    def snapshot(self) -> None:
        """Make the untouched copy a git repository so the agent's change is an exact diff."""
        git = ["git", "-c", "user.email=factory@local", "-c", "user.name=factory"]
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / ".git" / "info").mkdir(parents=True, exist_ok=True)
        (self.root / ".git" / "info" / "exclude").write_text("\n".join(sorted(HIDDEN)) + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run([*git, "commit", "-q", "-m", "base", "--allow-empty"], cwd=self.root, check=True)

    def diff(self) -> str:
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        return subprocess.run(["git", "diff", "--cached", "--no-color", "--no-ext-diff"], cwd=self.root,
                              check=True, capture_output=True, text=True).stdout


TOOL_SCHEMAS = {
    "list_files": {"description": "List files under a directory of the repository (recursive), optionally filtered by a filename glob.",
                   "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}}, "required": []},
    "read_file": {"description": "Read a text file, with line numbers. Optional 1-based line range.",
                  "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
                  "required": ["path"]},
    "search": {"description": "Search files for a Python regular expression. Optional directory and filename glob.",
               "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}},
               "required": ["pattern"]},
    "write_file": {"description": "Create or overwrite a file with the full content given.",
                   "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    "run": {"description": "Run the given test files (paths relative to the repository) and return the output.",
            "properties": {"tests": {"type": "array", "items": {"type": "string"}}}, "required": ["tests"]},
}


def tool_definitions(names: list[str]) -> list[dict]:
    defs = []
    for name in names:
        schema = TOOL_SCHEMAS[name]
        defs.append({"name": name, "description": schema["description"],
                     "input_schema": {"type": "object", "properties": schema["properties"],
                                      "required": schema["required"], "additionalProperties": False}})
    return defs
