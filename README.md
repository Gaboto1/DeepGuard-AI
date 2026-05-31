# DeepGuard AI — Deepfake Detection System

Professional deepfake detection for images and videos. Powered by Vision Transformer (ViT) AI, CUDA GPU acceleration, and a modern Next.js frontend.

---

## Features

- **Image detection**: JPG, PNG, WEBP → fake probability + attention heatmap (Grad-CAM++)
- **Video detection**: MP4, MOV, MKV, WEBM → frame-by-frame analysis + temporal timeline
- **Face detection**: MTCNN auto-detects and crops faces for targeted analysis
- **GPU accelerated**: CUDA-optimized for RTX 4070 Super (12GB VRAM)
- **Model**: `dima806/deepfake_vs_real_image_detection` (ViT fine-tuned on deepfake datasets)
- **Modern UI**: Dark futuristic interface with Framer Motion animations
- **Analysis history**: Local history stored in browser
- **Docker ready**: Full containerized deployment

---

## Requirements

| Component | Minimum |
|-----------|---------|
| GPU | NVIDIA with CUDA 12.1 (RTX 3060+ recommended) |
| VRAM | 6GB (8GB+ recommended) |
| RAM | 8GB |
| Python | 3.11+ |
| Node.js | 18+ |
| OS | Windows 11 / Ubuntu 20.04+ |
| CUDA | 12.1 |

---

## Quick Start — Windows (Recommended)

```powershell
# 1. Open PowerShell as Administrator and run:
powershell -ExecutionPolicy Bypass -File setup.ps1

# 2. Start backend (Terminal 1):
.\start-backend.bat

# 3. Start frontend (Terminal 2):
.\start-frontend.bat

# 4. Open browser:
# http://localhost:3000
```

The setup script will:
- Create Python virtualenv
- Install PyTorch with CUDA 12.1
- Install all dependencies
- Download the AI model (~350MB, cached locally)
- Install frontend packages
- Create start scripts

---

## Quick Start — Linux / Ubuntu VPS

```bash
# 1. Setup
chmod +x setup.sh && ./setup.sh

# 2. Start
./start-backend.sh &
./start-frontend.sh &

# Open: http://localhost:3000
```

---

## Manual Setup

### Backend

```bash
cd backend

# Create venv
python -m venv venv
.\venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux

# Install PyTorch with CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install dependencies
pip install -r requirements.txt

# Copy env file
cp .env.example .env

# Start server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

---

## Docker Deployment

### Local with GPU

```bash
# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend
```

> **Requires**: [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

### Production with Nginx + HTTPS

```bash
# Edit docker-compose.prod.yml and docker/nginx.conf with your domain

docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

---

## Public Access Options

### Cloudflare Tunnel (Easiest — Free)

```bash
# Install cloudflared
winget install Cloudflare.cloudflared  # Windows
# brew install cloudflared  # Mac

# Create tunnel (no domain needed)
cloudflared tunnel --url http://localhost:3000
# → Gets you https://random-name.trycloudflare.com
```

### ngrok

```bash
ngrok http 3000
```

### Railway / Render

See [DEPLOYMENT.md](DEPLOYMENT.md) for full cloud deployment guides.

---

## API Reference

Base URL: `http://localhost:8000`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Model status, GPU info |
| `POST` | `/api/analyze` | Upload image or video |
| `GET` | `/api/tasks/{id}` | Get task status/result |
| `GET` | `/api/history` | List recent analyses |
| `DELETE` | `/api/tasks/{id}` | Delete a task |

Interactive docs: http://localhost:8000/docs

### Upload Example

```bash
curl -X POST http://localhost:8000/api/analyze \
  -F "file=@test.jpg" \
  | python -m json.tool
```

Response:
```json
{
  "task_id": "abc-123",
  "status": "pending",
  "message": "Analysis started for test.jpg"
}
```

### Poll for Result

```bash
curl http://localhost:8000/api/tasks/abc-123
```

