#!/usr/bin/env python3
"""
diagnose_grammar.py

Testa, um a um, pedaços da gramática GBNF contra o llama-server em
http://127.0.0.1:8080, para descobrir exatamente qual regra está causando
o erro "failed to parse grammar". Roda localmente, não precisa de nada além
de 'requests' (já instalado no venv do projeto).

Uso:
    python3 diagnose_grammar.py
"""
import requests

SERVER = "http://127.0.0.1:8080"

TESTS = {
    "1_estrutura_basica (so ws + chaves)": '''
root ::= "{" ws "}"
ws ::= [ \\t\\n]*
''',

    "2_classification": '''
root ::= "{" ws "\\"classification\\":" ws classification ws "}"
classification ::= "\\"True_Positive\\"" | "\\"False_Positive\\"" | "\\"Benign\\"" | "\\"Needs_Investigation\\""
ws ::= [ \\t\\n]*
''',

    "3_tactic": '''
root ::= "{" ws "\\"mitre_tactic\\":" ws tactic ws "}"
tactic ::= "\\"Reconnaissance\\""
  | "\\"Resource_Development\\""
  | "\\"Initial_Access\\""
  | "\\"Execution\\""
  | "\\"Persistence\\""
  | "\\"Privilege_Escalation\\""
  | "\\"Defense_Evasion\\""
  | "\\"Credential_Access\\""
  | "\\"Discovery\\""
  | "\\"Lateral_Movement\\""
  | "\\"Collection\\""
  | "\\"Command_And_Control\\""
  | "\\"Exfiltration\\""
  | "\\"Impact\\""
  | "\\"Not_Applicable\\""
ws ::= [ \\t\\n]*
''',

    "4_technique": '''
root ::= "{" ws "\\"mitre_technique\\":" ws technique ws "}"
technique ::= "\\"" ( "T" digit digit digit digit ( "." digit digit digit )? | "N/A" ) "\\""
digit ::= [0-9]
ws ::= [ \\t\\n]*
''',

    "5_confidence": '''
root ::= "{" ws "\\"confidence\\":" ws confidence ws "}"
confidence ::= ( "0." digit digit | "1.00" )
digit ::= [0-9]
ws ::= [ \\t\\n]*
''',

    "6_reasoning": '''
root ::= "{" ws "\\"reasoning\\":" ws reasoning ws "}"
reasoning ::= "\\"" reasoning-char* "\\""
reasoning-char ::= [^"\\\\\\x00-\\x1f] | "\\\\" escape
escape ::= ["\\\\/bfnrt] | "u" hex hex hex hex
hex ::= [0-9a-fA-F]
ws ::= [ \\t\\n]*
''',
}


def test_grammar(name: str, grammar: str) -> None:
    try:
        resp = requests.post(
            f"{SERVER}/completion",
            json={"prompt": "teste", "grammar": grammar, "n_predict": 5},
            timeout=15,
        )
        if resp.status_code == 200:
            print(f"[OK]   {name}")
        else:
            print(f"[FALHA] {name}")
            print(f"        Status: {resp.status_code}")
            print(f"        Corpo:  {resp.text}")
    except requests.exceptions.RequestException as e:
        print(f"[ERRO DE CONEXAO] {name}: {e}")


if __name__ == "__main__":
    print(f"Testando contra {SERVER} ...\n")
    for name, grammar in TESTS.items():
        test_grammar(name, grammar)
