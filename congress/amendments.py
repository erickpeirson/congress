import re, logging, datetime, time, json
from lxml import etree

from congress import bill_info, bill


# TODO: I don't quite follow what's going on here -- as written, the behavior
#  of this function depends on the order of the list at action['result']; it's
#  hard to imagine a scenario in which this would be desirable (why not just
#  pop off the last item?).
def amendment_status_for(amdt):
    """
    """
    status = 'offered'
    status_date = data['introduced_at']

    for action in data['actions']:
        if action['type'] == 'vote':
            status = action['result']  # 'pass', 'fail'
            status_date = action['acted_at']
        if action['type'] == 'withdrawn':
            status = 'withdrawn'
            status_date = action['acted_at']

    return status, status_date


def amends_bill_for(fdsys_data):
    """
    Transform FDSYS data about the amended bill.
    """
    return {
        'bill_id': bill.build_bill_id(fdsys_data['type'].lower(),
                                     fdsys_data['number'],
                                     fdsys_data['congress']),
        'bill_type': fdsys_data['type'].lower(),
        'congress': int(fdsys_data['congress']),
        'number': int(fdsys_data['number'])
    }


def build_amendment_id(amdt_type, amdt_number, congress):
    """
    Generate a composite amendment id.
    """
    return "%s%s-%s" % (amdt_type, amdt_number, congress)


def amends_amendment_for(fdsys_data):
    """
    Restructure FDSYS data about amended amendment.
    """
    if fdsys_data is None:
        return None

    amendment_id = build_amendment_id(fdsys_data['type'].lower(),
                                      fdsys_data['number'],
                                      fdsys_data['congress'])
    return {
        'amendment_id': amendment_id,
        'amendment_type': fdsys_data.get('type', '').lower(),
        'congress': int(fdsys_data.get('congress', '')),
        'number': int(fdsys_data.get('number', '')),
        'purpose': fdsys_data.get('purpose', ''),
        'description': fdsys_data.get('description', '')
    }


def parse_amendment_action(action):
    """
    Extends :func:`congress.bill_info.action_for` to further structure
    action data.

    Parameters
    ----------
    action : dict

    Return
    ------
    dict
    """
    action = bill_info.action_for(action)

    # House Vote
    m = re.match(r"On agreeing to the .* amendments? (\(.*\) )?(?:as (?:modified|amended) )?(Agreed to|Failed) (without objection|by [^\.:]+|by (?:recorded vote|the Yeas and Nays): (\d+) - (\d+)(, \d+ Present)? \(Roll [nN]o. (\d+)\))\.", action['text'])
    if m:
        action["where"] = "h"
        action["type"] = "vote"
        action["vote_type"] = "vote"

        if m.group(2) == "Agreed to":
            action["result"] = "pass"
        else:
            action["result"] = "fail"

        action["how"] = m.group(3)
        if "recorded vote" in m.group(3) or "the Yeas and Nays" in m.group(3):
            action["how"] = "roll"
            action["roll"] = int(m.group(7))

    # Senate Vote
    m = re.match(r"(Motion to table )?Amendment SA \d+(?:, .*?)? (as modified )?(agreed to|not agreed to) in Senate by ([^\.:\-]+|Yea-Nay( Vote)?. (\d+) - (\d+)(, \d+ Present)?. Record Vote Number: (\d+))\.", action['text'])
    if m:
        action["type"] = "vote"
        action["vote_type"] = "vote"
        action["where"] = "s"

        if m.group(3) == "agreed to":
            action["result"] = "pass"
            if m.group(1):  # is a motion to table, so result is sort of reversed.... eeek
                action["result"] = "fail"
        else:
            if m.group(1):  # is a failed motion to table, so this doesn't count as a vote on agreeing to the amendment
                continue
            action["result"] = "fail"

        action["how"] = m.group(4)
        if "Yea-Nay" in m.group(4):
            action["how"] = "roll"
            action["roll"] = int(m.group(9))

    # Withdrawn
    m = re.match(r"Proposed amendment SA \d+ withdrawn in Senate", action['text'])
    if m:
        action['type'] = 'withdrawn'
    return action


# TODO: this is redundant, but we'll keep it to support legacy tests.
def parse_amendment_actions(actions):
    return map(parse_amendment_action, actions)


# TODO: this is redundant, but we'll keep it to support legacy tests.
def actions_for(actions):
    return parse_amendment_actions(actions))


def sponsor_for(sponsor, amendment_type):
    """
    Parse sponsorship statement.

    Parameters
    ----------
    sponsor : str
    amendment_type : str

    Returns
    -------
    dict
    """
    if sponsor.get('bioguideId') is None:
        # A committee can sponsor an amendment!
        # Change e.g. "Rules Committee" to "House Rules" for the committee name,
        # for backwards compatibility.
        name = re.sub(r"(.*) Committee$", ("House" if (amendment_type[0] == "h") else "Senate" ) + r" \1", sponsor['name'])
        return {
            "type": "committee",
            "name": name,
            #"committee_id": None, # TODO
        }
    return bill_info.sponsor_for(sponsor)


def parse_fdsys_amendment_data(fdsys_data, options):
    """
    Transform FDSYS amendment data into a more sensible data structure.

    Parameters
    ----------
    fdsys_data : dict
    options :

    Returns
    -------
    dict
    """
    # good set of tests for each situation:
    # samdt712-113 - amendment to bill
    # samdt112-113 - amendment to amendment on bill
    # samdt4904-111 - amendment to treaty
    # samdt4922-111 - amendment to amendment to treaty

    amendment_id = build_amendment_id(fdsys_data['type'].lower(),
                                      fdsys_data['number'],
                                      fdsys_data['congress'])

    amends_bill = amends_bill_for(fdsys_data.get('amendedBill'))  # almost always present
    amends_treaty = None # amends_treaty_for(fdsys_data) # the bulk data does not provide amendments to treaties (THOMAS did)
    amends_amendment = amends_amendment_for(fdsys_data.get('amendedAmendment'))  # sometimes present
    if not amends_bill and not amends_treaty:
        raise Exception("Choked finding out what bill or treaty the amendment"
                        " amends.")

    actions = actions_for(fdsys_data['actions']['actions']['item'])

    data = {
        'amendment_id': amendment_id,
        'amendment_type': fdsys_data['type'].lower(),
        'chamber': fdsys_data['type'][0].lower(),
        'number': int(fdsys_data['number']),
        'congress': fdsys_data['congress'],
        'amends_bill': amends_bill,
        'amends_treaty': amends_treaty,
        'amends_amendment': amends_amendment,
        'sponsor': sponsor_for(fdsys_data['sponsors']['item'][0], fdsys_data['type'].lower()),
        'purpose': fdsys_data['purpose'][0] if type(fdsys_data['purpose']) is list else fdsys_data['purpose'],

        'introduced_at': fdsys_data['submittedDate'][:10],
        'actions': actions,

        'updated_at':  fdsys_data['updateDate'],
    }

    # duplicate attributes creates lists when parsed, this block deduplicates
    if 'description' in fdsys_data:
        data['description'] = fdsys_data['description']
        if type(fdsys_data['description']) is list:
            data['description'] = data['description'][0]

    if fdsys_data['type'][0].lower() == 's':
        data['proposed_at'] = fdsys_data['proposedDate']

    # needs to come *after* the setting of introduced_at
    data['status'], data['status_at'] = amendment_status_for(data)

    return data
