"""Train a YOLO building detector from the screenshots you corrected in the app.

1. In the app: Settings -> Export YOLO dataset (writes <data dir>/dataset).
2. pip install ultralytics
3. python train_yolo.py            (add --epochs 100 for a better model)
The trained weights are copied to <data dir>/models/coc_buildings.pt and the app uses them
automatically on the next start. Aim for 100+ corrected screenshots before expecting good results.
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.db import default_data_dir  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--epochs", type=int, default=60)
p.add_argument("--imgsz", type=int, default=960)
p.add_argument("--base", default="yolov8n.pt")
args = p.parse_args()

data_dir = default_data_dir()
yaml_path = os.path.join(data_dir, "dataset", "data.yaml")
if not os.path.exists(yaml_path):
    sys.exit(f"No dataset at {yaml_path}. Export it from Settings first.")

from ultralytics import YOLO  # noqa: E402

model = YOLO(args.base)
result = model.train(data=yaml_path, epochs=args.epochs, imgsz=args.imgsz, project=os.path.join(data_dir, "runs"))
best = os.path.join(str(result.save_dir), "weights", "best.pt")
os.makedirs(os.path.join(data_dir, "models"), exist_ok=True)
shutil.copy(best, os.path.join(data_dir, "models", "coc_buildings.pt"))
print("Model saved to", os.path.join(data_dir, "models", "coc_buildings.pt"))
