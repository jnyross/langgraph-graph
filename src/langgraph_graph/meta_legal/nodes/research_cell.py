"""Research-cell worker: search → fetch → LLM extract LawRecordDrafts.

Soft-fail contract: never raise into the graph. Failures become ``cell_errors``
and/or empty ``drafts`` list updates for the Annotated reducers. Seed harvest
always floors drafts when curated instruments/URLs exist (exp_006).
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping

from pydantic import BaseModel, Field

from langgraph_graph.meta_legal.llm import DEFAULT_MODEL, get_llm
from langgraph_graph.meta_legal.models import (
    CellError,
    LawRecordDraft,
    ResearchCell,
    make_cell_id,
    normalize_domain,
    normalize_jurisdiction,
    slugify,
)
from langgraph_graph.meta_legal.tools.fetch import fetch_url as default_fetch_url
from langgraph_graph.meta_legal.tools.search import web_search as default_web_search
from langgraph_graph.meta_legal.nodes.seed_harvest import (
    harvest_seed_instruments,
    merge_drafts,
)


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """Fetch pool with daemon workers so hung GETs cannot pin process exit."""

    def _adjust_thread_count(self) -> None:  # type: ignore[override]
        super()._adjust_thread_count()
        for t in list(getattr(self, "_threads", ())):
            try:
                t.daemon = True
            except Exception:
                pass


SearchFn = Callable[[str, int], list[dict[str, str]]]
FetchFn = Callable[[str, int], str]

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "research.md"

# Domains that often appear as official/government/legal hosts.
_OFFICIAL_HOST_HINTS: tuple[str, ...] = (
    ".gov",
    ".gob.",
    ".gouv.",
    ".govt.",
    ".go.",
    ".mil",
    "europa.eu",
    "europarl.europa.eu",
    "eur-lex.europa.eu",
    "ec.europa.eu",
    "edpb.europa.eu",
    "legislation.gov.uk",
    "parliament.uk",
    "congress.gov",
    "federalregister.gov",
    "regulations.gov",
    "ftc.gov",
    "justice.gov",
    "courtlistener.com",
    "hudoc.echr",
    "who.int",
    "oecd.org",
    "un.org",
    ".leg.",
    "law.",
    "laws.",
    "legislation.",
    "regul",
    "gazette",
)

_DOMAIN_INSTRUMENTS: dict[str, tuple[str, ...]] = {
    "privacy": (
        "GDPR General Data Protection Regulation",
        "ePrivacy Directive",
        "CCPA CPRA California Consumer Privacy Act",
        "state comprehensive privacy acts",
        "UK GDPR Data Protection Act",
        "LGPD Brazil Lei Geral de Proteção de Dados",
        "DPDP Digital Personal Data Protection Act India",
        "PIPEDA Personal Information Protection Electronic Documents Act",
        "APPI Act on Protection of Personal Information Japan",
        "PIPA Personal Information Protection Act Korea",
        "PDPA Personal Data Protection Act Singapore",
        "POPIA Protection of Personal Information Act South Africa",
        "Privacy Act Australia",
        "CLOUD Act stored communications",
    ),
    "competition": (
        "Digital Markets Act DMA gatekeeper",
        "Articles 101 102 TFEU competition",
        "Sherman Act antitrust",
        "Clayton Act merger",
        "FTC Act unfair methods of competition",
        "Hart-Scott-Rodino HSR Act",
        "Digital Markets Competition and Consumers Act UK",
        "Competition Act 1998 UK",
        "Competition and Consumer Act ACL Australia",
        "Competition Act Canada",
        "CADE Brazilian competition law",
        "Competition Act India",
        "Antimonopoly Act Japan",
        "MRFTA Monopoly Regulation Fair Trade Act Korea",
        "Competition Act Singapore",
        "Competition Act South Africa",
    ),
    "youth_safety": (
        "Digital Services Act minors protection",
        "Age Appropriate Design Code AADC",
        "COPPA Children's Online Privacy Protection Act",
        "Online Safety Act UK",
        "Kids Online Safety Act",
        "NCMEC reporting obligations",
        "TAKE IT DOWN Act",
        "California Age-Appropriate Design Code",
        "California SB 976 social media",
        "Utah social media regulation minors",
        "Arkansas social media age verification",
        "New York child data protection",
        "Florida Digital Bill of Rights minors",
        "Ireland Online Safety and Media Regulation Act",
        "Online Safety Act Australia",
        "IT Rules 2021 India intermediary guidelines",
        "Network Act Korea youth protection",
        "Online Safety Singapore",
    ),
    "ip": (
        "DSM Copyright Directive digital single market",
        "InfoSoc copyright directive",
        "EU Trade Mark Regulation",
        "IP Enforcement Directive",
        "DMCA Digital Millennium Copyright Act",
        "Copyright Act United States Title 17",
        "Lanham Act trademark",
        "Copyright Designs and Patents Act UK",
        "Copyright Act Canada",
        "Copyright Act Australia",
        "Copyright Act India",
        "Copyright Act Japan",
        "Copyright Act South Africa",
        "Marco Civil da Internet Brazil",
    ),
    "accessibility": (
        "European Accessibility Act EAA",
        "Web Accessibility Directive public sector",
        "Cyber Resilience Act CRA",
        "ADA Americans with Disabilities Act Title III",
        "Rehabilitation Act Section 508",
        "CVAA Twenty-First Century Communications Video Accessibility Act",
        "E-Government Act accessibility",
        "Equality Act UK digital accessibility",
        "Public Sector Bodies Accessibility Regulations UK",
        "Disability Discrimination Act Australia",
        "Accessible Canada Act",
        "Rights of Persons with Disabilities Act India",
        "Promotion of Equality and Prevention of Unfair Discrimination Act South Africa",
        "Unruh Civil Rights Act California",
    ),
}

# Preferred instruments per (jurisdiction_id, domain_id) for query quality.
_JURISDICTION_DOMAIN_INSTRUMENTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("european_union", "privacy"): (
        "GDPR General Data Protection Regulation Regulation (EU) 2016/679",
        "ePrivacy Directive 2002/58/EC Cookie Directive privacy and electronic communications",
        "Law Enforcement Directive LED Police Directive Directive (EU) 2016/680",
        "Data Governance Act DGA Regulation (EU) 2022/868",
        "Data Act EU Data Act Regulation (EU) 2023/2854",
    ),
    ("european_union", "competition"): (
        "Digital Markets Act DMA Regulation (EU) 2022/1925",
        "TFEU Article 101 competition",
        "TFEU Article 102 abuse of dominance Article 102 TFEU",
        "EU Merger Regulation EUMR Council Regulation (EC) No 139/2004",
        "Platform-to-Business P2B Regulation (EU) 2019/1150",
    ),
    ("european_union", "youth_safety"): (
        "Digital Services Act DSA Regulation (EU) 2022/2065",
        "Audiovisual Media Services Directive AVMSD 2010/13/EU",
        "Child Sexual Abuse Regulation Proposal Framework CSAM Regulation proposal COM/2022/209 CELEX 52022PC0209",
        "GDPR children personal data Article 8",
    ),
    ("european_union", "ip"): (
        "Copyright in the Digital Single Market Directive CDSM 2019/790",
        "InfoSoc Directive 2001/29/EC",
        "EU Trade Mark Regulation 2017/1001",
        "IP Enforcement Directive IPRED Enforcement Directive 2004/48/EC",
        "e-Commerce Directive 2000/31/EC intermediary liability",
    ),
    ("european_union", "accessibility"): (
        "European Accessibility Act EAA Directive 2019/882",
        "Web Accessibility Directive WAD Directive (EU) 2016/2102",
        "Cyber Resilience Act CRA Regulation (EU) 2024/2847",
        "EN 301 549 accessibility standard",
    ),
    ("united_states", "privacy"): (
        "Federal Trade Commission Act FTC Act unfair deceptive practices privacy",
        "CLOUD Act Clarifying Lawful Overseas Use of Data Act Pub. L. 115-141",
        "E-Government Act of 2002 Pub. L. 107-347",
        "state comprehensive consumer privacy acts",
        "California Consumer Privacy Act CCPA CPRA",
        "stored communications electronic communications privacy",
    ),
    ("united_states", "competition"): (
        "Sherman Antitrust Act 15 USC 1-7",
        "Clayton Act antitrust mergers",
        "Federal Trade Commission Act unfair methods of competition",
        "Hart-Scott-Rodino Antitrust Improvements Act HSR",
    ),
    ("united_states", "youth_safety"): (
        "COPPA Children's Online Privacy Protection Act",
        "COPPA FTC Rule 16 CFR Part 312",
        "Communications Decency Act Section 230 CDA 230 47 USC 230",
        "NCMEC CyberTipline reporting obligations 18 USC 2258A Federal Child Sexual Exploitation Reporting Duties",
        "TAKE IT DOWN Act Tools to Address Known Exploitation by Immobilizing Technological Deepfakes on Websites and Networks Act Pub. L. 119-12",
    ),
    ("united_states", "ip"): (
        "Digital Millennium Copyright Act DMCA",
        "Copyright Act Title 17 United States Code",
        "Section 512 notice and takedown safe harbor",
        "Lanham Act trademark 15 USC 1051",
    ),
    ("united_states", "accessibility"): (
        "Americans with Disabilities Act ADA Title III",
        "Rehabilitation Act Section 508 ICT accessibility 29 USC 794d",
        "CVAA Twenty-First Century Communications and Video Accessibility Act 21st Century Communications and Video Accessibility Act",
        "Section 508 electronic and information technology accessibility standards",
    ),
    ("united_kingdom", "privacy"): (
        "UK GDPR retained Regulation",
        "Data Protection Act 2018",
        "Privacy and Electronic Communications Regulations PECR",
        "ICO guidance online platforms",
    ),
    ("united_kingdom", "youth_safety"): (
        "Online Safety Act 2023 OSA 2023 UK Online Safety Act",
        "Age Appropriate Design Code AADC Children's code ICO Children's Code",
        "children online safety duties of care Ofcom",
    ),
    ("united_kingdom", "competition"): (
        "Digital Markets Competition and Consumers Act 2024 DMCC",
        "Competition Act 1998",
        "CMA digital markets regime SMS",
    ),
    ("united_kingdom", "ip"): (
        "Copyright Designs and Patents Act 1988 CDPA",
        "online intermediary liability copyright UK",
        "notice and takedown hosting providers UK",
    ),
    ("united_kingdom", "accessibility"): (
        "Public Sector Bodies Accessibility Regulations 2018",
        "Equality Act 2010 digital accessibility",
        "WCAG web accessibility UK public sector",
    ),
    ("california", "privacy"): (
        "California Consumer Privacy Act CCPA",
        "California Privacy Rights Act CPRA",
        "California Delete Act SB 362 Cal. Civ. Code 1798.99.80",
        "CPPA California Privacy Protection Agency regulations",
        "Cal. Civ. Code 1798.100 et seq.",
    ),
    ("california", "youth_safety"): (
        "California Age-Appropriate Design Code Act AADC AB 2273",
        "California SB 976 Protecting Our Kids from Social Media Addiction Act",
        "California minors social media privacy",
    ),
    ("california", "accessibility"): (
        "Unruh Civil Rights Act California",
        "California disability web accessibility",
        "ADA Title III California private right of action",
    ),
    ("virginia", "privacy"): (
        "Virginia Consumer Data Protection Act VCDPA",
        "Code of Virginia consumer data protection",
        "Virginia Attorney General consumer privacy",
    ),
    ("colorado", "privacy"): (
        "Colorado Privacy Act CPA",
        "Colorado Consumer Protection Act privacy",
        "Colorado Attorney General privacy rules",
    ),
    ("connecticut", "privacy"): (
        "Connecticut Data Privacy Act CTDPA",
        "Connecticut personal data privacy protection",
        "Connecticut Attorney General data privacy",
    ),
    ("utah", "privacy"): (
        "Utah Consumer Privacy Act UCPA",
        "Utah personal data privacy",
    ),
    ("utah", "youth_safety"): (
        "Utah Social Media Regulation Act",
        "Utah minors social media age verification",
        "Utah child online protection",
    ),
    ("texas", "privacy"): (
        "Texas Data Privacy and Security Act TDPSA",
        "Texas consumer personal data rights",
        "Texas Attorney General privacy",
    ),
    ("oregon", "privacy"): (
        "Oregon Consumer Privacy Act OCPA",
        "Oregon personal data privacy",
    ),
    ("montana", "privacy"): (
        "Montana Consumer Data Privacy Act MCDPA Montana SB 384",
        "Montana personal data privacy",
    ),
    ("delaware", "privacy"): (
        "Delaware Personal Data Privacy Act",
        "Delaware consumer privacy",
    ),
    ("illinois", "privacy"): (
        "Illinois Biometric Information Privacy Act BIPA",
        "740 ILCS 14 BIPA",
        "Illinois biometric privacy",
    ),
    ("washington", "privacy"): (
        "Washington My Health My Data Act",
        "Washington consumer health data privacy",
        "Washington State Attorney General health data",
    ),
    ("florida", "privacy"): (
        "Florida Digital Bill of Rights",
        "Florida consumer data privacy",
        "Florida online protections for minors",
    ),
    ("arkansas", "youth_safety"): (
        "Arkansas social media age verification law",
        "Arkansas minors online safety",
        "Arkansas Act social media platforms",
    ),
    ("new_york", "youth_safety"): (
        "New York Child Data Protection Act",
        "New York Stop Addictive Feeds Exploitation SAFE for Kids Act",
        "New York minors online privacy",
    ),
    ("ireland", "youth_safety"): (
        "Online Safety and Media Regulation Act 2022 Ireland",
        "Coimisiún na Meán online safety code",
        "Ireland online safety media regulation",
    ),
    ("brazil", "privacy"): (
        "LGPD Lei Geral de Proteção de Dados Lei 13.709/2018",
        "Marco Civil da Internet Lei 12.965/2014 privacy",
        "ANPD Autoridade Nacional de Proteção de Dados",
    ),
    ("brazil", "competition"): (
        "CADE Law Lei 12.529/2011 competition",
        "Brazilian Competition Law antitrust",
        "CADE digital markets",
    ),
    ("brazil", "youth_safety"): (
        "ECA Estatuto da Criança e do Adolescente Brazil Law 8069/1990 Child and Adolescent Statute",
        "Marco Civil da Internet child protection",
        "Brazil online child safety",
    ),
    ("india", "privacy"): (
        "Digital Personal Data Protection Act 2023 DPDP",
        "Information Technology Act 2000",
        "IT Rules 2021 intermediary guidelines digital media",
    ),
    ("india", "youth_safety"): (
        "IT Rules 2021 intermediary guidelines child safety",
        "Information Technology Act children online",
        "India online child protection",
    ),
    ("india", "competition"): (
        "Competition Act 2002 India",
        "Competition Commission of India digital markets",
        "India antitrust competition law",
    ),
    ("india", "ip"): (
        "Copyright Act 1957 India",
        "India intermediary copyright liability",
        "India trademark online platforms",
    ),
    ("india", "accessibility"): (
        "Rights of Persons with Disabilities Act 2016 RPwD RPWD Act",
        "India digital accessibility guidelines",
        "RPwD web accessibility",
    ),
    ("australia", "privacy"): (
        "Privacy Act 1988 Australia",
        "Australian Privacy Principles APP",
        "OAIC Privacy Act guidance",
    ),
    ("australia", "youth_safety"): (
        "Online Safety Act 2021 Australia",
        "eSafety Commissioner online safety",
        "Australia basic online safety expectations",
    ),
    ("australia", "competition"): (
        "Competition and Consumer Act 2010 Australian Consumer Law ACL",
        "ACCC digital platforms",
        "Australia competition consumer law",
    ),
    ("australia", "ip"): (
        "Copyright Act 1968 Australia",
        "Australia safe harbour copyright",
        "Australia online copyright intermediary",
    ),
    ("australia", "accessibility"): (
        "Disability Discrimination Act 1992 DDA Australia",
        "Australia web accessibility WCAG",
        "DDA digital accessibility",
    ),
    ("canada", "privacy"): (
        "PIPEDA Personal Information Protection and Electronic Documents Act",
        "Canada privacy digital platforms",
        "OPC PIPEDA guidance",
    ),
    ("canada", "competition"): (
        "Competition Act Canada",
        "Competition Bureau Canada digital markets",
        "Canada antitrust competition",
    ),
    ("canada", "ip"): (
        "Copyright Act Canada Canadian Copyright Act R.S.C. 1985 c. C-42",
        "Canada notice and notice copyright",
        "Canada intermediary copyright liability",
    ),
    ("canada", "accessibility"): (
        "Accessible Canada Act ACA Accessible Canada Act 2019",
        "Canada digital accessibility standards",
        "Accessible Canada Act ICT",
    ),
    ("japan", "privacy"): (
        "Act on the Protection of Personal Information APPI Japan",
        "APPI personal data Japan",
        "PPC Japan personal information",
    ),
    ("japan", "competition"): (
        "Antimonopoly Act Japan",
        "Japan Fair Trade Commission digital markets",
        "Japan competition law platforms",
    ),
    ("japan", "ip"): (
        "Copyright Act Japan",
        "Japan online copyright intermediary",
        "Japan trademark internet",
    ),
    ("south_korea", "privacy"): (
        "Personal Information Protection Act PIPA Korea",
        "PIPA South Korea personal data",
        "PIPC Korea privacy",
    ),
    ("south_korea", "youth_safety"): (
        "Act on Promotion of Information and Communications Network Utilization and Information Protection Network Act Korea ICNA",
        "Korea youth protection online Network Act illegal content",
        "Network Act Korea youth safety",
    ),
    ("south_korea", "competition"): (
        "Monopoly Regulation and Fair Trade Act MRFTA Korea Korean Fair Trade Act",
        "Korea Fair Trade Commission digital platforms",
        "MRFTA online platforms",
    ),
    ("singapore", "privacy"): (
        "Personal Data Protection Act PDPA Singapore PDPA 2012 Act 26 of 2012",
        "PDPC Singapore personal data",
        "PDPA online platforms",
    ),
    ("singapore", "youth_safety"): (
        "Online Safety Singapore Online Criminal Harms Act",
        "Singapore Broadcasting Act online safety",
        "IMDA online safety Singapore",
    ),
    ("singapore", "competition"): (
        "Competition Act Singapore",
        "CCCSI Competition and Consumer Commission Singapore",
        "Singapore competition digital markets",
    ),
    ("south_africa", "privacy"): (
        "Protection of Personal Information Act POPIA",
        "POPIA South Africa personal information",
        "Information Regulator South Africa",
    ),
    ("south_africa", "competition"): (
        "Competition Act 89 of 1998 South Africa",
        "Competition Commission South Africa digital markets",
        "South Africa competition law",
    ),
    ("south_africa", "ip"): (
        "Copyright Act South Africa",
        "Electronic Communications and Transactions Act ECTA",
        "South Africa intermediary liability copyright",
    ),
    ("south_africa", "accessibility"): (
        "Promotion of Equality and Prevention of Unfair Discrimination Act PEPUDA",
        "South Africa disability equality digital access",
        "PEPUDA accessibility",
    ),
}

# High-confidence primary-source seeds keyed by (jurisdiction_id, domain_id).
_SEED_URLS: dict[tuple[str, str], tuple[str, ...]] = {
    ("european_union", "privacy"): (
        "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
        "https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
        "https://www.legislation.gov.uk/eur/2016/679/contents",
        "https://eur-lex.europa.eu/eli/dir/2002/58/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32002L0058",
        "https://eur-lex.europa.eu/eli/dir/2016/680/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016L0680",
        "https://eur-lex.europa.eu/eli/reg/2022/868/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R0868",
        "https://eur-lex.europa.eu/eli/reg/2023/2854/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R2854",
        "https://eur-lex.europa.eu/eli/reg/2022/2065/oj",
    ),
    ("european_union", "competition"): (
        "https://eur-lex.europa.eu/eli/reg/2022/1925/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R1925",
        "https://eur-lex.europa.eu/eli/treaty/tfeu_2012/art_102/oj",
        "https://eur-lex.europa.eu/eli/treaty/tfeu_2012/art_101/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:12012E/TXT",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:12016E101",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:12016E102",
        "https://eur-lex.europa.eu/eli/reg/2004/139/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32004R0139",
        "https://eur-lex.europa.eu/eli/reg/2019/1150/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019R1150",
    ),
    ("european_union", "youth_safety"): (
        "https://eur-lex.europa.eu/eli/reg/2022/2065/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R2065",
        "https://eur-lex.europa.eu/eli/dir/2010/13/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32010L0013",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52022PC0209",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A52022PC0209",
        "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
    ),
    ("european_union", "ip"): (
        "https://eur-lex.europa.eu/eli/dir/2019/790/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019L0790",
        "https://eur-lex.europa.eu/eli/dir/2001/29/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32001L0029",
        "https://eur-lex.europa.eu/eli/reg/2017/1001/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32017R1001",
        "https://eur-lex.europa.eu/eli/dir/2004/48/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32004L0048",
        "https://eur-lex.europa.eu/eli/dir/2000/31/oj",
    ),
    ("european_union", "accessibility"): (
        "https://eur-lex.europa.eu/eli/dir/2019/882/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019L0882",
        "https://eur-lex.europa.eu/eli/dir/2016/2102/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016L2102",
        "https://eur-lex.europa.eu/eli/reg/2024/2847/oj",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R2847",
    ),
    ("united_states", "privacy"): (
        "https://www.ftc.gov/legal-library/browse/statutes/federal-trade-commission-act",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section45",
        "https://www.congress.gov/bill/115th-congress/house-bill/4943",
        "https://www.justice.gov/criminal/cloud-act-resources",
        "https://www.congress.gov/bill/115th-congress/senate-bill/2383/text",
        "https://www.govinfo.gov/content/pkg/PLAW-115publ141/html/PLAW-115publ141.htm",
        "https://www.congress.gov/bill/107th-congress/house-bill/2458",
        "https://www.govinfo.gov/content/pkg/PLAW-107publ347/html/PLAW-107publ347.htm",
        "https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?division=3.&part=4.&lawCode=CIV&title=1.81.5",
        "https://www.ftc.gov/business-guidance/privacy-security",
    ),
    ("united_states", "competition"): (
        "https://www.ftc.gov/legal-library/browse/statutes/federal-trade-commission-act",
        "https://www.justice.gov/atr/sherman-act-15-usc-1-7",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section12",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section18a",
        "https://www.ftc.gov/enforcement/premerger-notification-program",
        "https://www.justice.gov/atr/antitrust-laws-and-you",
        "https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap1.htm",
    ),
    ("united_states", "youth_safety"): (
        "https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa",
        "https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-312",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section6501",
        "https://www.law.cornell.edu/uscode/text/47/230",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title47-section230",
        "https://www.law.cornell.edu/uscode/text/18/2258A",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title18-section2258A",
        "https://www.congress.gov/bill/118th-congress/senate-bill/1409",
        "https://www.congress.gov/bill/119th-congress/senate-bill/146",
        "https://www.missingkids.org/gethelpnow/cybertipline/cybertiplinedata",
    ),
    ("united_states", "ip"): (
        "https://www.copyright.gov/title17/",
        "https://www.copyright.gov/title17/92chap5.html#512",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title17-section512",
        "https://www.law.cornell.edu/uscode/text/17/512",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1051",
        "https://www.copyright.gov/legislation/dmca.pdf",
        "https://www.govinfo.gov/content/pkg/PLAW-105publ304/pdf/PLAW-105publ304.pdf",
    ),
    ("united_states", "accessibility"): (
        "https://www.ada.gov/law-and-regs/title-iii/",
        "https://www.ada.gov/law-and-regs/ada/",
        "https://www.access-board.gov/ict/",
        "https://www.section508.gov/manage/laws-and-policies/",
        "https://www.law.cornell.edu/uscode/text/29/794d",
        "https://www.fcc.gov/general/twenty-first-century-communications-and-video-accessibility-act-0",
        "https://www.fcc.gov/general/twenty-first-century-communications-and-video-accessibility-act",
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title29-section794d",
        "https://www.govinfo.gov/content/pkg/PLAW-111publ260/html/PLAW-111publ260.htm",
    ),
    ("united_kingdom", "privacy"): (
        "https://www.legislation.gov.uk/ukpga/2018/12/contents",
        "https://www.legislation.gov.uk/ukpga/2018/12/contents/enacted",
        "https://www.legislation.gov.uk/eur/2016/679/contents",
        "https://www.legislation.gov.uk/uksi/2003/2426/contents",
        "https://www.legislation.gov.uk/uksi/2003/2426/contents/made",
        "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/",
    ),
    ("united_kingdom", "youth_safety"): (
        "https://www.legislation.gov.uk/ukpga/2023/50/contents",
        "https://www.legislation.gov.uk/ukpga/2023/50/contents/enacted",
        "https://www.legislation.gov.uk/ukia/2020/63/contents",
        "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/childrens-information/childrens-code-guidance-and-resources/age-appropriate-design-a-code-of-practice-for-online-services/",
        "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/childrens-information/",
        "https://www.gov.uk/government/publications/age-appropriate-design-code",
        "https://www.ofcom.org.uk/online-safety",
    ),
    ("united_kingdom", "competition"): (
        "https://www.legislation.gov.uk/ukpga/1998/41/contents",
        "https://www.legislation.gov.uk/ukpga/1998/41/contents/enacted",
        "https://www.legislation.gov.uk/ukpga/2024/13/contents",
        "https://www.legislation.gov.uk/ukpga/2024/13/contents/enacted",
        "https://www.gov.uk/government/organisations/competition-and-markets-authority",
    ),
    ("united_kingdom", "ip"): (
        "https://www.legislation.gov.uk/ukpga/1988/48/contents",
        "https://www.legislation.gov.uk/ukpga/1988/48/contents/enacted",
        "https://www.gov.uk/topic/intellectual-property/copyright",
    ),
    ("united_kingdom", "accessibility"): (
        "https://www.legislation.gov.uk/uksi/2018/952/contents",
        "https://www.legislation.gov.uk/uksi/2018/952/contents/made",
        "https://www.legislation.gov.uk/ukpga/2010/15/contents",
        "https://www.gov.uk/guidance/accessibility-requirements-for-public-sector-websites-and-apps",
    ),
    ("california", "privacy"): (
        "https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?division=3.&part=4.&lawCode=CIV&title=1.81.5",
        "https://leginfo.legislature.ca.gov/faces/codes_displayexpandedbranch.xhtml?tocCode=CIV&division=3.&title=1.81.5&part=4.&chapter=&article=",
        "https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202320240SB362",
        "https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202320240SB362",
        "https://cppa.ca.gov/regulations/",
        "https://cppa.ca.gov/regulations/pdf/cppa_regs.pdf",
        "https://oag.ca.gov/privacy/ccpa",
        "https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=201920200AB375",
    ),
    ("california", "youth_safety"): (
        "https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202120220AB2273",
        "https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202120220AB2273",
        "https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202320240SB976",
        "https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202320240SB976",
        "https://oag.ca.gov/ab2273",
    ),
    ("california", "accessibility"): (
        "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=51",
        "https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?lawCode=CIV&division=1.&title=&part=2.&chapter=1.&article=",
        "https://www.dfeh.ca.gov/disabilityunruh/",
    ),
    ("virginia", "privacy"): (
        "https://law.lis.virginia.gov/vacodepopularnames/consumer-data-protection-act/",
        "https://law.lis.virginia.gov/vacode/title59.1/chapter53/",
        "https://lis.virginia.gov/cgi-bin/legp604.exe?212+ful+CHAP0035",
        "https://www.oag.state.va.us/consumer-protection/index.php/privacy",
    ),
    ("colorado", "privacy"): (
        "https://leg.colorado.gov/sites/default/files/2021a_190_signed.pdf",
        "https://leg.colorado.gov/bills/sb21-190",
        "https://coag.gov/resources/colorado-privacy-act/",
        "https://coloradosos.gov/CCR/GenerateRulePdf.do?ruleVersionId=11146",
    ),
    ("connecticut", "privacy"): (
        "https://www.cga.ct.gov/2022/ACT/PA/PDF/2022PA-00015-R00SB-00006-PA.PDF",
        "https://www.cga.ct.gov/asp/cgabillstatus/cgabillstatus.asp?selBillType=Bill&bill_num=SB00006&which_year=2022",
        "https://portal.ct.gov/AG/Sections/Privacy/The-Connecticut-Data-Privacy-Act",
    ),
    ("utah", "privacy"): (
        "https://le.utah.gov/~2022/bills/static/SB0227.html",
        "https://le.utah.gov/xcode/Title13/Chapter61/13-61.html",
        "https://attorneygeneral.utah.gov/utah-consumer-privacy-act/",
    ),
    ("utah", "youth_safety"): (
        "https://le.utah.gov/~2023/bills/static/SB0152.html",
        "https://le.utah.gov/xcode/Title13/Chapter63/13-63.html",
        "https://le.utah.gov/~2024/bills/static/SB0194.html",
    ),
    ("texas", "privacy"): (
        "https://capitol.texas.gov/tlodocs/88R/billtext/html/HB00004F.htm",
        "https://statutes.capitol.texas.gov/Docs/BC/htm/BC.541.htm",
        "https://www.texasattorneygeneral.gov/consumer-protection/file-consumer-complaint/consumer-privacy-rights",
    ),
    ("oregon", "privacy"): (
        "https://olis.oregonlegislature.gov/liz/2023R1/Measures/Overview/SB619",
        "https://olis.oregonlegislature.gov/liz/2023R1/Downloads/MeasureDocument/SB619/Enrolled",
        "https://www.doj.state.or.us/consumer-protection/id-theft-data-breaches/oregon-consumer-privacy-act/",
    ),
    ("montana", "privacy"): (
        "https://leg.mt.gov/bills/2023/billhtml/SB0384.htm",
        "https://leg.mt.gov/bills/2023/billpdf/SB0384.pdf",
        "https://dojmt.gov/consumer/montana-consumer-data-privacy-act/",
    ),
    ("delaware", "privacy"): (
        "https://legis.delaware.gov/BillDetail?LegislationId=140380",
        "https://delcode.delaware.gov/title6/c012D/index.html",
        "https://attorneygeneral.delaware.gov/",
    ),
    ("illinois", "privacy"): (
        "https://www.ilga.gov/legislation/ilcs/ilcs3.asp?ActID=3004&ChapterID=57",
        "https://www.ilga.gov/legislation/publicacts/fulltext.asp?Name=095-0994",
        "https://www.illinoisattorneygeneral.gov/Consumer-Protection/",
    ),
    ("washington", "privacy"): (
        "https://app.leg.wa.gov/RCW/default.aspx?cite=19.373",
        "https://lawfilesext.leg.wa.gov/biennium/2023-24/Pdf/Bills/Session%20Laws/House/1155-S.SL.pdf",
        "https://www.atg.wa.gov/protecting-washingtonians-personal-health-data-and-privacy",
    ),
    ("florida", "privacy"): (
        "https://www.flsenate.gov/Session/Bill/2023/262",
        "https://www.flsenate.gov/Session/Bill/2023/262/BillText/er/PDF",
        "https://www.myfloridalegal.com/",
    ),
    ("arkansas", "youth_safety"): (
        "https://www.arkleg.state.ar.us/Bills/Detail?id=sb396&ddBienniumSession=2023%2F2023R",
        "https://www.arkleg.state.ar.us/Home/FTPDocument?path=%2FACTS%2F2023R%2FPublic%2FACT689.pdf",
        "https://law.justia.com/codes/arkansas/title-4/subtitle-7/chapter-88/subchapter-14/",
    ),
    ("new_york", "youth_safety"): (
        "https://www.nysenate.gov/legislation/bills/2023/S7695",
        "https://www.nysenate.gov/legislation/bills/2023/A8148",
        "https://www.governor.ny.gov/news/governor-hochul-signs-legislation-establishing-protections-children-social-media",
        "https://www.dfs.ny.gov/",
    ),
    ("ireland", "youth_safety"): (
        "https://www.irishstatutebook.ie/eli/2022/act/41/enacted/en/html",
        "https://www.irishstatutebook.ie/eli/2022/act/41/enacted/en/print",
        "https://www.cnam.ie/",
        "https://www.gov.ie/en/publication/d8e4c-online-safety-and-media-regulation-act-2022/",
    ),
    ("brazil", "privacy"): (
        "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm",
        "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm",
        "https://www.gov.br/anpd/pt-br",
        "https://www.in.gov.br/en/web/dou/-/lei-n-13.709-de-14-de-agosto-de-2018-371562733",
    ),
    ("brazil", "competition"): (
        "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2011/lei/l12529.htm",
        "https://www.gov.br/cade/pt-br",
        "https://www.cade.gov.br/assuntos/normas-e-legislacao/lei-no-12-529-de-30-de-novembro-de-2011-1",
    ),
    ("brazil", "youth_safety"): (
        "https://www.planalto.gov.br/ccivil_03/leis/l8069.htm",
        "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm",
        "https://www.gov.br/mdh/pt-br/navegue-por-temas/crianca-e-adolescente",
    ),
    ("india", "privacy"): (
        "https://www.meity.gov.in/writereaddata/files/Digital%20Personal%20Data%20Protection%20Act%202023.pdf",
        "https://egazette.gov.in/WriteReadData/2023/248045.pdf",
        "https://www.indiacode.nic.in/handle/123456789/13116",
        "https://www.meity.gov.in/content/information-technology-act-2000",
        "https://www.meity.gov.in/writereaddata/files/Information%20Technology%20%28Intermediary%20Guidelines%20and%20Digital%20Media%20Ethics%20Code%29%20Rules%2C%202021%20%28updated%2006.04.2023%29-.pdf",
    ),
    ("india", "youth_safety"): (
        "https://www.meity.gov.in/writereaddata/files/Information%20Technology%20%28Intermediary%20Guidelines%20and%20Digital%20Media%20Ethics%20Code%29%20Rules%2C%202021%20%28updated%2006.04.2023%29-.pdf",
        "https://www.indiacode.nic.in/handle/123456789/1999",
        "https://www.meity.gov.in/content/information-technology-act-2000",
    ),
    ("india", "competition"): (
        "https://www.cci.gov.in/images/legalframeworkact/en/the-competition-act-20021652103427.pdf",
        "https://www.indiacode.nic.in/handle/123456789/2012",
        "https://www.cci.gov.in/",
    ),
    ("india", "ip"): (
        "https://copyright.gov.in/Documents/Copyrightrules1957.pdf",
        "https://www.indiacode.nic.in/handle/123456789/1367",
        "https://copyright.gov.in/",
    ),
    ("india", "accessibility"): (
        "https://www.indiacode.nic.in/handle/123456789/2155",
        "https://disabilityaffairs.gov.in/content/page/acts.php",
        "https://www.indiacode.nic.in/bitstream/123456789/2155/1/A2016-49.pdf",
    ),
    ("australia", "privacy"): (
        "https://www.legislation.gov.au/C2004A03712/latest/text",
        "https://www.legislation.gov.au/Details/C2023C00301",
        "https://www.oaic.gov.au/privacy/the-privacy-act",
        "https://www.oaic.gov.au/privacy/australian-privacy-principles",
    ),
    ("australia", "youth_safety"): (
        "https://www.legislation.gov.au/C2021A00076/latest/text",
        "https://www.legislation.gov.au/Details/C2021A00076",
        "https://www.esafety.gov.au/industry/basic-online-safety-expectations",
        "https://www.esafety.gov.au/about-us/who-we-are/our-legislative-functions",
    ),
    ("australia", "competition"): (
        "https://www.legislation.gov.au/C2004A00109/latest/text",
        "https://www.legislation.gov.au/Details/C2023C00294",
        "https://www.accc.gov.au/about-us/legislation",
        "https://www.accc.gov.au/business/competition-and-exemptions/competition-and-consumer-act",
    ),
    ("australia", "ip"): (
        "https://www.legislation.gov.au/C1968A00063/latest/text",
        "https://www.legislation.gov.au/Details/C2022C00192",
        "https://www.copyright.org.au/",
    ),
    ("australia", "accessibility"): (
        "https://www.legislation.gov.au/C2004A04426/latest/text",
        "https://www.legislation.gov.au/Details/C2016C00763",
        "https://www.humanrights.gov.au/our-work/disability-rights",
    ),
    ("canada", "privacy"): (
        "https://laws-lois.justice.gc.ca/eng/acts/P-8.6/",
        "https://laws-lois.justice.gc.ca/eng/acts/P-8.6/FullText.html",
        "https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/",
        "https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/02_05_d_15/",
    ),
    ("canada", "competition"): (
        "https://laws-lois.justice.gc.ca/eng/acts/C-34/",
        "https://laws-lois.justice.gc.ca/eng/acts/C-34/FullText.html",
        "https://competition-bureau.canada.ca/how-we-foster-competition/education-and-outreach/publications/competition-act",
    ),
    ("canada", "ip"): (
        "https://laws-lois.justice.gc.ca/eng/acts/C-42/",
        "https://laws-lois.justice.gc.ca/eng/acts/C-42/FullText.html",
        "https://ised-isde.canada.ca/site/canadian-intellectual-property-office/en",
    ),
    ("canada", "accessibility"): (
        "https://laws-lois.justice.gc.ca/eng/acts/A-0.6/",
        "https://laws-lois.justice.gc.ca/eng/acts/A-0.6/FullText.html",
        "https://www.canada.ca/en/employment-social-development/programs/accessible-canada.html",
    ),
    ("japan", "privacy"): (
        "https://www.japaneselawtranslation.go.jp/en/laws/view/4241",
        "https://www.ppc.go.jp/en/legal/",
        "https://www.ppc.go.jp/en/legal/act_on_protection_of_personal_information/",
        "https://elaws.e-gov.go.jp/document?lawid=415AC0000000057",
    ),
    ("japan", "competition"): (
        "https://www.japaneselawtranslation.go.jp/en/laws/view/3988",
        "https://www.jftc.go.jp/en/legislation_gls/index.html",
        "https://www.jftc.go.jp/en/legislation_gls/amended_ama09/index.html",
    ),
    ("japan", "ip"): (
        "https://www.japaneselawtranslation.go.jp/en/laws/view/4283",
        "https://www.cric.or.jp/english/clj/",
        "https://www.bunka.go.jp/english/policy/copyright/",
    ),
    ("south_korea", "privacy"): (
        "https://elaw.klri.re.kr/eng_service/lawView.do?hseq=53044&lang=ENG",
        "https://www.pipc.go.kr/np/en/main.do",
        "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=213857&viewCls=engLsInfoR&urlMode=engLsInfoR",
    ),
    ("south_korea", "youth_safety"): (
        "https://elaw.klri.re.kr/eng_service/lawView.do?hseq=38422&lang=ENG",
        "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=232201&viewCls=engLsInfoR&urlMode=engLsInfoR",
        "https://www.msit.go.kr/eng/index.do",
    ),
    ("south_korea", "competition"): (
        "https://elaw.klri.re.kr/eng_service/lawView.do?hseq=55910&lang=ENG",
        "https://www.ftc.go.kr/eng/coping.do",
        "https://www.ftc.go.kr/eng/index.do",
        "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=232678&viewCls=engLsInfoR&urlMode=engLsInfoR",
    ),
    ("singapore", "privacy"): (
        "https://sso.agc.gov.sg/Act/PDPA2012",
        "https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=P1I-",
        "https://www.pdpc.gov.sg/Overview-of-PDPA/The-Legislation/Personal-Data-Protection-Act",
    ),
    ("singapore", "youth_safety"): (
        "https://sso.agc.gov.sg/Acts-Supp/24-2023/Published/20230801?DocDate=20230801",
        "https://sso.agc.gov.sg/Act/BCA1994",
        "https://www.imda.gov.sg/regulations-and-licensing-listing/content-standards-and-classification/standards-and-classification/online-safety",
    ),
    ("singapore", "competition"): (
        "https://sso.agc.gov.sg/Act/CA2004",
        "https://www.cccs.gov.sg/legislation/competition-act",
        "https://sso.agc.gov.sg/Act/CA2004?ProvIds=P1III-",
    ),
    ("south_africa", "privacy"): (
        "https://www.gov.za/documents/protection-personal-information-act",
        "https://www.gov.za/sites/default/files/gcis_document/201409/3706726-11act4of2013protectionofpersonalinforcorrect.pdf",
        "https://inforegulator.org.za/popia/",
        "https://www.gov.za/documents/acts/protection-personal-information-act-4-2013-26-nov-2013-0000",
    ),
    ("south_africa", "competition"): (
        "https://www.gov.za/documents/competition-act",
        "https://www.gov.za/sites/default/files/gcis_document/201409/a89-98.pdf",
        "https://www.compcom.co.za/the-competition-act/",
    ),
    ("south_africa", "ip"): (
        "https://www.gov.za/documents/copyright-act-16-apr-2015-0000",
        "https://www.gov.za/documents/electronic-communications-and-transactions-act",
        "https://www.gov.za/sites/default/files/gcis_document/201409/a25-02.pdf",
    ),
    ("south_africa", "accessibility"): (
        "https://www.gov.za/documents/promotion-equality-and-prevention-unfair-discrimination-act",
        "https://www.gov.za/sites/default/files/gcis_document/201409/a4-000.pdf",
        "https://www.gov.za/documents/acts/promotion-equality-and-prevention-unfair-discrimination-act-4-2000-02-feb-2000-0000",
    ),
}

_JURISDICTION_SITE_HINTS: dict[str, tuple[str, ...]] = {
    "european_union": (
        "site:eur-lex.europa.eu",
        "site:europa.eu",
        "site:edpb.europa.eu",
    ),
    "united_states": (
        "site:congress.gov",
        "site:ftc.gov",
        "site:justice.gov",
        "site:govinfo.gov",
        "site:uscode.house.gov",
    ),
    "united_kingdom": (
        "site:legislation.gov.uk",
        "site:gov.uk",
        "site:ico.org.uk",
    ),
    "california": (
        "site:leginfo.legislature.ca.gov",
        "site:cppa.ca.gov",
        "site:oag.ca.gov",
    ),
    "virginia": (
        "site:law.lis.virginia.gov",
        "site:lis.virginia.gov",
        "site:oag.state.va.us",
    ),
    "colorado": (
        "site:leg.colorado.gov",
        "site:coag.gov",
        "site:coloradosos.gov",
    ),
    "connecticut": (
        "site:cga.ct.gov",
        "site:portal.ct.gov",
    ),
    "utah": (
        "site:le.utah.gov",
        "site:attorneygeneral.utah.gov",
    ),
    "texas": (
        "site:capitol.texas.gov",
        "site:statutes.capitol.texas.gov",
        "site:texasattorneygeneral.gov",
    ),
    "oregon": (
        "site:olis.oregonlegislature.gov",
        "site:oregonlegislature.gov",
        "site:doj.state.or.us",
    ),
    "montana": (
        "site:leg.mt.gov",
        "site:dojmt.gov",
    ),
    "delaware": (
        "site:legis.delaware.gov",
        "site:delcode.delaware.gov",
        "site:attorneygeneral.delaware.gov",
    ),
    "illinois": (
        "site:ilga.gov",
        "site:illinoisattorneygeneral.gov",
    ),
    "washington": (
        "site:app.leg.wa.gov",
        "site:lawfilesext.leg.wa.gov",
        "site:atg.wa.gov",
    ),
    "florida": (
        "site:flsenate.gov",
        "site:leg.state.fl.us",
        "site:myfloridalegal.com",
    ),
    "arkansas": (
        "site:arkleg.state.ar.us",
    ),
    "new_york": (
        "site:nysenate.gov",
        "site:nyassembly.gov",
        "site:governor.ny.gov",
    ),
    "ireland": (
        "site:irishstatutebook.ie",
        "site:gov.ie",
        "site:cnam.ie",
    ),
    "brazil": (
        "site:planalto.gov.br",
        "site:gov.br",
        "site:in.gov.br",
    ),
    "india": (
        "site:meity.gov.in",
        "site:indiacode.nic.in",
        "site:egazette.gov.in",
        "site:cci.gov.in",
    ),
    "australia": (
        "site:legislation.gov.au",
        "site:oaic.gov.au",
        "site:esafety.gov.au",
        "site:accc.gov.au",
    ),
    "canada": (
        "site:laws-lois.justice.gc.ca",
        "site:priv.gc.ca",
        "site:competition-bureau.canada.ca",
        "site:canada.ca",
    ),
    "japan": (
        "site:japaneselawtranslation.go.jp",
        "site:ppc.go.jp",
        "site:jftc.go.jp",
        "site:elaws.e-gov.go.jp",
    ),
    "south_korea": (
        "site:law.go.kr",
        "site:elaw.klri.re.kr",
        "site:pipc.go.kr",
        "site:ftc.go.kr",
    ),
    "singapore": (
        "site:sso.agc.gov.sg",
        "site:pdpc.gov.sg",
        "site:cccs.gov.sg",
        "site:imda.gov.sg",
    ),
    "south_africa": (
        "site:gov.za",
        "site:inforegulator.org.za",
        "site:compcom.co.za",
    ),
}

_META_HOST_DEMOTE: tuple[str, ...] = (
    "meta.com",
    "about.meta.com",
    "facebook.com",
    "fb.com",
    "instagram.com",
    "whatsapp.com",
    "messenger.com",
    "workplace.com",
    "oculus.com",
    "threads.net",
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_META_NEXUS_OK = frozenset({"named_party", "platform_obligation", "sector_rule", "other"})
_SOURCE_TYPE_OK = frozenset({"primary", "secondary"})
_RETRY_JSON_ONLY_PROMPT = (
    "Return a JSON array only. No markdown. No prose. "
    "Each item needs title, citation, source_url from the materials, "
    "source_type, excerpt, meta_nexus, meta_nexus_rationale, language, "
    "effective_date, status, confidence. If nothing applies, return []."
)


class _ExtractedLawItem(BaseModel):
    """LLM-facing draft fields only (cell/worker stamped later)."""

    title: str = ""
    citation: str = ""
    source_url: str = ""
    source_type: Literal["primary", "secondary"] = "secondary"
    excerpt: str = ""
    meta_nexus: Literal[
        "named_party", "platform_obligation", "sector_rule", "other"
    ] = "platform_obligation"
    meta_nexus_rationale: str = ""
    language: str = "en"
    effective_date: str | None = None
    status: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class _ExtractedLawList(BaseModel):
    """Wrapper for with_structured_output (OpenAI-compatible tools/json_schema)."""

    drafts: list[_ExtractedLawItem] = Field(default_factory=list)


def _load_system_prompt(cell: ResearchCell) -> str:
    try:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        template = (
            "Extract laws for {{subject}} in {{jurisdiction}} / {{domain}}. "
            "Return a JSON array only with title, citation, source_url from materials, "
            "and meta_nexus. No markdown."
        )
    return (
        template.replace("{{subject}}", cell.subject)
        .replace("{{jurisdiction}}", cell.jurisdiction)
        .replace("{{jurisdiction_id}}", cell.jurisdiction_id)
        .replace("{{domain}}", cell.domain)
        .replace("{{domain_id}}", cell.domain_id)
    )


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            return dict(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return dict(value.dict())
        except Exception:
            pass
    return {}


def _coerce_cell(payload: Mapping[str, Any] | ResearchCell | Any) -> ResearchCell:
    """Accept flat Send payload, nested ``cell``, or ResearchCell instance."""
    if isinstance(payload, ResearchCell):
        return payload

    data = _as_mapping(payload)
    if not data and payload is not None and not isinstance(payload, Mapping):
        # object with attributes
        data = {
            k: getattr(payload, k)
            for k in (
                "cell_id",
                "jurisdiction",
                "jurisdiction_id",
                "domain",
                "domain_id",
                "subject",
                "status",
                "cell",
            )
            if hasattr(payload, k)
        }

    nested = data.get("cell")
    if nested is not None:
        nested_map = _as_mapping(nested)
        if nested_map:
            data = {**nested_map, **{k: v for k, v in data.items() if k != "cell" and v not in (None, "")}}

    jurisdiction = str(data.get("jurisdiction") or "").strip() or "Unknown"
    domain_raw = str(data.get("domain") or data.get("domain_id") or "").strip() or "privacy"
    # Always re-canonicalize so aliases (ca → California → california) match gold.
    if jurisdiction != "Unknown":
        jurisdiction = normalize_jurisdiction(jurisdiction) or jurisdiction
    raw_jid = str(data.get("jurisdiction_id") or "").strip()
    if raw_jid:
        # Prefer slugifying the normalized form of whatever was supplied
        # (handles "California", "ca", "united_states").
        jurisdiction_id = slugify(normalize_jurisdiction(raw_jid.replace("_", " "))) or slugify(raw_jid)
    else:
        jurisdiction_id = slugify(normalize_jurisdiction(jurisdiction)) if jurisdiction != "Unknown" else "unknown"
    # If label and id disagree after normalize (e.g. label California, id united_states),
    # prefer the more specific label-derived slug when it is a known non-generic id.
    if jurisdiction != "Unknown":
        label_jid = slugify(normalize_jurisdiction(jurisdiction))
        if label_jid and label_jid != jurisdiction_id:
            # Keep label when id is a parent/generic US while label is a state.
            if jurisdiction_id in {"united_states", "us", "usa"} and label_jid not in {
                "united_states",
                "us",
                "usa",
            }:
                jurisdiction_id = label_jid
            elif not raw_jid:
                jurisdiction_id = label_jid
    domain_id = str(data.get("domain_id") or "").strip() or normalize_domain(domain_raw)
    domain_id = normalize_domain(domain_id) or domain_id
    domain = str(data.get("domain") or domain_id).strip() or domain_id
    subject = str(data.get("subject") or "Meta").strip() or "Meta"
    cell_id = str(data.get("cell_id") or "").strip() or make_cell_id(jurisdiction_id, domain_id)
    # Keep cell_id prefix aligned with canonical jurisdiction_id when possible.
    if "::" in cell_id:
        _prefix, _sep, _suffix = cell_id.partition("::")
        if _suffix == domain_id and _prefix != jurisdiction_id:
            cell_id = make_cell_id(jurisdiction_id, domain_id)
    status = data.get("status") or "researching"
    if status not in ("pending", "researching", "validating", "done", "error"):
        status = "researching"

    return ResearchCell(
        cell_id=cell_id,
        jurisdiction=jurisdiction,
        jurisdiction_id=jurisdiction_id,
        domain=domain,
        domain_id=domain_id,
        subject=subject,
        status=status,  # type: ignore[arg-type]
    )


def _instruments_for_cell(cell: ResearchCell) -> tuple[str, ...]:
    jid = (cell.jurisdiction_id or slugify(normalize_jurisdiction(cell.jurisdiction or ""))).strip()
    domain_id = cell.domain_id or normalize_domain(cell.domain or "")
    specific = _JURISDICTION_DOMAIN_INSTRUMENTS.get((jid, domain_id))
    if specific:
        return specific
    generic = _DOMAIN_INSTRUMENTS.get(domain_id)
    if generic:
        return generic
    label = (cell.domain or domain_id or "regulation").strip()
    return (label,)


def build_search_queries(cell: ResearchCell) -> list[str]:
    """Build instrument-first legal discovery queries (Meta not leading every query)."""
    subject = (cell.subject or "Meta").strip() or "Meta"
    jurisdiction = (cell.jurisdiction or "").strip() or "Unknown"
    jid = (cell.jurisdiction_id or slugify(normalize_jurisdiction(jurisdiction))).strip()
    domain_id = cell.domain_id or normalize_domain(cell.domain)
    instruments = _instruments_for_cell(cell)
    site_hints = _JURISDICTION_SITE_HINTS.get(jid, ())
    domain_label = domain_id.replace("_", " ").strip() or "regulation"

    queries: list[str] = []

    # For each instrument: official text + site-restricted variants.
    for instrument in instruments:
        name = (instrument or "").strip()
        if not name:
            continue
        queries.append(f"{name} official text")
        queries.append(f"{name} {jurisdiction} official text")
        for site in site_hints[:3]:
            queries.append(f"{name} {site}")

    # Domain-level official legislation sweep (no subject leading).
    if site_hints:
        queries.append(f"{jurisdiction} {domain_label} law regulation {site_hints[0]}")
    else:
        queries.append(
            f"{jurisdiction} {domain_label} legislation statute regulation official text"
        )

    # Exactly one subject-nexus query (Meta-bearing) — always retained.
    subject_query = f"{subject} {jurisdiction} {domain_label} legal obligations regulation"

    # De-dupe while preserving order; reserve one slot for subject nexus.
    seen: set[str] = set()
    out: list[str] = []
    budget = 23  # leave room for subject_query
    for q in queries:
        key = " ".join(q.lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(" ".join(q.split()))
        if len(out) >= budget:
            break

    subject_key = " ".join(subject_query.lower().split())
    if subject_key and subject_key not in seen:
        out.append(" ".join(subject_query.split()))
    return out


def seed_urls_for_cell(cell: ResearchCell) -> list[str]:
    """Return high-confidence primary-source URLs for the cell, if known."""
    jid = (cell.jurisdiction_id or "").strip() or slugify(
        normalize_jurisdiction(cell.jurisdiction or "")
    )
    domain_id = (cell.domain_id or normalize_domain(cell.domain or "")).strip()
    seeds = list(_SEED_URLS.get((jid, domain_id), ()))
    # Soft jurisdiction aliases
    if not seeds and jid in {"eu", "european-union"}:
        seeds = list(_SEED_URLS.get(("european_union", domain_id), ()))
    if not seeds and jid in {"us", "usa", "united-states-of-america"}:
        seeds = list(_SEED_URLS.get(("united_states", domain_id), ()))
    out: list[str] = []
    seen: set[str] = set()
    for url in seeds:
        key = url.split("#", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out


def _host_score(url: str) -> int:
    u = (url or "").lower()
    score = 0
    for hint in _OFFICIAL_HOST_HINTS:
        if hint in u:
            score += 3
    if any(ext in u for ext in (".pdf", "/eli/", "/legal-content/", "/legislation", "/ukpga/")):
        score += 1
    if any(bad in u for bad in ("pinterest.", "facebook.com/posts", "twitter.com", "x.com/", "reddit.com")):
        score -= 2
    # Demote Meta marketing / product hosts heavily unless already official.
    if any(host in u for host in _META_HOST_DEMOTE):
        score -= 8
    return score


def select_urls(
    results: Iterable[Mapping[str, Any]],
    *,
    limit: int = 5,
) -> list[str]:
    """Rank search hits and return top official-looking unique URLs."""
    ranked: list[tuple[int, int, str]] = []
    for idx, item in enumerate(results):
        url = str(item.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        ranked.append((_host_score(url), -idx, url))
    ranked.sort(reverse=True)

    out: list[str] = []
    seen: set[str] = set()
    for _score, _neg_idx, url in ranked:
        key = url.split("#", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def _message_text(response: Any) -> str:
    if response is None:
        return ""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif hasattr(block, "get"):
                parts.append(str(block.get("text") or block.get("content") or ""))
        return "".join(parts)
    return str(content or "")


def _extract_json_payload(text: str) -> Any:
    raw = (text or "").strip()
    if not raw:
        return None
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Best-effort: first {...} or [...] blob
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except Exception:
                continue
    return None


def _payload_from_structured(response: Any) -> Any:
    """Normalize with_structured_output / tool-call responses into parseable payload."""
    if response is None:
        return None
    if isinstance(response, _ExtractedLawList):
        return response.model_dump()
    if isinstance(response, _ExtractedLawItem):
        return [response.model_dump()]
    if isinstance(response, list):
        return response
    if isinstance(response, Mapping):
        return dict(response)
    if hasattr(response, "model_dump"):
        try:
            dumped = response.model_dump()
            if isinstance(dumped, (dict, list)):
                return dumped
        except Exception:
            pass
    if hasattr(response, "dict"):
        try:
            dumped = response.dict()
            if isinstance(dumped, (dict, list)):
                return dumped
        except Exception:
            pass
    text = _message_text(response)
    return _extract_json_payload(text) if text else None


def _drafts_from_payload(
    payload: Any,
    *,
    cell: ResearchCell,
    worker_model: str,
) -> list[LawRecordDraft]:
    if payload is None:
        return []

    items: list[Any]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, Mapping):
        if isinstance(payload.get("drafts"), list):
            items = payload["drafts"]
        elif isinstance(payload.get("records"), list):
            items = payload["records"]
        elif isinstance(payload.get("items"), list):
            items = payload["items"]
        else:
            items = [payload]
    else:
        return []

    drafts: list[LawRecordDraft] = []
    for item in items:
        data = _as_mapping(item)
        if not data:
            continue
        title = str(data.get("title") or "").strip()
        if not title:
            continue
        nexus = str(data.get("meta_nexus") or "platform_obligation").strip()
        if nexus not in _META_NEXUS_OK:
            nexus = "platform_obligation"
        source_type = str(data.get("source_type") or "secondary").strip()
        if source_type not in _SOURCE_TYPE_OK:
            source_type = "secondary"
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        effective = data.get("effective_date")
        if effective is not None:
            effective = str(effective).strip() or None

        status = data.get("status")
        if status is not None:
            status = str(status).strip() or None

        try:
            jid = (cell.jurisdiction_id or "").strip() or slugify(
                normalize_jurisdiction(cell.jurisdiction or "")
            )
            did = (cell.domain_id or "").strip() or normalize_domain(cell.domain or "")
            draft = LawRecordDraft(
                title=title,
                jurisdiction_id=jid,
                domain_id=did,
                meta_nexus=nexus,
                meta_nexus_rationale=str(data.get("meta_nexus_rationale") or "").strip(),
                citation=str(data.get("citation") or "").strip(),
                source_url=str(data.get("source_url") or data.get("url") or "").strip(),
                source_type=source_type,  # type: ignore[arg-type]
                excerpt=str(data.get("excerpt") or "").strip(),
                language=str(data.get("language") or "en").strip() or "en",
                effective_date=effective,
                status=status,
                confidence=confidence,
                worker_model=worker_model,
                cell_id=cell.cell_id or make_cell_id(jid, did),
            )
        except Exception:
            continue
        drafts.append(draft)
    return drafts


def _build_extract_messages(cell: ResearchCell, context: str, *, retry: bool = False) -> list[dict[str, str]]:
    system = _load_system_prompt(cell)
    if retry:
        user = (
            f"{_RETRY_JSON_ONLY_PROMPT}\n\n"
            f"Cell: {cell.cell_id}\n"
            f"Jurisdiction: {cell.jurisdiction} ({cell.jurisdiction_id})\n"
            f"Domain: {cell.domain} ({cell.domain_id})\n"
            f"Subject: {cell.subject}\n\n"
            f"Materials:\n{context}"
        )
        return [{"role": "user", "content": user}]

    user = (
        f"Cell: {cell.cell_id}\n"
        f"Jurisdiction: {cell.jurisdiction} ({cell.jurisdiction_id})\n"
        f"Domain: {cell.domain} ({cell.domain_id})\n"
        f"Subject: {cell.subject}\n\n"
        f"Search/fetch materials:\n{context}\n\n"
        "Extract applicable law drafts. Return a JSON array only — no markdown fences, "
        "no chain-of-thought, no wrapper object. source_url must come from the materials."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "429" in text or "rate limit" in text or "rate_limit" in text or "too many requests" in text


def _call_llm(llm: Any, messages: list[dict[str, str]]) -> Any:
    """Invoke chat model; on OpenRouter/HTTP 429 retry once with short backoff."""

    def _invoke_once() -> Any:
        try:
            return llm.invoke(messages)
        except Exception:
            return llm(messages)

    try:
        return _invoke_once()
    except Exception as first:
        if not _is_rate_limit_error(first):
            raise RuntimeError(f"llm invoke failed: {first}") from first
        time.sleep(1.5)
        try:
            return _invoke_once()
        except Exception as second:
            raise RuntimeError(f"llm invoke failed after 429 retry: {second}") from second


def _try_structured_output(llm: Any, messages: list[dict[str, str]]) -> Any | None:
    """Prefer ChatOpenAI.with_structured_output when available (OpenRouter-compatible)."""
    binder = getattr(llm, "with_structured_output", None)
    if not callable(binder):
        return None
    structured = None
    last_err: Exception | None = None
    for kwargs in (
        {"method": "json_schema"},
        {"method": "function_calling"},
        {},
    ):
        try:
            structured = binder(_ExtractedLawList, **kwargs) if kwargs else binder(_ExtractedLawList)
            break
        except TypeError:
            # Older signatures may not accept method=
            try:
                structured = binder(_ExtractedLawList)
                break
            except Exception as exc:
                last_err = exc
                structured = None
        except Exception as exc:
            last_err = exc
            structured = None
    if structured is None:
        if last_err is not None:
            return None
        return None
    try:
        return _call_llm(structured, messages)
    except Exception:
        return None


def _try_json_mode(llm: Any, messages: list[dict[str, str]]) -> Any | None:
    """Fallback: OpenAI-compatible response_format json_object when supported."""
    binder = getattr(llm, "bind", None)
    if not callable(binder):
        return None
    bound = None
    for fmt in (
        {"type": "json_object"},
        {"type": "json_schema", "json_schema": {
            "name": "law_drafts",
            "schema": _ExtractedLawList.model_json_schema(),
        }},
    ):
        try:
            bound = binder(response_format=fmt)
            break
        except Exception:
            bound = None
    if bound is None:
        return None
    try:
        return _call_llm(bound, messages)
    except Exception:
        return None


def _invoke_llm_for_drafts(
    *,
    llm: Any,
    cell: ResearchCell,
    context: str,
    worker_model: str,
) -> list[LawRecordDraft]:
    """Extract drafts via structured output → JSON mode → text parse, with one empty retry.

    Never raises; empty list on total failure (caller records cell_errors).
    """
    messages = _build_extract_messages(cell, context, retry=False)

    def _parse_response(response: Any) -> list[LawRecordDraft]:
        payload = _payload_from_structured(response)
        return _drafts_from_payload(payload, cell=cell, worker_model=worker_model)

    # 1) structured output (preferred)
    response = _try_structured_output(llm, messages)
    if response is not None:
        drafts = _parse_response(response)
        if drafts:
            return drafts

    # 2) JSON mode / response_format
    response = _try_json_mode(llm, messages)
    if response is not None:
        drafts = _parse_response(response)
        if drafts:
            return drafts

    # 3) plain text invoke + JSON parse
    try:
        response = _call_llm(llm, messages)
        drafts = _parse_response(response)
        if drafts:
            return drafts
    except Exception:
        drafts = []

    # 4) one automatic retry with shorter "JSON array only" prompt
    retry_messages = _build_extract_messages(cell, context, retry=True)
    try:
        # Prefer lightweight paths on retry: json mode then plain text.
        response = _try_json_mode(llm, retry_messages)
        if response is None:
            response = _call_llm(llm, retry_messages)
        drafts = _parse_response(response)
        if drafts:
            return drafts
    except Exception:
        return []

    return []



def _resolve_worker_model(llm: Any | None) -> str:
    env_model = (
        os.getenv("OPENROUTER_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or os.getenv("META_LEGAL_WORKER_MODEL")
        or DEFAULT_MODEL
    )
    if llm is None:
        return env_model
    for attr in ("model_name", "model"):
        value = getattr(llm, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return env_model


def run_research_cell(
    cell: Mapping[str, Any] | ResearchCell | Any,
    *,
    search_fn: SearchFn | None = None,
    fetch_fn: FetchFn | None = None,
    llm: Any | None = None,
    max_results_per_query: int = 5,
    max_urls: int = 7,
    max_chars_per_page: int = 8000,
    max_fetch_workers: int = 5,
) -> dict[str, list[Any]]:
    """Core research worker with injectable tools/LLM (for tests).

    Returns reducer-friendly ``{"drafts": [...]}`` and/or ``{"cell_errors": [...]}``.
    Never raises.
    """
    search = search_fn or default_web_search
    fetch = fetch_fn or default_fetch_url
    drafts: list[LawRecordDraft] = []
    errors: list[CellError] = []

    try:
        resolved = _coerce_cell(cell)
    except Exception as exc:
        return {
            "drafts": [],
            "cell_errors": [
                CellError(cell_id="unknown", message=f"invalid cell payload: {exc}", stage="research")
            ],
        }

    cell_id = resolved.cell_id
    worker_model = _resolve_worker_model(llm)

    # --- search ---
    search_hits: list[dict[str, str]] = []
    try:
        for query in build_search_queries(resolved):
            try:
                hits = search(query, max_results_per_query) or []
            except TypeError:
                # Allow fns that only take query
                try:
                    hits = search(query) or []  # type: ignore[misc,call-arg]
                except Exception as exc:
                    errors.append(
                        CellError(
                            cell_id=cell_id,
                            message=f"search failed for query {query!r}: {exc}",
                            stage="research",
                        )
                    )
                    hits = []
            except Exception as exc:
                errors.append(
                    CellError(
                        cell_id=cell_id,
                        message=f"search failed for query {query!r}: {exc}",
                        stage="research",
                    )
                )
                hits = []
            for hit in hits:
                if isinstance(hit, Mapping):
                    search_hits.append(
                        {
                            "title": str(hit.get("title") or ""),
                            "url": str(hit.get("url") or ""),
                            "snippet": str(hit.get("snippet") or ""),
                        }
                    )
    except Exception as exc:
        errors.append(
            CellError(cell_id=cell_id, message=f"search loop failed: {exc}", stage="research")
        )

    # Merge high-confidence primary seeds even when search is empty/partial.
    seed_urls = seed_urls_for_cell(resolved)
    for seed in seed_urls:
        search_hits.append(
            {
                "title": f"Seed primary source: {seed}",
                "url": seed,
                "snippet": "Curated primary-source seed for this jurisdiction/domain cell.",
            }
        )

    if not search_hits:
        errors.append(
            CellError(
                cell_id=cell_id,
                message="search returned no results",
                stage="research",
            )
        )
        return {"drafts": [], "cell_errors": errors}

    urls = select_urls(search_hits, limit=max_urls)
    if not urls:
        # Fall back to any http URLs from hits + seeds (ignore host ranking).
        fallback: list[str] = []
        seen_fb: set[str] = set()
        for item in search_hits:
            url = str(item.get("url") or "").strip()
            if not url.startswith("http"):
                continue
            key = url.split("#", 1)[0].rstrip("/")
            if key in seen_fb:
                continue
            seen_fb.add(key)
            fallback.append(url)
            if len(fallback) >= max_urls:
                break
        urls = fallback

    # Ensure seeds remain in the fetch list even if ranking dropped them.
    if seed_urls:
        seen_urls = {u.split("#", 1)[0].rstrip("/") for u in urls}
        for seed in seed_urls:
            key = seed.split("#", 1)[0].rstrip("/")
            if key in seen_urls:
                continue
            urls.append(seed)
            seen_urls.add(key)
            if len(urls) >= max_urls + len(seed_urls):
                break
        # Seed-heavy cells may keep a couple extra primary URLs beyond max_urls.
        urls = urls[: max(max_urls, min(len(urls), max_urls + 3))]

    # --- fetch (concurrent; preserve URL order in context) ---
    def _fetch_one(url: str) -> tuple[str, str, str | None]:
        """Return (url, text, error_message). Never raises."""
        try:
            text = fetch(url, max_chars_per_page) or ""
        except TypeError:
            try:
                text = fetch(url) or ""  # type: ignore[misc,call-arg]
            except Exception as exc:
                return url, "", f"fetch failed for {url}: {exc}"
        except Exception as exc:
            return url, "", f"fetch failed for {url}: {exc}"
        return url, text, None

    fetched_by_url: dict[str, str] = {}
    workers = max(1, min(int(max_fetch_workers or 5), len(urls) or 1))
    if urls:
        with _DaemonThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {pool.submit(_fetch_one, url): url for url in urls}
            for fut in as_completed(future_map):
                url = future_map[fut]
                try:
                    got_url, text, err_msg = fut.result()
                except Exception as exc:
                    errors.append(
                        CellError(
                            cell_id=cell_id,
                            message=f"fetch failed for {url}: {exc}",
                            stage="research",
                        )
                    )
                    continue
                if err_msg:
                    errors.append(
                        CellError(cell_id=cell_id, message=err_msg, stage="research")
                    )
                if (text or "").strip():
                    fetched_by_url[got_url] = text.strip()

    fetched_blocks: list[str] = [
        f"URL: {url}\n{fetched_by_url[url]}"
        for url in urls
        if url in fetched_by_url
    ]

    # Always include search snippets so LLM can still work if all fetches fail.
    snippet_lines = []
    for hit in search_hits[: max_urls * 2]:
        snippet_lines.append(
            f"- {hit.get('title') or ''}\n  URL: {hit.get('url') or ''}\n  "
            f"Snippet: {hit.get('snippet') or ''}"
        )
    context_parts = [
        "SEARCH RESULTS:",
        "\n".join(snippet_lines) if snippet_lines else "(none)",
    ]
    if fetched_blocks:
        context_parts.append("FETCHED PAGES:")
        context_parts.append("\n\n---\n\n".join(fetched_blocks))
    else:
        errors.append(
            CellError(
                cell_id=cell_id,
                message="all URL fetches failed or returned empty; using search snippets only",
                stage="research",
            )
        )
    context = "\n\n".join(context_parts)

    # --- LLM extract ---
    active_llm = llm
    if active_llm is None:
        try:
            active_llm = get_llm(worker_model)
        except Exception as exc:
            errors.append(
                CellError(
                    cell_id=cell_id,
                    message=f"llm init failed: {exc}",
                    stage="research",
                )
            )
            active_llm = None

    drafts = []
    if active_llm is not None:
        try:
            drafts = _invoke_llm_for_drafts(
                llm=active_llm,
                cell=resolved,
                context=context,
                worker_model=worker_model,
            )
        except Exception as exc:
            errors.append(
                CellError(
                    cell_id=cell_id,
                    message=f"llm extraction failed: {exc}",
                    stage="research",
                )
            )
            drafts = []

    if not drafts and not any("search returned no results" in e.message for e in errors):
        # Soft warning when model produced nothing usable (harvest may still fill).
        errors.append(
            CellError(
                cell_id=cell_id,
                message="llm returned no usable drafts",
                stage="research",
            )
        )

    # Deterministic floor: curated instruments + seed URLs even if LLM/search flaked.
    try:
        # Prefer already-fetched pages; harvest may fetch remaining seeds if needed.
        harvested = harvest_seed_instruments(
            resolved,
            instruments=_instruments_for_cell(resolved),
            seed_urls=seed_urls,
            fetch_fn=fetch,
            fetched_cache=fetched_by_url,
            max_chars_excerpt=min(1200, max_chars_per_page),
            max_chars_fetch=max_chars_per_page,
            worker_model="seed_harvest",
        )
        drafts = merge_drafts(drafts, harvested)
    except Exception as exc:
        errors.append(
            CellError(
                cell_id=cell_id,
                message=f"seed harvest failed: {exc}",
                stage="research",
            )
        )

    result: dict[str, list[Any]] = {"drafts": drafts}
    if errors:
        result["cell_errors"] = errors
    return result


def research_cell(state: dict[str, Any] | ResearchCell | Any) -> dict[str, list[Any]]:
    """LangGraph node entry: research one Send() cell payload.

    Expected state is a cell payload (flat ResearchCell fields or nested
    ``cell``). Returns ``drafts`` / ``cell_errors`` list updates only.
    """
    try:
        return run_research_cell(state)
    except Exception as exc:  # absolute soft-fail belt
        data = _as_mapping(state)
        nested = _as_mapping(data.get("cell")) if data.get("cell") is not None else {}
        cell_id = str(
            data.get("cell_id")
            or nested.get("cell_id")
            or "unknown"
        )
        return {
            "drafts": [],
            "cell_errors": [
                CellError(cell_id=cell_id, message=f"research_cell crashed: {exc}", stage="research")
            ],
        }


__all__ = [
    "build_search_queries",
    "harvest_seed_instruments",
    "research_cell",
    "run_research_cell",
    "seed_urls_for_cell",
    "select_urls",
]
