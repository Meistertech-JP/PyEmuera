"""VariableEvaluator.ItemSales/BuyItem: availability and ordered side effects."""


def item_on_sale(data, index):
    sales = data.variables['ITEMSALES']
    names = data.variables['ITEMNAME']
    if index < 0 or index >= sales.dims[0] or index >= names.dims[0]:
        return False
    # Native distinguishes a null CSV entry from an explicitly empty name.
    # Sparse string variables expose both as "", so retain CSV definition
    # presence separately. Nonempty internal API assignments also define a name.
    defined = index in data.item_name_definitions or (index,) in names.values
    return sales.get((index,)) != 0 and defined


def buy_item(vm, index):
    if not item_on_sale(vm.data, index):
        return False
    prices = vm.data.variables['ITEMPRICE']
    if index >= prices.dims[0]:
        return False
    price = prices.get((index,))
    if vm.get('MONEY') < price:
        return False
    # Do not preflight ITEM bounds or move BOUGHT earlier: the native array
    # write can fail after MONEY has already changed. Each set wraps Int64.
    vm.set('MONEY', vm.get('MONEY') - price)
    items = vm.data.variables['ITEM']
    items.set((index,), items.get((index,)) + 1)
    vm.set('BOUGHT', index)
    return True


def callback_keeps_input(console):
    """A temporary callback result retries input without SHOW_SHOP again."""
    if not console.temporary_line:
        return False
    if not console.current.strip():
        console.write('無効な値です', True)
    return True
