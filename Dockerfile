FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# System deps: Python, Node.js, OpenSCAD, curl
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl openscad \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g pnpm \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# --- Python API ---
COPY api/pyproject.toml api/uv.lock api/
RUN cd api && uv sync --frozen --no-dev

COPY api/ api/

# --- Next.js frontend ---
COPY quakka-cad/package.json quakka-cad/pnpm-lock.yaml quakka-cad/
RUN cd quakka-cad && pnpm install --frozen-lockfile

COPY quakka-cad/ quakka-cad/

# Build Next.js for production
ENV API_BASE_URL=http://localhost:8000
RUN cd quakka-cad && pnpm run build

EXPOSE 3000 8000

# Run both services with concurrently
CMD pnpx concurrently \
    --names "api,web" \
    --prefix-colors "cyan,green" \
    "cd api && uv run uvicorn main:app --host 0.0.0.0 --port 8000" \
    "cd quakka-cad && pnpm start"
