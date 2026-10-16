"""SELECTCASE search and natural-flow error edges (v24 IsError contract)."""


def skip_search_error(frame, instruction):
    if instruction.op != '_CASE':
        return False
    select, _ = instruction.data
    if select not in frame.select_searches:
        return False
    frame.pc = instruction.jump
    return True


def case_match(vm, frame, instruction, pc):
    select, default = instruction.data
    if default or vm._case(frame.selects[select], instruction.arg):
        frame.select_searches.discard(select)
    else:
        frame.pc = instruction.jump


def exit_target(frame, instruction):
    if isinstance(instruction.data, tuple) and instruction.data[0] == 'select_exit':
        candidate = instruction.data[1]
        if frame.function.code[candidate].argument_error is not None:
            return candidate
    return instruction.jump
