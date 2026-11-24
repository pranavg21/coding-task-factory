from pathlib import Path
from factory.schemas import ProofMatrix, ProofRunRecord
from factory.sandbox.patch_guard import validate_reference_patch
from factory.verifier.diff_mutator import generate_diff_mutants
from factory.verifier.variety_scorer import check_candidate_uniqueness
from factory.reporting.html_report import generate_html_report


SAMPLE_GOOD_DIFF = """--- a/shop/pricing.py
+++ b/shop/pricing.py
@@ -10,0 +11,6 @@
+def apply_discount(subtotal, pct):
+    if pct >= 100:
+        return 0
+    if pct == 0:
+        return subtotal
+    return subtotal - (subtotal * pct / 100)
"""

SAMPLE_BAD_DIFF = """--- a/tests/test_cart.py
+++ b/tests/test_cart.py
@@ -1,2 +1,3 @@
+@pytest.mark.skip(reason="broken")
 def test_existing():
     assert True
"""


def test_patch_guard_accepts_source_only_diff():
    res = validate_reference_patch(SAMPLE_GOOD_DIFF, existing_test_paths=["tests/test_cart.py"])
    assert res.passed is True
    assert res.touched_files == ["shop/pricing.py"]


def test_patch_guard_blocks_existing_test_tampering():
    res = validate_reference_patch(SAMPLE_BAD_DIFF, existing_test_paths=["tests/test_cart.py"])
    assert res.passed is False
    assert any("test" in v.lower() for v in res.violations)


def test_diff_mutator_generates_targeted_mutants():
    mutants = generate_diff_mutants(SAMPLE_GOOD_DIFF, max_mutants=5)
    assert len(mutants) >= 2
    assert any(m.rule_name == "gte_to_gt" for m in mutants)
    assert any(m.rule_name == "eq_to_neq" for m in mutants)


def test_variety_scorer_catches_cosmetic_marquee_duplicates():
    black_friday = "Add a scrolling Black Friday Sale banner marquee to the storefront header with discount text."
    christmas = "Add a scrolling Christmas Holiday Sale banner marquee to the storefront header with discount text."
    voucher = "Implement backend checkout voucher validation with expiry timestamps and minimum subtotal rules."

    dup = check_candidate_uniqueness(
        christmas, ["frontend/Header.tsx"],
        [black_friday], [["frontend/Header.tsx"]],
    )
    assert dup.is_duplicate is True

    unique = check_candidate_uniqueness(
        voucher, ["backend/pricing.py"],
        [black_friday], [["frontend/Header.tsx"]],
    )
    assert unique.is_duplicate is False


def test_proof_matrix_and_html_report(tmp_path: Path):
    proof = ProofMatrix(
        task_id="T-01",
        PASS_TO_PASS=["test_a"],
        FAIL_TO_PASS=["test_b"],
        runs=[
            ProofRunRecord(run_index=i, check1_baseline_pass=True, check2_patched_all_pass=True, check3_unpatched_new_fail=True, duration_sec=1.0)
            for i in (1, 2, 3)
        ],
        mutants_total=8, mutants_killed=7,
        adversary_total=2, adversary_caught=2,
    )
    assert proof.all_checks_passed is True
    assert proof.kill_rate == 0.9

    out = generate_html_report({"funnel": [], "tasks": [], "runs": []}, tmp_path / "index.html")
    assert out.exists() and "Coding Task Factory" in out.read_text(encoding="utf-8")


def test_diff_mutator_skips_docstrings_and_comments():
    diff = (
        "--- a/m.py\n+++ b/m.py\n@@ -1,0 +1,8 @@\n"
        '+def f(a, b):\n+    """True if a >= b and more.\n+    Still docs: x == y\n+    """\n'
        "+    # a >= b\n+    return a >= b\n"
    )
    mutants = generate_diff_mutants(diff, max_mutants=10)
    assert mutants and all(m.original_line == "return a >= b" for m in mutants)
