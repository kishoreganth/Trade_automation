from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import requests
import xml.etree.ElementTree as ET
import os
import hashlib
import logging
import time

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# Define known namespaces
namespaces = {
    'xbrli': 'http://www.xbrl.org/2003/instance',
    'in': 'https://www.sebi.gov.in/xbrl/2022-04-30/in-capmkt',
    'in2': 'https://www.sebi.gov.in/xbrl/2022-12-31/in-capmkt',
    'in3': 'https://www.sebi.gov.in/xbrl/2023-12-31/in-capmkt',
    'in-capmkt': 'https://www.sebi.gov.in/xbrl/2023-12-31/in-capmkt'  # Add this new namespace
}

# Known tags we care about
fields = [
    # Existing fields
    "NSESymbol", "NameOfTheCompany", "ReasonOfChange", "Designation",
    "NameOfThePersonOrAuditorOrAuditFirmOrRTA",
    "EffectiveDateOfAppointmentOrResignationOrRemovalOrDisqualificationOrCessationOrVacationOfOfficeDueToStatutoryAuthorityOrderOrAdditionalChargeOrChangeInDesignation",
    "TermOfAppointment", "BriefProfile", "RemarksForWebsiteDissemination",
    "TypeOfAnnouncementPertainingToRegulation30Restructuring",
    "EventOfAnnouncementPertainingToRegulation30Restructuring",
    "DateOfEventOfAnnouncementPertainingToRegulation30Restructuring",
    "NameOfAcquirer", "RelationshipOfAcquirerWithTheListedEntity",
    "DetailsOfOtherRelationWithTheListedEntity", "NameOfTheTargetEntity",
    "TurnoverOfTargetEntity", "ProfitAfterTaxOfTargetEntity",
    "NetWorthOfTargetEntity",
    "WhetherTheAcquisitionWouldFallWithinRelatedPartyTransactions",
    "WhetherAcquisitionEventRPTIsMaterial",
    "ObjectsAndEffectsOfAcquisitionIncludingButNotLimitedToDisclosureOfReasonsForAcquisitionOfTargetEntityIfItsBusinessIsOutsideTheMainLineOfBusinessOfTheListedEntity",
    "DisclosureOfRelationshipsBetweenDirectorsInCaseOfAppointmentOfDirector",
    "IndustryToWhichTheEntityBeingAcquiredBelongs",
    "CountryInWhichTheAcquiredEntityHasPresence",
    "DateOfBoardMeetingInWhichRPTApprovalTakenForAcquisitionEvent",
    "DateOfAuditCommitteeMeetingInWhichRPTApprovalTakenForAcquisitionEvent",
    "WhetherThePromoterOrPromoterGroupOrGroupOrAssociateOrHoldingOrSubsidiaryCompaniesOrDirectorAndKMPAndItsRelativesHaveAnyInterestInTheEntityBeingAcquired",
    "WhetherAcquisitionIsDoneAtArmsLength",
    "WhetherAnyGovernmentalOrRegulatoryApprovalsRequiredForTheAcquisition",
    "WhetherTheAcquisitionTransactionWillBeInTranches",
    "IndicativeTimePeriodForCompletionOfTheAcquisition",
    "NatureOfConsiderationForAcquisitionEvent",
    "CostOfAcquisitionOrThePriceAtWhichTheSharesAreAcquired",
    "ExistingPercentageOfShareholdingHeldByAcquirer",
    "BriefBackgroundAboutTheEntityAcquiredInTermsOfProductsLineOfBusinessAcquired",
    "StartYearOfFirstPreviousYear", "EndYearOfFirstPreviousYear",
    "TurnoverOfFirstPreviousYear", "PANOfDesignatedPerson",

    # New fields from XML7
    "ISIN", "TypeOfAnnouncement", "TypeOfEvent", "DateOfOccurrenceOfEvent",
    "TimeOfOccurrenceOfEvent", "DateOfReport",
    "DateOfBoardMeetingForApprovalOfIssuanceOfSecurityForAllotmentOfSecurities",
    "WhetherAnyDisclosureWasMadeForTheIssuanceOfSecuritiesAsPerSEBILODRAndCircular9ThSeptember2015ForAllotmentOfSecurities",
    "ReasonsForNonDisclosureForTheIssuanceOfSecuritiesAsPerSEBILODRAndCircular9ThSeptember2015ForAllotmentOfSecurities",
    "DateOfBoardOrCommitteeForAllotmentOfSecurities",
    "TypeOfSecuritiesAllottedForAllotmentOfSecurities",
    "TypeOfIssuanceForAllotmentOfSecurities",
    "PaidUpShareCapitalPreAllotmentOfSecurities",
    "NumberOfSharesPaidUpPreAllotmentOfSecurities",
    "PaidUpShareCapitalPostAllotmentOfSecurities",
    "NumberOfSharesPaidUpPostAllotmentOfSecurities"
]

