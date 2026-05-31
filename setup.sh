#!/bin/bash
# ============================================================
# DeepGuard AI — Linux/Mac Setup Script
# For Ubuntu VPS / RunPod / Vast.ai deployment
# Usage: chmod +x setup.sh && ./setup.sh
# ============================================================

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

echo ""
echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}   DeepGuard AI - Linux Setup${NC}"
echo -e "${CYAN}================================================${NC}"
echo ""

# System deps
echo -e "${YELLOW}[1/6] Installing system dependencies...${NC}"
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends ffmpeg libmagic1 python3-pip python3-venv nodejs npm curl
fi

# Backend
echo -e "${YELLOW}[2/6] Creating Python virtualenv...${NC}"
cd "$ROOT/backend"
python3 -m venv venv
source venv/bin/activate

echo -e "${YELLOW}[3/6] Installing PyTorch (CUDA 12.1)...${NC}"
if command -v nvidia-smi &>/dev/null; then
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 -q
    echo -e "${GREEN}  PyTorch CUDA installed${NC}"
else
    pip install torch torchvision torchaudio -q
    echo -e "${YELLOW}  PyTorch CPU installed (no GPU detected)${NC}"
fi

pip install -r requirements.txt -q
echo -e "${GREEN}  Backend deps installed${NC}"

[ ! -f .env ] && cp .env.example .env

mkdir -p "$ROOT/uploads" "$ROOT/models" "$ROOT/backend/logs"

# Frontend
echo -e "${YELLOW}[4/6] Installing frontend...${NC}"
cd "$ROOT/frontend"
npm install --silent
[ ! -f .env.local ] && echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

# Download model
echo -e "${YELLOW}[5/6] Downloading AI model (~350MB)...${NC}"
cd "$ROOT/backend"
source venv/bin/activate
TRANSFORMERS_CACHE="$ROOT/models" HF_HOME="$ROOT/models" python3 -c "
from transformers import AutoImageProcessor, AutoModelForImageClassification
import os
cache = os.environ['TRANSFORMERS_CACHE']
print('Downloading model...')
AutoImageProcessor.from_pretrained('dima806/deepfake_vs_real_image_detection', cache_dir=cache)
AutoModelForImageClassification.from_pretrained('dima806/deepfake_vs_real_image_detection', cache_dir=cache)
print('Done!')
"

# Launch scripts
echo -e "${YELLOW}[6/6] Creating launch scripts...${NC}"

cat > "$ROOT/start-backend.sh" << 'EOF'
#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"
source venv/bin/activate
export TRANSFORMERS_CACHE="$ROOT/models"
export HF_HOME="$ROOT/models"
uvicorn app.main:app --host 0.0.0.0 --port 8000
EOF
chmod +x "$ROOT/start-backend.sh"

cat > "$ROOT/start-frontend.sh" << 'EOF'
#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/frontend"
npm run dev
EOF
chmod +x "$ROOT/start-frontend.sh"

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}   Setup Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "Terminal 1: ${CYAN}./start-backend.sh${NC}"
echo -e "Terminal 2: ${CYAN}./start-frontend.sh${NC}"
echo ""
echo -e "Web:  ${YELLOW}http://localhost:3000${NC}"
echo -e "API:  ${YELLOW}http://localhost:8000/docs${NC}"
echo ""
echo -e "${YELLOW}For public access with Cloudflare Tunnel:${NC}"
echo "  cloudflared tunnel --url http://localhost:3000"
