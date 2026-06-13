from __future__ import annotations

from beagle.lifecycle import FrappeLifecyclePolicy


def names(policy, rel):
    return [e.name for e in policy.events_for(rel)]


def test_save_sequence_source_order():
    policy = FrappeLifecyclePolicy()
    assert names(policy, "SAVES_DOCTYPE") == [
        "before_validate", "validate", "before_save", "db_update", "on_update", "on_change"
    ]


def test_insert_runs_before_insert_and_after_insert():
    policy = FrappeLifecyclePolicy()
    seq = names(policy, "INSERTS_DOCTYPE")
    assert seq[0] == "before_insert"
    assert seq.index("after_insert") < seq.index("on_update")
    assert seq[-1] == "on_change"


def test_submit_on_update_before_on_submit():
    policy = FrappeLifecyclePolicy()
    seq = names(policy, "SUBMITS_DOCTYPE")
    assert seq.index("on_update") < seq.index("on_submit")
    assert "before_submit" in seq


def test_cancel_has_no_validate():
    policy = FrappeLifecyclePolicy()
    seq = names(policy, "CANCELS_DOCTYPE")
    assert "validate" not in seq
    assert "before_validate" not in seq
    assert seq[0] == "before_cancel"
    assert "on_cancel" in seq


def test_db_set_does_not_run_save_lifecycle():
    policy = FrappeLifecyclePolicy()
    seq = names(policy, "DB_SETS_DOCTYPE")
    assert seq == ["before_change", "db_update_field", "on_change"]
    assert "validate" not in seq and "on_update" not in seq


def test_validate_marked_conditional_on_ignore_validate():
    policy = FrappeLifecyclePolicy()
    validate = next(e for e in policy.events_for("SAVES_DOCTYPE") if e.name == "validate")
    assert validate.conditional and "ignore_validate" in validate.note


def test_policy_metadata_pinned():
    meta = FrappeLifecyclePolicy().meta
    assert meta["framework"] == "frappe"
    assert len(meta["commit"]) == 40
    assert meta["policy_version"] == 1
