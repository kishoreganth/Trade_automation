FROM python:3.10-slim
WORKDIR /Trade_automation
COPY . .

# Install OpenCV dependencies
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev

# Install Python requirements
RUN pip install --no-cache-dir -r requirements.txt

# Run FastAPI
CMD ["uvicorn", "nse_url_test:app", "--host", "0.0.0.0", "--port", "5000"]