Response (completed):
```json
{
  "task_id": "abc-123",
  "status": "completed",
  "file_type": "image",
  "fake_probability": 0.87,
  "real_probability": 0.13,
  "verdict": "DEEPFAKE",
  "confidence": "HIGH",
  "explanation": "Strong indicators of AI-generated manipulation...",
  "analysis_time": 0.45,
  "faces_detected": 1,
  "heatmap": "data:image/png;base64,...",
  "model_used": "dima806/deepfake_vs_real_image_detection",
  "device_used": "NVIDIA GeForce RTX 4070 SUPER"
}
```

---

## Project Structure

```
PROYECTO TITULO FINAL/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app
│   │   ├── config.py            # Settings
│   │   ├── models/
│   │   │   ├── deepfake_detector.py  # ViT model + Grad-CAM
│   │   │   └── face_detector.py      # MTCNN face detection
│   │   ├── api/
│   │   │   ├── routes.py        # API endpoints
│   │   │   └── schemas.py       # Pydantic schemas
│   │   ├── services/
│   │   │   ├── analysis_service.py  # Task management
│   │   │   ├── image_service.py     # Image pipeline
│   │   │   └── video_service.py     # Video pipeline
│   │   └── utils/
│   │       ├── file_validator.py
│   │       └── helpers.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx         # Main page
│   │   │   └── globals.css
│   │   ├── components/
│   │   │   ├── Navbar.tsx
│   │   │   ├── Hero.tsx
│   │   │   ├── UploadZone.tsx
│   │   │   ├── AnalysisProgress.tsx
│   │   │   ├── ResultCard.tsx
│   │   │   ├── HowItWorks.tsx
│   │   │   └── HistorySection.tsx
│   │   ├── lib/api.ts           # API client
│   │   └── types/index.ts
│   └── Dockerfile
├── models/          # Cached model weights (auto-downloaded)
├── uploads/         # Temp uploaded files
├── docker/          # Nginx config
├── docker-compose.yml
├── setup.ps1        # Windows setup
├── setup.sh         # Linux setup
└── README.md
```

---

## AI Model Details

**Model**: `dima806/deepfake_vs_real_image_detection`
- Architecture: Vision Transformer (ViT)
- Training data: Deepfake detection datasets (FaceForensics++, DFDC, etc.)
- Input: 224×224 RGB images
- Output: FAKE / REAL probabilities
- Size: ~350MB (cached in `models/` folder)
- Source: [HuggingFace](https://huggingface.co/dima806/deepfake_vs_real_image_detection)

**Face Detection**: `facenet-pytorch` MTCNN
- Detects faces, crops with margin
- Passes cropped face to classifier for better accuracy
- Falls back to full image if no face detected

**Heatmap**: Grad-CAM++ on ViT
- Shows which regions influenced the model's decision
- Generated for likely-fake content (probability > 40%)
- Returned as base64 PNG overlay

---

## Configuration (.env)

```env
MODEL_NAME=dima806/deepfake_vs_real_image_detection
DEVICE=cuda          # or cpu
MAX_FRAMES=50        # video frame sampling
MAX_FILE_SIZE_MB=500
RATE_LIMIT_PER_MINUTE=10
```

---

## Troubleshooting

**Model download fails**
```bash
# Check internet, then manually:
python -c "
from transformers import AutoImageProcessor, AutoModelForImageClassification
AutoModelForImageClassification.from_pretrained('dima806/deepfake_vs_real_image_detection', cache_dir='./models')
"
```

**CUDA out of memory**
- Set `DEVICE=cpu` in `.env` (slower but works)
- Or reduce `MAX_FRAMES` for video

**CORS error in browser**
- Make sure `ALLOWED_ORIGINS` in `.env` includes `http://localhost:3000`

**Frontend can't reach backend**
- Verify backend is running on port 8000
- Check `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local`

**python-magic error on Windows**
- Install: `pip install python-magic-bin` (Windows binary)
- Or: file type validation falls back to extension-only mode

---

## Performance (RTX 4070 SUPER)

| Task | Time |
|------|------|
| Image (single) | ~0.3–0.5s |
| Image + heatmap | ~1–2s |
| Video (30s, 50 frames) | ~5–15s |
| Model cold start | ~5–10s (first request) |

GPU utilization: ~20–40% during inference (ViT-base is lightweight)

---

## License

MIT — Free for personal and commercial use.
