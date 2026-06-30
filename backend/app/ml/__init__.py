"""
ML package for ResQHub.

Structure:
  - features.py   : feature schema + engineering (validated)
  - dataset.py    : realistic synthetic data generator for training
  - train.py      : CLI to train score + ranker models, dump artifacts
  - inference.py  : model loading + prediction (no training code here)
  - store.py      : joblib serialization helpers + version registry
  - explain.py    : SHAP-based explanations
  - routing_ml.py : LightGBM-based ranker for assignment priority
"""
