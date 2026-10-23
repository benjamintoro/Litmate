"""Agregados del benchmark: mediciones ausentes no se convierten en éxitos."""
from unittest import TestCase

from resumir_benchmark_ia import summarize


class BenchmarkSummaryTests(TestCase):
    def test_percentiles_stages_model_calls_and_resources(self):
        rows = [
            {'seconds': 1, 'status': 'answered', 'model_calls': 0,
             'first_progress_seconds': .02, 'first_text_seconds': 1,
             'diagnostics': {'exact_answer_cache_hit': True,
                             'progress_metrics': {'elapsed_ms': 900,
                                                  'stage_totals_ms': {'cache_lookup': 4}}},
             'resources': {'rss_mb': 50, 'peak_rss_mb': 60, 'cpu_seconds': .1}},
            {'seconds': 31, 'status': 'unavailable', 'model_calls': None,
             'stage_totals_ms': {'generation': 30000},
             'diagnostics': {'stage_timings': [
                 {'stage': 'answer', 'elapsed_ms': 12000, 'model': 'local'},
                 {'stage': 'answer', 'elapsed_ms': 18000, 'model': 'local'}]},
             'resources': {'rss_mb': 70, 'peak_rss_mb': 80, 'cpu_seconds': .2}},
        ]
        result = summarize(rows)
        self.assertEqual(result['p50_seconds'], 16)
        self.assertEqual(result['p95_seconds'], 31)
        self.assertEqual(result['under_30_seconds'], 1)
        self.assertEqual(result['answered_under_30_seconds'], 1)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['model_calls_unknown_turns'], 1)
        self.assertEqual(result['exact_answer_cache_hits'], 1)
        self.assertEqual(result['model_stage_calls'], {'answer': 2})
        self.assertEqual(result['stage_totals_ms'], {'cache_lookup': 4, 'generation': 30000})
        self.assertEqual(result['delivery_overhead_p50_ms'], 100)
        self.assertEqual(result['max_rss_mb'], 70)
        self.assertEqual(result['peak_rss_mb'], 80)
        self.assertEqual(result['cpu_seconds'], .3)

    def test_empty_and_invalid_measurements_are_not_fabricated(self):
        self.assertIsNone(summarize([])['p95_seconds'])
        result = summarize([{'model_calls': float('inf'), 'seconds': float('nan')},
                            {'model_calls': -1, 'seconds': True}])
        self.assertIsNone(result['p50_seconds'])
        self.assertEqual(result['model_calls_unknown_turns'], 2)
        self.assertEqual(result['under_5_seconds'], 0)
