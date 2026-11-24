from factory.onboarding.baseline import discover


def test_only_tests_passing_every_run_are_kept():
    runs = [{"a": "PASSED", "b": "PASSED", "c": "FAILED", "d": "SKIPPED"},
            {"a": "PASSED", "b": "FAILED", "c": "FAILED", "d": "SKIPPED"},
            {"a": "PASSED", "b": "PASSED", "c": "FAILED"}]
    base = discover(runs)
    assert base.pass_to_pass == ["a"]
    assert base.excluded["b"].startswith("flaky") and base.excluded["c"] == "failed"
    assert base.excluded["d"].startswith("flaky")  # skipped twice, missing once
