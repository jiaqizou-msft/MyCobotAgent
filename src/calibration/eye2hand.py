"""
Eye-to-hand calibration: pixel coordinates → robot base frame coordinates.

Uses a simple N-point linear interpolation (minimum 2 points).
For better accuracy, use more calibration points and fit an affine transform.
"""

import logging
from typing import List, Tuple

import numpy as np

from src.cobot.config import get_config

logger = logging.getLogger(__name__)


class Eye2Hand:
    """
    Transforms pixel (u, v) from the overhead camera image
    to robot workspace (X_mc, Y_mc) in the robot base frame.

    Supports two modes:
      - 2-point linear interpolation (default, from config.yaml)
      - N-point affine transform (call calibrate_affine with ≥ 3 point pairs)
    """

    def __init__(self):
        cfg = get_config().calibration
        self.pixel_1 = cfg.pixel_1
        self.robot_1 = cfg.robot_1
        self.pixel_2 = cfg.pixel_2
        self.robot_2 = cfg.robot_2
        self._affine_matrix = None  # set if calibrate_affine() is called

    # ── 2-point linear interpolation ─────────────────────────────────────

    def pixel_to_robot_linear(self, u: float, v: float) -> Tuple[float, float]:
        """
        Convert pixel (u, v) to robot (X, Y) using 2-point linear interp.
        """
        X_cali_im = [self.pixel_1[0], self.pixel_2[0]]
        X_cali_mc = [self.robot_1[0], self.robot_2[0]]
        Y_cali_im = [self.pixel_2[1], self.pixel_1[1]]  # ascending order
        Y_cali_mc = [self.robot_2[1], self.robot_1[1]]

        X_mc = float(np.interp(u, X_cali_im, X_cali_mc))
        Y_mc = float(np.interp(v, Y_cali_im, Y_cali_mc))
        return X_mc, Y_mc

    # ── N-point affine transform (more accurate) ─────────────────────────

    def calibrate_affine(
        self,
        pixel_points: List[Tuple[float, float]],
        robot_points: List[Tuple[float, float]],
    ):
        """
        Compute an affine transformation matrix from ≥ 3 corresponding
        pixel↔robot point pairs.

        pixel_points: [(u1,v1), (u2,v2), ...]
        robot_points: [(x1,y1), (x2,y2), ...]
        """
        n = len(pixel_points)
        if n < 3:
            raise ValueError("Need at least 3 calibration points for affine transform.")
        if n != len(robot_points):
            raise ValueError("pixel_points and robot_points must have the same length.")

        # Build least-squares system: [u, v, 1] * M = [x, y]
        A = np.zeros((n, 3))
        B = np.zeros((n, 2))
        for i in range(n):
            A[i] = [pixel_points[i][0], pixel_points[i][1], 1]
            B[i] = [robot_points[i][0], robot_points[i][1]]

        # Solve A @ M = B  →  M = (A^T A)^-1 A^T B
        M, _, _, _ = np.linalg.lstsq(A, B, rcond=None)
        self._affine_matrix = M
        logger.info(f"Affine calibration computed from {n} points:\n{M}")

    def pixel_to_robot_affine(self, u: float, v: float) -> Tuple[float, float]:
        """Convert pixel (u,v) to robot (X,Y) using the affine matrix."""
        if self._affine_matrix is None:
            raise RuntimeError("Affine calibration not computed yet. Call calibrate_affine() first.")
        pt = np.array([u, v, 1.0])
        result = pt @ self._affine_matrix
        return float(result[0]), float(result[1])

    # ── Unified interface ────────────────────────────────────────────────

    def pixel_to_robot(self, u: float, v: float) -> Tuple[float, float]:
        """
        Convert pixel to robot coords using the best available method.
        If affine calibration has been done, use it; otherwise fall back to linear.
        """
        if self._affine_matrix is not None:
            return self.pixel_to_robot_affine(u, v)
        return self.pixel_to_robot_linear(u, v)

    def update_linear_calibration(
        self,
        pixel_1: List[float], robot_1: List[float],
        pixel_2: List[float], robot_2: List[float],
    ):
        """Update the 2-point calibration values at runtime."""
        self.pixel_1 = pixel_1
        self.robot_1 = robot_1
        self.pixel_2 = pixel_2
        self.robot_2 = robot_2
        logger.info(f"Linear calibration updated: px1={pixel_1} mc1={robot_1}, px2={pixel_2} mc2={robot_2}")


# Singleton
_eye2hand = None

def get_eye2hand() -> Eye2Hand:
    global _eye2hand
    if _eye2hand is None:
        _eye2hand = Eye2Hand()
    return _eye2hand
