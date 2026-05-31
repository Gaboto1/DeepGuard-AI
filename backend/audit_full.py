# -*- coding: utf-8 -*-
"""
Auditoría completa del backend: sintaxis, imports, rutas, variables huérfanas.
Ejecutar: python audit_full.py
"""
import ast
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent / "app"
errors   = []
warnings = []
ok_files = []

for pyfile in sorted(ROOT.rglob("*.py")):
    if "__pycache__" in str(pyfile):
        continue

    rel = pyfile.relative_to(ROOT.parent)

    # ── 1. Sintaxis ───────────────────────────────────────────────────────────
    try:
        src  = pyfile.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except SyntaxError as e:
        errors.append(f"[SYNTAX ]  {rel}:{e.lineno}: {e.msg}")
        continue

    ok_files.append(str(rel))

    # ── 2. Reimportaciones locales de logger (causan UnboundLocalError) ───────
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom):
                    if child.module and "loguru" in child.module:
                        for alias in child.names:
                            if alias.name == "logger":
                                errors.append(
                                    f"[LOCAL_LOGGER] {rel}:{child.lineno} "
                                    f"en funcion '{node.name}' — causa UnboundLocalError"
                                )

    # ── 3. Rutas de API legacy sin prefijo v1 ─────────────────────────────────
    legacy_pattern = re.compile(r"""['"/](api)/(tasks|analyze|history)['"/]""")
    for i, line in enumerate(src.splitlines(), 1):
        if legacy_pattern.search(line) and "/api/v1" not in line:
            # Excluir definiciones de router (son el backend mismo)
            if "prefix=" in line or "@router." in line or "APIRouter" in line:
                continue
            warnings.append(
                f"[LEGACY_ROUTE] {rel}:{i}: {line.strip()[:90]}"
            )

    # ── 4. Variables usadas antes de asignación en try/except ─────────────────
    # Buscar patrones: variable asignada solo dentro de except, usada fuera
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            # Variables asignadas SOLO en except handlers (no en el try body)
            except_assigns = set()
            for handler in node.handlers:
                for child in ast.walk(handler):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                        except_assigns.add(child.id)

            # Variables asignadas en el try body (no problemáticas)
            try_assigns = set()
            for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    try_assigns.add(child.id)

            # Si la misma variable se usa después del try/except y solo fue
            # asignada en except, puede ser problemática.
            # (Heurística simple — solo reportamos patrones de logger)
            for var in except_assigns - try_assigns:
                if var == "logger":
                    errors.append(
                        f"[ORPHAN_VAR] {rel}: '{var}' asignado solo en except — "
                        f"puede causar UnboundLocalError si el except no se ejecuta"
                    )


# ─── Reporte ──────────────────────────────────────────────────────────────────

print("\n" + "="*60)
print(" AUDITORIA BACKEND DeepGuard AI")
print("="*60)

print(f"\n[+] Archivos Python auditados: {len(ok_files)}")

print("\n--- ERRORES CRITICOS ---")
if errors:
    for e in errors:
        print(f"  {e}")
else:
    print("  Ninguno. Todos los archivos son validos.")

print("\n--- ADVERTENCIAS (rutas legacy en Python) ---")
if warnings:
    for w in warnings:
        print(f"  {w}")
else:
    print("  Ninguna.")

print("\n" + "="*60)
sys.exit(1 if errors else 0)
