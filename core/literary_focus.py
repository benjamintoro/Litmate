"""Reader-selected work in the existing session, separate from factual evidence.

A requested title can be remembered before its author is verified. It is a
search target, never a bibliographic record or a source for factual answers.
"""
import copy
import re

from .literary_identity import normalize_identity, title_matches, work_identity


def focus_history(state):
    """Build worker input without rewriting an earlier answer's book cards."""
    turns = copy.deepcopy(state.get('turns', []))
    active = state.get('active_work')
    if isinstance(active, dict) and active.get('title'):
        last_focus = turns[-1].get('context_work', {}) if turns else {}
        if (normalize_identity(last_focus.get('title')) == normalize_identity(active['title'])
                and normalize_identity(last_focus.get('author')) == normalize_identity(active.get('author'))):
            return turns
        last_books = turns[-1].get('books', []) if turns else []
        if (len(last_books) == 1
                and normalize_identity(last_books[0].get('title')) == normalize_identity(active['title'])
                and normalize_identity(last_books[0].get('author')) == normalize_identity(active.get('author'))):
            return turns
        turns.append({'accepted': True, 'question': '', 'answer': '',
                      'books': [], 'sources': [], 'context_work': dict(active),
                      'context_only': True})
    return turns


def _select(state, work):
    work = {key: value for key, value in work.items() if key in {
        'title', 'author', 'work_id', 'confirmed_aliases', 'isbns', 'identity_status', 'source', 'url'}}
    if not work.get('title'):
        return
    active = state.get('active_work', {})
    if active.get('title') and normalize_identity(active['title']) != normalize_identity(work['title']):
        state['previous_work'] = dict(active)
    state['active_work'] = work
    order = state.setdefault('work_order', [])
    if not any(normalize_identity(old.get('title')) == normalize_identity(work['title'])
               and (not old.get('author') or not work.get('author')
                    or normalize_identity(old['author']) == normalize_identity(work['author'])) for old in order):
        order.append(dict(work))
    state['work_order'] = order[-24:]


def prepare_focus(state, message):
    """Resolve user intent before workers, including failed/clarification turns."""
    from .ai_narrative_answers import request_for as narrative_request
    from .ai_character_answers import request_for as character_request
    value = normalize_identity(message)
    state['_focus_selected'] = False
    state.pop('_focus_navigation', None)
    order = state.get('work_order', [])
    navigation = re.fullmatch(
        r'(?:volvamos|regresemos|retomemos|vuelve|regresa|retoma)(?: a| al| a la)? '
        r'(?:(?:el|la) )?(primer(?:o|a)?|anterior|ese|esa)(?: libro| novela| obra)?', value)
    if navigation:
        word = navigation.group(1)
        selected = (order[0] if word.startswith('primer') and order else
                    state.get('previous_work') if word == 'anterior' else state.get('active_work'))
        if selected:
            _select(state, selected)
            state['_focus_selected'] = True
            state['_focus_navigation'] = True
            state.pop('pending_clarification', None)
        return
    history = focus_history(state)
    # Summary/title requests take priority over "tell me about <character>".
    narrative = narrative_request(message, history)
    character = character_request(message, history)
    request = narrative or character
    if (narrative and character and character.get('task') == 'character'
            and character.get('title') and character.get('names')):
        # "Háblame de X" can describe a known character, not a new work.
        # Use existing, bound facts to disambiguate; no inference/model call.
        from .ai_character_answers import _bound, _facts, _name_in
        sources = [source for turn in history for source in turn.get('sources', [])]
        facts = _facts(character, _bound(character, sources))
        if any(_name_in(name, fact['name']) for name in character['names'] for fact in facts):
            request = character
    if not request or not request.get('title') or request.get('ambiguous'):
        return
    title = request['title']
    if re.fullmatch(r'(?:(?:el|la) )?(?:primer[oa]?|segund[oa]|tercer[oa]?|anterior)'
                    r'(?: libro| novela| obra)?', normalize_identity(title)):
        return  # Unresolved reference, not a new book named "segundo".
    targets = request.get('targets', [])
    identity = work_identity(targets[0]) if len(targets) == 1 else {}
    work = identity or {'title': title, 'author': request.get('author_hint', ''),
                        'identity_status': 'reader_request'}
    old = state.get('active_work', {})
    if (not identity and normalize_identity(old.get('title')) == normalize_identity(title)
            and (not work.get('author') or normalize_identity(work['author']) == normalize_identity(old.get('author')))):
        work = dict(old)
    if normalize_identity(old.get('title')) != normalize_identity(work['title']):
        state.pop('pending_clarification', None)
    _select(state, work)
    state['_focus_selected'] = True


def remember_focus(state, turn):
    """Refine a selected title only with matching, identified source metadata."""
    from .literary_identity import _history_works
    from .literary_research import is_topic_recommendation
    if turn.get('intent') == 'recommend' or is_topic_recommendation(turn.get('question', '')):
        # Keep suggestion cards in this turn; they are not a reader selection.
        # Explicit ordinal/title references resolve them in the next request.
        if state.get('active_work'):
            turn['context_work'] = dict(state['active_work'])
        return
    works = _history_works(turn)
    active = state.get('active_work', {})
    if state.get('_focus_selected'):
        # Model-only cards are not authority for an author's identity.
        sources = turn.get('sources', [])
        sourced_books = [source for source in sources if source.get('kind') == 'book'
                         and work_identity(source)]
        verified = _history_works({'books': sourced_books, 'sources': sources})
        matching = [work for work in verified if title_matches(active.get('title', ''), work)]
        if len(matching) == 1:
            identity = work_identity(matching[0])
            if identity:
                _select(state, identity)
    elif len(works) == 1:
        _select(state, work_identity(works[0]) or works[0])
    elif works:
        state.pop('active_work', None)
    if state.get('active_work'):
        turn['context_work'] = dict(state['active_work'])
