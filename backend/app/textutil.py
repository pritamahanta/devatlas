"""Small text helpers shared by embeddings and retrieval."""
import re

_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "do", "does", "did",
    "how", "what", "where", "when", "which", "who", "why", "in", "on", "of", "to",
    "for", "from", "with", "and", "or", "it", "its", "this", "that", "these", "those",
    "can", "could", "should", "would", "me", "my", "i", "you", "we", "by", "as", "at",
    "if", "not", "there", "about", "into", "used", "use", "work", "works", "get",
}


def split_identifier(token: str) -> list[str]:
    """get_user_byId -> ['get', 'user', 'by', 'id'] (lowercase parts)."""
    parts: list[str] = []
    for chunk in token.split("_"):
        parts += [m.group(0).lower() for m in _WORD.finditer(chunk)]
    return parts
