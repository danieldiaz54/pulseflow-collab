import json
import re
import sys

DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"\brmdir\s+/s\s+/q\s+[c-z]:\\", re.IGNORECASE),
    re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+SCHEMA\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bformat\s+[c-z]:", re.IGNORECASE),
    re.compile(r"\bgit\s+push\b[^\n]*(--force|-f)[^\n]*\bmain\b", re.IGNORECASE),
]


def evaluate_command(cmd: str) -> dict:
    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern.search(cmd):
            return {
                "decision": "deny",
                "reason": f"[Safety Gate] Comando destructivo bloqueado preventivamente: {cmd}",
            }
    return {"decision": "allow"}


def main() -> None:
    raw = sys.stdin.read()
    if not raw or not raw.strip():
        print(json.dumps({"decision": "allow"}))
        return

    try:
        payload = json.loads(raw)
        cmd = (
            payload.get("toolCall", {})
            .get("args", {})
            .get("CommandLine")
            or payload.get("CommandLine")
            or ""
        )
        print(json.dumps(evaluate_command(str(cmd))))
    except Exception:
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
