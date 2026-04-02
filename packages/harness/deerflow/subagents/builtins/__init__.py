"""Built-in subagent configurations."""

from .bash_agent import BASH_AGENT_CONFIG
from .general_purpose import GENERAL_PURPOSE_CONFIG
from .rumor_evidence_archiver import RUMOR_EVIDENCE_ARCHIVER_CONFIG
from .rumor_knowledge_analyst import RUMOR_KNOWLEDGE_ANALYST_CONFIG
from .rumor_rag_analyst import RUMOR_RAG_ANALYST_CONFIG
from .rumor_web_researcher import RUMOR_WEB_RESEARCHER_CONFIG

__all__ = [
    "GENERAL_PURPOSE_CONFIG",
    "BASH_AGENT_CONFIG",
    "RUMOR_WEB_RESEARCHER_CONFIG",
    "RUMOR_KNOWLEDGE_ANALYST_CONFIG",
    "RUMOR_RAG_ANALYST_CONFIG",
    "RUMOR_EVIDENCE_ARCHIVER_CONFIG",
]

# Registry of built-in subagents
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "web-researcher": RUMOR_WEB_RESEARCHER_CONFIG,
    "knowledge-analyst": RUMOR_KNOWLEDGE_ANALYST_CONFIG,
    "rag-analyst": RUMOR_RAG_ANALYST_CONFIG,
    "evidence-archiver": RUMOR_EVIDENCE_ARCHIVER_CONFIG,
}
