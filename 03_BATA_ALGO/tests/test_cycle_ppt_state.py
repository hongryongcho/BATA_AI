import unittest

from cycle_ppt_state import build_cycle_event_plan


class CyclePptStateTests(unittest.TestCase):
    def test_generates_new_reports_for_new_completed_and_open_cycle(self):
        state = {
            "TQQQ": {
                "last_completed_cycle": 1,
                "last_open_cycle": 1,
            }
        }
        completed = [{"cycle_no": 2}]
        open_cycle = {"cycle_no": 2}

        plan = build_cycle_event_plan("TQQQ", completed, open_cycle, state)

        self.assertEqual(plan, ["매도종료", "매수시작"])

    def test_skips_when_cycle_numbers_are_unchanged(self):
        state = {
            "TQQQ": {
                "last_completed_cycle": 2,
                "last_open_cycle": 2,
            }
        }
        completed = [{"cycle_no": 2}]
        open_cycle = {"cycle_no": 2}

        plan = build_cycle_event_plan("TQQQ", completed, open_cycle, state)

        self.assertEqual(plan, [])


if __name__ == "__main__":
    unittest.main()
