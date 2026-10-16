"""Bulk assignment error presentation, preserving sequential writes/exceptions."""

from .errors import EraError


def write_many(refs, values):
    for position, (ref, value) in enumerate(zip(refs, values)):
        try:
            ref.set(value)
        except EraError as error:
            # VariableTerm.SetValue(array) first CheckElement(original index),
            # then reports element-count overflow. Successful prior writes prove
            # the original start index was valid; do not replace first-index errors.
            if position > 0 and error.code == 'E_INDEX':
                error.diagnostic_message = (
                    '配列変数'
                    + ref.variable.name
                    + 'の要素数を超えて代入しようとしました'
                )
            raise
