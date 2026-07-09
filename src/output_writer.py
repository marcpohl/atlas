"""
output_writer.py

Grava os resultados de classificação em disco (JSONL ou CSV, conforme
configurado) e também imprime um resumo de cada classificação no console.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class ClassificationRecord:
    # --- rastreabilidade ---
    event_id: str
    rule_id: str
    source_file: str
    event_timestamp: str
    # --- classificação (campos vindos do LLM, restritos pela gramática) ---
    classification: str
    mitre_tactic: str
    mitre_technique: str
    confidence: float
    reasoning: str
    # --- metadados da execução ---
    model_name: str
    classified_at: str


class OutputWriter:
    """Escreve registros incrementalmente (append) durante o processamento,
    para não perder resultados já obtidos em caso de interrupção."""

    def __init__(self, output_dir: Path, output_format: str = "jsonl"):
        self.output_dir = output_dir
        self.output_format = output_format
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if output_format == "jsonl":
            self.output_path = self.output_dir / "classifications.jsonl"
            self._fh = open(self.output_path, "a", encoding="utf-8")
        elif output_format == "csv":
            self.output_path = self.output_dir / "classifications.csv"
            is_new = not self.output_path.exists() or self.output_path.stat().st_size == 0
            self._fh = open(self.output_path, "a", encoding="utf-8", newline="")
            self._csv_writer = csv.DictWriter(
                self._fh, fieldnames=list(ClassificationRecord.__annotations__.keys())
            )
            if is_new:
                self._csv_writer.writeheader()
        else:
            raise ValueError(
                f"output_format '{output_format}' inválido. Use 'jsonl' ou 'csv'."
            )

    def write(self, record: ClassificationRecord) -> None:
        record_dict = asdict(record)

        if self.output_format == "jsonl":
            self._fh.write(json.dumps(record_dict, ensure_ascii=False) + "\n")
        else:
            self._csv_writer.writerow(record_dict)
        self._fh.flush()

        self._print_console(record)

    @staticmethod
    def _print_console(record: ClassificationRecord) -> None:
        print(
            f"[{record.classification}] evento={record.event_id} "
            f"rule={record.rule_id} tactic={record.mitre_tactic} "
            f"technique={record.mitre_technique} "
            f"confidence={record.confidence:.2f} "
            f"modelo={record.model_name}"
        )

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "OutputWriter":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
