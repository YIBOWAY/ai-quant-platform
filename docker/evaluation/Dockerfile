# Keep machine-learning evaluation separate from the existing execution image.
ARG BASE_IMAGE=hqa-d34-rdagent-qlib:0.1.0
FROM ${BASE_IMAGE}
RUN python -m pip install --no-deps \
    "scikit-learn==1.7.2" "threadpoolctl==3.6.0"
LABEL hqa.evaluation.scope="research_only"
ENTRYPOINT ["python"]
