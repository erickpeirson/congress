from govtrack import govtrack_type_codes
from . import utils


def create_govtrack_xml(amendment_data, options):
    """
    Generate a GovTrack XML document from amendment data.

    Parameters
    ----------
    amendment_data : dict
        These data have already been parsed/restructured from the original
        FDSYS data.
    options : dict

    Returns
    -------
    str
        Full XML document.
    """
    root = etree.Element("amendment")
    root.set("session", amendment_data['congress'])
    root.set("chamber", amendment_data['amendment_type'][0])
    root.set("number", str(amendment_data['number']))
    root.set("updated", utils.format_datetime(amendment_data['updated_at']))



    if amendment_data.get("amends_bill", None):
        utils.make_node(root, "amends", None,
                  type=govtrack_type_codes[amendment_data["amends_bill"]["bill_type"]],
                  number=str(amendment_data["amends_bill"]["number"]),
                  sequence=str(amendment_data["house_number"]) if amendment_data.get("house_number", None) else "")
    elif amendment_data.get("amends_treaty", None):
        utils.make_node(root, "amends", None,
                  type="treaty",
                  number=str(amendment_data["amends_treaty"]["number"]))

    utils.make_node(root, "status", amendment_data['status'], datetime=amendment_data['status_at'])

    if amendment_data['sponsor'] and amendment_data['sponsor']['type'] == 'person':
        v = amendment_data['sponsor']['bioguide_id']
        if not options.get("govtrack", False):
            utils.make_node(root, "sponsor", None, bioguide_id=v)
        else:
            v = str(utils.translate_legislator_id('bioguide', v, 'govtrack'))
            utils.make_node(root, "sponsor", None, id=v)
    elif amendment_data['sponsor'] and amendment_data['sponsor']['type'] == 'committee':
        utils.make_node(root, "sponsor", None, committee=amendment_data['sponsor']['name'])
    else:
        utils.make_node(root, "sponsor", None)

    utils.make_node(root, "offered", None, datetime=amendment_data['introduced_at'])

    utils.make_node(root, "description", amendment_data["description"] if amendment_data["description"] else amendment_data["purpose"])
    if amendment_data["description"]:
        utils.make_node(root, "purpose", amendment_data["purpose"])

    actions = utils.make_node(root, "actions", None)
    for action in amendment_data['actions']:
        a = utils.make_node(actions,
                      action['type'] if action['type'] in ("vote",) else "action",
                      None,
                      datetime=action['acted_at'])
        if action['type'] == 'vote':
            a.set("how", action["how"])
            a.set("result", action["result"])
            if action.get("roll") != None:
                a.set("roll", str(action["roll"]))
        if action.get('text'):
            utils.make_node(a, "text", action['text'])
        if action.get('in_committee'):
            utils.make_node(a, "committee", None, name=action['in_committee'])
        for cr in action['references']:
            utils.make_node(a, "reference", None, ref=cr['reference'], label=cr['type'])

    return etree.tostring(root, pretty_print=True)


def process_amendment(fdsys_data, bill_id, options):
    """
    Rewrite FDSYS amendment data (parsed from XML) as JSON and GovTrack XML
    documents.
    """
    data = amendments.parse_fdsys_amendment_data(fdsys_data, options)
    path = amendment_output_path(data['amendment_id'], "json")

    logging.info("[%s] Saving %s to %s..." % (bill_id, data['amendment_id'], path))

    # output JSON - so easy!
    utils.write(json.dumps(data, sort_keys=True, indent=2, default=utils.format_datetime), path)

    with open(output_path(data['amendment_id'], "xml"), 'wb') as xml_file:
        xml_file.write(create_govtrack_xml(data, options))


def output_path(amendment_id, file_extension):
    """
    Generate an output file path for an amendment.

    Parameters
    ----------
    amendment_id : str
    file_extension : str
        E.g. 'xml' or 'json'

    Returns
    -------
    str
        Full path to file (which may not yet exist).
    """
    amendment_type, number, congress = utils.split_bill_id(amendment_id)
    return "%s/%s/amendments/%s/%s%s/%s" % (utils.data_dir(), congress, amendment_type, amendment_type, number, "data.%s" % file_extension)
