"""Command line: generate tasks, prove a package, list Gemini models, build the audit report."""
from __future__ import annotations

import json
from pathlib import Path
import typer
from rich.console import Console

from factory.reporting.html_report import generate_html_report

app = typer.Typer(help="Coding Task Factory CLI (Innodata AI Hackathon — Track 1)")
console = Console()


@app.command()
def generate(
    repo: str = typer.Option(..., "--repo", help="Supplied repository: click, zod or jsoncpp"),
    checkout: Path = typer.Option(..., "--checkout", help="Checkout at the pinned commit (environments/setup.sh)"),
    n: int = typer.Option(15, "--n", min=1, max=50, help="Target number of accepted tasks"),
    seed: int = typer.Option(42, "--seed", help="Seed for variety-cell selection"),
    out: Path = typer.Option(Path("outputs"), "--out", help="Output directory"),
    mode: str = typer.Option("record", "--mode", help="record (call Claude, save responses), replay, or live"),
    recordings: Path = typer.Option(Path("recordings"), "--recordings", help="Where responses are saved or read"),
    python: str = typer.Option("python", "--python", help="Python with the repository installed (click)"),
    provider: str = typer.Option("gemini", "--provider", help="gemini (Google AI Studio key) or anthropic"),
    model: str = typer.Option("", "--model", help="Model ID; default from GEMINI_MODEL (see `factory models`)"),
    blind_attempts: int = typer.Option(1, "--blind-attempts", min=0, max=3,
                                       help="Independent blind-solve attempts per accepted task (0 to skip)"),
) -> None:
    """Generate, prove and package tasks for one supplied repository."""
    import subprocess

    from factory.agents.llm import LLM
    from factory.pipeline.generate import RepoContext
    from factory.pipeline.generate import generate as run_factory
    from factory.repos import REPOS
    from factory.stacks import stack_for
    from factory.verifier.proof_runner import local_executor

    if repo not in REPOS:
        raise typer.BadParameter(f"unknown repository {repo!r}; choose from {', '.join(REPOS)}")
    spec = REPOS[repo]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True).stdout.strip()
    if head != spec["pinned_version"]:
        raise typer.BadParameter(f"{checkout} is at {head or 'no commit'}, expected {spec['pinned_version']}")
    python_dir = Path(python).parent if spec["framework"] == "pytest" and "/" in python else None
    ctx = RepoContext(repo_id=spec["repo_id"], repo_source=spec["repo_source"], base=checkout.resolve(),
                      pinned_version=spec["pinned_version"], language=spec["language"],
                      stack=stack_for(spec["framework"], python=python),
                      executor=local_executor(python_dir), docker_image=spec["docker_image"],
                      test_cmd=spec["test_cmd"], test_project=spec.get("test_project", ""))
    llm = LLM(mode=mode, recordings=recordings / spec["repo_id"], provider=provider, model=model)  # type: ignore[arg-type]
    funnel = run_factory(ctx, n=n, seed=seed, llm=llm, out_dir=out, blind_attempts=blind_attempts)
    accepted = sum(e.status == "accepted" for e in funnel)
    console.print(f"[green]{accepted} accepted[/green] of {len(funnel)} candidates; "
                  f"{llm.usage.calls} API calls, ${llm.usage.cost_usd}")


@app.command()
def models() -> None:
    """List the Gemini models this Google AI Studio key can call with generateContent."""
    import os

    from google import genai

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or (
        "replaced-by-proxy" if os.environ.get("GEMINI_KEY_VIA_PROXY") == "1" else "")
    if not key:
        raise typer.BadParameter("Set GEMINI_API_KEY (or GEMINI_KEY_VIA_PROXY=1 behind a key-injecting proxy)")
    client = genai.Client(api_key=key)  # keep a reference: listing pages lazily through this client
    for m in client.models.list():
        if "generateContent" in (m.supported_actions or []):
            console.print(f"{m.name.removeprefix('models/')}  [dim]{m.display_name}[/dim]")


@app.command()
def prove(
    task: Path = typer.Option(..., "--task", help="Task package directory (contains tests/run_tests.sh)"),
    repo: Path = typer.Option(..., "--repo", help="Checkout of the base repository at the pinned version"),
    image: str = typer.Option("", "--image", help="Run inside this offline Docker image instead of locally"),
    runs: int = typer.Option(3, "--runs", min=1, max=3, help="Repeat the proof to detect flaky tests"),
) -> None:
    """Re-run the 3-condition proof for one task package and rewrite its evidence/proof.json."""
    from factory.schemas import ProofMatrix
    from factory.verifier.proof_runner import docker_executor, local_executor
    from factory.verifier.proof_runner import prove as run_proof

    proof_path = task / "evidence" / "proof.json"
    proof = ProofMatrix.model_validate_json(proof_path.read_text(encoding="utf-8"))
    execute = docker_executor(image) if image else local_executor()
    result = run_proof(task, repo, proof, execute, runs=runs, logs_dir=task / "evidence" / "logs")
    with proof_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(result.model_dump_json(indent=2) + "\n")
    for record in result.runs:
        console.print(
            f"run {record.run_index}: Condition 1 {'PASS' if record.check1_baseline_pass else 'FAIL'} | "
            f"Condition 2 {'PASS' if record.check2_patched_all_pass else 'FAIL'} | "
            f"Condition 3 {'PASS' if record.check3_unpatched_new_fail else 'FAIL'}"
        )
        for problem in record.problems:
            console.print(f"  [red]{problem}[/red]")
    verdict = "[green]ACCEPTED[/green]" if result.all_checks_passed else "[red]REJECTED[/red]"
    console.print(f"{verdict} flaky tests: {result.flake_count}")
    raise typer.Exit(0 if result.all_checks_passed else 1)


@app.command()
def report(
    outputs: Path = typer.Option(Path("outputs"), "--outputs", help="Folder with task packages and run records"),
    output_html: Path = typer.Option(Path("report/index.html"), "--out"),
) -> None:
    """Build the HTML audit report from the output folders (no hand-entered numbers)."""
    from factory.reporting.collect import collect

    data = collect(outputs)
    log = Path("manual_interventions.json")
    if log.exists():
        data["manual_edits"] = json.loads(log.read_text(encoding="utf-8")).get("total_manual_edits", 0)
    path = generate_html_report(data, output_html)
    console.print(f"[green]Generated HTML audit report:[/green] {path}")


if __name__ == "__main__":
    app()
