"""Phase 12 model implementations, all satisfying src.ml.baseline.Model.

naive.py has no ML dependency (the bar every real model must clear).
sklearn_models.py wraps scikit-learn estimators - the "simple baseline"
family from docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 24 (Logistic
Regression, Random Forest, Extra Trees), which must be beaten
out-of-sample before anything more expensive (LightGBM/XGBoost/CatBoost,
then deep learning) is justified.
"""
