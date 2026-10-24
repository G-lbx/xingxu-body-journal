"""Boundary and behavior checks using fictional profiles and measurements."""
import copy
from datetime import datetime, timedelta
import json
import unittest

from analysis import SHANGHAI, build_analysis


TODAY = datetime.now(SHANGHAI).date()
HEALTHY = {"age": 30, "height": 175, "sex": "male", "training_level": "regular", "training_days": 3, "health_context": "none", "limitations": ""}


def record(days_ago=0, **values):
    return {"measured_at": f"{TODAY - timedelta(days=days_ago)}T08:00", "weight": 75, "body_fat": 20.1, "muscle_mass": 55.2, "skeletal_mass": 30, **values}


def action_ids(result):
    return {item["id"] for item in result["actions"]}


class AnalysisTests(unittest.TestCase):
    def test_empty_input_is_baseline_and_json_safe(self):
        result = build_analysis([], {}, [])
        self.assertEqual(result["stage"], "baseline")
        self.assertIsNone(result["metrics"]["weight"]["latest"])
        self.assertTrue(result["sources"])
        self.assertEqual(len(result["weekly"]["schedule"]), 7)
        self.assertTrue(result["generated_at"].endswith("+08:00"))
        json.dumps(result, allow_nan=False)

    def test_missing_source_does_not_discard_real_record(self):
        result = build_analysis([record(device_comparison={"weight_delta": -0.4, "body_fat_delta": -0.2})])
        self.assertEqual(result["data_quality"]["valid_records"], 1)
        self.assertEqual(result["metrics"]["weight"]["latest"], 75)
        self.assertIsNone(result["metrics"]["weight"]["previous"])
        self.assertIsNone(result["metrics"]["weight"]["week_delta"])

    def test_inferred_history_never_populates_comparison(self):
        result = build_analysis([record(10, source="inferred", weight=75.4), record()])
        self.assertEqual(result["data_quality"]["ignored_records"], 1)
        self.assertIsNone(result["metrics"]["weight"]["previous"])
        self.assertEqual(result["metrics"]["weight"]["days_previous"], 0)

    def test_same_day_counts_once_and_averages_before_week(self):
        rows = [record(0, weight=60), record(0, weight=70, measured_at=f"{TODAY}T20:00"), record(1, weight=62), record(2, weight=62)]
        result = build_analysis(rows)
        metric = result["metrics"]["weight"]
        self.assertEqual(metric["days_current"], 3)
        self.assertEqual(metric["week_mean"], 63)
        self.assertEqual(metric["latest"], 70)
        self.assertIsNone(metric["week_delta"])

    def test_windows_are_disjoint_calendar_days(self):
        rows = [record(day, weight=64 if day >= 7 else 62) for day in (0, 3, 6, 7, 10, 13, 14)]
        result = build_analysis(rows)
        metric = result["metrics"]["weight"]
        self.assertEqual(metric["days_current"], 3)
        self.assertEqual(metric["days_previous"], 3)
        self.assertEqual(metric["week_delta"], -2)
        self.assertEqual(result["stage"], "review")
        self.assertEqual(result["window"]["previous_end"], str(TODAY - timedelta(days=7)))

    def test_missing_metric_has_own_minimum_sample_threshold(self):
        rows = [record(day, body_fat=None if day in (0, 7) else 20.1) for day in (0, 1, 2, 7, 8, 9)]
        result = build_analysis(rows)
        self.assertEqual(result["metrics"]["weight"]["week_delta"], 0)
        self.assertIsNone(result["metrics"]["body_fat"]["week_delta"])
        self.assertEqual(result["metrics"]["body_fat"]["days_current"], 2)

    def test_two_days_do_not_claim_muscle_loss(self):
        result = build_analysis([record(1, muscle_mass=49.9), record(0, muscle_mass=48)], HEALTHY)
        self.assertIsNone(result["metrics"]["muscle_mass"]["week_delta"])
        self.assertNotIn("check-muscle-signal", action_ids(result))
        self.assertEqual(result["stage"], "baseline")

    def test_health_confirmation_is_required(self):
        profile = {**HEALTHY, "health_context": ""}
        result = build_analysis([record()], profile)
        self.assertIsNone(result["targets"]["protein_min"])
        self.assertIsNone(result["targets"]["training_days"])
        self.assertNotIn("strength-routine", action_ids(result))
        self.assertIn("健康与运动限制确认", result["missing_profile"])

    def test_minor_never_receives_adult_quantitative_plan(self):
        result = build_analysis([record()], {**HEALTHY, "age": 17})
        self.assertTrue(all(value is None for value in result["targets"].values()))
        self.assertIn("监护人", json.dumps(result, ensure_ascii=False))
        self.assertFalse(result["data_quality"]["low_bmi"])

    def test_health_limits_block_load_and_protein(self):
        for update in ({"health_context": "special"}, {"limitations": "膝关节疼痛"}, {"training_level": ""}):
            with self.subTest(update=update):
                result = build_analysis([record()], {**HEALTHY, **update})
                self.assertIsNone(result["targets"]["protein_min"])
                self.assertIsNone(result["targets"]["training_days"])

    def test_healthy_adult_protein_reference_never_uses_bmr_as_calories(self):
        result = build_analysis([record(bmr=1650)], HEALTHY)
        self.assertEqual(result["targets"]["protein_min"], 105)
        self.assertEqual(result["targets"]["protein_max"], 150)
        self.assertIsNone(result["targets"]["calories"])

    def test_novice_training_is_spaced_and_capped(self):
        result = build_analysis([record()], {**HEALTHY, "training_level": "beginner", "training_days": 7})
        self.assertEqual(result["targets"]["training_days"], 2)
        days = [i for i, day in enumerate(result["weekly"]["schedule"]) if day["type"] == "strength"]
        self.assertEqual(days, [0, 3])
        self.assertIn("balance-and-rest", action_ids(result))

    def test_explicit_zero_available_days_is_respected(self):
        result = build_analysis([record()], {**HEALTHY, "training_days": 0})
        self.assertEqual(result["targets"]["training_days"], 0)
        self.assertFalse(any(day["type"] == "strength" for day in result["weekly"]["schedule"]))

    def test_outliers_future_and_nan_are_ignored(self):
        rows = [record(weight=float("nan"), muscle_mass=999), record(1, weight=-4, body_fat=200, muscle_mass=None, skeletal_mass=None), record(-1), {"measured_at": "bad", "weight": 60}]
        result = build_analysis(rows, HEALTHY)
        self.assertEqual(result["data_quality"]["valid_records"], 1)
        self.assertEqual(result["data_quality"]["ignored_records"], 3)
        self.assertIsNone(result["metrics"]["weight"]["latest"])
        self.assertIsNone(result["targets"]["protein_min"])
        json.dumps(result, allow_nan=False)

    def test_muscle_cannot_exceed_weight(self):
        result = build_analysis([record(weight=60, muscle_mass=90, skeletal_mass=61)])
        self.assertIsNone(result["metrics"]["muscle_mass"]["latest"])
        self.assertIsNone(result["metrics"]["skeletal_mass"]["latest"])

    def test_stale_weight_keeps_history_but_withholds_protein(self):
        result = build_analysis([record(30)], HEALTHY)
        self.assertEqual(result["window"]["end"], str(TODAY - timedelta(days=30)))
        self.assertIsNone(result["targets"]["protein_min"])
        self.assertIn("超过 14 天", result["confidence"])

    def test_recovery_checkins_change_next_plan(self):
        checkins = [{"date": str(TODAY - timedelta(days=day)), "sleep": 5.5, "energy": "low", "training": "strength", "minutes": 30} for day in range(3)]
        result = build_analysis([record()], HEALTHY, checkins)
        detail = next(item["detail"] for item in result["actions"] if item["id"] == "strength-routine")
        self.assertIn("不增加负荷", detail)
        self.assertTrue(any("恢复" in item["title"] for item in result["insights"]))

    def test_new_other_metric_cannot_make_old_weight_fresh(self):
        result = build_analysis([record(30), record(0, weight=None)], HEALTHY)
        self.assertIsNone(result["targets"]["protein_min"])
        self.assertTrue(any("体重记录需要更新" == item["title"] for item in result["insights"]))

    def test_fast_weight_change_produces_review_not_a_calorie_deficit(self):
        rows = [record(day, weight=64 if day >= 7 else 62) for day in (0, 1, 2, 7, 8, 9)]
        result = build_analysis(rows, HEALTHY)
        self.assertIn("review-fast-change", action_ids(result))
        self.assertIsNone(result["targets"]["calories"])

    def test_stable_weight_waist_reduction_changes_advice(self):
        rows = [record(day, waist=80 if day >= 7 else 79) for day in (0, 1, 2, 7, 8, 9)]
        result = build_analysis(rows, HEALTHY)
        self.assertIn("keep-consistency", action_ids(result))

    def test_low_bmi_and_device_mismatch_take_priority(self):
        profile = {**HEALTHY, "height": 180, "training_days": 7, "health_context": "", "training_focus": "上肢训练"}
        result = build_analysis([record(weight=58, bmi=22.4)], profile)
        self.assertEqual(result["data_quality"]["profile_bmi"], 17.9)
        self.assertEqual(result["data_quality"]["device_bmi"], 22.4)
        self.assertTrue(result["data_quality"]["bmi_mismatch"])
        self.assertTrue(result["data_quality"]["low_bmi"])
        self.assertEqual(result["title"], "优先增肌、充足饮食与恢复")
        self.assertIn("verify-device-profile", action_ids(result))
        self.assertIn("muscle-recovery-priority", action_ids(result))
        self.assertIn("balance-and-rest", action_ids(result))
        self.assertIsNone(result["targets"]["protein_min"])

    def test_low_bmi_does_not_trigger_intake_reduction_for_rising_waist(self):
        rows = [record(day, weight=57.4 if day >= 7 else 58, waist=70 if day >= 7 else 71) for day in (0, 1, 2, 7, 8, 9)]
        result = build_analysis(rows, {**HEALTHY, "height": 180})
        self.assertNotIn("review-intake-habits", action_ids(result))
        self.assertIn("muscle-recovery-priority", action_ids(result))

    def test_adult_bmi_threshold_not_applied_to_18_19_year_old(self):
        result = build_analysis([record(weight=58)], {**HEALTHY, "age": 19, "height": 180})
        self.assertEqual(result["data_quality"]["profile_bmi"], 17.9)
        self.assertFalse(result["data_quality"]["low_bmi"])

    def test_input_objects_are_not_modified(self):
        rows, profile, checkins = [record()], dict(HEALTHY), [{"date": str(TODAY), "sleep": 8}]
        before = copy.deepcopy((rows, profile, checkins))
        build_analysis(rows, profile, checkins)
        self.assertEqual((rows, profile, checkins), before)


if __name__ == "__main__":
    unittest.main()
