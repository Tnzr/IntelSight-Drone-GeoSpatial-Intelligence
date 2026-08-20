import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "modules" / "cv-pipeline"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from spatial_feature_matching import (
    MatchConfig,
    binary_similarity_matrix,
    build_spatial_buckets,
    mutual_nearest_matches,
    pairwise_hamming_distance,
    spatial_candidate_ids,
)


class SpatialFeatureMatchingTests(unittest.TestCase):
    def test_pairwise_hamming_distance_and_similarity(self) -> None:
        current = np.array([[0, 0], [255, 0]], dtype=np.uint8)
        previous = np.array([[0, 0], [255, 255]], dtype=np.uint8)

        distances = pairwise_hamming_distance(current, previous, device="cpu")
        similarities = binary_similarity_matrix(current, previous, device="cpu")

        np.testing.assert_array_equal(distances, np.array([[0, 16], [8, 8]], dtype=np.int16))
        np.testing.assert_allclose(similarities, np.array([[1.0, 0.0], [0.5, 0.5]], dtype=np.float32))

    def test_mutual_nearest_filter_prevents_many_to_one_matches(self) -> None:
        rng = np.random.default_rng(17)
        previous = rng.integers(0, 256, size=(4, 32), dtype=np.uint8)
        current = previous.copy()
        current[1] = current[0]
        config = MatchConfig(device="cpu", dynamic_threshold_sigma=0.0, min_similarity=0.7)

        matches = mutual_nearest_matches(current, previous, config)
        train_indices = [match.train_index for match in matches]

        self.assertEqual(len(train_indices), len(set(train_indices)))
        self.assertIn((0, 0), {(match.query_index, match.train_index) for match in matches})
        self.assertNotIn((1, 0), {(match.query_index, match.train_index) for match in matches})

    def test_spatial_grid_returns_only_neighboring_cells(self) -> None:
        gallery = {
            1: {"xyxy": [10, 10, 50, 50]},
            2: {"xyxy": [170, 10, 210, 50]},
            3: {"xyxy": [650, 650, 700, 700]},
        }
        config = MatchConfig(grid_size=160, neighborhood=1)
        buckets = build_spatial_buckets(gallery, config.grid_size)

        candidates = spatial_candidate_ids([20, 20, 60, 60], buckets, config)

        self.assertEqual(candidates, {1, 2})

    def test_descriptor_validation_rejects_float_embeddings(self) -> None:
        with self.assertRaisesRegex(TypeError, "ORB descriptors must use uint8"):
            pairwise_hamming_distance(
                np.zeros((2, 32), dtype=np.float32),
                np.zeros((2, 32), dtype=np.float32),
                device="cpu",
            )


if __name__ == "__main__":
    unittest.main()
