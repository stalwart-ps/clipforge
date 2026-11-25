"""Shared GPU Face Engine: SCRFD-10GF Face Detection & ArcFace ResNet50 Embedding.

Uses ONLY numpy, cv2, and onnxruntime.
Supports CUDAExecutionProvider with automatic CPUExecutionProvider fallback.
"""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

# Preload DLLs on Windows for pip-installed CUDA/cuDNN packages
try:
    if hasattr(ort, "preload_dlls"):
        ort.preload_dlls()
except Exception:
    pass

# Standard ArcFace 5-point alignment destination coordinates (112x112)
ARCFACE_DST_112 = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def _nms(boxes: np.ndarray, scores: np.ndarray, thresh: float = 0.40) -> list[int]:
    """Greedy Non-Maximum Suppression."""
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]

    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-7)

        inds = np.where(ovr <= thresh)[0]
        order = order[inds + 1]
    return keep


class FaceEngine:
    """Self-contained GPU Face Detection (SCRFD-10GF) and Recognition (ArcFace) Engine."""

    def __init__(self, load_recognizer: bool = True):
        self.model_dir = Path(__file__).resolve().parents[1] / "models" / "face"
        self.det_model_path = self.model_dir / "det_10g.onnx"
        self.rec_model_path = self.model_dir / "w600k_r50.onnx"

        if not self.det_model_path.exists():
            raise FileNotFoundError(f"SCRFD detector model not found at: {self.det_model_path}")

        cuda_options = {"gpu_mem_limit": 2 * 1024 * 1024 * 1024}
        providers = [("CUDAExecutionProvider", cuda_options), "CPUExecutionProvider"]

        # Detector Session
        try:
            self.det_session = ort.InferenceSession(str(self.det_model_path), providers=providers)
        except Exception:
            self.det_session = ort.InferenceSession(str(self.det_model_path), providers=["CPUExecutionProvider"])

        # Recognizer Session
        self.rec_session = None
        if load_recognizer and self.rec_model_path.exists():
            try:
                self.rec_session = ort.InferenceSession(str(self.rec_model_path), providers=providers)
            except Exception:
                self.rec_session = ort.InferenceSession(str(self.rec_model_path), providers=["CPUExecutionProvider"])

        active_provider = self.det_session.get_providers()[0] if self.det_session.get_providers() else "CPUExecutionProvider"
        print(f"[CLIPFORGE VISION] FaceEngine active on {active_provider}", flush=True)

    def close(self):
        """Release ONNX sessions and collect garbage to free GPU VRAM."""
        if hasattr(self, "det_session") and self.det_session is not None:
            del self.det_session
            self.det_session = None
        if hasattr(self, "rec_session") and self.rec_session is not None:
            del self.rec_session
            self.rec_session = None
        gc.collect()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    def detect(
        self,
        frame_bgr: np.ndarray,
        input_size: tuple[int, int] = (640, 640),
        score_thresh: float = 0.35,
        nms_thresh: float = 0.40,
    ) -> list[dict]:
        """Detect faces using SCRFD-10GF.

        Args:
            frame_bgr: Input BGR image (H, W, 3).
            input_size: Target inference resolution (det_w, det_h).
            score_thresh: Confidence score threshold.
            nms_thresh: NMS IoU threshold.

        Returns:
            List of dicts: {"x", "y", "w", "h", "cx", "cy", "score", "confidence", "kps": [[x_px, y_px], ...]}
            sorted by confidence descending.
        """
        if self.det_session is None or frame_bgr is None or frame_bgr.size == 0:
            return []

        img_h, img_w = frame_bgr.shape[:2]
        det_w, det_h = input_size

        # Letterbox-resize preserving aspect ratio onto a zero-padded canvas
        im_ratio = float(img_h) / img_w
        model_ratio = float(det_h) / det_w
        if im_ratio > model_ratio:
            new_h = det_h
            new_w = int(round(new_h / im_ratio))
        else:
            new_w = det_w
            new_h = int(round(new_w * im_ratio))

        det_scale = float(new_h) / img_h
        resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        det_img = np.zeros((det_h, det_w, 3), dtype=np.uint8)
        det_img[:new_h, :new_w, :] = resized

        # BGR -> RGB, normalize (img - 127.5) / 128.0, transpose to [1, 3, H, W]
        rgb_img = cv2.cvtColor(det_img, cv2.COLOR_BGR2RGB)
        blob = (rgb_img.astype(np.float32) - 127.5) / 128.0
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, :]

        input_name = self.det_session.get_inputs()[0].name
        net_outs = self.det_session.run(None, {input_name: blob})

        # Match 9 outputs across strides: feat_stride_fpn=[8, 16, 32], num_anchors=2
        # For each stride: scores [N, 1], bbox distances [N, 4] * stride, keypoint offsets [N, 10] * stride
        reshaped_outs: list[np.ndarray] = []
        for out in net_outs:
            arr = np.asarray(out)
            if arr.ndim == 3 and arr.shape[0] == 1:
                arr = arr[0]
            last_dim = arr.shape[-1]
            reshaped_outs.append(arr.reshape((-1, last_dim)))

        feat_strides = [8, 16, 32]
        all_boxes: list[np.ndarray] = []
        all_scores: list[np.ndarray] = []
        all_kpss: list[np.ndarray] = []

        for s in feat_strides:
            fh = det_h // s
            fw = det_w // s
            expected_n = fh * fw * 2

            stride_score: np.ndarray | None = None
            stride_bbox: np.ndarray | None = None
            stride_kps: np.ndarray | None = None

            for arr in reshaped_outs:
                if arr.shape[0] == expected_n:
                    if arr.shape[1] == 1 and stride_score is None:
                        stride_score = arr
                    elif arr.shape[1] == 4 and stride_bbox is None:
                        stride_bbox = arr
                    elif arr.shape[1] == 10 and stride_kps is None:
                        stride_kps = arr

            if stride_score is None or stride_bbox is None or stride_kps is None:
                continue

            scores = stride_score.flatten()
            pos_inds = np.where(scores >= score_thresh)[0]
            if len(pos_inds) == 0:
                continue

            # Anchor centers per cell
            y_grid, x_grid = np.mgrid[:fh, :fw]
            centers = np.stack([x_grid, y_grid], axis=-1).astype(np.float32) * s
            centers = centers.reshape((-1, 2))
            centers = np.repeat(centers, 2, axis=0)  # [expected_n, 2]

            pos_scores = scores[pos_inds]
            pos_centers = centers[pos_inds]
            pos_bbox = stride_bbox[pos_inds] * s
            pos_kps = stride_kps[pos_inds] * s

            # Bounding box reconstruction: [x1, y1, x2, y2]
            x1 = pos_centers[:, 0] - pos_bbox[:, 0]
            y1 = pos_centers[:, 1] - pos_bbox[:, 1]
            x2 = pos_centers[:, 0] + pos_bbox[:, 2]
            y2 = pos_centers[:, 1] + pos_bbox[:, 3]

            # Scale back to original pixel coordinates
            x1_orig = np.clip(x1 / det_scale, 0, img_w)
            y1_orig = np.clip(y1 / det_scale, 0, img_h)
            x2_orig = np.clip(x2 / det_scale, 0, img_w)
            y2_orig = np.clip(y2 / det_scale, 0, img_h)
            boxes_orig = np.stack([x1_orig, y1_orig, x2_orig, y2_orig], axis=1)

            # Keypoints reconstruction: 5 keypoints [(lx, ly), ...]
            kps_orig = np.zeros((len(pos_inds), 10), dtype=np.float32)
            for k in range(5):
                kp_x = pos_centers[:, 0] + pos_kps[:, k * 2]
                kp_y = pos_centers[:, 1] + pos_kps[:, k * 2 + 1]
                kps_orig[:, k * 2] = np.clip(kp_x / det_scale, 0, img_w)
                kps_orig[:, k * 2 + 1] = np.clip(kp_y / det_scale, 0, img_h)

            all_boxes.append(boxes_orig)
            all_scores.append(pos_scores)
            all_kpss.append(kps_orig)

        if not all_boxes:
            return []

        boxes_cat = np.concatenate(all_boxes, axis=0)
        scores_cat = np.concatenate(all_scores, axis=0)
        kpss_cat = np.concatenate(all_kpss, axis=0)

        keep = _nms(boxes_cat, scores_cat, thresh=nms_thresh)
        if not keep:
            return []

        results: list[dict] = []
        for idx in keep:
            bx1, by1, bx2, by2 = boxes_cat[idx]
            bw = max(0.0, bx2 - bx1)
            bh = max(0.0, by2 - by1)
            norm_x = max(0.0, min(1.0, float(bx1 / img_w)))
            norm_y = max(0.0, min(1.0, float(by1 / img_h)))
            norm_w = max(0.0, min(1.0 - norm_x, float(bw / img_w)))
            norm_h = max(0.0, min(1.0 - norm_y, float(bh / img_h)))
            norm_cx = norm_x + norm_w / 2.0
            norm_cy = norm_y + norm_h / 2.0
            sc = float(scores_cat[idx])

            kp_pts = [[float(kpss_cat[idx, k * 2]), float(kpss_cat[idx, k * 2 + 1])] for k in range(5)]

            results.append({
                "x": round(norm_x, 4),
                "y": round(norm_y, 4),
                "w": round(norm_w, 4),
                "h": round(norm_h, 4),
                "cx": round(norm_cx, 4),
                "cy": round(norm_cy, 4),
                "score": round(sc, 4),
                "confidence": round(sc, 4),
                "kps": kp_pts,
            })

        results.sort(key=lambda f: f["score"], reverse=True)
        return results

    def get_embedding(self, frame_bgr: np.ndarray, kps: list | np.ndarray) -> np.ndarray | None:
        """Align face using 5 keypoints and extract ArcFace 512-dim L2-normalized embedding."""
        if self.rec_session is None or frame_bgr is None or frame_bgr.size == 0:
            return None

        src_kps = np.asarray(kps, dtype=np.float32).reshape((5, 2))
        M, _ = cv2.estimateAffinePartial2D(src_kps, ARCFACE_DST_112, method=cv2.LMEDS)
        if M is None:
            M = cv2.getAffineTransform(src_kps[:3], ARCFACE_DST_112[:3])

        crop = cv2.warpAffine(frame_bgr, M, (112, 112), borderValue=0.0)
        crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        blob = (crop_rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, :]  # [1, 3, 112, 112]

        input_name = self.rec_session.get_inputs()[0].name
        outs = self.rec_session.run(None, {input_name: blob})
        emb = outs[0].flatten().astype(np.float32)
        norm = float(np.linalg.norm(emb))
        if norm > 1e-6:
            emb = emb / norm
        return emb

    @staticmethod
    def cosine_similarity(emb1: np.ndarray | None, emb2: np.ndarray | None) -> float:
        """Calculate cosine similarity between two L2-normalized vectors in [-1, 1]."""
        if emb1 is None or emb2 is None:
            return 0.0
        val = float(np.dot(emb1.flatten(), emb2.flatten()))
        return float(np.clip(val, -1.0, 1.0))
