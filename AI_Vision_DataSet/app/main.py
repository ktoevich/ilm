import streamlit as st
from PIL import Image
import sys
import os

# Add the root directory to path so we can import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.inference import SoilClassifier
from src.recommendations import get_soil_info

st.set_page_config(
    page_title="Soil Fertility Analysis",
    page_icon="🌱",
    layout="wide"
)

# Custom CSS for aesthetics
st.markdown("""
    <style>
    .main {
        background-color: #f0f2f6;
    }
    .stButton>button {
        background-color: #4CAF50;
        color: white;
        border-radius: 10px;
    }
    .report-card {
        padding: 20px;
        background-color: white;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    h1 {
        color: #2E7D32;
    }
    h2 {
        color: #388E3C;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🌱 AI Soil Fertility Analysis")
st.write("Upload a photo of your soil to analyze its type, fertility, and get crop recommendations.")

@st.cache_resource
def load_classifier():
    return SoilClassifier()

classifier = load_classifier()

col1, col2 = st.columns([1, 1])

with col1:
    st.markdown("### 📸 Upload Image")
    uploaded_file = st.file_uploader("Choose a soil image...", type=["jpg", "jpeg", "png"])

    image = None
    if uploaded_file is not None:
        image = Image.open(uploaded_file).convert('RGB')
    elif st.button("Use Sample Image"):
        # Create a sample image on the fly if needed or load one
        # We'll generate a dummy 'Black Soil' lookalike
        image = Image.new('RGB', (224, 224), (40, 40, 40)) 
        st.info("Using a generated sample image (Dark/Black Soil simulation).")

    if image is not None:
        st.image(image, caption='Analyzed Image', use_column_width=True)
        
        if st.button('Analyze Soil', key='analyze_btn'):
            with st.spinner('Analyzing texture and color...'):
                # Run Inference
                prediction, confidence = classifier.predict(image)
                
                # Get Info
                info = get_soil_info(prediction)
                
                # Display Results in col2
                with col2:
                    st.markdown("## 📊 Analysis Report")
                    
                    st.markdown(f"""
                    <div class="report-card">
                        <h3>Detected Soil Type: <b>{prediction}</b></h3>
                        <p>Confidence: {confidence:.2%}</p>
                        <hr>
                        <h4>🌍 General Info</h4>
                        <p><b>Visual:</b> {info['visual_characteristics']}</p>
                        <p><b>Description:</b> {info['description']}</p>
                        <hr>
                        <h4>🌱 Fertility Assessment</h4>
                        <p style="font-size: 18px; color: #2E7D32;"><b>{info['fertility']}</b></p>
                        <hr>
                        <h4>🚜 Recommended Crops</h4>
                        <ul>
                            {''.join([f'<li>{crop}</li>' for crop in info['crops']])}
                        </ul>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.warning("⚠️ Note: This is a visual analysis based on AI. For precise chemical composition (pH, Nitrogen, etc.), please consult a laboratory.")

with st.expander("ℹ️ How it works"):
    st.write("""
    1. **Visual Analysis**: The AI looks at color (related to humus/organic matter) and texture (sand/clay/loam balance).
    2. **Classification**: It matches the image to known soil types: Black Soil, Clay, Sand, Loam, etc.
    3. **Recommendation**: Based on the type, we suggest crops that thrive in those conditions.
    """)
