# Recordatorios WhatsApp contra no-shows — MVP

## Cómo ejecutar
```bash
cd backend
cp ../.env.example ../.env
../.venv/Scripts/python app.py
# abre http://localhost:5004
```
Sin credenciales reales de Google/WhatsApp en `.env`, la app usa automáticamente clientes **mock** (simulados) — funcional para demo/pruebas sin gastar nada.

## Cómo correr los tests
```bash
.venv/Scripts/python -m pytest tests/ -v
```

Ver `NORMATIVA.md` (políticas Meta/WhatsApp y RGPD) y `RESUMEN.md` (decisiones y pasos a producción).
