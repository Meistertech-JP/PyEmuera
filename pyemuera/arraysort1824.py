"""Framework 4.5+ Array.Sort control flow for v24 string ARRAYSORT.

Source-informed adaptation of Microsoft Reference Source's
mscorlib/system/collections/generic/arraysorthelper.cs (both single-array
helpers). Copyright (c) Microsoft Corporation; MIT license and permission:
licenses/MICROSOFT_REFERENCE_SOURCE_MIT.txt. See THIRD_PARTY_NOTICES.md.

Unlike ARRAYMSORT's List, the temporary array has exactly the input length.
Default string[] sorting uses GenericArraySortHelper's Comparable path;
the reversed Comparison delegate uses ArraySortHelper's comparer path.
These differ in pivot receiver, null guards and heap equality handling.
"""

from .errors import EraError


class _ArrayBoundsError(IndexError):
    """A CLR-style array access outside the temporary array."""


def _at(items, index):
    if index < 0 or index >= len(items):
        raise _ArrayBoundsError('Framework Array.Sort array index')
    return items[index]


def _swap(items, left, right):
    if left != right:
        items[left], items[right] = items[right], items[left]


def _swap_if_greater(items, compare, left, right, comparable, is_null):
    if left != right and (not comparable or not is_null(items[left])):
        if compare(items[left], items[right]) > 0:
            _swap(items, left, right)


def _insertion_sort(items, compare, low, high, comparable, is_null):
    for index in range(low, high):
        previous = index
        value = items[index + 1]
        while previous >= low and (
            (comparable and is_null(value)) or compare(value, items[previous]) < 0
        ):
            items[previous + 1] = items[previous]
            previous -= 1
        items[previous + 1] = value


def _down_heap(items, compare, index, count, low, comparable, is_null):
    value = items[low + index - 1]
    while index <= count // 2:
        child = 2 * index
        if child < count and (
            (comparable and is_null(items[low + child - 1]))
            or compare(items[low + child - 1], items[low + child]) < 0
        ):
            child += 1
        candidate = items[low + child - 1]
        if comparable:
            # Comparable compares child to saved value, and moves equal keys.
            if is_null(candidate) or compare(candidate, value) < 0:
                break
        elif compare(value, candidate) >= 0:
            break
        items[low + index - 1] = candidate
        index = child
    items[low + index - 1] = value


def _heap_sort(items, compare, low, high, comparable, is_null):
    count = high - low + 1
    for index in range(count // 2, 0, -1):
        _down_heap(items, compare, index, count, low, comparable, is_null)
    for index in range(count, 1, -1):
        _swap(items, low, low + index - 1)
        _down_heap(items, compare, 1, index - 1, low, comparable, is_null)


def _partition(items, compare, low, high, comparable, is_null):
    middle = low + (high - low) // 2
    for left, right in ((low, middle), (low, high), (middle, high)):
        _swap_if_greater(items, compare, left, right, comparable, is_null)
    pivot = items[middle]
    _swap(items, middle, high - 1)
    left, right = low, high - 1
    while left < right:
        if comparable and is_null(pivot):
            while left < high - 1:
                left += 1
                if not is_null(_at(items, left)):
                    break
            while right > low:
                right -= 1
                if is_null(_at(items, right)):
                    break
        elif comparable:
            left += 1
            while compare(pivot, _at(items, left)) > 0:
                left += 1
            right -= 1
            while compare(pivot, _at(items, right)) < 0:
                right -= 1
        else:
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


def _intro_sort(items, compare, low, high, depth, comparable, is_null):
    while high > low:
        count = high - low + 1
        if count <= 16:
            if count == 2:
                _swap_if_greater(items, compare, low, high, comparable, is_null)
            elif count == 3:
                for left, right in ((low, high - 1), (low, high), (high - 1, high)):
                    _swap_if_greater(items, compare, left, right, comparable, is_null)
            else:
                _insertion_sort(items, compare, low, high, comparable, is_null)
            return
        if depth == 0:
            _heap_sort(items, compare, low, high, comparable, is_null)
            return
        depth -= 1
        pivot = _partition(items, compare, low, high, comparable, is_null)
        _intro_sort(items, compare, pivot + 1, high, depth, comparable, is_null)
        high = pivot - 1


def _sort_in_place(items, compare, *, comparable, is_null=lambda value: value is None):
    """Raw temporary-array mutation; comparison failures leave partial state.

    Exposed internally for differential trace tests. The public API stages all
    changes. Framework FloorLog2 counts binary digits, including the top bit.
    """
    if len(items) > 1:
        _intro_sort(items, compare, 0, len(items) - 1, 2 * len(items).bit_length(),
                    comparable, is_null)


def framework_array_sort(values, *, backward=False, compare=None):
    """Return a sorted copy; never mutate the caller's sequence.

    The caller validates/snapshots its requested range before this call and
    writes back only after success. Default comparison is obtained dynamically
    from collation1824, so backend selection and fault injection remain visible.
    Backend exceptions propagate unchanged, preserving the Python contract.
    None is supported as a Framework diagnostic value; game string variables
    normally supply strings. BACK's null receiver raises before copy-back.
    """
    items = list(values)
    if compare is None:
        from .collation1824 import compare_strings

        compare = compare_strings

    def compare_to(left, right):
        if left is None:
            raise EraError('ARRAYSORT null String.CompareTo receiver', code='E_RUNTIME')
        if right is None:
            return 1
        return compare(left, right)

    def reversed_compare(left, right):
        return compare_to(right, left)

    try:
        _sort_in_place(items, reversed_compare if backward else compare_to,
                       comparable=not backward)
    except _ArrayBoundsError as exc:
        # Framework translates internal IndexOutOfRange to ArgumentException.
        # Do not catch arbitrary backend IndexError or EraError here.
        raise EraError('ARRAYSORT comparer produced inconsistent sort results',
                       code='E_ARGUMENT') from exc
    return items
