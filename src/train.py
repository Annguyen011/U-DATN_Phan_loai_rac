"""
train.py — Train YOLOv11n cho TrashSorter
=============================================
Chạy:  python train.py

Yêu cầu: Đã đặt ảnh + label vào datasets/{kim_loai,nhua,giay,khong_phai_rac}/

Kết quả sau khi train:
  models/best_ncnn_model/model.ncnn.bin   ← copy vào Pi để chạy
  models/best_ncnn_model/model.ncnn.param ← copy vào Pi để chạy
  runs/train_trash/                       ← TẤT CẢ biểu đồ + reports
"""

import os
import shutil
import sys
from pathlib import Path

# ── 1. Kiểm tra ảnh ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent          # thư mục gốc dự án
DATASET_DIR = BASE_DIR / "datasets"
CLASSES = ["kim_loai", "nhua", "giay", "khong_phai_rac"]

print("=" * 60)
print("  TrashSorter — Training Pipeline")
print("=" * 60)

# Kiểm tra dataset
total_images = 0
for cls in CLASSES:
    cls_dir = DATASET_DIR / cls
    images = list(cls_dir.glob("*.jpg")) + list(cls_dir.glob("*.jpeg")) + \
             list(cls_dir.glob("*.png")) + list(cls_dir.glob("*.bmp"))
    labels = list(cls_dir.glob("*.txt"))
    total_images += len(images)
    print(f"  {cls:20s}: {len(images):4d} ảnh | {len(labels):4d} labels")

print(f"  {'TOTAL':20s}: {total_images:4d} ảnh")
print()

if total_images == 0:
    print("  CHƯA CÓ ẢNH! Hãy đặt ảnh vào datasets/{kim_loai,nhua,giay,khong_phai_rac}/")
    print("  Mỗi ảnh cần 1 file .txt label tương ứng (định dạng YOLO).")
    print("  Sau đó chạy: python train.py")
    sys.exit(0)

# ── 2. Chuẩn bị cấu trúc YOLO ─────────────────────────────────────────────
# YOLO yêu cầu: datasets/train/images/*.jpg + datasets/train/labels/*.txt
#               datasets/val/images/*.jpg   + datasets/val/labels/*.txt

YOLO_TRAIN = DATASET_DIR / "train"
YOLO_VAL   = DATASET_DIR / "val"

# Xóa cấu trúc cũ nếu có
shutil.rmtree(YOLO_TRAIN, ignore_errors=True)
shutil.rmtree(YOLO_VAL, ignore_errors=True)

# Gom tất cả ảnh từ các thư mục lớp
all_files = []
for cls_idx, cls in enumerate(CLASSES):
    cls_dir = DATASET_DIR / cls
    for img_path in cls_dir.glob("*"):
        if img_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"):
            label_path = cls_dir / f"{img_path.stem}.txt"
            all_files.append((img_path, label_path, cls_idx))

print(f"  Tổng số file: {len(all_files)}")
print()

# ── 3. Split train/val (80/20) ─────────────────────────────────────────────
import random
random.seed(42)
random.shuffle(all_files)
split_idx = int(len(all_files) * 0.8)
train_files = all_files[:split_idx]
val_files   = all_files[split_idx:]

def copy_files(file_list, target_dir):
    """Copy ảnh + label vào cấu trúc YOLO"""
    (target_dir / "images").mkdir(parents=True, exist_ok=True)
    (target_dir / "labels").mkdir(parents=True, exist_ok=True)

    for img_path, lbl_path, cls_idx in file_list:
        # Copy ảnh
        shutil.copy2(img_path, target_dir / "images" / img_path.name)

        # Copy label nếu có
        if lbl_path.exists():
            shutil.copy2(lbl_path, target_dir / "labels" / lbl_path.name)
        else:
            print(f"  ⚠️  Thiếu label: {lbl_path.name} — tạo label mặc định class={cls_idx}")
            # Tạo label YOLO mặc định (giả định toàn ảnh là object)
            (target_dir / "labels" / f"{img_path.stem}.txt").write_text(
                f"{cls_idx} 0.5 0.5 0.9 0.9\n"
            )

copy_files(train_files, YOLO_TRAIN)
copy_files(val_files, YOLO_VAL)

print(f"  Train: {len(train_files)} files → {YOLO_TRAIN}")
print(f"  Val:   {len(val_files)} files → {YOLO_VAL}")
print()

# ── 4. Train YOLO ──────────────────────────────────────────────────────────
from ultralytics import YOLO

RUN_DIR = Path("runs/train_trash")

