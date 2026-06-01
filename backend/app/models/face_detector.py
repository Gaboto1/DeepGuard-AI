"""
Face detector using MTCNN from facenet-pytorch.
Detects and crops faces from images for targeted deepfake analysis.
"""
from typing import Optional
import numpy as np
import torch
from PIL import Image
from loguru import logger

from app.config import settings


class FaceDetector:
    _instance: Optional["FaceDetector"] = None

    def __init__(self) -> None:
        self.device = torch.device(
            "cuda" if settings.DEVICE == "cuda" and torch.cuda.is_available() else "cpu"
        )
        self._detector = None
        self._loaded = False

    @classmethod
    def get_instance(cls) -> "FaceDetector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self) -> None:
        if self._loaded:
            return
        try:
            from facenet_pytorch import MTCNN
            self._detector = MTCNN(
                keep_all=True,
                device=self.device,
                min_face_size=30,
                thresholds=[0.6, 0.7, 0.7],
                post_process=False,
            )
            self._loaded = True
            logger.success(f"Face detector (MTCNN) loaded on {self.device}")
        except ImportError:
            logger.warning("facenet-pytorch not available. Face detection disabled.")
        except Exception as e:
            logger.warning(f"Face detector failed to load: {e}")

    def detect_faces(
        self, image: Image.Image, min_confidence: float = 0.90
    ) -> list[Image.Image]:
        """
        Detect and return face crops from an image.
        Returns list of PIL Images (face crops), largest face first.
        Falls back to the whole image if no faces found.
        """
        self.load()

        if self._detector is None:
            return []

        try:
            boxes, probs = self._detector.detect(image)

            if boxes is None or len(boxes) == 0:
                return []

            faces = []
            for box, prob in zip(boxes, probs):
                if prob is None or prob < min_confidence:
                    continue
                x1, y1, x2, y2 = (int(max(0, b)) for b in box)
                w, h = image.size
                x2 = min(x2, w)
                y2 = min(y2, h)
                if x2 <= x1 or y2 <= y1:
                    continue

                margin_x = int((x2 - x1) * 0.15)
                margin_y = int((y2 - y1) * 0.15)
                x1 = max(0, x1 - margin_x)
                y1 = max(0, y1 - margin_y)
                x2 = min(w, x2 + margin_x)
                y2 = min(h, y2 + margin_y)

                face = image.crop((x1, y1, x2, y2))
                area = (x2 - x1) * (y2 - y1)
                faces.append((area, prob, face))

            # Sort by area (largest face first)
            faces.sort(key=lambda x: x[0], reverse=True)
            return [f[2] for f in faces]

        except Exception as e:
            logger.debug(f"Face detection error: {e}")
            return []

    def get_primary_face(self, image: Image.Image) -> Optional[Image.Image]:
        """Returns the largest detected face, or None."""
        faces = self.detect_faces(image)
        return faces[0] if faces else None

    def count_faces(self, image: Image.Image) -> int:
        return len(self.detect_faces(image))
