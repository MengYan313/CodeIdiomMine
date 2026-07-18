import unittest

import torch

from src.mining.clustering import ClusteringProcessor
from src.mining.code_embedding import is_within_extent, parse_extent


class MiningHelperTests(unittest.TestCase):
    def test_extent_helpers(self):
        self.assertEqual(parse_extent("1-0-4-1"), (1, 0, 4, 1))
        self.assertTrue(is_within_extent("1-0-4-1", "2-2-3-4"))
        self.assertFalse(is_within_extent("2-2-3-4", "1-0-4-1"))

    def test_dbscan_preserves_cluster_schema(self):
        embeddings = [
            torch.tensor([[1.0, 0.0]]),
            torch.tensor([[0.9, 0.1]]),
            torch.tensor([[0.0, 1.0]]),
        ]
        sources = ["return first;", "return medoid;", "return third;"]
        infos = [
            ["sample", "sample.cpp", "1-0-1-13", {}],
            ["sample", "sample.cpp", "2-0-2-14", {}],
            ["sample", "sample.cpp", "3-0-3-13", {}],
        ]

        labels, clusters = ClusteringProcessor.perform_dbscan_clustering(
            "sample",
            sources,
            embeddings,
            infos,
            eps=1.0,
            min_samples=2,
        )

        self.assertEqual(labels.tolist(), [0, 0, 0])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(int(clusters.iloc[0]["cluster_size"]), 3)
        self.assertEqual(clusters.iloc[0]["center_point"], "return medoid;")
        self.assertEqual(
            clusters.columns.tolist(),
            [
                "label",
                "center_point",
                "else_point",
                "cluster_size",
                "center_point_info",
                "infos",
                "loc_label",
            ],
        )


if __name__ == "__main__":
    unittest.main()
