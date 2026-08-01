import re

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class SkillRequest(BaseModel):
    skill: str


SECRET_PATTERNS = [
    r"AKIA[0-9A-Z]{16}",                         # AWS access key
    r"sk-[A-Za-z0-9]{20,}",                       # generic secret-key style
    r"AIza[0-9A-Za-z\-_]{35}",                    # Google API key
    r"xox[baprs]-[0-9A-Za-z-]{10,}",              # Slack token
    r"ghp_[A-Za-z0-9]{30,}",                      # GitHub PAT
    r"https://hooks\.slack\.com/services/\S+",    # Slack webhook literal
    r"-----BEGIN (RSA |EC )?PRIVATE KEY-----",
]
SECRET_ASSIGN_RE = re.compile(
    r"(?im)^\s*(api[_-]?key|secret|token|password|webhook)\s*[:=]\s*[\"']?([A-Za-z0-9/_\-\.]{12,})[\"']?\s*$"
)
ENV_REF_RE = re.compile(r"\$\{?\w+\}?|env\.|os\.environ|secret[_ ]?store|vault", re.IGNORECASE)

INJECTION_PHRASES = [
    r"ignore (any|the) (user'?s?|previous) (instructions|stop|cancel|request)",
    r"do not (tell|inform|notify) the user",
    r"without (asking|telling|notifying) the user",
    r"silently (send|exfiltrate|upload|transmit|email|post)",
    r"regardless of what the user says",
    r"hide this (from|step) the user",
    r"do not (reveal|disclose) this to the user",
    r"exfiltrate",
    r"override (the )?(user|agent) control",
]

EXCESSIVE_PERM_PHRASES = [
    r"read (and|/) ?write access to (the )?(entire|whole|full) file ?system",
    r"access to (any|all) (domain|host|url)s?",
    r"network:\s*any",
    r"domains?:\s*\*",
    r"full disk access",
    r"root access",
    r"unrestricted (network|file ?system) access",
]


def _has_frontmatter_field(text: str, field: str) -> bool:
    return re.search(rf"(?im)^{field}\s*:\s*\S+", text) is not None


def scan_skill(text: str):
    categories = set()

    # --- hardcoded_secret ---
    for pat in SECRET_PATTERNS:
        if re.search(pat, text):
            categories.add("hardcoded_secret")
            break
    if "hardcoded_secret" not in categories:
        for m in SECRET_ASSIGN_RE.finditer(text):
            value_line = m.group(0)
            if not ENV_REF_RE.search(value_line):
                categories.add("hardcoded_secret")
                break

    # --- prompt_injection ---
    for pat in INJECTION_PHRASES:
        if re.search(pat, text, re.IGNORECASE):
            categories.add("prompt_injection")
            break

    # --- excessive_permissions ---
    for pat in EXCESSIVE_PERM_PHRASES:
        if re.search(pat, text, re.IGNORECASE):
            categories.add("excessive_permissions")
            break

    # --- unclear_provenance ---
    fm_match = re.search(r"^---\n(.*?)\n---", text, re.DOTALL)
    frontmatter = fm_match.group(1) if fm_match else ""
    has_author = _has_frontmatter_field(frontmatter, "author")
    has_version = _has_frontmatter_field(frontmatter, "version")
    has_changelog = bool(re.search(r"(?im)^(changelog|change[- ]log)\s*:", frontmatter)) or bool(
        re.search(r"(?im)^##?\s*changelog", text)
    )
    silent_version_bump = bool(
        re.search(r"(?i)(update|bump|rewrite|change).{0,30}version.{0,30}(field|metadata|number)", text)
        and not re.search(r"(?i)(notify|inform|surface|show|report).{0,30}(user|reviewer)", text)
    )
    if (not has_author and not has_version and not has_changelog) or silent_version_bump:
        categories.add("unclear_provenance")

    return sorted(categories)


@router.post("/skill-scanner")
def skill_scanner(req: SkillRequest):
    return {"categories": scan_skill(req.skill)}
