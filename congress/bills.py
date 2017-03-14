from govtrack import govtrack_type_codes
from lxml import etree

from congress import bill_info, utils



def _fixup_top_term_case(term):
    if term in ("Native Americans",):
        return term
    return term.capitalize()


def billstatus_url_for(bill_id, bulkdata_base_url="https://www.gpo.gov/fdsys/bulkdata/"):
    """
    Build full path to bill status XML document.
    """
    bill_type, bill_number, congress = utils.split_bill_id(bill_id)
    return '{0}BILLSTATUS/{1}/{2}/BILLSTATUS-{1}{2}{3}.xml'.format(bulkdata_base_url, congress, bill_type, bill_number)


def build_bill_id(bill_type, bill_number, congress):
    """
    Build composite bill id.
    """
    return "%s%s-%s" % (bill_type, bill_number, congress)


def form_bill_json_dict(xml_as_dict):
    """
    Handles converting a government bulk XML file to legacy dictionary form.

    @param bill_id: id of the bill in format [type][number]-[congress] e.x. s934-113
    @type bill_id: str
    @return: dictionary of bill attributes
    @rtype: dict
    """

    bill_dict = xml_as_dict['billStatus']['bill']
    bill_id = build_bill_id(bill_dict['billType'].lower(),
                            bill_dict['billNumber'],
                            bill_dict['congress'])
    titles = bill_info.titles_for(bill_dict['titles']['item'])
    actions = bill_info.actions_for(bill_dict['actions']['item'],
                                    bill_id,
                                    bill_info.current_title_for(titles,
                                                                'official'))
    _introduced = bill_dict.get('introducedDate', '')
    status, status_date = bill_info.latest_status(actions, _introduced)

    bill_data = {
        'bill_id': bill_id,
        'bill_type': bill_dict.get('billType').lower(),
        'number': bill_dict.get('billNumber'),
        'congress': bill_dict.get('congress'),

        'url': billstatus_url_for(bill_id),

        'introduced_at': bill_dict.get('introducedDate', ''),
        'by_request': bill_dict['sponsors']['item'][0]['byRequestType'] is not None,
        'sponsor': bill_info.sponsor_for(bill_dict['sponsors']['item'][0]),
        'cosponsors': bill_info.cosponsors_for(bill_dict['cosponsors']),

        'actions': actions,
        'history': bill_info.history_from_actions(actions),
        'status': status,
        'status_at': status_date,
        'enacted_as': bill_info.slip_law_from(actions),

        'titles': titles,
        'official_title': bill_info.current_title_for(titles, 'official'),
        'short_title': bill_info.current_title_for(titles, 'short'),
        'popular_title': bill_info.current_title_for(titles, 'popular'),

        'summary': bill_info.summary_for(bill_dict['summaries']['billSummaries']),

        # The top term's case has changed with the new bulk data. It's now in
        # Title Case. For backwards compatibility, the top term is run through
        # '.capitalize()' so it matches the old string. TODO: Remove one day?
        'subjects_top_term': _fixup_top_term_case(bill_dict['policyArea']['name']) if bill_dict['policyArea'] else None,
        'subjects':
            sorted(
                ([_fixup_top_term_case(bill_dict['policyArea']['name'])] if bill_dict['policyArea'] else []) +
                ([item['name'] for item in bill_dict['subjects']['billSubjects']['legislativeSubjects']['item']] if bill_dict['subjects']['billSubjects']['legislativeSubjects'] else [])
            ),

        'related_bills': bill_info.related_bills_for(bill_dict['relatedBills']),
        'committees': bill_info.committees_for(bill_dict['committees']['billCommittees']),
        'amendments': bill_info.amendments_for(bill_dict['amendments']),
        'committee_reports': bill_info.committee_reports_for(bill_dict['committeeReports']),

        'updated_at': bill_dict.get('updateDate', ''),
    }

    return bill_data
