from __future__ import annotations

import json
import re
from dataclasses import dataclass

from shared.billing import CostSession
from shared.kb import article_ids, load_article
from shared.llm import ChatMessage, LlmClient
from shared.tools import format_thread, get_order, get_ticket

from question1.agent import parse_resolution


@dataclass
class TicketResolution:
    action: str
    kb_article: str


# >>> Retrieval: deterministic, zero LLM tokens
_STOP = {"the", "a", "an", "of", "to", "i", "my", "you", "is", "it", "and", "for", "in", "on", "was", "me", "can", "please"}
_VALID_ACTIONS = {"REFUND", "REPLACE", "SEND_ARTICLE", "ESCALATE_TIER2"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 2}


def _order_terms(order: dict) -> str:
    terms = [str(order.get("product_type", "")), str(order.get("sku", ""))]
    if order.get("customized"):
        terms.append("custom personalized")
    if order.get("license_revealed"):
        terms.append("digital license key")
    if order.get("damage_reported"):
        terms.append("damaged replacement")
    if "subscription_age_days" in order:
        terms.append("subscription annual cancelled")
    if order.get("product_type") == "physical" and not order.get("damage_reported"):
        terms.append("returns refund physical")
    return " ".join(terms)


def retrieve_articles(thread: str, order: dict, k: int = 2) -> list[str]:
    # >>> Order facts weigh 2x thread words (thread can contain negations like "not custom")
    qt = _words(thread)
    qo = _words(_order_terms(order))
    scored = []
    for aid in article_ids():
        doc = _words(aid.replace("-", " ") + " " + load_article(aid))
        scored.append((2 * len(qo & doc) + len(qt & doc), aid))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [aid for _, aid in scored[:k]]


def _compact(aid: str) -> str:
    body = " ".join(ln.strip() for ln in load_article(aid).splitlines() if ln.strip() and not ln.startswith("#"))
    return f"{aid}: {body}"


_SYSTEM = (
    "ShopAssist Tier-1 support router. Choose one action and the KB article that backs it.\n"
    "Actions: REFUND, REPLACE, SEND_ARTICLE, ESCALATE_TIER2.\n"
    'Output only compact JSON: {"action":"...","kb_article":"..."}'
)


class SupportPipeline:
    """Same product as Question 1 - collapsed to one LLM call + code-side retrieve/audit."""

    def __init__(self, session: CostSession | None = None):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        ticket = get_ticket(ticket_id)
        order = get_order(ticket["order_id"])
        thread = format_thread(ticket)
        snapshot = json.dumps(order, separators=(",", ":"))

        # >>> retrieve (code) -> compose (1 LLM call) -> audit (code)
        ids = retrieve_articles(thread, order)
        user = (
            "KB:\n" + "\n".join(_compact(a) for a in ids)
            + f"\nTHREAD:\n{thread}\nORDER_SNAPSHOT:\n{snapshot}\nEND_SNAPSHOT"
        )
        raw = self.llm.chat("compose", [ChatMessage("system", _SYSTEM), ChatMessage("user", user)])
        parsed = parse_resolution(raw)

        if parsed.action not in _VALID_ACTIONS or parsed.kb_article not in article_ids():
            return TicketResolution("ESCALATE_TIER2", ids[0] if ids else "")
        return TicketResolution(parsed.action, parsed.kb_article)
