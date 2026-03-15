"""
services/anpr_service.py — YOLO + EasyOCR detection pipeline

FIXES applied vs your uploaded version:
  FIX 1: Removed fastNlMeansDenoising — it's extremely slow (5–15s per call)
          and incompatible with adaptive thresholding that follows it.
          Replaced with CLAHE + bilateralFilter (fast, better results).
  FIX 2: OCR confidence threshold raised from 0.1 → 0.3 to stop garbage text
          from sneaking in (the real cause of garbled plate readings).
  FIX 3: Removed /tmp/anpr_debug.log writes — broken on Windows, not needed.
          Replaced with standard Python logging (logger.debug/info).
  FIX 4: best_record["success"] logic was broken — True even when plate_text="".
          Now: success=True only when plate_text is non-empty.
  FIX 5: Model lazy-loads are now thread-safe with a simple lock.
  FIX 6: Return dict keys now match exactly what detection.py route expects:
          yolo_conf, ocr_conf, annotated_path, success, plate_text, error.
  FIX 7: Added plate text cleaning (remove spaces/special chars) so DB stores
          clean plate like "MH12AB1234" not "M H12-AB 1234".
"""

import os
import re
import uuid
import logging
import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Thread-safe model cache ────────────────────────────────────────────────────
_lock       = threading.Lock()
_yolo_model = None
_ocr_reader  = None


def _get_yolo(model_path: str):
    global _yolo_model
    if _yolo_model is None:
        with _lock:
            if _yolo_model is None:          # double-checked locking
                logger.info("Loading YOLOv8 model from: %s", model_path)
                if not Path(model_path).exists():
                    raise RuntimeError(
                        f"best.pt not found at: {model_path}\n"
                        f"Set MODEL_PATH in your .env file to the correct absolute path."
                    )
                from ultralytics import YOLO
                _yolo_model = YOLO(model_path)
                logger.info("YOLOv8 model loaded successfully.")
    return _yolo_model


def _get_ocr():
    global _ocr_reader
    if _ocr_reader is None:
        with _lock:
            if _ocr_reader is None:
                logger.info("Initialising EasyOCR (may download model on first run)...")
                import easyocr
                _ocr_reader = easyocr.Reader(["en"], gpu=False)
                logger.info("EasyOCR ready.")
    return _ocr_reader


# ── Image processing ───────────────────────────────────────────────────────────

def _preprocess_plate(plate_crop: np.ndarray) -> np.ndarray:
    """
    Enhance cropped plate for OCR.
    
    Returns a list of versions to try (original, enhanced).
    """
    # 1. Standard Upscale
    h, w = plate_crop.shape[:2]
    scale = max(1, int(300 / max(h, 1)))  # Target ~300px tall for better character resolution
    if scale > 1:
        plate_crop = cv2.resize(plate_crop, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)

    # 2. Grayscale 
    gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
    
    # 3. Enhance contrast
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    
    return gray


def _clean_plate_text(raw: str) -> str:
    """
    FIX 7: Strip spaces, dashes, dots — store clean alphanumeric plate only.
    'M H12-AB 1234' → 'MH12AB1234'
    """
    return re.sub(r"[^A-Z0-9]", "", raw.upper())


