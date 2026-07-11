"""状态机单元测试。v0.9"""
import pytest
from state_machine import initial_state, is_terminal, next_state, STATES


class TestStateMachine:
    def test_initial_state(self):
        assert initial_state() == "INIT"

    def test_init_not_terminal(self):
        assert not is_terminal("INIT")

    def test_done_is_terminal(self):
        assert is_terminal("DONE")

    def test_all_states_known(self):
        assert set(STATES) == {"INIT", "STATIC", "AI_GATE", "AI_RUN", "MERGE", "DONE"}

    # ── 正常路径：INIT → STATIC → AI_GATE → AI_RUN → MERGE → DONE ──

    def test_normal_full_flow(self):
        s = initial_state()
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

    # ── 降级路径：AI_GATE blocked → MERGE（跳过 AI） ──

    def test_degraded_flow(self):
        s = "AI_GATE"
        s, a = next_state(s, "blocked")
        assert s == "MERGE" and a == "merge_degraded"

    # ── MERGE 终止 ──

    def test_merge_transitions_to_done(self):
        s, a = next_state("MERGE", "")
        assert s == "DONE" and a == "finish"

    def test_done_stays_done(self):
        s, a = next_state("DONE", "anything")
        assert s == "DONE" and a == "finish"

    # ── 边界 ──

    def test_unknown_state_raises(self):
        with pytest.raises(ValueError, match="未知状态"):
            next_state("BOGUS", "")

    def test_allowed_event_goes_to_ai_run(self):
        s, a = next_state("AI_GATE", "allowed")
        assert s == "AI_RUN"

    def test_unknown_event_still_blocked(self):
        s, a = next_state("AI_GATE", "random_event")
        assert s == "MERGE"  # 非 "allowed" 一律 blocked
