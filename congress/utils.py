def split_bill_id(bill_id):
    return re.match("^([a-z]+)(\d+)-(\d+)$", bill_id).groups()