print("=" * 60)
print("  Bắt đầu training...")
print(f"  Model:     YOLOv11n")
print(f"  Input:     320×320")
print(f"  Classes:   {len(CLASSES)} ({', '.join(CLASSES)})")
print(f"  Epochs:    100")
print(f"  Device:    CPU (không có GPU)")
print(f"  Save dir:  {RUN_DIR}")
print("=" * 60)
print()

# Load model pretrained
model = YOLO("yolo11n.pt")  # tự download nếu chưa có

# Train
results = model.train(
    data=str(BASE_DIR / "datasets" / "data.yaml"),
    epochs=100,
    imgsz=320,
    batch=8,
    device="cpu",
    workers=4,
    name="train_trash",
    exist_ok=True,
    plots=True,          # ← TỰ ĐỘNG vẽ tất cả biểu đồ
    save=True,
    save_period=10,       # Lưu checkpoint mỗi 10 epoch
    val=True,
    amp=False,            # CPU không có AMP
    verbose=True,
)

print()
print("=" * 60)
print("  Training hoàn tất!")
print("=" * 60)
print()

# ── 5. Liệt kê tất cả biểu đồ đã được tạo ──────────────────────────────────
print("=" * 60)
print("  📊 BIỂU ĐỒ & REPORTS (dùng cho báo cáo)")
print("=" * 60)

REPORT_FILES = {
    "results.png":            "Tổng hợp loss + metrics theo epoch",
    "confusion_matrix.png":   "Ma trận nhầm lẫn",
    "F1_curve.png":           "Đường cong F1",
    "PR_curve.png":           "Precision-Recall curve",
    "P_curve.png":            "Precision curve",
    "R_curve.png":            "Recall curve",
    "labels.jpg":             "Phân phối labels",
    "labels_correlogram.jpg": "Tương quan labels",
    "results.csv":            "Bảng số liệu chi tiết",
    "args.yaml":              "Cấu hình training",
}

weights_dir = Path(results.save_dir) / "weights"
report_dir  = Path(results.save_dir)

print(f"\n  📁 Thư mục kết quả: {report_dir}")
print()
for fname, desc in REPORT_FILES.items():
    fpath = report_dir / fname
    status = "✅" if fpath.exists() else "❌"
    print(f"  {status}  {fname:30s} — {desc}")

print()

# ── 6. Export sang NCNN ────────────────────────────────────────────────────
print("=" * 60)
print("  🔄 Export sang NCNN (cho Raspberry Pi 4)")
print("=" * 60)

best_pt = weights_dir / "best.pt"
if best_pt.exists():
    print(f"  Model: {best_pt}")
    ncnn_model = model.export(format="ncnn", imgsz=320, half=False)
    print(f"  NCNN export: {ncnn_model}")
    print()

    # Copy vào models/best_ncnn_model/
    NCNN_DIR = BASE_DIR / "models" / "best_ncnn_model"
    print("  Copy model vào models/best_ncnn_model/ ...")
    # NCNN export tạo folder cùng tên với file weights
    export_dir = Path(results.save_dir) / "weights" / "best_ncnn_model"
    
    if export_dir.exists():
        for f in export_dir.iterdir():
            if f.is_file():
                dest = NCNN_DIR / f.name
                shutil.copy2(f, dest)
                print(f"    ✅ {f.name} → {dest}")
    else:
        # Tìm export folder
        for p in Path().rglob("*best_ncnn_model"):
            if p.is_dir():
                for f in p.iterdir():
                    if f.is_file():
                        dest = NCNN_DIR / f.name
                        shutil.copy2(f, dest)
                        print(f"    ✅ {f.name} → {dest}")
                break
    
    print()
    print("  ✅ Model NCNN đã sẵn sàng cho Pi!")
else:
    print("  ❌ Không tìm thấy best.pt — kiểm tra lại training")
    print()

# ── 7. Tổng kết ────────────────────────────────────────────────────────────
print("=" * 60)
print("  🎯 TỔNG KẾT")
print("=" * 60)
print(f"""
  📁 Biểu đồ báo cáo:  {report_dir}
  📁 Model NCNN:        {BASE_DIR}/models/best_ncnn_model/
  📊 Files cần copy lên Pi:
     - models/best_ncnn_model/model.ncnn.bin
     - models/best_ncnn_model/model.ncnn.param

  🚀 Chạy trên Pi:
     cd ~/phan_loai_rac/DATN/U-DATN_Phan_loai_rac
     git pull origin main
     source venv/bin/activate
     python3 main.py --debug
""")