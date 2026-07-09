"""
wazuh_reader.py

Leitura dos arquivos alerts.json do Wazuh (formato JSON Lines: um objeto
JSON por linha) a partir de uma pasta informada na execução. Não há
pré-processamento/normalização em disco -- cada linha é lida, parseada e
entregue evento a evento para classificação.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class WazuhEvent:
    """Representa um evento (alerta) do Wazuh já parseado, com os campos
    de rastreabilidade extraídos e o dicionário bruto completo preservado
    para uso na construção do prompt."""

    source_file: str
    line_number: int
    raw: dict = field(repr=False)

    @property
    def event_id(self) -> str:
        return str(self.raw.get("id", f"{self.source_file}:{self.line_number}"))

    @property
    def rule_id(self) -> str:
        return str(self.raw.get("rule", {}).get("id", "unknown"))

    @property
    def rule_level(self):
        return self.raw.get("rule", {}).get("level")

    @property
    def rule_description(self) -> str:
        return self.raw.get("rule", {}).get("description", "")

    @property
    def rule_groups(self) -> list:
        return self.raw.get("rule", {}).get("groups", [])

    @property
    def timestamp(self) -> str:
        return str(self.raw.get("timestamp", ""))

    @property
    def agent_name(self) -> str:
        return self.raw.get("agent", {}).get("name", "unknown")

    @property
    def full_log(self) -> str:
        return self.raw.get("full_log", "")

    @property
    def mitre_techniques_hint(self) -> list:
        """Técnicas MITRE que o próprio Wazuh já associou à regra (quando
        disponível). Não substitui a classificação do modelo, mas serve
        como pista adicional no prompt."""
        return self.raw.get("rule", {}).get("mitre_techniques", []) or self.raw.get("rule", {}).get("mitre", {}).get("id", [])

    @property
    def mitre_tactics_hint(self) -> list:
        return self.raw.get("rule", {}).get("mitre_tactics", []) or self.raw.get("rule", {}).get("mitre", {}).get("tactic", [])

    @property
    def extra_context(self) -> str:
        """Contexto adicional para eventos onde 'full_log' vem vazio (ex.:
        eventos SCA/compliance, onde o conteúdo relevante fica em 'data').
        Extrai um subconjunto legível de 'data', evitando campos muito
        grandes/irrelevantes (ex.: scripts de remediação completos)."""
        data = self.raw.get("data", {})
        if not data:
            return ""

        # Caso específico e comum: eventos de SCA (Security Configuration
        # Assessment / compliance benchmarks).
        sca = data.get("sca")
        if sca:
            check = sca.get("check", {})
            parts = [
                f"Política: {sca.get('policy', 'N/A')}",
                f"Verificação: {check.get('title', 'N/A')}",
                f"Descrição: {check.get('description', 'N/A')}",
                f"Justificativa (rationale): {check.get('rationale', 'N/A')}",
                f"Resultado: {sca.get('result', 'N/A')}",
            ]
            if sca.get("reason"):
                parts.append(f"Motivo: {sca.get('reason')}")
            return " | ".join(parts)

        # Caso genérico: outros tipos de evento com campo 'data' não vazio
        # e sem 'full_log'. Serializa de forma compacta, sem campos de
        # texto muito longos (heurística simples por tamanho).
        try:
            compact = {
                k: v for k, v in data.items()
                if not isinstance(v, (dict, list)) or len(json.dumps(v)) < 300
            }
            return json.dumps(compact, ensure_ascii=False)
        except (TypeError, ValueError):
            return ""


def find_alert_files(data_dir: Path, pattern: str = "*.json") -> list[Path]:
    """Localiza arquivos de alerta na pasta de dados informada."""
    if not data_dir.exists() or not data_dir.is_dir():
        raise FileNotFoundError(f"Pasta de dados não encontrada: {data_dir}")
    files = sorted(data_dir.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"Nenhum arquivo '{pattern}' encontrado em {data_dir}"
        )
    return files


def iter_events(data_dir: Path, pattern: str = "*.json") -> Iterator[WazuhEvent]:
    """Itera evento a evento sobre todos os arquivos alerts.json da pasta.

    Formato esperado: JSON Lines (um objeto JSON por linha), que é o
    formato nativo do alerts.json do Wazuh. Linhas vazias ou malformadas
    são reportadas em stderr e ignoradas, sem interromper o processamento.
    """
    for file_path in find_alert_files(data_dir, pattern):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as e:
                    print(
                        f"[AVISO] Linha malformada ignorada "
                        f"({file_path.name}:{line_number}): {e}"
                    )
                    continue
                yield WazuhEvent(
                    source_file=file_path.name,
                    line_number=line_number,
                    raw=raw,
                )
