FROM pytorch/pytorch:1.11.0-cuda11.3-cudnn8-runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential cmake && \
    rm -rf /var/lib/apt/lists/*
ADD . /workspace
RUN pip install -f https://data.pyg.org/whl/torch-1.11.0+cu113.html -e .