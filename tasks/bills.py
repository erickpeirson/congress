import json
import logging
import os
import re
import xmltodict

from congress import bill_info, amendments
from congress import utils as congress_utils
import fdsys

from . import bill_info, utils


def run(options):
    bill_id = options.get('bill_id', None)

    if bill_id:
        bill_type, number, congress = utils.split_bill_id(bill_id)
        to_fetch = [bill_id]
    else:
        to_fetch = get_bills_to_process(options)

        if not to_fetch:
            logging.warn("No bills changed.")
            return None

        limit = options.get('limit', None)
        if limit:
            to_fetch = to_fetch[:int(limit)]

    utils.process_set(to_fetch, process_bill, options)


def get_bills_to_process(options):
    # Return a generator over bill_ids that need to be processed.
    # Every time we process a bill we copy the fdsys_billstatus-lastmod.txt
    # file to data-fromfdsys-lastmod.txt, next to data.json. This way we
    # know when the FDSys XML file has changed.

    def get_data_path(*args):
        # Utility function to generate a part of the path
        # to data/{congress}/bills/{billtype}/{billtypenumber}
        # given as many path elements as are provided. args
        # is a list of zero or more of congress, billtype,
        # and billtypenumber (in order).
        args = list(args)
        if len(args) > 0:
            args.insert(1, "bills")
        return os.path.join(utils.data_dir(), *args)

    if not options.get('congress'):
        # Get a list of all congress directories on disk.
        # Filter out non-integer directory names, then sort on the
        # integer.
        def filter_ints(seq):
            for s in seq:
                try:
                    yield int(s)
                except:
                    # Not an integer.
                    continue
        congresses = sorted(filter_ints(os.listdir(get_data_path())))
    else:
        congresses = sorted([int(c) for c in options['congress'].split(',')])

    # walk through congresses
    for congress in congresses:
        # turn this back into a string
        congress = str(congress)

        # walk through all bill types in that congress
        # (sort by bill type so that we proceed in a stable order each run)

        bill_types = [bill_type for bill_type in os.listdir(get_data_path(congress)) if not bill_type.startswith(".")]

        for bill_type in sorted(bill_types):

            # walk through each bill in that congress and bill type
            # (sort by bill number so that we proceed in a normal order)

            bills = [bill for bill in os.listdir(get_data_path(congress, bill_type)) if not bill.startswith(".")]
            for bill_type_and_number in sorted(
                bills,
                key = lambda x : int(x.replace(bill_type, ""))
                ):

                fn = get_data_path(congress, bill_type, bill_type_and_number, fdsys.FDSYS_BILLSTATUS_FILENAME)
                if os.path.exists(fn):
                    # The FDSys bulk data file exists. Does our JSON data
                    # file need to be updated?
                    bulkfile_lastmod = utils.read(fn.replace(".xml", "-lastmod.txt"))
                    parse_lastmod = utils.read(get_data_path(congress, bill_type, bill_type_and_number, "data-fromfdsys-lastmod.txt"))
                    if bulkfile_lastmod != parse_lastmod or options.get("force"):
                        bill_id = bill_type_and_number + "-" + congress
                        yield bill_id


def process_bill(bill_id, options):
    """
    Parse FDSYS XML record for a bill, and save the data as JSON and GovTrack
    XML.

    Parameters
    ----------
    bill_id
    options

    Returns
    -------
    dict
    """
    fdsys_xml_path = _path_to_billstatus_file(bill_id)
    logging.info("[%s] Processing %s..." % (bill_id, fdsys_xml_path))

    # Read FDSys bulk data file.
    xml_as_dict = read_fdsys_bulk_bill_status_file(fdsys_xml_path, bill_id)
    bill_data = form_bill_json_dict(xml_as_dict)

    # Convert and write out data.json and data.xml.
    utils.write(
        unicode(json.dumps(bill_data, indent=2, sort_keys=True)),
        os.path.dirname(fdsys_xml_path) + '/data.json')

    with open(os.path.dirname(fdsys_xml_path) + '/data.xml', 'wb') as xml_file:
        xml_file.write(create_govtrack_xml(bill_data, options))

    if options.get("amendments", True):
        process_amendments(bill_id, xml_as_dict, options)

    # Mark this bulk data file as processed by saving its lastmod
    # file under a new path.
    utils.write(
        utils.read(_path_to_billstatus_file(bill_id).replace(".xml", "-lastmod.txt")),
        os.path.join(os.path.dirname(fdsys_xml_path), "data-fromfdsys-lastmod.txt"))

    return {
        "ok": True,
        "saved": True,
    }

