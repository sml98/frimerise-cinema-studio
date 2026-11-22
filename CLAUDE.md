# CLAUDE.md — FrimeRise Cinema Studio

Leia e siga integralmente todas as regras em [AGENTS.md](./AGENTS.md).

Resumo imediato:
1. **Economia de tokens:** para gerar, retomar ou auditar vídeos, rode `.venv/bin/python batch_produce.py ...` (Python determinístico, 0 tokens de agente na execução).
2. **Quality Lock v3.0.0:** nunca reduza resolução (`1920x1080` / `1080x1920`), FPS (`30`), 5 categorias Mixed-Media, Era-Lock + Vision Gate, RetentionDoctor v3, `-14 LUFS / <= -1.0 dBTP`, Pattern Interrupts `240s` ou final abrupto `0.50s` sem CTA (`config/high_retention_doc_engine_v3.json`).
3. **Disco & Google Drive:** garanta >=10 GB livres antes de renderizar; mantenha `gdrive_auto_upload=1` e `gdrive_prune_local=1` (via `./setup_gdrive.sh`).
4. **Segredos:** nunca commite `data/frimerise.db`, tokens OAuth, `.env` ou `outputs/`.
