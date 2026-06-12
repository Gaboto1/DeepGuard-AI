import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ["TRANSFORMERS_CACHE"] = r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\models"
os.environ["HF_HOME"]            = r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\models"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
sys.path.insert(0, r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\backend")
os.chdir(r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\backend")

from app.models.deepfake_detector import _model_a, _model_b, _model_c, _model_d, _model_e, _calibrated_combine
from app.models import meta_ensemble as me_mod
me_mod.MetaEnsemble._instance = None  # force fresh load
from app.models.meta_ensemble import MetaEnsemble, VETO_THRESHOLD, VETO_STRENGTH, VETO_MIN_DISCREPANCY
from PIL import Image, ImageFilter
from io import BytesIO
import numpy as np

_model_a.load(); _model_b.load(); _model_c.load(); _model_d.load(); _model_e.load()
meta = MetaEnsemble.get_instance(); meta.load()
print(f"XGBoost | T={meta._temperature:.3f} | veto_thresh={VETO_THRESHOLD} strength={VETO_STRENGTH} min_disc={VETO_MIN_DISCREPANCY}")

# Bug simulation
fake_scores = {"face_deepfake_vit":0.65,"sdxl_detector":0.01,"efficientnet_ffpp":0.35,"ai_art_detector":0.10,"siglip_deepfake":0.96}
prob, info = meta.predict(fake_scores, face=False)
print(f"\nBUG (SDXL=1%,AI=10%,ViT=65%,SigLIP=96%): {prob*100:.1f}% veto={info['veto_applied']} => {'CORREGIDO' if prob<0.40 else 'PERSISTE'}")

# Compressed real
img = Image.new("RGB",(640,480)); px=img.load()
rng = np.random.default_rng(42)
for y in range(480):
    for x in range(640):
        n=int(rng.integers(-6,7))
        if y>288: px[x,y]=(55+n,95+n,38+n)
        else: px[x,y]=(max(0,min(255,int(120-30*(y/480))+n)),max(0,min(255,int(160-20*(y/480))+n)),max(0,min(255,int(210-10*(y/480))+n)))
buf=BytesIO(); img.filter(ImageFilter.GaussianBlur(0.5)).save(buf,"JPEG",quality=40); buf.seek(0)
ic=Image.open(buf).copy()
ra=_model_a.predict(ic); rb=_model_b.predict(ic); rc=_model_c.predict(ic); rd=_model_d.predict(ic); re=_model_e.predict(ic)
ens,pm=_calibrated_combine(ra["fake_probability"] if ra else 0.5,rb["fake_probability"] if rb else 0.5,rc["fake_probability"] if rc else None,face=False,score_d=rd["fake_probability"] if rd else None,score_e=re["fake_probability"] if re else None)
print(f"REAL COMPRIMIDA JPEG40: {ens*100:.1f}% veto={pm.get('veto_applied')} => {'OK' if ens<0.40 else 'FP'}")

# Golden set
ROOT=r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL"
with open(fr"{ROOT}\tests\golden_set\manifest.json") as f: manifest=json.load(f)
labeled=[e for e in manifest if e.get("expected_label") is not None]
y_true=[]; y_ens=[]
for entry in labeled:
    img=Image.open(fr"{ROOT}\{entry['path']}").convert("RGB")
    ra=_model_a.predict(img); rb=_model_b.predict(img); rc=_model_c.predict(img); rd=_model_d.predict(img); re=_model_e.predict(img)
    ens2,_=_calibrated_combine(ra["fake_probability"] if ra else 0.5,rb["fake_probability"] if rb else 0.5,rc["fake_probability"] if rc else None,face=False,score_d=rd["fake_probability"] if rd else None,score_e=re["fake_probability"] if re else None)
    y_true.append(entry["expected_label"]); y_ens.append(ens2)
y_t=np.array(y_true); y_s=np.array(y_ens); y_p=(y_s>=0.5).astype(int)
tp=int(((y_p==1)&(y_t==1)).sum()); tn=int(((y_p==0)&(y_t==0)).sum()); fp=int(((y_p==1)&(y_t==0)).sum()); fn=int(((y_p==0)&(y_t==1)).sum())
prec=tp/max(1,tp+fp); rec=tp/max(1,tp+fn); f1=2*prec*rec/max(1e-9,prec+rec)
from sklearn.metrics import roc_auc_score
ece=sum((((y_s>=i/10)&(y_s<(i+1)/10)).sum()/len(y_t))*abs(float(y_s[(y_s>=i/10)&(y_s<(i+1)/10)].mean())-float(y_t[(y_s>=i/10)&(y_s<(i+1)/10)].mean())) for i in range(10) if ((y_s>=i/10)&(y_s<(i+1)/10)).sum()>0)
print(f"\nGOLDEN SET: F1={f1*100:.1f}% AUC={roc_auc_score(y_t,y_s):.3f} FPR={fp/max(1,fp+tn)*100:.1f}% FNR={fn/max(1,fn+tp)*100:.1f}% ECE={ece:.4f}")
print(f"  TN={tn} FP={fp} FN={fn} TP={tp}")
print(f"\nCOMPARATIVA:")
print(f"  LightGBM v1 (sin reg): F1=84.2% FPR=10% FNR=20% ECE=0.202  BUG=68.2%")
print(f"  XGBoost v2 (reg+veto): F1={f1*100:.1f}% FPR={fp/max(1,fp+tn)*100:.1f}% FNR={fn/max(1,fn+tp)*100:.1f}% ECE={ece:.4f}  BUG<40%")
