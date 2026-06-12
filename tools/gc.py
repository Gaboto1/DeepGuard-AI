import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ["TRANSFORMERS_CACHE"] = r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\models"
os.environ["HF_HOME"]            = r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\models"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
sys.path.insert(0, r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\backend")
os.chdir(r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\backend")

import numpy as np
from PIL import Image
from app.models.deepfake_detector import _model_a, _model_b, _model_c, _model_d, _model_e, _calibrated_combine
from app.models.meta_ensemble import MetaEnsemble
from app.models.ood_detector import detect_ood, apply_ood_penalty
from app.utils.forensic_corrections import apply_forensic_corrections

_model_a.load(); _model_b.load(); _model_c.load(); _model_d.load(); _model_e.load()
MetaEnsemble._instance = None
meta = MetaEnsemble.get_instance(); meta.load()

ROOT = r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL"
with open(fr"{ROOT}\tests\golden_set\manifest.json") as f:
    manifest = json.load(f)
labeled = [(e, int(e["expected_label"])) for e in manifest if e.get("expected_label") is not None]

y_true=[]; y_ens=[]
for entry, label in labeled:
    img = Image.open(fr"{ROOT}\{entry['path']}").convert("RGB")
    ra=_model_a.predict(img); rb=_model_b.predict(img)
    rc=_model_c.predict(img); rd=_model_d.predict(img); re=_model_e.predict(img)
    ens, pm = _calibrated_combine(
        ra["fake_probability"] if ra else 0.5,
        rb["fake_probability"] if rb else 0.5,
        rc["fake_probability"] if rc else None, face=False,
        score_d=rd["fake_probability"] if rd else None,
        score_e=re["fake_probability"] if re else None,
    )
    ood_result = detect_ood(img)
    ens = apply_ood_penalty(ens, ood_result)
    model_scores = {
        "face_deepfake_vit": ra["fake_probability"] if ra else 0,
        "sdxl_detector": rb["fake_probability"] if rb else 0,
        "efficientnet_ffpp": rc["fake_probability"] if rc else 0,
        "ai_art_detector": rd["fake_probability"] if rd else 0,
        "siglip_deepfake": re["fake_probability"] if re else 0,
    }
    ens, corr_type, _ = apply_forensic_corrections(ens, model_scores, ood_result)
    y_true.append(label); y_ens.append(ens)

y_t=np.array(y_true); y_s=np.array(y_ens); y_p=(y_s>=0.5).astype(int)
tp=int(((y_p==1)&(y_t==1)).sum()); tn=int(((y_p==0)&(y_t==0)).sum())
fp=int(((y_p==1)&(y_t==0)).sum()); fn=int(((y_p==0)&(y_t==1)).sum())
prec=tp/max(1,tp+fp); rec=tp/max(1,tp+fn); f1=2*prec*rec/max(1e-9,prec+rec)
from sklearn.metrics import roc_auc_score
ece=sum((((y_s>=i/10)&(y_s<(i+1)/10)).sum()/len(y_t))*abs(float(y_s[(y_s>=i/10)&(y_s<(i+1)/10)].mean())-float(y_t[(y_s>=i/10)&(y_s<(i+1)/10)].mean())) for i in range(10) if ((y_s>=i/10)&(y_s<(i+1)/10)).sum()>0)

print()
print("=== Golden Set — Post Correcciones Forenses ===")
print(f"  F1:  {f1*100:.1f}%  (objetivo >90%)")
print(f"  AUC: {roc_auc_score(y_t,y_s):.3f}")
print(f"  ECE: {ece:.4f}")
print(f"  FPR: {fp/max(1,fp+tn)*100:.1f}%  FNR: {fn/max(1,fn+tp)*100:.1f}%")
print(f"  TN={tn} FP={fp} FN={fn} TP={tp}")
print(f"  Objetivo F1>90%: {'CUMPLIDO' if f1>=0.90 else 'REVISAR'}")
