import unittest

from app.core.academy_metrics import attendance_summary


class AcademyMetricTests(unittest.TestCase):
    def test_rate_uses_present_late_and_excused_marks(self) -> None:
        summary = attendance_summary({"present": 7, "late": 1, "excused": 1, "absent": 1})
        self.assertEqual(summary["total"], 10)
        self.assertEqual(summary["attended"], 9)
        self.assertEqual(summary["rate"], 90.0)

    def test_no_marks_is_not_a_rate(self) -> None:
        summary = attendance_summary({})
        self.assertEqual(summary["total"], 0)
        self.assertIsNone(summary["rate"])


if __name__ == "__main__":
    unittest.main()