"""ADR-0016: enforced operating budget, append-only ledger. Never calls a
real model or spends real money -- these tests exercise ego_os.store's
ledger primitives directly against an isolated temp DB (temp_env)."""

import pytest


def test_global_budget_is_seeded_at_1500_cents_on_a_fresh_db(temp_env):
    from ego_os import store

    store.init_db()
    assert store.get_global_available_cents() == 1500  # USD 15.00, ADR-0016


def test_init_db_never_reseeds_the_global_budget_on_a_second_call(temp_env):
    from ego_os import store

    store.init_db()
    store.reserve_budget(None, 100)  # spend down the balance a bit
    store.init_db()  # simulate a second app startup
    assert store.get_global_available_cents() == 1400, "a second init_db() must never re-add another 1500"


def test_reserve_spend_release_cycle_trues_up_to_actual_cost(temp_env):
    from ego_os import store

    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("x", project_id)

    store.reserve_budget(task_id, 200)  # conservative ceiling reservation
    assert store.get_global_available_cents() == 1300
    assert store.get_task_net_reserved_cents(task_id) == 200

    store.record_spend(task_id, 120)  # actual measured cost was lower
    store.release_reservation(task_id, 80)  # release the unused 200-120

    assert store.get_global_available_cents() == 1380, "released amount must be added back"
    assert store.get_task_net_reserved_cents(task_id) == 120


def test_task_sub_limit_is_enforced_independently_of_the_global_balance(temp_env):
    from ego_os import store

    store.init_db()  # global balance: 1500 cents, plenty
    project_id = store.ensure_default_project()
    task_id = store.create_task("x", project_id)

    store.reserve_budget(task_id, 50, task_budget_cents=100)
    with pytest.raises(store.BudgetError):
        store.reserve_budget(task_id, 60, task_budget_cents=100)  # 50+60 > 100 task sub-limit, even though global has room

    # A budget_exhausted event was recorded, not silently swallowed.
    conn = store.get_connection()
    rows = conn.execute("SELECT event_type FROM budget_ledger_events WHERE task_id = ?", (task_id,)).fetchall()
    conn.close()
    assert any(r["event_type"] == "budget_exhausted" for r in rows)


def test_global_limit_is_enforced_and_never_silently_overspent(temp_env):
    from ego_os import store

    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("x", project_id)

    store.reserve_budget(task_id, 1500)  # exactly the whole global balance
    assert store.get_global_available_cents() == 0
    with pytest.raises(store.BudgetError):
        store.reserve_budget(task_id, 1)  # even one more cent must be refused


def test_reserve_budget_rejects_a_non_integer_amount(temp_env):
    from ego_os import store

    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("x", project_id)
    with pytest.raises(TypeError):
        store.reserve_budget(task_id, 1.5)  # money must be exact integer cents, never a float


def test_release_amount_cannot_be_negative(temp_env):
    from ego_os import store

    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("x", project_id)
    store.reserve_budget(task_id, 100)
    with pytest.raises(ValueError):
        store.release_reservation(task_id, -1)


def test_releasing_zero_is_a_no_op_not_a_ledger_row(temp_env):
    from ego_os import store

    store.init_db()
    project_id = store.ensure_default_project()
    task_id = store.create_task("x", project_id)
    store.reserve_budget(task_id, 100)
    store.release_reservation(task_id, 0)
    conn = store.get_connection()
    rows = conn.execute(
        "SELECT * FROM budget_ledger_events WHERE task_id = ? AND event_type = 'reservation_released'", (task_id,),
    ).fetchall()
    conn.close()
    assert rows == []


def test_multiple_reservations_across_two_tasks_never_double_count(temp_env):
    """Defense-in-depth concurrency proxy: two sequential reservations
    (simulating two worker calls) must draw down the SAME shared global
    balance, never each starting from a stale snapshot."""
    from ego_os import store

    store.init_db()
    project_id = store.ensure_default_project()
    task_a = store.create_task("a", project_id)
    task_b = store.create_task("b", project_id)

    store.reserve_budget(task_a, 800)
    store.reserve_budget(task_b, 700)  # 800 + 700 == 1500, exactly the whole balance
    assert store.get_global_available_cents() == 0

    with pytest.raises(store.BudgetError):
        store.reserve_budget(task_a, 1)


def test_unknown_capability_fails_closed_never_treated_as_free(monkeypatch, temp_env):
    from ego_os import model_provider, store

    store.init_db()
    with pytest.raises(model_provider.ModelSelectionError):
        model_provider.complete("no_such_capability", "prompt")


def test_unpriced_model_fails_closed(monkeypatch, temp_env):
    from ego_os import model_provider, store

    store.init_db()
    monkeypatch.setitem(model_provider._CAPABILITY_MODELS, "test_cap", "some/unpriced-model")
    with pytest.raises(model_provider.ModelSelectionError):
        model_provider.complete("test_cap", "prompt")


def test_conservative_reservation_is_computed_from_max_tokens_and_prompt_length():
    from ego_os import model_provider

    price = {"input": 1.0 / 1_000_000, "output": 5.0 / 1_000_000}
    cents = model_provider._conservative_reservation_cents("x" * 4000, 1000, price)
    # ~1500 estimated input tokens (4000/4 + 500 buffer) + 1000 output tokens,
    # at the given per-token price, rounded UP to the next whole cent.
    expected_usd = (4000 // 4 + 500) * price["input"] + 1000 * price["output"]
    import math
    assert cents == math.ceil(expected_usd * 100)
    assert cents > 0


def test_reserve_budget_rejects_a_nonexistent_task_id(temp_env):
    import sqlite3

    from ego_os import store

    store.init_db()  # PRAGMA foreign_keys = ON (get_connection) enforces tasks(id) referential integrity
    with pytest.raises(sqlite3.IntegrityError):
        store.reserve_budget(999999, 100)