r
def _path_to_billstatus_file(bill_id):
    return output_for_bill(bill_id, fdsys.FDSYS_BILLSTATUS_FILENAME, is_data_dot=False)

def read_fdsys_bulk_bill_status_file(fn, bill_id):
    fdsys_billstatus = utils.read(fn)
    return xmltodict.parse(fdsys_billstatus, force_list=('item', 'amendment', 'committeeReport',))


def output_for_bill(bill_id, format, is_data_dot=True):
    """
    Builds an output path for data about a bill.

    Parameters
    ----------
    bill_id
    format
    is_data_dot : bool

    Returns
    -------
    str
    """
    bill_type, number, congress = utils.split_bill_id(bill_id)
    if is_data_dot:
        fn = "data.%s" % format
    else:
        fn = format
    return "%s/%s/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, fn)


def process_amendments(bill_id, bill_amendments, options):
    amdt_list = bill_amendments['billStatus']['bill']['amendments']
    if amdt_list is None:  # many bills don't have amendments
        return

    for amdt in amdt_list['amendment']:
        amendments.process_amendment(amdt, bill_id, options)


def create_govtrack_xml(bill, options):
    """
    Generate a GovTrack XML document from bill data.
    """

    root = etree.Element("bill")
    root.set("session", bill['congress'])
    root.set("type", govtrack_type_codes[bill['bill_type']])
    root.set("number", bill['number'])
    root.set("updated", utils.format_datetime(bill['updated_at']))

    def make_node(parent, tag, text, **attrs):
        if options.get("govtrack", False):
            # Rewrite bioguide_id attributes as just id with GovTrack person IDs.
            attrs2 = {}
            for k, v in attrs.items():
                if v:
                    if k == "bioguide_id":
                        # remap "bioguide_id" attributes to govtrack "id"
                        k = "id"
                        v = str(utils.translate_legislator_id('bioguide', v, 'govtrack'))
                    attrs2[k] = v
            attrs = attrs2

        return utils.make_node(parent, tag, text, **attrs)

    # for American Memory Century of Lawmaking bills...
    for source in bill.get("sources", []):
        n = make_node(root, "source", "")
        for k, v in sorted(source.items()):
            if k == "source":
                n.text = v
            elif k == "source_url":
                n.set("url", v)
            else:
                n.set(k, unicode(v))
    if "original_bill_number" in bill:
        make_node(root, "bill-number", bill["original_bill_number"])

    make_node(root, "state", bill['status'], datetime=bill['status_at'])
    old_status = make_node(root, "status", None)
    make_node(old_status, "introduced" if bill['status'] in ("INTRODUCED", "REFERRED") else "unknown", None, datetime=bill['status_at'])  # dummy for the sake of comparison

    make_node(root, "introduced", None, datetime=bill['introduced_at'])
    titles = make_node(root, "titles", None)
    for title in bill['titles']:
        n = make_node(titles, "title", title['title'])
        n.set("type", title['type'])
        if title['as']:
            n.set("as", title['as'])
        if title['is_for_portion']:
            n.set("partial", "1")

    if bill['sponsor']:
        # TODO: Sponsored by committee?
        make_node(root, "sponsor", None, bioguide_id=bill['sponsor']['bioguide_id'])
    else:
        make_node(root, "sponsor", None)

    cosponsors = make_node(root, "cosponsors", None)
    for cosp in bill['cosponsors']:
        n = make_node(cosponsors, "cosponsor", None, bioguide_id=cosp["bioguide_id"])
        if cosp["sponsored_at"]:
            n.set("joined", cosp["sponsored_at"])
        if cosp["withdrawn_at"]:
            n.set("withdrawn", cosp["withdrawn_at"])

    actions = make_node(root, "actions", None)
    for action in bill['actions']:
        a = make_node(actions,
                      action['type'] if action['type'] in ("vote", "vote-aux", "calendar", "topresident", "signed", "enacted", "vetoed") else "action",
                      None,
                      datetime=action['acted_at'])
        if action.get("status"):
            a.set("state", action["status"])
        if action['type'] in ('vote', 'vote-aux'):
            a.clear()  # re-insert date between some of these attributes
            a.set("how", action["how"])
            a.set("type", action["vote_type"])
            if action.get("roll") != None:
                a.set("roll", action["roll"])
            a.set("datetime", utils.format_datetime(action['acted_at']))
            a.set("where", action["where"])
            a.set("result", action["result"])
            if action.get("suspension"):
                a.set("suspension", "1")
            if action.get("status"):
                a.set("state", action["status"])
        if action['type'] == 'calendar' and "calendar" in action:
            a.set("calendar", action["calendar"])
            if action["under"]:
                a.set("under", action["under"])
            if action["number"]:
                a.set("number", action["number"])
        if action['type'] == 'enacted':
            a.clear()  # re-insert date between some of these attributes
            a.set("number", "%s-%s" % (bill['congress'], action["number"]))
            a.set("type", action["law"])
            a.set("datetime", utils.format_datetime(action['acted_at']))
            if action.get("status"):
                a.set("state", action["status"])
        if action['type'] == 'vetoed':
            if action.get("pocket"):
                a.set("pocket", "1")
        if action.get('text'):
            make_node(a, "text", action['text'])
        if action.get('in_committee'):
            make_node(a, "committee", None, name=action['in_committee'])
        for cr in action['references']:
            make_node(a, "reference", None, ref=cr['reference'], label=cr['type'])

    committees = make_node(root, "committees", None)
    for cmt in bill['committees']:
        make_node(committees, "committee", None, code=(cmt["committee_id"] + cmt["subcommittee_id"]) if cmt.get("subcommittee_id", None) else cmt["committee_id"], name=cmt["committee"], subcommittee=cmt.get("subcommittee").replace("Subcommittee on ", "") if cmt.get("subcommittee") else "", activity=", ".join(c.title() for c in cmt["activity"]))

    relatedbills = make_node(root, "relatedbills", None)
    for rb in bill['related_bills']:
        if rb['type'] == "bill":
            rb_bill_type, rb_number, rb_congress = congress_utils.split_bill_id(rb['bill_id'])
            make_node(relatedbills, "bill", None, session=rb_congress, type=govtrack_type_codes[rb_bill_type], number=rb_number, relation="unknown" if rb['reason'] == "related" else rb['reason'])

    subjects = make_node(root, "subjects", None)
    if bill['subjects_top_term']:
        make_node(subjects, "term", None, name=bill['subjects_top_term'])
    for s in bill['subjects']:
        if s != bill['subjects_top_term']:
            make_node(subjects, "term", None, name=s)

    amendments = make_node(root, "amendments", None)
    for amd in bill['amendments']:
        make_node(amendments, "amendment", None, number=amd["chamber"] + str(amd["number"]))

    if bill.get('summary'):
        make_node(root, "summary", bill['summary']['text'], date=bill['summary']['date'], status=bill['summary']['as'])

    committee_reports = make_node(root, "committee-reports", None)
    for report in bill['committee_reports']:
        make_node(committee_reports, "report", report)

    return etree.tostring(root, pretty_print=True)
