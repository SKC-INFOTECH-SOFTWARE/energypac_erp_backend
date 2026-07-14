"""
Document numbering — collision-proof.

Every generator in the system was written as "take the last row, add 1":

    last = Model.objects.filter(number__startswith=prefix).order_by('-created_at').first()
    new  = int(last.number.split('/')[-1]) + 1

That breaks in three ways, and all three end in a duplicate number:

  1. `-created_at` is not `-number`. The newest row is not necessarily the highest
     number — especially once a user types their own number, or a revision suffixes
     an 'R'.
  2. A user-entered number is invisible to the generator, so the next auto number
     can land straight on top of it.
  3. Two people saving at the same moment compute the same "next" number.

next_number() instead takes the highest numeric suffix actually in use for that
prefix and then walks forward until it finds a number nobody holds. Combined with
the UNIQUE constraint in the database (and a retry on the create path), the same
number can never be issued twice — auto-generated or hand-typed.
"""

import re

_TRAILING_INT = re.compile(r'(\d+)\D*$')


def _suffix_int(value):
    """'EEL/IND/RAJ/101R' → 101 ; 'EEL/2026/007' → 7 ; anything odd → None"""
    if not value:
        return None
    match = _TRAILING_INT.search(value)
    return int(match.group(1)) if match else None


def next_number(model, field, prefix, width, start=1):
    """
    Next free number for `prefix`, e.g. next_number(Requisition, 'requisition_number',
    'EEL/2026/', 3) → 'EEL/2026/011'.

    Looks at the highest suffix in use (not the most recent row) and skips anything
    already taken, so it can never collide with a hand-typed number.
    """
    existing = model.objects.filter(
        **{f'{field}__startswith': prefix}
    ).values_list(field, flat=True)

    taken = set(existing)
    highest = start - 1
    for value in existing:
        number = _suffix_int(value[len(prefix):] if value.startswith(prefix) else value)
        if number is not None and number > highest:
            highest = number

    candidate_num = max(highest + 1, start)
    while True:
        candidate = f'{prefix}{candidate_num:0{width}d}'
        if candidate not in taken and not model.objects.filter(**{field: candidate}).exists():
            return candidate
        candidate_num += 1
