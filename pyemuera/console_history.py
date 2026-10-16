"""History operations suppress argument evaluation before touching Console."""

from .expr import integer


def execute(vm, spec, arg):
    console = vm.console
    if console.skip_print:
        return True
    if spec['name'] == 'CLEARLINE':
        console.clear_lines(integer(vm.eval(arg)))
    else:
        console.reuse_line(vm.format(arg))
    return True
