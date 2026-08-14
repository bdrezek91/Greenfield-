"""Feature engineering. Every feature may only use information available up to t.

See docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 23 for the feature
families, and src/features/pipeline.py:build_feature_matrix() for the
single assembly entry point. Lookahead protection is proven structurally
in tests/lookahead/test_feature_no_lookahead.py.
"""
