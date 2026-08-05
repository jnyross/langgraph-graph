#!/usr/bin/env python3
"""Generate a realistic demo dossier under data/dossiers/demo_<timestamp>/.

Covers 8 jurisdictions x 5 domains = 40 cells, populated ~22 cells with
1-4 laws each (total ~40 laws) to show heatmap variation. Uses the canonical
filesystem writer so the aggregator and frontend consume it identically to a
real research run.

Usage:
    uv run python scripts/seed_matrix_demo.py              # writes demo_<timestamp>
    uv run python scripts/seed_matrix_demo.py --run-id demo_custom
    DOSSIER_ROOT=/tmp/dossiers uv run python scripts/seed_matrix_demo.py
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langgraph_graph.meta_legal.models import LawRecord, ResearchCell, make_cell_id, slugify
from langgraph_graph.meta_legal.nodes.write_dossier import write_dossier_to_root

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

JURISDICTIONS: list[str] = [
    "European Union",
    "United States",
    "California",
    "Germany",
    "France",
    "United Kingdom",
    "Brazil",
    "Japan",
]

DOMAINS: list[str] = [
    "privacy",
    "competition",
    "youth_safety",
    "ip",
    "accessibility",
]

DEFAULT_DOSSIER_ROOT = "data/dossiers"

# Stable slug mapping (matches slugify()) - computed once for law generation
JID_SLUGS: dict[str, str] = {j: slugify(j) for j in JURISDICTIONS}

# ---------------------------------------------------------------------------
# law catalogue — 22 populated cells, ~40 laws
# Each entry: (jurisdiction_display, domain_id, [law defs ...])
# law def: dict with title, citation, source_url leaf, source_type, excerpt,
#          meta_nexus, confidence, effective_date, status, language
# ---------------------------------------------------------------------------

# Helper to build source_url slugs
def _url(jid_slug: str, slug: str) -> str:
    return f"https://example.com/laws/{jid_slug}/{slug}"


# fmt: off
LAW_CATALOGUE: list[tuple[str, str, list[dict]]] = [
    # --- European Union ---------------------------------------------------
    ("European Union", "privacy", [
        {
            "title": "GDPR — General Data Protection Regulation (Regulation (EU) 2016/679)",
            "citation": "Regulation (EU) 2016/679, OJ L 119, 4.5.2016",
            "slug": "gdpr-2016-679",
            "source_type": "primary",
            "excerpt": "Requires Meta to provide a lawful basis for processing, honour data-subject rights and conduct DPIAs for high-risk processing on Facebook and Instagram.",
            "meta_nexus": "platform_obligation",
            "rationale": "Applies directly to Meta as data controller for EU users; governs all personal-data processing on the platform.",
            "confidence": 0.95, "effective_date": "2018-05-25", "status": "in_force",
        },
        {
            "title": "ePrivacy Directive — Directive 2002/58/EC (as amended)",
            "citation": "Directive 2002/58/EC, OJ L 201, 31.7.2002",
            "slug": "eprivacy-directive-2002-58",
            "source_type": "primary",
            "excerpt": "Mandates prior consent for storing or accessing information on user devices, directly affecting Meta Pixel, cookies and messaging metadata.",
            "meta_nexus": "platform_obligation",
            "rationale": "Platform must obtain consent before deploying tracking technologies across EU web properties.",
            "confidence": 0.88, "effective_date": "2002-07-31", "status": "in_force",
        },
        {
            "title": "Data Act — Regulation (EU) 2023/2854",
            "citation": "Regulation (EU) 2023/2854, OJ L 2023/2854, 22.12.2023",
            "slug": "data-act-2023-2854",
            "source_type": "primary",
            "excerpt": "Obliges data holders including Meta to make IoT and platform-generated data available to users and third parties under FRAND terms.",
            "meta_nexus": "platform_obligation",
            "rationale": "Creates interoperability and data-sharing duties for large platforms holding connected-device data.",
            "confidence": 0.82, "effective_date": "2025-09-12", "status": "in_force",
        },
        {
            "title": "EU-US Data Privacy Framework — Adequacy Decision",
            "citation": "Commission Implementing Decision (EU) 2023/1795, 10.7.2023",
            "slug": "eu-us-dpf-adequacy-2023",
            "source_type": "secondary",
            "excerpt": "Provides the adequacy basis for Meta's transatlantic transfers of EU personal data to the United States after Schrems II.",
            "meta_nexus": "sector_rule",
            "rationale": "Sector-wide adequacy mechanism that determines how Meta may lawfully transfer EU user data to US servers.",
            "confidence": 0.78, "effective_date": "2023-07-10", "status": "in_force",
        },
    ]),
    ("European Union", "competition", [
        {
            "title": "Digital Markets Act — Regulation (EU) 2022/1925",
            "citation": "Regulation (EU) 2022/1925, OJ L 265, 12.10.2022",
            "slug": "dma-2022-1925",
            "source_type": "primary",
            "excerpt": "Designates Meta as a gatekeeper and prohibits self-preferencing, mandates interoperability for Messenger and data-portability APIs.",
            "meta_nexus": "named_party",
            "rationale": "Meta is explicitly designated as a gatekeeper; obligations target its core platform services directly.",
            "confidence": 0.94, "effective_date": "2023-05-02", "status": "in_force",
        },
        {
            "title": "Digital Services Act — Regulation (EU) 2022/2065",
            "citation": "Regulation (EU) 2022/2065, OJ L 277, 27.10.2022",
            "slug": "dsa-2022-2065",
            "source_type": "primary",
            "excerpt": "Imposes transparency, risk-assessment and content-moderation duties on Meta as a Very Large Online Platform for Facebook and Instagram.",
            "meta_nexus": "platform_obligation",
            "rationale": "VLOP designation triggers systemic-risk and recommender-system transparency duties for Meta's platforms.",
            "confidence": 0.93, "effective_date": "2024-02-17", "status": "in_force",
        },
        {
            "title": "EU Antitrust — Article 102 TFEU Enforcement (Meta Marketplace / Data)",
            "citation": "European Commission, Case AT.40684 — Facebook Marketplace, Decision 2024",
            "slug": "eu-antitrust-fb-marketplace-2024",
            "source_type": "secondary",
            "excerpt": "Commission's abuse-of-dominance proceedings address Meta tying Marketplace to Facebook and leveraging advertising data.",
            "meta_nexus": "named_party",
            "rationale": "Enforcement action names Meta as addressee for alleged tying and data-leveraging practices.",
            "confidence": 0.81, "effective_date": None, "status": "enforcement",
        },
    ]),
    ("European Union", "youth_safety", [
        {
            "title": "Digital Services Act — Youth Protection (Art. 28 DSA)",
            "citation": "Regulation (EU) 2022/2065, Art. 28",
            "slug": "dsa-art28-youth",
            "source_type": "primary",
            "excerpt": "Requires VLOPs including Meta to put in place proportionate measures to protect minors from harmful content and high-privacy defaults.",
            "meta_nexus": "platform_obligation",
            "rationale": "Platform must design recommender and privacy defaults for minors on Instagram and Facebook.",
            "confidence": 0.86, "effective_date": "2024-02-17", "status": "in_force",
        },
        {
            "title": "Audiovisual Media Services Directive — Protection of Minors (2018/1808)",
            "citation": "Directive (EU) 2018/1808, OJ L 303, 28.11.2018",
            "slug": "avmsd-2018-1808-minors",
            "source_type": "primary",
            "excerpt": "Extends obligations to video-sharing platforms such as Facebook Watch and Instagram Reels to protect minors from harmful video content.",
            "meta_nexus": "platform_obligation",
            "rationale": "Meta's video surfaces qualify as video-sharing platforms under AVMSD.",
            "confidence": 0.76, "effective_date": "2020-09-19", "status": "in_force",
        },
    ]),
    ("European Union", "ip", [
        {
            "title": "Copyright in the Digital Single Market — Directive (EU) 2019/790 (Art. 17)",
            "citation": "Directive (EU) 2019/790, OJ L 130, 17.5.2019, Art. 17",
            "slug": "copyright-directive-2019-790-art17",
            "source_type": "primary",
            "excerpt": "Obliges Meta as an online content-sharing service provider to obtain authorisation or deploy best-effort filtering for user-uploaded content.",
            "meta_nexus": "platform_obligation",
            "rationale": "Directly regulates Meta's liability for user uploads on Facebook and Instagram.",
            "confidence": 0.89, "effective_date": "2021-06-07", "status": "in_force",
        },
        {
            "title": "Trade Secrets Directive — Directive (EU) 2016/943",
            "citation": "Directive (EU) 2016/943, OJ L 157, 15.6.2016",
            "slug": "trade-secrets-2016-943",
            "source_type": "primary",
            "excerpt": "Harmonises trade-secret protection and affects Meta's handling of confidential business information in B2B data-sharing products.",
            "meta_nexus": "sector_rule",
            "rationale": "Sector-wide IP regime affecting platform data-sharing and scraping enforcement.",
            "confidence": 0.72, "effective_date": "2018-06-09", "status": "in_force",
        },
    ]),
    ("European Union", "accessibility", [
        {
            "title": "European Accessibility Act — Directive (EU) 2019/882",
            "citation": "Directive (EU) 2019/882, OJ L 151, 7.6.2019",
            "slug": "eaa-2019-882",
            "source_type": "primary",
            "excerpt": "Requires Meta's e-commerce, messaging and audiovisual services to meet harmonised accessibility requirements for persons with disabilities.",
            "meta_nexus": "platform_obligation",
            "rationale": "Platform services including Marketplace and messaging fall within EAA service scope.",
            "confidence": 0.84, "effective_date": "2025-06-28", "status": "in_force",
        },
        {
            "title": "Web Accessibility Directive — Directive (EU) 2016/2102",
            "citation": "Directive (EU) 2016/2102, OJ L 327, 2.12.2016",
            "slug": "web-accessibility-2016-2102",
            "source_type": "primary",
            "excerpt": "Sets accessibility standards that inform Meta's compliance for public-sector-facing pages and Workplace integrations.",
            "meta_nexus": "sector_rule",
            "rationale": "Sector rule influencing platform accessibility expectations even where Meta is not the direct addressee.",
            "confidence": 0.71, "effective_date": "2018-09-23", "status": "in_force",
        },
    ]),
    # --- United States (federal) -------------------------------------------
    ("United States", "privacy", [
        {
            "title": "COPPA — Children's Online Privacy Protection Act (15 U.S.C. §§ 6501-6506)",
            "citation": "15 U.S.C. §§ 6501-6506; 16 C.F.R. Part 312",
            "slug": "coppa-15-usc-6501",
            "source_type": "primary",
            "excerpt": "Requires Meta to obtain verifiable parental consent before collecting personal information from children under 13 on Messenger Kids and Instagram.",
            "meta_nexus": "platform_obligation",
            "rationale": "Platform must age-gate and obtain parental consent for under-13 users across Meta products.",
            "confidence": 0.91, "effective_date": "1998-10-21", "status": "in_force",
        },
        {
            "title": "Section 230 — Communications Decency Act (47 U.S.C. § 230)",
            "citation": "47 U.S.C. § 230",
            "slug": "cda-section-230",
            "source_type": "primary",
            "excerpt": "Provides Meta limited immunity for third-party content on Facebook and Instagram while preserving moderation discretion.",
            "meta_nexus": "platform_obligation",
            "rationale": "Foundational platform liability shield that defines Meta's content-moderation obligations and protections.",
            "confidence": 0.88, "effective_date": "1996-02-08", "status": "in_force",
        },
    ]),
    ("United States", "competition", [
        {
            "title": "Sherman Act — Section 2 Monopolization (15 U.S.C. § 2) — FTC v. Meta",
            "citation": "15 U.S.C. § 2; FTC v. Meta Platforms, Inc., No. 1:20-cv-03590 (D.D.C.)",
            "slug": "sherman-s2-ftc-v-meta",
            "source_type": "secondary",
            "excerpt": "Federal antitrust litigation alleges Meta illegally maintained monopoly power through acquisitions of Instagram and WhatsApp.",
            "meta_nexus": "named_party",
            "rationale": "Litigation names Meta as defendant for alleged monopolization via strategic acquisitions.",
            "confidence": 0.83, "effective_date": None, "status": "litigation",
        },
        {
            "title": "Hart-Scott-Rodino Antitrust Improvements Act — Merger Review",
            "citation": "15 U.S.C. § 18a; 16 C.F.R. Parts 801-803",
            "slug": "hsr-act-merger-review",
            "source_type": "primary",
            "excerpt": "Requires Meta to file premerger notifications and observe waiting periods for reportable acquisitions.",
            "meta_nexus": "platform_obligation",
            "rationale": "Platform acquirer must submit HSR filings for qualifying transactions.",
            "confidence": 0.79, "effective_date": "1976-09-14", "status": "in_force",
        },
    ]),
    ("United States", "youth_safety", [
        {
            "title": "Protecting Kids on Social Media Act (Proposed — S.1291, 2023)",
            "citation": "S.1291, 118th Cong. (2023) — proposed",
            "slug": "kids-social-media-act-s1291",
            "source_type": "secondary",
            "excerpt": "Would require Meta to verify user age, restrict under-13 access and disable algorithmic recommendations for minors by default.",
            "meta_nexus": "platform_obligation",
            "rationale": "Would impose age-verification and design-code duties directly on covered platforms like Instagram.",
            "confidence": 0.74, "effective_date": None, "status": "proposed",
        },
    ]),
    ("United States", "ip", [
        {
            "title": "DMCA — Digital Millennium Copyright Act (17 U.S.C. § 512)",
            "citation": "17 U.S.C. § 512",
            "slug": "dmca-512-safe-harbor",
            "source_type": "primary",
            "excerpt": "Requires Meta to operate a notice-and-takedown system and repeat-infringer policy for Facebook and Instagram to retain safe harbor.",
            "meta_nexus": "platform_obligation",
            "rationale": "Platform must maintain DMCA-compliant takedown workflows to preserve liability protection.",
            "confidence": 0.92, "effective_date": "1998-10-28", "status": "in_force",
        },
        {
            "title": "Lanham Act — Trademark Infringement (15 U.S.C. § 1114) — Platform Liability",
            "citation": "15 U.S.C. §§ 1114, 1125",
            "slug": "lanham-trademark-platform",
            "source_type": "primary",
            "excerpt": "Exposes Meta to contributory trademark liability for counterfeit listings on Facebook Marketplace and Instagram Shopping.",
            "meta_nexus": "platform_obligation",
            "rationale": "Marketplace operator may be liable for failing to address counterfeit seller activity.",
            "confidence": 0.77, "effective_date": "1946-07-05", "status": "in_force",
        },
    ]),
    # --- California ---------------------------------------------------------
    ("California", "privacy", [
        {
            "title": "CCPA as amended by CPRA — California Consumer Privacy Act (Cal. Civ. Code §§ 1798.100-1798.199.100)",
            "citation": "Cal. Civ. Code §§ 1798.100 et seq. (as amended by CPRA, 2020)",
            "slug": "ccpa-cpra-cal-civ-1798",
            "source_type": "primary",
            "excerpt": "Grants California residents rights to know, delete and opt out of sale/sharing of personal information and requires Meta to honour Global Privacy Control signals.",
            "meta_nexus": "platform_obligation",
            "rationale": "Meta meets CCPA thresholds as a large data-processing business serving California residents.",
            "confidence": 0.94, "effective_date": "2023-01-01", "status": "in_force",
        },
        {
            "title": "California Delete Act — SB 362 (Cal. Civ. Code § 1798.99 et seq.)",
            "citation": "Cal. Civ. Code §§ 1798.99.80-1798.99.84 (SB 362, 2023)",
            "slug": "delete-act-sb362-2023",
            "source_type": "primary",
            "excerpt": "Establishes a one-stop deletion mechanism for data brokers that Meta must interoperate with for people-search and ad-audience products.",
            "meta_nexus": "platform_obligation",
            "rationale": "Platform acting as data broker for certain ad products must respond to centralised deletion requests.",
            "confidence": 0.80, "effective_date": "2024-01-01", "status": "in_force",
        },
        {
            "title": "CalOPPA — California Online Privacy Protection Act (Cal. Bus. & Prof. Code §§ 22575-22579)",
            "citation": "Cal. Bus. & Prof. Code §§ 22575-22579",
            "slug": "caloppa-bus-prof-22575",
            "source_type": "primary",
            "excerpt": "Requires Meta to conspicuously post a privacy policy disclosing data-collection practices for california.com visitors.",
            "meta_nexus": "platform_obligation",
            "rationale": "Website operator collecting PII from California residents must disclose practices via accessible privacy policy.",
            "confidence": 0.86, "effective_date": "2004-07-01", "status": "in_force",
        },
    ]),
    ("California", "youth_safety", [
        {
            "title": "California Age-Appropriate Design Code — AB 2273 (Cal. Civ. Code § 1798.99.28 et seq.)",
            "citation": "Cal. Civ. Code §§ 1798.99.28-1798.99.32 (AB 2273, 2022)",
            "slug": "ca-adc-ab2273-2022",
            "source_type": "primary",
            "excerpt": "Requires Meta to configure Instagram and Facebook to default to the highest privacy and safety settings for users under 18.",
            "meta_nexus": "platform_obligation",
            "rationale": "Directly regulates design choices for services likely to be accessed by children in California.",
            "confidence": 0.87, "effective_date": "2024-07-01", "status": "in_force",
        },
    ]),
    # --- Germany ------------------------------------------------------------
    ("Germany", "privacy", [
        {
            "title": "BDSG — Federal Data Protection Act (Bundesdatenschutzgesetz)",
            "citation": "BDSG, BGBl. I S. 2097 (2017), as amended",
            "slug": "bdsg-2017",
            "source_type": "primary",
            "excerpt": "Supplements GDPR with German specifics on employee data, DPO appointment and supervisory authority structure affecting Meta's German operations.",
            "meta_nexus": "platform_obligation",
            "rationale": "Meta's German establishment must comply with BDSG overlays alongside GDPR.",
            "confidence": 0.85, "effective_date": "2018-05-25", "status": "in_force",
        },
        {
            "title": "TTDSG — Telecommunications-Telemedia Data Protection Act",
            "citation": "TTDSG, BGBl. I S. 1380 (2021)",
            "slug": "ttdsg-2021",
            "source_type": "primary",
            "excerpt": "Transposes ePrivacy consent rules for terminal-equipment access, governing Meta Pixel and SDK storage on German users' devices.",
            "meta_nexus": "platform_obligation",
            "rationale": "German implementation of consent for accessing device storage applies to Meta tracking technologies.",
            "confidence": 0.81, "effective_date": "2021-12-01", "status": "in_force",
        },
    ]),
    ("Germany", "competition", [
        {
            "title": "GWB Digitalisation Act — Section 19a GWB (10th Amendment)",
            "citation": "Gesetz gegen Wettbewerbsbeschränkungen (GWB) § 19a, 10. Amendment 2021",
            "slug": "gwb-19a-10th-amendment",
            "source_type": "primary",
            "excerpt": "Designates Meta as an undertaking of paramount significance for competition across markets, enabling Bundeskartellamt proactive interventions.",
            "meta_nexus": "named_party",
            "rationale": "Federal Cartel Office designated Meta under §19a GWB for cross-market competition significance.",
            "confidence": 0.90, "effective_date": "2021-01-19", "status": "in_force",
        },
    ]),
    # --- France -------------------------------------------------------------
    ("France", "privacy", [
        {
            "title": "Loi Informatique et Libertés (as amended by Ordonnance 2018-1125)",
            "citation": "Loi n° 78-17 du 6 janvier 1978, as amended 2018",
            "slug": "loi-informatique-78-17",
            "source_type": "primary",
            "excerpt": "French data-protection law implementing GDPR derogations on age of consent and CNIL sanction powers affecting Meta's French users.",
            "meta_nexus": "platform_obligation",
            "rationale": "CNIL enforces national GDPR derogations against Meta's French data processing.",
            "confidence": 0.83, "effective_date": "2018-06-01", "status": "in_force",
        },
    ]),
    ("France", "competition", [
        {
            "title": "French Commercial Code — Antitrust (L420-2) — Adtech Proceedings",
            "citation": "Code de commerce, Art. L420-2; Autorité de la concurrence, Décision 21-D-11",
            "slug": "fr-antitrust-adtech-21-d-11",
            "source_type": "secondary",
            "excerpt": "Autorité's adtech enforcement addresses parity and self-preferencing concerns in programmatic advertising relevant to Meta Audience Network.",
            "meta_nexus": "sector_rule",
            "rationale": "Competition enforcement in adtech shapes constraints on Meta's Audience Network and ad auctions.",
            "confidence": 0.75, "effective_date": "2021-06-07", "status": "enforcement",
        },
    ]),
    # --- United Kingdom -----------------------------------------------------
    ("United Kingdom", "privacy", [
        {
            "title": "UK GDPR and Data Protection Act 2018",
            "citation": "Data Protection Act 2018, c. 12; UK GDPR (retained EU law)",
            "slug": "uk-gdpr-dpa-2018",
            "source_type": "primary",
            "excerpt": "Requires Meta to maintain a UK lawful basis, appoint a UK representative and respond to ICO enforcement for UK user data.",
            "meta_nexus": "platform_obligation",
            "rationale": "Post-Brexit UK data-protection regime applies independently to Meta's UK processing.",
            "confidence": 0.92, "effective_date": "2021-01-01", "status": "in_force",
        },
        {
            "title": "Privacy and Electronic Communications Regulations 2003 (PECR)",
            "citation": "SI 2003/2426, as amended",
            "slug": "pecr-2003-2426",
            "source_type": "primary",
            "excerpt": "UK consent rules for cookies and electronic marketing governing Meta Pixel deployment and Messenger marketing messages.",
            "meta_nexus": "platform_obligation",
            "rationale": "ICO enforces PECR consent for storage and access on UK users' devices via Meta technologies.",
            "confidence": 0.84, "effective_date": "2003-12-11", "status": "in_force",
        },
    ]),
    ("United Kingdom", "competition", [
        {
            "title": "Digital Markets, Competition and Consumers Act 2024 (DMCC)",
            "citation": "DMCC Act 2024, c. 13, Part 1",
            "slug": "dmcc-2024-part1",
            "source_type": "primary",
            "excerpt": "Empowers the CMA's Digital Markets Unit to designate Meta with Strategic Market Status and impose conduct requirements.",
            "meta_nexus": "platform_obligation",
            "rationale": "SMS designation pathway directly contemplates large platforms such as Meta.",
            "confidence": 0.82, "effective_date": "2025-01-01", "status": "in_force",
        },
    ]),
    ("United Kingdom", "youth_safety", [
        {
            "title": "Online Safety Act 2023",
            "citation": "Online Safety Act 2023, c. 50",
            "slug": "uk-online-safety-act-2023",
            "source_type": "primary",
            "excerpt": "Requires Meta as a Category 1 service to remove illegal content, enforce age-assurance and publish transparency reports for Facebook and Instagram.",
            "meta_nexus": "platform_obligation",
            "rationale": "Category 1 duties impose illegal-content, age-assurance and user-empowerment obligations on the largest platforms.",
            "confidence": 0.91, "effective_date": "2023-10-26", "status": "in_force",
        },
    ]),
    # --- Brazil -------------------------------------------------------------
    ("Brazil", "privacy", [
        {
            "title": "LGPD — Lei Geral de Proteção de Dados (Lei nº 13.709/2018)",
            "citation": "Lei nº 13.709, de 14 de agosto de 2018",
            "slug": "lgpd-13709-2018",
            "source_type": "primary",
            "excerpt": "Requires Meta to appoint a DPO, honour data-subject rights and maintain processing records for Brazilian users on WhatsApp, Facebook and Instagram.",
            "meta_nexus": "platform_obligation",
            "rationale": "Brazil's comprehensive data-protection law applies to Meta's processing of Brazilian residents' data.",
            "confidence": 0.93, "effective_date": "2020-09-18", "status": "in_force",
        },
        {
            "title": "Marco Civil da Internet — Law No. 12.965/2014",
            "citation": "Lei nº 12.965, de 23 de abril de 2014",
            "slug": "marco-civil-12965-2014",
            "source_type": "primary",
            "excerpt": "Establishes net-neutrality and intermediary-liability principles shaping how Meta responds to court-ordered content removals in Brazil.",
            "meta_nexus": "platform_obligation",
            "rationale": "Defines intermediary liability and data-retention duties for application providers like Meta in Brazil.",
            "confidence": 0.80, "effective_date": "2014-06-23", "status": "in_force",
        },
    ]),
    ("Brazil", "competition", [
        {
            "title": "CADE — Competition Law (Lei nº 12.529/2011) — Digital Markets Inquiry",
            "citation": "Lei nº 12.529/2011; CADE Inquérito Digital Markets 2023",
            "slug": "cade-12529-digital-inquiry",
            "source_type": "secondary",
            "excerpt": "CADE's digital-markets inquiry examines Meta's conduct in social networking and advertising markets for potential abuse of dominance.",
            "meta_nexus": "sector_rule",
            "rationale": "Competition inquiry into digital platforms may produce conduct remedies applicable to Meta's services.",
            "confidence": 0.73, "effective_date": "2011-11-30", "status": "enforcement",
        },
    ]),
    # --- Japan --------------------------------------------------------------
    ("Japan", "privacy", [
        {
            "title": "APPI — Act on Protection of Personal Information (as amended 2022)",
            "citation": "Act No. 57 of 2003, as amended by Act No. 44 of 2020 (enforced 2022)",
            "slug": "appi-2022-amendment",
            "source_type": "primary",
            "excerpt": "Requires Meta to disclose cross-border transfers, obtain opt-out for third-party provision and report data breaches affecting Japanese users.",
            "meta_nexus": "platform_obligation",
            "rationale": "PPC enforces APPI transfer and breach-notification duties on foreign operators serving Japanese residents.",
            "confidence": 0.88, "effective_date": "2022-04-01", "status": "in_force",
        },
        {
            "title": "Telecommunications Business Act — External Transmission Rules (2023 Amendment)",
            "citation": "Telecommunications Business Act, as amended 2023 (MIC Ordinance)",
            "slug": "tba-external-transmission-2023",
            "source_type": "primary",
            "excerpt": "Requires Meta to notify and obtain consent for transmitting user information to external parties via SDKs and pixels in Japan.",
            "meta_nexus": "platform_obligation",
            "rationale": "External-transmission rules govern Meta's collection of browsing data through embedded scripts in Japan.",
            "confidence": 0.79, "effective_date": "2023-06-16", "status": "in_force",
        },
    ]),
    ("Japan", "ip", [
        {
            "title": "Copyright Act — Article 30-4 (Flexible Rights Limitation for Data Analysis)",
            "citation": "Copyright Act (Act No. 48 of 1970), Art. 30-4 (2018 amendment)",
            "slug": "jp-copyright-art30-4-2018",
            "source_type": "primary",
            "excerpt": "Permits limited use of copyrighted works for AI training but creates opt-out and licensing tensions for Meta's generative-AI training on Japanese content.",
            "meta_nexus": "sector_rule",
            "rationale": "Flexibility for computational analysis affects Meta AI training while rightholder opt-outs create compliance complexity.",
            "confidence": 0.76, "effective_date": "2019-01-01", "status": "in_force",
        },
    ]),
]
# fmt: on


def _build_cells() -> list[ResearchCell]:
    """All 40 cartesian cells (so manifest covers every pair)."""
    cells: list[ResearchCell] = []
    for j in JURISDICTIONS:
        for d in DOMAINS:
            jid = JID_SLUGS[j]
            cells.append(
                ResearchCell(
                    cell_id=make_cell_id(jid, d),
                    jurisdiction=j,
                    jurisdiction_id=jid,
                    domain=d,
                    domain_id=d,
                    status="done",
                    subject="Meta",
                )
            )
    return cells


def _build_laws(seed: int | None = None) -> list[LawRecord]:
    rng = random.Random(seed)
    laws: list[LawRecord] = []
    for jurisdiction_display, domain_id, entries in LAW_CATALOGUE:
        jid = JID_SLUGS[jurisdiction_display]
        cell_id = make_cell_id(jid, domain_id)
        for entry in entries:
            # Slight confidence jitter so heatmap is not uniform (±0.03)
            base_conf = float(entry["confidence"])
            jitter = rng.uniform(-0.03, 0.03)
            confidence = round(max(0.70, min(0.95, base_conf + jitter)), 2)
            # Stable law_id: slug-like, unique across dossier
            raw_law_id = f"{jid}--{entry['slug']}"
            law = LawRecord(
                law_id=raw_law_id,
                title=entry["title"],
                jurisdiction_id=jid,
                domain_id=domain_id,
                cell_id=cell_id,
                citation=entry["citation"],
                source_url=_url(jid, entry["slug"]),
                source_type=entry["source_type"],  # type: ignore[arg-type]
                excerpt=entry["excerpt"],
                language="en",
                meta_nexus=entry["meta_nexus"],  # type: ignore[arg-type]
                meta_nexus_rationale=entry["rationale"],
                confidence=confidence,
                effective_date=entry.get("effective_date"),
                status=entry.get("status"),
                validated=True,
                worker_model="demo-seed",
            )
            laws.append(law)
    # Deterministic shuffle to avoid visual grouping by creation order
    rng.shuffle(laws)
    return laws


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate demo dossier for law-matrix website.")
    parser.add_argument(
        "--run-id",
        dest="run_id",
        default=None,
        help="Override run_id (default: demo_<UTC timestamp>)",
    )
    parser.add_argument(
        "--dossier-root",
        dest="dossier_root",
        default=None,
        help="Override dossier root (default: $DOSSIER_ROOT or data/dossiers)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for confidence jitter (default: 42)",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv()
    except Exception:
        pass

    root = Path(args.dossier_root or os.environ.get("DOSSIER_ROOT", DEFAULT_DOSSIER_ROOT))
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    run_id = (args.run_id or f"demo_{ts}_{uuid4().hex[:6]}").strip()
    if not run_id:
        run_id = f"demo_{ts}_{uuid4().hex[:6]}"

    cells = _build_cells()
    laws = _build_laws(seed=args.seed)

    dossier_dir = write_dossier_to_root(
        root,
        run_id=run_id,
        jurisdictions=JURISDICTIONS,
        domains=DOMAINS,
        subject="Meta",
        accepted=laws,
        rejected=[],
        cells=cells,
        model="demo-seed",
    )

    # Summary
    from collections import Counter

    by_cell = Counter(law.cell_id for law in laws)
    populated = len(by_cell)
    total_cells = len(cells)
    empty = total_cells - populated

    print(f"Wrote demo dossier: {dossier_dir}")
    print(f"  run_id={run_id}")
    print(f"  jurisdictions={len(JURISDICTIONS)} domains={len(DOMAINS)} cells={total_cells}")
    print(f"  laws={len(laws)}  populated_cells={populated}  empty_cells={empty}")
    # Show distribution so reviewers can spot heatmap variation
    for cid in sorted(by_cell):
        print(f"    {cid}: {by_cell[cid]} law(s)")
    # Also list a few empty cells for visibility
    all_cids = {c.cell_id for c in cells}
    empty_cids = sorted(all_cids - set(by_cell))
    if empty_cids:
        print(f"  empty (sample {min(5, len(empty_cids))} of {len(empty_cids)}): {', '.join(empty_cids[:5])}")
    print(f"  manifest: {dossier_dir / 'manifest.json'}")
    print(f"  index:    {dossier_dir / 'index.json'}")


if __name__ == "__main__":
    main()