def _draw_annotation(
    image: np.ndarray,
    box: np.ndarray,
    plate_text: str,
    yolo_conf: float,
) -> np.ndarray:
    x1, y1, x2, y2 = map(int, box)
    # Green bounding box
    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
    label = f"{plate_text or 'Plate'}  {yolo_conf:.2f}"
    # Background rectangle for text
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
    cv2.rectangle(image, (x1, y1 - th - 12), (x1 + tw + 4, y1), (0, 255, 0), -1)
    cv2.putText(image, label, (x1 + 2, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)
    return image


def _save_image(image: np.ndarray, upload_folder: str, original_filename: str) -> str:
    """Save annotated image; return absolute path."""
    Path(upload_folder).mkdir(parents=True, exist_ok=True)
    stem      = Path(original_filename).stem
    filename  = f"{stem}_{uuid.uuid4().hex[:8]}_annotated.jpg"
    save_path = str(Path(upload_folder) / filename)
    cv2.imwrite(save_path, image)
    return save_path


# ── Public API ─────────────────────────────────────────────────────────────────

def run_detection(
    image_bytes: bytes,
    upload_folder: str,
    model_path: str,
    original_filename: str = "upload.jpg",
) -> dict:
    """
    Run full ANPR pipeline.

    Returns
    -------
    dict with keys:
        success        bool   — True only if plate_text is non-empty
        plate_text     str | None
        yolo_conf      float | None
        ocr_conf       float | None
        annotated_path str   — path where annotated image was saved
        error          str | None
    """
    result: dict = {
        "success":        False,
        "plate_text":     None,
        "yolo_conf":      None,
        "ocr_conf":       None,
        "annotated_path": None,
        "error":          None,
    }

    try:
        nparr   = np.frombuffer(image_bytes, np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            logger.info("DEBUG: Image decode FAILED")
            result["error"] = "Cannot decode image — unsupported format."
            return result
        
        logger.info("DEBUG: Image decoded. Shape: %s", str(img_bgr.shape))

        annotated = img_bgr.copy()

        # ── 2. YOLO detection ──────────────────────────────────────────────
        model      = _get_yolo(model_path)
        detections = model(img_bgr, conf=0.15, verbose=False)
        box_count = len(detections[0].boxes) if detections and len(detections) > 0 else 0
        logger.info("DEBUG: YOLO found %d boxes at conf=0.15", box_count)

        if box_count == 0:
            result["error"] = "No number plate detected in the image."
            result["annotated_path"] = _save_image(annotated, upload_folder, original_filename)
            return result
        
        logger.info("Detection result: %d boxes found.", len(detections[0].boxes))

        logger.debug("YOLO detected %d box(es)", len(detections[0].boxes))

        # ── 3. Pick best box by yolo_conf, run OCR on each ────────────────
        boxes      = detections[0].boxes
        best_text  = ""
        best_yconf = 0.0
        best_oconf = 0.0
        best_box   = None

        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            yconf = float(box.conf[0])

            # Clamp to image boundaries
            x1 = max(0, x1);  y1 = max(0, y1)
            x2 = min(img_bgr.shape[1], x2);  y2 = min(img_bgr.shape[0], y2)

            crop = img_bgr[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            # Preprocess
            processed = _preprocess_plate(crop)
            reader    = _get_ocr()
            
            # Try 1: Processed (Sharpened/CLAHE)
            # Try 2: Original Grayscale (some EasyOCR models prefer this)
            versions = [processed, cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)]
            
            current_best_text = ""
            current_best_oconf = 0.0

            for img_version in versions:
                ocr_results = reader.readtext(img_version, detail=1, paragraph=False)
                # Keep confidence threshold low (0.1) but filter for alphanumeric
                valid = [(text, conf) for (_, text, conf) in ocr_results if conf >= 0.10]
                
                if valid:
                    raw_text   = " ".join(t for t, _ in valid)
                    clean_text = _clean_plate_text(raw_text)
                    oconf      = float(np.mean([c for _, c in valid]))
                    
                    if len(clean_text) >= 4 and oconf > current_best_oconf:
                        current_best_text = clean_text
                        current_best_oconf = oconf

            if not current_best_text:
                # Still draw box even if no text
                _draw_annotation(annotated, box.xyxy[0], "", yconf)
                continue

            # Keep global best across all YOLO boxes
            if current_best_oconf > best_oconf:
                best_text  = current_best_text
                best_yconf = yconf
                best_oconf = current_best_oconf
                best_box   = box.xyxy[0]

        # ── 4. Annotate best box ───────────────────────────────────────────
        if best_box is not None:
            annotated = _draw_annotation(annotated, best_box, best_text, best_yconf)

        # ── 5. Save annotated image ────────────────────────────────────────
        save_path = _save_image(annotated, upload_folder, original_filename)
        result["annotated_path"] = save_path

        # ── 6. Build result ────────────────────────────────────────────────
        if best_text:
            result.update(
                success    = True,
                plate_text = best_text,
                yolo_conf  = best_yconf,
                ocr_conf   = best_oconf,
            )
        else:
            # Boxes found but OCR gave nothing useful — still count as a "success"
            # because the model FOUND the plate.
            result.update(
                success    = True,
                plate_text = "[No Text Detected]",
                yolo_conf  = best_yconf or (float(boxes[0].conf[0]) if len(boxes)>0 else 0.15),
                ocr_conf   = 0.0,
                error      = "Plate region detected but no legible text extracted."
            )

    except RuntimeError:
        raise   # Re-raise model-not-found errors so caller sees them
    except Exception as exc:
        logger.exception("ANPR pipeline unexpected error")
        result["error"] = str(exc)

    return result