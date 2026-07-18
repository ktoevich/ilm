import os
import shutil
import random

# Fix random seed for reproducibility
random.seed(42)

# Source directories
base_dir = r"c:\Users\Sherzod\Desktop\soil_project\Soil-Classification-Dataset-main\Soil-Classification-Dataset-main"
orig_dir = os.path.join(base_dir, "Orignal-Dataset")
cyaug_dir = os.path.join(base_dir, "CyAUG-Dataset")

# Destination directory
dest_dir = r"c:\Users\Sherzod\Desktop\soil_project\dataset"

# Fertility classification mapping
mapping = {
    "high_fertility": ["Alluvial_Soil", "Black_Soil"],
    "medium_fertility": ["Red_Soil", "Yellow_Soil", "Mountain_Soil"],
    "low_fertility": ["Arid_Soil", "Laterite_Soil"]
}

# Image extensions to search for
valid_extensions = {".jpg", ".jpeg", ".png", ".bmp"}

def collect_unique_files(folders, categories):
    """
    Collects unique files from Orignal-Dataset and CyAUG-Dataset for specified subfolder names.
    Returns a list of tuples: (filename, source_filepath)
    """
    unique_files = {}
    
    # We prioritize CyAUG-Dataset, then add any additional files from Orignal-Dataset
    for dataset_path in [cyaug_dir, orig_dir]:
        if not os.path.exists(dataset_path):
            continue
        for cat in categories:
            cat_path = os.path.join(dataset_path, cat)
            if not os.path.exists(cat_path):
                continue
            for fname in os.listdir(cat_path):
                ext = os.path.splitext(fname)[1].lower()
                if ext in valid_extensions:
                    # To prevent name conflicts, we can key by filename.
                    # Since some folders might contain different images with the same name,
                    # we can prepend the category name to keep them unique.
                    unique_name = f"{cat}_{fname}"
                    if unique_name not in unique_files:
                        unique_files[unique_name] = os.path.join(cat_path, fname)
                        
    return list(unique_files.items())

def distribute():
    print("Starting dataset distribution...")
    
    # Create target directories
    for split in ["train", "val"]:
        for fertility in mapping.keys():
            os.makedirs(os.path.join(dest_dir, split, fertility), exist_ok=True)
            
    total_train_copied = 0
    total_val_copied = 0
    
    for fertility, categories in mapping.items():
        print(f"\nProcessing category: {fertility} (mapped from {categories})")
        
        # Collect all unique files for this fertility group
        files = collect_unique_files([cyaug_dir, orig_dir], categories)
        print(f"Found {len(files)} unique images for {fertility}.")
        
        # Shuffle files
        random.shuffle(files)
        
        # Calculate split index (80% train, 20% val)
        split_idx = int(len(files) * 0.8)
        train_files = files[:split_idx]
        val_files = files[split_idx:]
        
        print(f"Splitting: {len(train_files)} for training, {len(val_files)} for validation.")
        
        # Copy train files
        train_dest = os.path.join(dest_dir, "train", fertility)
        for unique_name, src_path in train_files:
            shutil.copy2(src_path, os.path.join(train_dest, unique_name))
            total_train_copied += 1
            
        # Copy val files
        val_dest = os.path.join(dest_dir, "val", fertility)
        for unique_name, src_path in val_files:
            shutil.copy2(src_path, os.path.join(val_dest, unique_name))
            total_val_copied += 1
            
    print(f"\nDistribution complete!")
    print(f"Total training images copied: {total_train_copied}")
    print(f"Total validation images copied: {total_val_copied}")

if __name__ == "__main__":
    distribute()
