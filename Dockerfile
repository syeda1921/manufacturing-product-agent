FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 user

# Copy code and set ownership to that user
COPY --chown=user:user . /app

# Install deps as root
USER root
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
      python-dotenv \
      websockets \
      pydantic \
      dataclasses-json \
      pandas \
      chainlit \
      openai \
      griffe
# (Removed: 'agents' from PyPI)

# Optional: Expose a conventional port; HF will route $PORT
# EXPOSE accepts only the number—no trailing comments on that line
EXPOSE 7860

# Ensure Chainlit’s dirs exist and are writable by our app user
RUN mkdir -p /app/.files /app/.chainlit && chown -R user:user /app

# Drop privileges for runtime
USER user

ENV CHAINLIT_BROWSER_AUTO_OPEN=false
CMD ["sh", "-c", "chainlit run app.py --host 0.0.0.0 --port ${PORT:-7860}"]
