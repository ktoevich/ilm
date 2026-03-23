@echo off
echo ==========================================
echo      Soil Fertility AI - Setup & Run
echo ==========================================

echo [1/3] Checking dependencies...
pip install -r requirements.txt

echo [2/3] Training model on dummy data (for demonstration)...
python src/train.py

echo [3/3] Launching App...
streamlit run app/main.py
