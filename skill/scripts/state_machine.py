"""评审流程状态机：init → static → ai_gate → ai_run → merge → done。"""
from __future__ import annotations

STATES = ["INIT", "STATIC", "AI_GATE", "AI_RUN", "MERGE", "DONE"]


def initial_state() -> str:
    return "INIT"


def is_terminal(state: str) -> bool:
    return state == "DONE"


def next_state(state: str, event: str) -> tuple[str, str]:
    """返回 (new_state, action)。action 告诉 app.py 该执行哪一步。"""
    if state == "INIT":
        return "STATIC", "run_static"
    if state == "STATIC":
        return "AI_GATE", "check_gate"
    if state == "AI_GATE":
        if event == "allowed":
            return "AI_RUN", "run_ai"
        return "MERGE", "merge_degraded"
    if state == "AI_RUN":
        return "MERGE", "merge_normal"
    if state in ("MERGE", "DONE"):
        return "DONE", "finish"
    raise ValueError(f"未知状态 {state}")


if __name__ == "__main__":
    s = initial_state()
    assert not is_terminal(s)
    s, a = next_state(s, "")
    assert s == "STATIC" and a == "run_static"
    s, a = next_state(s, "")
    assert s == "AI_GATE" and a == "check_gate"
    s, a = next_state(s, "allowed")
    assert s == "AI_RUN" and a == "run_ai"
    s, a = next_state(s, "")
    assert s == "MERGE" and a == "merge_normal"
    s, a = next_state(s, "")
    assert s == "DONE" and a == "finish"
    s = "AI_GATE"
    s, a = next_state(s, "blocked")
    assert s == "MERGE" and a == "merge_degraded"
    print("state_machine smoke PASS")
