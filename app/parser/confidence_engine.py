"""
Confidence Engine.
Aggregates confidence scores from each parser module into an overall score.
"""
from typing import Dict


class ConfidenceEngine:
    """
    Computes a weighted confidence score from individual module scores.
    """

    # Weights for each module (sum = 1.0)
    _WEIGHTS: Dict[str, float] = {
        "claim_detection": 0.25,
        "dependency": 0.20,
        "transition": 0.15,
        "enumeration": 0.15,
        "semicolon": 0.10,
        "hierarchy": 0.15,
    }

    def compute(self, module_scores: Dict[str, float]) -> float:
        """
        Computes the weighted average confidence score.
        module_scores should map module names to scores (0-100).
        Any module not provided defaults to 100 (assumed perfect).
        """
        total_weight = 0.0
        weighted_sum = 0.0

        for module, weight in self._WEIGHTS.items():
            score = module_scores.get(module, 100.0)
            weighted_sum += score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0
        return round(weighted_sum / total_weight, 2)

    def build_report(self, module_scores: Dict[str, float]) -> Dict:
        """
        Builds a detailed confidence report for diagnostics.
        """
        overall = self.compute(module_scores)
        return {
            "confidence": overall,
            "modules": {k: module_scores.get(k, 100.0) for k in self._WEIGHTS},
        }
