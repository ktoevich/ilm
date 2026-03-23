import os
from PIL import Image, ImageDraw
import random

def create_dummy_images(base_path, classes, num_images=10):
    for class_name, color in classes.items():
        dir_path = os.path.join(base_path, class_name)
        os.makedirs(dir_path, exist_ok=True)
        
        for i in range(num_images):
            # Create a random variation of the color
            r = max(0, min(255, color[0] + random.randint(-20, 20)))
            g = max(0, min(255, color[1] + random.randint(-20, 20)))
            b = max(0, min(255, color[2] + random.randint(-20, 20)))
            
            img = Image.new('RGB', (224, 224), (r, g, b))
            draw = ImageDraw.Draw(img)
            
            # Add some "texture" noise
            for _ in range(500):
                x = random.randint(0, 224)
                y = random.randint(0, 224)
                noise_color = (
                    max(0, min(255, r + random.randint(-50, 50))),
                    max(0, min(255, g + random.randint(-50, 50))),
                    max(0, min(255, b + random.randint(-50, 50)))
                )
                draw.point((x, y), fill=noise_color)
                
            img.save(os.path.join(dir_path, f"dummy_{i}.jpg"))
    print(f"Created {num_images} dummy images for {list(classes.keys())} in {base_path}")

classes = {
    "Black_Soil": (30, 30, 30),      # Dark
    "Sand": (230, 210, 100),         # Yellow
    "Clay": (180, 140, 90),          # Light Brown
    "Loam": (100, 80, 50)            # Brownish
}

if __name__ == "__main__":
    create_dummy_images("data/train", classes, num_images=20)
    create_dummy_images("data/val", classes, num_images=5)
