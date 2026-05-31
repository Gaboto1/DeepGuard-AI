# -*- coding: utf-8 -*-
"""Auditoría de analysis_tasks.py: parámetros Celery y carga LLaVA."""
import ast
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

src  = Path("app/tasks/analysis_tasks.py").read_text(encoding="utf-8")
tree = ast.parse(src)

tasks_found = []
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                dec_str = ast.unparse(dec)
                if "task" in dec_str:
                    kws = {kw.arg: ast.unparse(kw.value) for kw in dec.keywords}
                    tasks_found.append({
                        "fn": node.name,
                        "bind": "bind" in kws,
                        "max_retries": "max_retries" in kws,
                        "soft_time_limit": "soft_time_limit" in kws,
                        "time_limit": "time_limit" in kws,
                        "kws": kws,
                    })

print("=== Tareas Celery registradas ===")
all_ok = True
for t in tasks_found:
    ok = t["bind"] and t["max_retries"] and t["soft_time_limit"]
    status = "OK" if ok else "REVISAR"
    print(f"  [{status}] {t['fn']}")
    for k, v in t["kws"].items():
        print(f"         {k}={v}")
    if not ok:
        all_ok = False

print()
print("=== Características del worker ===")
has_llava         = "_SemanticInspector" in src
has_worker_signal = "worker_init" in src
has_error_guard   = "e_llava" in src
has_retry_logic   = "retry" in src and "countdown" in src

print(f"  LLaVA en init_worker_models: {has_llava}")
print(f"  worker_init signal: {has_worker_signal}")
print(f"  Guard de error LLaVA: {has_error_guard}")
print(f"  Logica de retry en tareas: {has_retry_logic}")

# Verificar que los retry usan exc= (no raise directo)
has_safe_retry = "raise self.retry(exc=exc" in src
print(f"  Retry seguro (exc=exc): {has_safe_retry}")

print()
if all_ok:
    print("  Todas las tareas Celery tienen parametros criticos.")
else:
    print("  ADVERTENCIA: Algunas tareas faltan parametros.")

sys.exit(0 if (all_ok and has_llava and has_worker_signal) else 1)
