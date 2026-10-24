"""Regression tests using fictional OCR tokens and an optional private local image."""
from pathlib import Path
import json
import os
import unittest
from unittest.mock import patch
import subprocess

import ocr


def line(text, x, y, width=180, height=30):
    return {'text': text, 'words': [{'text': text, 'x': x, 'y': y, 'width': width, 'height': height}]}


def report():
    return {'width': 1000, 'height': 2400, 'lines': [
        line('2024-05-20 08:15', 300, 30, 350),
        line('Current weight (kg)', 60, 100), line('75.25', 60, 155),
        line('Than last time (2024-05-07 07:40)', 60, 230, 400),
        line('Weight-0.40kg Bfp-0.20%', 60, 280, 400),
        line('BMI', 130, 500), line('24.6', 60, 570),
        line('Standard weight', 630, 500), line('68kg', 560, 570),
        line('Bfp', 130, 750), line('20.1%', 60, 820),
        line('Fat weight', 630, 750), line('15.1kg', 560, 820),
        line('WaterRate', 130, 1000), line('55.4%', 60, 1070),
        line('Water', 630, 1000), line('41.6kg', 560, 1070),
        line('MuscleRate', 130, 1250), line('73.6%', 60, 1320),
        line('Muscle', 630, 1250), line('55.2kg', 560, 1320),
        line('Bmr', 130, 1500), line('1650', 60, 1570),
        line('Vf', 630, 1500), line('8.1', 560, 1570),
    ]}


class ParserTests(unittest.TestCase):
    def test_current_date_and_weight_not_previous_delta(self):
        parsed = ocr.parse_ocr(report())['fields']
        self.assertEqual(parsed['measured_at'], '2024-05-20T08:15')
        self.assertEqual(parsed['weight'], 75.25)
        self.assertEqual(parsed['standard_weight'], 68)
        self.assertEqual(parsed['body_fat'], 20.1)

    def test_changed_numbers_are_read_not_seeded(self):
        payload = report()
        replacements = {'75.25': '71.38', '20.1%': '22.4%', '55.2kg': '52.1kg', '8.1': '7.2'}
        for entry in payload['lines']:
            if entry['text'] in replacements:
                entry['text'] = replacements[entry['text']]
                entry['words'][0]['text'] = entry['text']
        parsed = ocr.parse_ocr(payload)['fields']
        self.assertEqual(parsed['weight'], 71.38)
        self.assertEqual(parsed['body_fat'], 22.4)
        self.assertEqual(parsed['muscle_mass'], 52.1)
        self.assertEqual(parsed['visceral_fat'], 7.2)

    def test_missing_left_value_never_borrows_right_column(self):
        payload = report()
        payload['lines'] = [entry for entry in payload['lines'] if entry['text'] != '20.1%']
        parsed = ocr.parse_ocr(payload)['fields']
        self.assertIsNone(parsed['body_fat'])
        self.assertEqual(parsed['fat_mass'], 15.1)
        self.assertEqual(parsed['water_pct'], 55.4)

    def test_unlabelled_value_stays_unassigned(self):
        payload = report()
        payload['lines'] = [entry for entry in payload['lines'] if entry['text'] != 'Vf']
        parsed = ocr.parse_ocr(payload)
        self.assertIsNone(parsed['fields']['visceral_fat'])
        self.assertTrue(any('内脏脂肪' in text for text in parsed['warnings']))

    def test_chinese_inline_labels_and_signed_decimals(self):
        parsed = ocr.parse_ocr('2024年5月20日 08:15\n体重:75.25kg\n体脂率:20.1%\n骨骼肌量:30.2kg\n肥胖度:-1.4%\n肌肉控制:+0.6kg')['fields']
        self.assertEqual(parsed['weight'], 75.25)
        self.assertEqual(parsed['body_fat'], 20.1)
        self.assertEqual(parsed['skeletal_mass'], 30.2)
        self.assertEqual(parsed['obesity_pct'], -1.4)
        self.assertEqual(parsed['muscle_control'], .6)

    def test_ocr_decimal_punctuation_and_review_flag(self):
        parsed = ocr.parse_ocr('体重:75 ． 25kg\n体脂率:20 · 1 ％\n体重控制:+O.8kg')
        self.assertEqual(parsed['fields']['weight'], 75.25)
        self.assertEqual(parsed['fields']['body_fat'], 20.1)
        self.assertEqual(parsed['fields']['weight_control'], .8)
        self.assertTrue(any('O' in text for text in parsed['warnings']))

    def test_combined_two_column_lines_split_by_coordinates(self):
        payload = report()
        bmi, standard = payload['lines'][5], payload['lines'][7]
        values_left, values_right = payload['lines'][6], payload['lines'][8]
        payload['lines'][5:9] = [
            {'text': 'BMI Standard weight', 'words': bmi['words'] + standard['words']},
            {'text': '24.6 68kg', 'words': values_left['words'] + values_right['words']},
        ]
        fields = ocr.parse_ocr(payload)['fields']
        self.assertEqual(fields['bmi'], 24.6)
        self.assertEqual(fields['standard_weight'], 68)

    def test_ambiguous_same_label_is_empty(self):
        payload = report()
        payload['lines'] += [line('Muscle', 630, 1900), line('50kg', 560, 1970)]
        result = ocr.parse_ocr(payload)
        self.assertIsNone(result['fields']['muscle_mass'])
        self.assertTrue(any('多个不同数值' in text for text in result['warnings']))

    def test_unstructured_text_does_not_zip_labels_and_values(self):
        result = ocr.parse_ocr('BMI\n体脂率\n24.6\n20.1')
        self.assertIsNone(result['fields']['bmi'])
        self.assertIsNone(result['fields']['body_fat'])

    def test_timeout_returns_editable_empty_result(self):
        with patch.object(ocr, '_run', side_effect=subprocess.TimeoutExpired('OCR', 35)):
            result = ocr.extract_image(__file__)
        self.assertTrue(all(value is None for value in result['fields'].values()))
        self.assertIn('超时', result['warnings'][0])


class LocalEngineTests(unittest.TestCase):
    def test_optional_private_reference_image(self):
        # The image and its expected values stay outside the published repository.
        # A manifest contains {"image": "report.png", "expected": {"weight": 75}}.
        fixture = os.environ.get('BODY_JOURNAL_OCR_FIXTURE')
        if not fixture:
            self.skipTest('Set BODY_JOURNAL_OCR_FIXTURE to a private JSON manifest to run the native OCR check')
        manifest = Path(fixture).resolve()
        payload = json.loads(manifest.read_text(encoding='utf-8-sig'))
        image = (manifest.parent / payload['image']).resolve()
        self.assertTrue(image.is_file(), 'The fixture image must exist')
        expected = payload['expected']
        self.assertIsInstance(expected, dict)
        self.assertTrue(expected, 'Provide at least one expected field')
        if not ocr.available():
            self.skipTest('Windows OCR unavailable')
        result = ocr.extract_image(image)
        for field, value in expected.items():
            with self.subTest(field=field):
                self.assertIn(field, result['fields'])
                self.assertEqual(result['fields'][field], value)
        self.assertEqual(result['engine'], 'Windows OCR')


if __name__ == '__main__':
    unittest.main(verbosity=2)
