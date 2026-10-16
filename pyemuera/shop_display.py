"""SHOP list shares purchase availability; skip precedes evaluation."""


def execute(vm, spec, arg):
    op = spec['name']
    console = vm.console
    if console.skip_print:
        return True
    from .shop_purchase import item_on_sale

    names = vm.data.variables['ITEMNAME']
    sales = vm.data.variables['ITEMSALES']
    prices = vm.data.variables['ITEMPRICE']
    count = 0
    from .printing import column_text

    per_line = int(vm.data.config.get('PRINTCを並べる数', '3'))
    for i in range(min(names.dims[0], sales.dims[0], prices.dims[0])):
        if item_on_sale(vm.data, i):
            text = (
                f'[{i}] {names.get((i, ))}({vm.data.settings.money(prices.get((i, )))})'
            )
            console.write(column_text(vm, text, 'left'))
            count += 1
            if per_line > 0 and count % per_line == 0:
                console.write('', True)
    if console.current:
        console.write('', True)
    return True
