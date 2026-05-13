"""humanize_zh._core — backward-compat shim package.

P2.8a/P2.8b collapsed the language-registry, protocol, and prompt
modules onto ``humanize_core``. This package now exists *purely* to
keep the legacy import paths
(``humanize_zh._core.language_registry``,
``humanize_zh._core.protocols``,
``humanize_zh._core.prompt``)
working: each name is aliased into ``sys.modules`` to point at the
live ``humanize_core`` module.

Why aliasing instead of ``from … import *``? Tests reach into
private attributes (``reg._LOCK``, ``reg._DISCOVERY_DONE``) and *write*
to them. A wildcard re-export would copy the names into a fresh
namespace, so writes would diverge from the canonical module. Sharing
the module object means every consumer sees the same mutable state.

The ZH-specific ``build_humanize_postprocess_prompt`` dispatcher used
to live in ``humanize_zh._core.prompt`` (alongside the EN placeholder
templates). P2.8b moved it to :mod:`humanize_zh.prompt` because the
rule-list injection it does is plugin-internal — only ZH consults the
rule list. The framework EN templates remain in ``humanize_core.prompt``
which is what the alias above resolves to.
"""
from __future__ import annotations

import sys as _sys

from humanize_core import language_registry as _language_registry
from humanize_core import prompt as _prompt
from humanize_core import protocols as _protocols

_sys.modules[__name__ + ".language_registry"] = _language_registry
_sys.modules[__name__ + ".protocols"] = _protocols
_sys.modules[__name__ + ".prompt"] = _prompt

del _sys, _language_registry, _protocols, _prompt