def format_field_name(field_name):
    """Convert camelCase field names to readable format"""
    # Add space before uppercase letters
    formatted = ''.join([' ' + c if c.isupper() else c for c in field_name]).strip()
    # Replace common abbreviations
    replacements = {
        'NSE': 'NSE',
        'BSE': 'BSE', 
        'KMP': 'KMP',
        'RTA': 'RTA',
        'RPT': 'RPT'
    }
    for old, new in replacements.items():
        formatted = formatted.replace(old, new)
    return formatted.title()

def convert_xml_to_pdf(xml_url):
    try:
        logger.info(f"Fetching XML from URL: {xml_url}")
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(xml_url, headers=headers, timeout=10)
        res.raise_for_status()
        print(res.content)
        
        if not res.content:
            logger.error("Empty response received from XML URL")
            return None
            
        root = ET.fromstring(res.content)
        if root is None:
            logger.error("Failed to parse XML content")
            return None

        # Get namespaces from root element attributes
        namespaces = dict([node for node in root.attrib.items() if node[0].startswith('xmlns:')])
        # Add any namespaces from the root tag
        if '}' in root.tag:
            ns = root.tag.split('}')[0].strip('{')
            namespaces['xmlns'] = ns
        print("Available namespaces:", namespaces)

        data = {}
        found_fields = 0

        # First, get all elements and their values
        print("\nAll elements found in XML:")
        for elem in root.iter():
            # Remove namespace from tag if present
            if '}' in elem.tag:
                tag = elem.tag.split('}')[1]
            else:
                tag = elem.tag
                
            if elem.text and elem.text.strip():
                value = elem.text.strip()
                print(f"Found: {tag} = {value}")
                data[tag] = value
                found_fields += 1

        if found_fields == 0:
            logger.warning("No fields found in XML document")
            return None

        # Create PDF from the extracted data
        if data:
            try:
                # Ensure PDF directory exists
                pdf_dir = "files/pdf"
                os.makedirs(pdf_dir, exist_ok=True)
                
                # Create filename from company symbol or name
                company_name = data.get('NSESymbol', data.get('NameOfTheCompany', 'Unknown')).replace('/', '_')
                pdf_filename = f"CA_{company_name}_{int(time.time())}.pdf"
                pdf_path = os.path.join(pdf_dir, pdf_filename)
                
                # Create PDF
                doc = SimpleDocTemplate(
                    pdf_path, 
                    pagesize=letter,
                    rightMargin=50, leftMargin=50,
                    topMargin=50, bottomMargin=50
                )
                
                styles = getSampleStyleSheet()
                story = []
                
                # Title
                title = f"{data.get('NSESymbol', 'N/A')} - {data.get('NameOfTheCompany', 'Corporate Announcement')}"
                title_style = ParagraphStyle(
                    'CustomTitle',
                    parent=styles['Title'],
                    fontSize=18,
                    spaceAfter=20,
                    alignment=1,
                    textColor=colors.darkblue,
                    fontName='Helvetica-Bold'
                )
                story.append(Paragraph(title, title_style))
                
                # Add all fields
                for field, value in data.items():
                    if value and field not in ['NSESymbol', 'NameOfTheCompany']:  # Skip title fields
                        # Format field name
                        field_name = ' '.join(field.split('_')).title()
                        # Add field
                        story.append(Paragraph(f"<b>{field_name}:</b>", styles['Heading3']))
                        story.append(Paragraph(value, styles['Normal']))
                        story.append(Spacer(1, 10))
                
                # Build PDF
                doc.build(story)
                logger.info(f"Successfully created PDF: {pdf_path}")
                
                return f"http://localhost:5000/files/pdf/{pdf_filename}"
                
            except Exception as e:
                logger.error(f"Error creating PDF: {str(e)}")
                return None
        else:
            logger.warning("No data extracted from XML")
            return None
            
    except Exception as e:
        logger.error(f"Error in convert_xml_to_pdf: {str(e)}")
        return None
    
# attachment_file = "https://nsearchives.nseindia.com/corporate/xbrl/ALTERATION_OF_CAPITAL_AND_FUND_RAISING_1477175_04072025121101_WEB.xml"

# attachment_file = "https://nsearchives.nseindia.com/corporate/xbrl/OUTCOME_1477176_04072025121116_WEB.xml"
# attachment_file = "https://nsearchives.nseindia.com/corporate/xbrl/CLOSURE_TRADING_WINDOW_1477177_04072025121119_WEB.xml"
# attachment_file = "https://nsearchives.nseindia.com/corporate/xbrl/PRIOR_INTIMATION_59031_1477100_03072025115235_WEB.xml"

attachment_file = "https://nsearchives.nseindia.com/corporate/xbrl/REG30_Restructuring_1477095_03072025110932_WEB.xml"
print(convert_xml_to_pdf(attachment_file))