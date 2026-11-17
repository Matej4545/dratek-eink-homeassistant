"""Helpers the door screens are built on: departure filtering, the day outlook, advice, alerts."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "dratek_screen_ui_test", ROOT / "custom_components" / "dratek_eink" / "screen_ui.py"
)
ui = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ui  # dataclasses look their module up while being created
spec.loader.exec_module(ui)

NOW = datetime(2026, 11, 17, 7, 30)
DEPARTURES = [
    {"line": "8", "destination": "Starý Hloubětín", "minutes": 3},
    {"line": "3", "destination": "Lehovec", "minutes": 4},
    {"line": "12", "destination": "Sídliště Barrandov", "minutes": 5},
    {"line": "8", "destination": "Podbaba", "minutes": 6},
    {"line": "12", "destination": "Lehovec", "minutes": 16},
]


def hourly(rows):
    """rows: (hours from now, temperature, probability or None, amount or None, condition)."""
    out = []
    for h, temp, prob, amount, cond in rows:
        entry = {"datetime": (NOW.replace(minute=0) + timedelta(hours=h)).isoformat(), "temperature": temp,
                 "condition": cond}
        if prob is not None:
            entry["precipitation_probability"] = prob
        if amount is not None:
            entry["precipitation"] = amount
        out.append(entry)
    return out


class FilterDeparturesTests(unittest.TestCase):
    def dest(self, rows):
        return [(r["line"], r["destination"]) for r in rows]

    def test_no_filters_keeps_everything(self):
        self.assertEqual(len(ui.filter_departures(DEPARTURES)), 5)

    def test_directions_match_part_of_the_name_without_diacritics_or_case(self):
        rows = ui.filter_departures(DEPARTURES, destinations=["stary hloub", "LEHOVEC"])
        self.assertEqual(self.dest(rows), [("8", "Starý Hloubětín"), ("3", "Lehovec"), ("12", "Lehovec")])

    def test_comma_separated_string_works_like_a_list(self):
        self.assertEqual(ui.filter_departures(DEPARTURES, destinations="Lehovec, Podbaba"),
                         ui.filter_departures(DEPARTURES, destinations=["Lehovec", "Podbaba"]))

    def test_lines_exclude_and_walking_time(self):
        rows = ui.filter_departures(DEPARTURES, lines=["8", "12"], exclude=["barrandov"], min_minutes=4)
        self.assertEqual(self.dest(rows), [("8", "Podbaba"), ("12", "Lehovec")])


class OutlookTests(unittest.TestCase):
    def test_rain_window_from_probability(self):
        outlook = ui.day_outlook(hourly([
            (0, 4, 10, None, "cloudy"), (1, 5, 20, None, "cloudy"), (2, 7, 60, None, "rainy"),
            (3, 8, 80, None, "rainy"), (4, 7, 30, None, "cloudy"),
        ]), NOW)
        self.assertEqual((outlook.hi, outlook.lo), (8, 4))
        self.assertEqual(len(outlook.rain_windows), 1)
        start, end, peak = outlook.rain_windows[0]
        self.assertEqual((start.hour, end.hour, peak), (9, 11, 0.8))
        self.assertEqual(ui.describe_rain(outlook, NOW), "Déšť 09–11 h")

    def test_amount_only_forecast_like_met_no(self):
        outlook = ui.day_outlook(hourly([(0, 4, None, 0.0, "cloudy"), (1, 4, None, 0.6, "rainy"),
                                         (2, 4, None, 0.1, "cloudy")]), NOW)
        self.assertTrue(outlook.wet)
        self.assertEqual(ui.describe_rain(outlook, NOW), "Déšť 08–09 h")

    def test_raining_now_and_open_ended_rain(self):
        now_wet = ui.day_outlook(hourly([(0, 4, 90, None, "rainy"), (1, 4, 10, None, "cloudy")]), NOW)
        self.assertEqual(ui.describe_rain(now_wet, NOW), "Prší do 08 h")
        later = ui.day_outlook(hourly([(0, 4, 0, None, "cloudy"), (1, 4, 70, None, "rainy")]), NOW)
        self.assertEqual(ui.describe_rain(later, NOW), "Déšť od 08 h")

    def test_amounts_and_probability_are_summed_for_the_label(self):
        outlook = ui.day_outlook(hourly([(0, 4, 20, 0.0, "cloudy"), (1, 4, 70, 1.5, "rainy"),
                                         (2, 4, 90, 2.5, "pouring")]), NOW)
        self.assertTrue(outlook.has_amounts and outlook.has_probability)
        self.assertEqual((outlook.total_mm, outlook.max_mm, outlook.max_prob), (4.0, 2.5, 90))

    def test_dry(self):
        outlook = ui.day_outlook(hourly([(0, 20, 0, None, "sunny"), (1, 22, 5, None, "sunny")]), NOW)
        self.assertFalse(outlook.wet)
        self.assertEqual(ui.describe_rain(outlook, NOW), "Bez deště")

    def test_window_is_limited_to_the_requested_hours(self):
        rows = [(h, 5 + h, 0, None, "cloudy") for h in range(24)]
        self.assertEqual(len(ui.day_outlook(hourly(rows), NOW, hours=6).hours), 6)

    def test_empty_forecast_falls_back_to_the_current_temperature(self):
        outlook = ui.day_outlook([], NOW, current_temperature=12.5)
        self.assertEqual((outlook.hi, outlook.lo, outlook.wet), (12.5, 12.5, False))


class AdviceTests(unittest.TestCase):
    def texts(self, outlook, feels=None):
        return [t for t, _ in ui.clothing_advice(outlook, feels)]

    def test_cold_and_wet(self):
        outlook = ui.day_outlook(hourly([(0, 2, 80, None, "rainy"), (1, 1, 70, None, "rainy")]), NOW)
        advice = ui.clothing_advice(outlook, feels_like=-1)
        self.assertEqual(advice[0], ("Deštník", True))
        self.assertIn("Teplá bunda", self.texts(outlook, -1))
        self.assertIn(("Pozor, kluzko", True), advice)

    def test_warm_sunny_day(self):
        rows = [(h, 26 + h, 0, None, "sunny") for h in range(4)]
        entries = hourly(rows)
        for e in entries:
            e["uv_index"] = 7
        texts = self.texts(ui.day_outlook(entries, NOW), 27)
        self.assertEqual(texts[0], "Nalehko")
        self.assertIn("Opalovací krém", texts)
        self.assertIn("Voda s sebou", texts)

    def test_the_coldest_moment_decides(self):
        outlook = ui.day_outlook(hourly([(0, 14, 0, None, "sunny"), (6, 2, 0, None, "clear-night")]), NOW)
        self.assertIn("Teplá bunda", self.texts(outlook, 14))


class AlertTests(unittest.TestCase):
    def test_only_active_entities_are_named(self):
        states = {"binary_sensor.door": ("on", "Balkon"), "light.hall": ("off", "Chodba"),
                  "lock.front": ("unlocked", "Zámek")}
        ctx = types.SimpleNamespace(
            state=lambda e, default=None: states.get(e, (default,))[0],
            attr=lambda e, name, default=None: states.get(e, (None, default))[1],
        )
        self.assertEqual(ui.active_alerts(ctx, "binary_sensor.door, light.hall, lock.front, sensor.missing"),
                         ["Balkon", "Zámek"])


if __name__ == "__main__":
    unittest.main()
