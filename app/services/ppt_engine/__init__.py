# -*- coding: utf-8 -*-
"""华为红售前 PPT 引擎（模板唯一出口）

用法：
    from app.services.ppt_engine import render_deck, DeckValidationError
    n = render_deck(prs, deck)   # deck 未过门禁抛 DeckValidationError
"""
from .engine import render_deck, validate_deck, DeckValidationError
from .layouts import SLOT_SPEC, LAYOUTS
from . import tokens

__all__ = ['render_deck', 'validate_deck', 'DeckValidationError',
           'SLOT_SPEC', 'LAYOUTS', 'tokens']
