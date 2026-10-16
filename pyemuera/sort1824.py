"""The generic .NET Framework 4.5+ sort used by v24 ARRAYMSORT.

Source-informed Python adaptation of Microsoft Reference Source's
mscorlib/system/collections/generic/arraysorthelper.cs and list.cs.
Copyright (c) Microsoft Corporation. Licensed under the MIT license;
see licenses/MICROSOFT_REFERENCE_SOURCE_MIT.txt and THIRD_PARTY_NOTICES.md.

This deliberately preserves comparison direction, swaps, small-partition
networks, right-first recursion, and backing-array capacity. A wrapped Int64
subtraction is not a total order; replacing it with Python's sorted() changes
observable results. Sort mechanics use no CLR; string comparison delegates to
the independent culture backend rather than to Python's scalar ordering.
"""

from .errors import EraError


def compare_int64(left, right):
    """Math.Sign(unchecked((long)left - (long)right)), including overflow."""
    difference = (left - right + (1 << 63)) % (1 << 64) - (1 << 63)
    return (difference > 0) - (difference < 0)


def _swap(items, left, right):
    if left != right:
        items[left], items[right] = items[right], items[left]


def _swap_if_greater(items, compare, left, right):
    if left != right and compare(items[left], items[right]) > 0:
        _swap(items, left, right)


def _insertion_sort(items, compare, low, high):
    for index in range(low, high):
        previous = index
        value = items[index + 1]
        while previous >= low and compare(value, items[previous]) < 0:
            items[previous + 1] = items[previous]
            previous -= 1
        items[previous + 1] = value


def _down_heap(items, compare, index, count, low):
    value = items[low + index - 1]
    while index <= count // 2:
        child = 2 * index
        if child < count and compare(items[low + child - 1], items[low + child]) < 0:
            child += 1
        if compare(value, items[low + child - 1]) >= 0:
            break
        items[low + index - 1] = items[low + child - 1]
        index = child
    items[low + index - 1] = value


def _heap_sort(items, compare, low, high):
    count = high - low + 1
    for index in range(count // 2, 0, -1):
        _down_heap(items, compare, index, count, low)
    for index in range(count, 1, -1):
        _swap(items, low, low + index - 1)
        _down_heap(items, compare, 1, index - 1, low)


def _at(items, index):
    # C# arrays reject negative indices; Python lists otherwise wrap them.
    if index < 0 or index >= len(items):
        raise IndexError('Framework sort backing-array index')
    return items[index]


def _partition(items, compare, low, high):
    middle = low + (high - low) // 2
    _swap_if_greater(items, compare, low, middle)
    _swap_if_greater(items, compare, low, high)
    _swap_if_greater(items, compare, middle, high)
    pivot = items[middle]
    _swap(items, middle, high - 1)
    left, right = low, high - 1
    while left < right:
        left += 1
        while compare(_at(items, left), pivot) < 0:
            left += 1
        right -= 1
        while compare(pivot, _at(items, right)) < 0:
            right -= 1
        if left >= right:
            break
        _swap(items, left, right)
    _swap(items, left, high - 1)
    return left


def _intro_sort(items, compare, low, high, depth):
    while high > low:
        count = high - low + 1
        if count <= 16:
            if count == 2:
                _swap_if_greater(items, compare, low, high)
            elif count == 3:
                _swap_if_greater(items, compare, low, high - 1)
                _swap_if_greater(items, compare, low, high)
                _swap_if_greater(items, compare, high - 1, high)
            else:
                _insertion_sort(items, compare, low, high)
            return
        if depth == 0:
            _heap_sort(items, compare, low, high)
            return
        depth -= 1
        pivot = _partition(items, compare, low, high)
        _intro_sort(items, compare, pivot + 1, high, depth)
        high = pivot - 1


def framework_list_order(keys, *, string=False):
    """Return source-row indices from a default List built by successive Add.

    The caller stages its game-array writes until this succeeds. Unused capacity
    consists of default KeyValuePair values, as in the managed backing array.
    String comparison belongs to collation1824: Windows delegates to NLS,
    while other hosts use the pinned portable ja-JP profile. Received Framework
    and native observations are bounded oracles; broader culture/Unicode claims
    remain outside this sorting algorithm.
    """
    count = len(keys)
    if count < 2:
        return list(range(count))
    capacity = max(4, 1 << (count - 1).bit_length())
    items = [(key, index) for index, key in enumerate(keys)]
    items.extend([(None if string else 0, 0)] * (capacity - count))

    def compare(left, right):
        if not string:
            return compare_int64(left[0], right[0])
        # Comparison and sort mechanics are independent responsibilities.
        # Nonempty string keys cannot expose padding for a consistent order.
        from .collation1824 import compare_strings

        return compare_strings(left[0], right[0])

    try:
        # Reference Source FloorLog2 counts binary digits, including the top bit.
        _intro_sort(items, compare, 0, count - 1, 2 * capacity.bit_length())
    except IndexError as exc:
        # Framework 4.5+ throws Arg_BogusIComparer rather than returning a partial
        # sort. The local List can change, but Emuera has not copied any row yet.
        # Numeric diagnostic profile: received ja-JP Framework 4.8-targeted
        # execution on installed 4.8.1. Preserve the Python API classification
        # and cause; do not project a CLR stack or claim all UI cultures match.
        raise EraError(
            'ARRAYMSORT comparer produced inconsistent sort results',
            code='E_ARGUMENT',
            diagnostic_message=(
                'System.ArgumentException:IComparer.Compare() メソッドから矛盾する結果が返されたため、'
                '並べ替えできません。値をそれ自体と比較したときに等しい結果にならないか、'
                'またはある値を別の値と繰り返し比較したときに異なる結果が生じます。'
                "IComparer: 'System.Array+FunctorComparer`1[System.Collections.Generic."
                "KeyValuePair`2[System.Int64,System.Int32]]'。"
                if not string
                else None
            ),
        ) from exc
    return [item[1] for item in items[:count]]
