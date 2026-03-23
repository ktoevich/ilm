import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image
import os
import json

class SoilClassifier:
    def __init__(self, model_path="models/soil_classifier.pth", classes_path="models/classes.json"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_path = model_path
        self.classes_path = classes_path
        self.classes = None
        self.model = None
        
        self.transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])
        
        self.load_artifacts()

    def load_artifacts(self):
        # Load classes
        if os.path.exists(self.classes_path):
            with open(self.classes_path, 'r') as f:
                self.classes = json.load(f)
        else:
            print(f"Warning: {self.classes_path} not found. Using default dummy classes.")
            self.classes = ["Black_Soil", "Clay", "Loam", "Sand"]
            
        # Load model
        # Use MobileNetV2 as defined in train.py
        self.model = models.mobilenet_v2(pretrained=False)
        self.model.classifier[1] = nn.Linear(self.model.last_channel, len(self.classes))
        
        if os.path.exists(self.model_path):
            try:
                self.model.load_state_dict(torch.load(self.model_path, map_location=self.device))
                print(f"Model loaded from {self.model_path}")
            except Exception as e:
                print(f"Error loading model weights: {e}")
        else:
             print(f"Warning: {self.model_path} not found. Running with uninitialized weights.")

        self.model = self.model.to(self.device)
        self.model.eval()

    def predict(self, image):
        """
        Predicts the soil type from a PIL Image.
        Returns: (class_name, confidence)
        """
        if self.model is None:
            return "Error", 0.0
            
        img_t = self.transform(image)
        batch_t = torch.unsqueeze(img_t, 0).to(self.device)
        
        with torch.no_grad():
            output = self.model(batch_t)
            probabilities = torch.nn.functional.softmax(output[0], dim=0)
            confidence, index = torch.max(probabilities, 0)
            
        return self.classes[index.item()], confidence.item()
