# Multi-stage build for Lumina - Single Container Edition
# Use NVIDIA CUDA base image for GPU acceleration
# Using CUDA 13.0 for enhanced GPU support
FROM nvidia/cuda:13.0.0-runtime-ubuntu22.04 as base

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Install Python 3.11 and PostgreSQL
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    postgresql-14 \
    postgresql-client-14 \
    postgresql-server-dev-14 \
    git \
    build-essential \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Install pgvector extension from source
RUN cd /tmp && \
    git clone --branch v0.5.1 https://github.com/pgvector/pgvector.git && \
    cd pgvector && \
    make && \
    make install && \
    cd / && \
    rm -rf /tmp/pgvector

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # ExifTool for metadata extraction
    libimage-exiftool-perl \
    # Image processing libraries
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    libheif-dev \
    # RAW image processing fallback (for older RAW formats not supported by rawpy)
    dcraw \
    # Video processing
    ffmpeg \
    # Build tools
    gcc \
    g++ \
    make \
    curl \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml README.md ./

# Install Python dependencies (base)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e .
    # Install additional dependencies for web application
RUN pip install --no-cache-dir \
    pydantic-settings \
    uvicorn[standard] \
    click

# Install GPU acceleration packages (PyTorch with CUDA support)
# Using nightly build with CUDA 12.8 for RTX 5060 Ti Blackwell (sm_120) support
# CUDA 12.8+ is required for Blackwell architecture (sm_120)
RUN pip install --no-cache-dir --pre \
    torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu128

# Install tagging dependencies (OpenCLIP and Ollama client)
RUN pip install --no-cache-dir \
    open-clip-torch>=2.24.0 \
    ftfy>=6.1.0 \
    ollama>=0.3.0

# Copy application code and set PATH
COPY lumina/ ./lumina/
ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/bin:/app
# Copy application code
COPY lumina/ ./lumina/

# Create directories for catalogs and photos (PostgreSQL data dir will be created by initdb)
RUN mkdir -p /app/catalogs /app/photos /var/log/postgresql

# Create startup script
COPY scripts/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Allow passwordless sudo for postgres user (needed for startup script)
RUN echo "postgres ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Expose ports
EXPOSE 8000 5432

# Start PostgreSQL and application
CMD ["/app/start.sh"]
