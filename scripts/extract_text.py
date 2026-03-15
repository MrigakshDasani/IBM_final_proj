import os
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

import cv2
import csv
import json
import easyocr
import numpy as np
from datetime import datetime
from ultralytics import YOLO
from pathlib import Path

# ──────────────────────────────────────────────
# CONFIGURATION — edit these paths as needed
# ──────────────────────────────────────────────
MODEL_PATH      = r'C:\Users\Admin\runs\detect\train8\weights\best.pt'
TEST_IMAGE_DIR  = r'C:\Users\Admin\runs\detect\train8'
OUTPUT_DIR      = r'c:\Users\Admin\Documents\Clg_stuff\SEM8\IBM_proj\results'
CONF_THRESHOLD  = 0.3
SAVE_CROPS      = True
SAVE_ANNOTATED  = True


# ──────────────────────────────────────────────
# INITIALIZE MODEL AND OCR
# ──────────────────────────────────────────────
print("[INFO] Loading YOLO model...")
model = YOLO(MODEL_PATH)

print("[INFO] Loading EasyOCR (first run downloads models, may take a minute)...")
reader = easyocr.Reader(['en'], gpu=False)


# ──────────────────────────────────────────────
# PREPROCESSING
# ──────────────────────────────────────────────
def preprocess_plate(plate_crop):
    """
    Enhance the cropped plate image for better OCR accuracy.
    """
    plate_crop = cv2.resize(plate_crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    gray = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gray


# ──────────────────────────────────────────────
# SAVE RESULTS TO CSV
# ──────────────────────────────────────────────
def save_to_csv(records, csv_path):
    fieldnames = ['image', 'plate_text', 'yolo_confidence', 'ocr_confidence', 'bbox', 'timestamp']
    file_exists = os.path.isfile(csv_path)
    with open(csv_path, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(records)


# ──────────────────────────────────────────────
# SAVE RESULTS TO JSON
# ──────────────────────────────────────────────
def save_to_json(all_records, json_path):
    existing = []
    if os.path.isfile(json_path):
        with open(json_path, 'r') as f:
            try:
                existing = json.load(f)
            except:
                existing = []
    existing.extend(all_records)
    with open(json_path, 'w') as f:
        json.dump(existing, f, indent=4)


# ──────────────────────────────────────────────
# MAIN DETECTION + OCR FUNCTION
# ──────────────────────────────────────────────
def detect_and_read_plate(image_path, output_dir):
    filename = os.path.basename(image_path)
    img = cv2.imread(str(image_path))

    if img is None:
        print(f"[WARNING] Could not read image: {image_path}")
        return []

    print(f"\n[INFO] Processing: {filename}")
    results = model(image_path)

    records = []
    annotated_img = img.copy()

    for result in results:
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            print(f"  [INFO] No plates detected in {filename}")
            continue

        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            yolo_conf = float(box.conf[0])

            plate_crop = img[y1:y2, x1:x2]
            if plate_crop.size == 0:
                continue

            processed = preprocess_plate(plate_crop)
            ocr_results = reader.readtext(processed)

            plate_texts = [(text, conf) for (_, text, conf) in ocr_results if conf >= CONF_THRESHOLD]
            plate_text  = ' '.join([t for t, c in plate_texts]).strip()
            avg_ocr_conf = round(sum([c for t, c in plate_texts]) / len(plate_texts), 4) if plate_texts else 0.0

            print(f"  [RESULT] Box {i+1}: '{plate_text}' | YOLO conf: {yolo_conf:.2f} | OCR conf: {avg_ocr_conf:.2f}")

            if SAVE_CROPS and plate_text:
                crops_dir = os.path.join(output_dir, 'crops')
                os.makedirs(crops_dir, exist_ok=True)
                crop_name = f"{os.path.splitext(filename)[0]}_plate{i+1}.jpg"
                cv2.imwrite(os.path.join(crops_dir, crop_name), plate_crop)

            color = (0, 255, 0)
            cv2.rectangle(annotated_img, (x1, y1), (x2, y2), color, 2)
            label = plate_text if plate_text else "No Text"
            cv2.putText(annotated_img, label, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

            records.append({
                'image'          : filename,
                'plate_text'     : plate_text,
                'yolo_confidence': round(yolo_conf, 4),
                'ocr_confidence' : avg_ocr_conf,
                'bbox'           : f"[{x1},{y1},{x2},{y2}]",
                'timestamp'      : datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })

    if SAVE_ANNOTATED:
        annotated_dir = os.path.join(output_dir, 'annotated')
        os.makedirs(annotated_dir, exist_ok=True)
        cv2.imwrite(os.path.join(annotated_dir, filename), annotated_img)

    return records


# ──────────────────────────────────────────────
# RUN ON ALL IMAGES IN TEST FOLDER
# ──────────────────────────────────────────────
def run_on_folder(image_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    csv_path  = os.path.join(output_dir, 'extracted_plates.csv')
    json_path = os.path.join(output_dir, 'extracted_plates.json')

    supported_exts = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff')
    image_files = [f for f in os.listdir(image_dir) if f.lower().endswith(supported_exts)]

    if not image_files:
        print(f"[ERROR] No images found in {image_dir}")
        return

    print(f"[INFO] Found {len(image_files)} images to process.")
    all_records = []

    for img_file in image_files:
        img_path = os.path.join(image_dir, img_file)
        records  = detect_and_read_plate(img_path, output_dir)
        all_records.extend(records)
        if records:
            save_to_csv(records, csv_path)

    if all_records:
        save_to_json(all_records, json_path)

    print("\n" + "="*50)
    print(f"[DONE] Processed {len(image_files)} images.")
    print(f"[DONE] Total plates detected: {len(all_records)}")
    print("="*50)


if __name__ == '__main__':
    run_on_folder(TEST_IMAGE_DIR, OUTPUT_DIR)