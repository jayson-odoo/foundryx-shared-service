"""Template engine (plan sprint-2/07) - the third platform engine.

PLATFORM CORE, not an App Store module (core auth mails render through it;
the Workflow engine consumes ``render_email``). Modules adopt it by
registering :class:`~app.template_engine.contexts.TemplateContext` rows at
install - same lifecycle as permissions.csv / fact sources / status entities.
"""

from app.template_engine.compiler import compile_document, document_text
from app.template_engine.contexts import (
    TemplateContext,
    ensure_core_contexts,
    get_context,
    list_contexts,
    register_context,
)
from app.template_engine.merge import collect_tokens, render_tokens
from app.template_engine.renderer import (
    RenderedEmail,
    render_canvas,
    render_canvas_batch,
    render_canvas_html,
    render_document,
    render_email,
    render_email_doc,
)
from app.template_engine.schemas import (
    CanvasDocumentModel,
    TemplateDocumentModel,
    validate_canvas_doc,
    validate_doc,
)

__all__ = [
    "CanvasDocumentModel",
    "TemplateContext",
    "TemplateDocumentModel",
    "RenderedEmail",
    "collect_tokens",
    "compile_document",
    "document_text",
    "ensure_core_contexts",
    "get_context",
    "list_contexts",
    "register_context",
    "render_canvas",
    "render_canvas_batch",
    "render_canvas_html",
    "render_document",
    "render_email",
    "render_email_doc",
    "render_tokens",
    "validate_canvas_doc",
    "validate_doc",
]
