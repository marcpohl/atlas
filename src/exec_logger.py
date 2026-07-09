"""
exec_logger.py

Gera um log de execução detalhado (uma linha JSONL por chamada ao LLM),
contendo o prompt completo enviado, contagem de tokens e o modelo utilizado.
Este log é distinto do arquivo de resultados de classificação: serve para
auditoria/depuração/análise de custo de tokens.

ATENÇÃO: como o prompt completo (incluindo trechos de logs do Wazuh) é
gravado neste arquivo, ele deve ser tratado com o mesmo cuidado de acesso
que os próprios logs de segurança. Veja recomendações no README.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class ExecutionLogger:
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.logs_dir / "execution_log.jsonl"
        self._fh = open(self.log_path, "a", encoding="utf-8")

    def log(
        self,
        model_name: str,
        prompt: str,
        input_tokens: int,
        output_tokens: int,
        event_id: str | None = None,
        error: str | None = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_name": model_name,
            "event_id": event_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "prompt": prompt,
        }
        if error:
            entry["error"] = error

        self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "ExecutionLogger":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
